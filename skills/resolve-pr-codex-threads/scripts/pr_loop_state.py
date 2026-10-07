#!/usr/bin/env -S uv run -q --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Report the current branch's pull-request loop state and next action."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Never, TypeIs, cast
from urllib.parse import urlparse

CI_CHECK_NAME = "ci"
CODEX_LOGIN = "chatgpt-codex-connector"
CODEX_SUMMARY_MARKER = "<!-- codex-pull-request-review-summary -->"
REVIEW_ROW_CELLS = 6
GH_COMMAND = "gh"
GIT_COMMAND = "git"
NO_PR_ERRORS = (
    "could not resolve to a pull request",
    "could not resolve to a pullrequest",
    "no pull requests found",
)
PR_URL_PARTS = 4
SNAPSHOT_ATTEMPTS = 2

type GateState = Literal["action", "green", "running", "terminated"]

THREADS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$endCursor:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100,after:$endCursor){
        pageInfo{hasNextPage endCursor}
        nodes{
          id isResolved path startLine line
          comments(first:100){
            nodes{ body url author{ login } }
          }
        }
      }
    }
  }
}
"""

COMMENTS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$endCursor:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      comments(first:100,after:$endCursor){
        pageInfo{hasNextPage endCursor}
        nodes{body url author{login}}
      }
    }
  }
}
"""


class CommandError(RuntimeError):
    """A required local command failed or returned invalid output."""

    def __init__(self, command: str, detail: str) -> None:
        super().__init__(f"`{command}` failed: {detail}")


type JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class ReviewComment:
    body: str
    url: str
    author_login: str | None


@dataclass(frozen=True, slots=True)
class ReviewThread:
    id: str
    is_resolved: bool
    path: str
    start_line: int | None
    end_line: int | None
    comments: list[ReviewComment]


@dataclass(frozen=True, slots=True)
class PullRequest:
    head_oid: str
    is_draft: bool
    number: int
    state: str
    url: str


@dataclass(frozen=True, slots=True)
class PRCheck:
    bucket: str
    link: str
    name: str
    state: str
    workflow: str


@dataclass(frozen=True, slots=True)
class CodexReview:
    commit_prefix: str
    status: str
    url: str


@dataclass(frozen=True, slots=True)
class BranchPosition:
    ahead: int
    behind: int
    local_head_oid: str


@dataclass(frozen=True, slots=True)
class GateSnapshot:
    pr_checks: list[PRCheck]
    ci_check: PRCheck | None
    ci_state: GateState
    codex_review: CodexReview | None
    codex_state: GateState
    codex_threads: list[ReviewThread]


def raise_command_error(
    command: str,
    detail: str,
    *,
    cause: Exception | None = None,
) -> Never:
    error = CommandError(command, detail)
    if cause is None:
        raise error
    raise error from cause


def write_line(message: str = "") -> None:
    sys.stdout.write(message + "\n")


def run_command(
    tool: str,
    arguments: list[str],
    *,
    accept_failure: bool = False,
    allow_empty: bool = False,
) -> str:
    executable = shutil.which(tool)
    command = " ".join([tool, *arguments])
    if executable is None:
        raise CommandError(command, f"{tool} is not installed or not on PATH")
    completed = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0 and not accept_failure:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise CommandError(command, detail)
    if not completed.stdout.strip() and not allow_empty:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise CommandError(command, f"returned no output: {detail}")
    return completed.stdout


def load_gh_json(arguments: list[str], *, accept_failure: bool = False) -> object:
    output = run_command(GH_COMMAND, arguments, accept_failure=accept_failure)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        detail = f"returned invalid JSON: {error}"
        raise CommandError("gh " + " ".join(arguments), detail) from error


def cast_json_object(payload: object) -> JsonObject:
    return cast("JsonObject", payload)


def cast_json_objects(payload: object) -> list[JsonObject]:
    return cast("list[JsonObject]", payload)


def parse_pull_request(payload: object) -> PullRequest:
    fields = cast_json_object(payload)
    return PullRequest(
        head_oid=cast("str", fields["headRefOid"]),
        is_draft=cast("bool", fields["isDraft"]),
        number=cast("int", fields["number"]),
        state=cast("str", fields["state"]),
        url=cast("str", fields["url"]),
    )


def parse_pr_check(payload: JsonObject) -> PRCheck:
    return PRCheck(
        bucket=cast("str", payload["bucket"]),
        link=cast("str", payload["link"]),
        name=cast("str", payload["name"]),
        state=cast("str", payload["state"]),
        workflow=cast("str", payload["workflow"]),
    )


def parse_review_comment(payload: JsonObject) -> ReviewComment:
    author = payload["author"]
    author_login = None if author is None else cast("str", cast_json_object(author)["login"])
    return ReviewComment(
        body=cast("str", payload["body"]),
        url=cast("str", payload["url"]),
        author_login=author_login,
    )


def parse_review_thread(payload: JsonObject) -> ReviewThread:
    comments = cast_json_objects(cast_json_object(payload["comments"])["nodes"])
    return ReviewThread(
        id=cast("str", payload["id"]),
        is_resolved=cast("bool", payload["isResolved"]),
        path=cast("str", payload["path"]),
        start_line=cast("int | None", payload["startLine"]),
        end_line=cast("int | None", payload["line"]),
        comments=[parse_review_comment(comment) for comment in comments],
    )


def validate_repo_root() -> None:
    root = Path(run_command(GIT_COMMAND, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    if Path.cwd().resolve() != root:
        raise_command_error(
            "scripts/pr_loop_state.py",
            f"run this script with the repository root as the working directory: {root}",
        )


def find_current_pr() -> PullRequest | None:
    arguments = [
        "pr",
        "view",
        "--json",
        "number,url,state,isDraft,headRefOid",
    ]
    try:
        return parse_pull_request(load_gh_json(arguments))
    except CommandError as error:
        if any(message in str(error).casefold() for message in NO_PR_ERRORS):
            return None
        raise


def parse_pr_repo(url: str) -> tuple[str, str]:
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < PR_URL_PARTS or parts[2] != "pull":
        raise_command_error("parse PR URL", f"unexpected URL {url!r}")
    return parts[0], parts[1]


def fetch_pr_checks(owner: str, repo: str, pr_number: int) -> list[PRCheck]:
    payloads = load_gh_json(
        [
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "name,bucket,link,state,workflow",
        ],
        accept_failure=True,
    )
    return [parse_pr_check(payload) for payload in cast_json_objects(payloads)]


def find_ci_check(pr_checks: list[PRCheck]) -> PRCheck | None:
    return next(
        (check for check in pr_checks if check.name.casefold() == CI_CHECK_NAME),
        None,
    )


def is_working_tree_clean() -> bool:
    working_tree_status = run_command(
        GIT_COMMAND,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        allow_empty=True,
    )
    return not working_tree_status.strip()


def inspect_branch_position(pr_head_oid: str) -> BranchPosition | None:
    local_head_oid = run_command(GIT_COMMAND, ["rev-parse", "HEAD"]).strip()
    counts = run_command(
        GIT_COMMAND,
        ["rev-list", "--left-right", "--count", f"{pr_head_oid}...{local_head_oid}"],
        accept_failure=True,
        allow_empty=True,
    ).split()
    try:
        behind_count, ahead_count = counts
    except ValueError:
        return None
    try:
        behind = int(behind_count)
        ahead = int(ahead_count)
    except ValueError as error:
        raise_command_error(
            "git rev-list --left-right --count",
            f"returned invalid counts: {' '.join(counts)}",
            cause=error,
        )
    return BranchPosition(ahead=ahead, behind=behind, local_head_oid=local_head_oid)


def is_codex_comment(comment: ReviewComment) -> bool:
    return comment.author_login is not None and comment.author_login.removesuffix("[bot]") == CODEX_LOGIN


def fetch_pr_connection(owner: str, repo: str, pr_number: int, query: str, connection: str) -> list[JsonObject]:
    responses = cast_json_objects(
        load_gh_json([
            "api",
            "graphql",
            "--paginate",
            "--slurp",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={repo}",
            "-F",
            f"number={pr_number}",
            "-f",
            f"query={query}",
        ])
    )
    nodes: list[JsonObject] = []
    for response in responses:
        data = cast_json_object(response["data"])
        repository = cast_json_object(data["repository"])
        pull_request = cast_json_object(repository["pullRequest"])
        page = cast_json_object(pull_request[connection])
        nodes.extend(cast_json_objects(page["nodes"]))
    return nodes


def fetch_codex_review(owner: str, repo: str, pr_number: int) -> CodexReview | None:
    comments = fetch_pr_connection(owner, repo, pr_number, COMMENTS_QUERY, "comments")
    for payload in reversed(comments):
        comment = parse_review_comment(payload)
        if not is_codex_comment(comment) or CODEX_SUMMARY_MARKER not in comment.body:
            continue
        for line in comment.body.splitlines():
            cells = line.split("|")
            if len(cells) != REVIEW_ROW_CELLS or "**Code Review**" not in cells[1]:
                continue
            status = re.search(r"\*\*([^*]+)\*\*", cells[2])
            commit = re.search(r"`([0-9a-f]{7,40})`", cells[3])
            if status is not None and commit is not None:
                return CodexReview(commit_prefix=commit[1], status=status[1].casefold(), url=comment.url)
        raise_command_error("parse Codex summary", f"Code Review status or commit is unavailable: {comment.url}")
    return None


def fetch_unresolved_codex_threads(owner: str, repo: str, pr_number: int) -> list[ReviewThread]:
    threads: list[ReviewThread] = []
    for payload in fetch_pr_connection(owner, repo, pr_number, THREADS_QUERY, "reviewThreads"):
        thread = parse_review_thread(payload)
        if not thread.is_resolved and thread.comments and is_codex_comment(thread.comments[0]):
            threads.append(thread)
    return threads


def format_timestamp() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def print_step(step: int, message: str) -> None:
    write_line(f"{format_timestamp()} - {step}: {message}")
    sys.stdout.flush()


def format_count(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def format_ci_check_state(ci_check: PRCheck | None) -> str:
    if ci_check is None:
        return f"{CI_CHECK_NAME}=missing"
    return f"{CI_CHECK_NAME}={ci_check.bucket}"


def format_codex_review_state(review: CodexReview | None, head_oid: str) -> str:
    if review is None:
        return "codex-review=missing"
    status = review.status if head_oid.startswith(review.commit_prefix) else "stale"
    return f"codex-review={status} ({review.commit_prefix})"


def assess_ci_check(ci_check: PRCheck | None) -> GateState:
    if ci_check is None or ci_check.bucket == "pending":
        return "running"
    if ci_check.bucket == "pass":
        return "green"
    if ci_check.bucket == "fail":
        return "action"
    return "terminated"


def assess_codex_review(review: CodexReview | None, head_oid: str) -> GateState:
    if review is None or not head_oid.startswith(review.commit_prefix):
        return "action"
    if review.status == "completed":
        return "green"
    if review.status in {"running", "queued"}:
        return "running"
    return "terminated"


def fetch_gate_snapshot(owner: str, repo: str, pr: PullRequest) -> GateSnapshot:
    pr_checks = fetch_pr_checks(owner, repo, pr.number)
    ci_check = find_ci_check(pr_checks)
    codex_review = fetch_codex_review(owner, repo, pr.number)
    ci_state = assess_ci_check(ci_check)
    return GateSnapshot(
        pr_checks=pr_checks,
        ci_check=ci_check,
        ci_state=ci_state,
        codex_review=codex_review,
        codex_state=assess_codex_review(codex_review, pr.head_oid),
        codex_threads=fetch_unresolved_codex_threads(owner, repo, pr.number),
    )


def format_thread_location(thread: ReviewThread) -> str:
    start_line = thread.start_line
    end_line = thread.end_line
    if start_line is not None and end_line is not None and start_line != end_line:
        return f"{thread.path}:{start_line}-{end_line}"
    line = end_line if end_line is not None else start_line
    return f"{thread.path}:{line}" if line is not None else thread.path


def list_failed_ci_checks(pr_checks: list[PRCheck]) -> list[PRCheck]:
    return [check for check in pr_checks if check.bucket == "fail" and check.name.casefold() == CI_CHECK_NAME]


def print_ci_failures(failed_ci_checks: list[PRCheck], pr_url: str) -> None:
    write_line(f"CI FAILURES ({len(failed_ci_checks)})")
    for index, check in enumerate(failed_ci_checks, start=1):
        write_line()
        write_line(f"[{index}/{len(failed_ci_checks)}] {check.name}")
        if check.workflow:
            write_line(f"Workflow: {check.workflow}")
        write_line(f"State: {check.state or check.bucket.upper()}")
        write_line(f"URL: {check.link or pr_url + '/checks'}")


def print_codex_threads(threads: list[ReviewThread]) -> None:
    write_line(f"UNRESOLVED CODEX THREADS ({len(threads)})")
    for thread_index, thread in enumerate(threads, start=1):
        write_line()
        write_line(f"[{thread_index}/{len(threads)}] {format_thread_location(thread)}")
        write_line(f"Thread ID: {thread.id}")
        write_line("Use this ID as pullRequestReviewThreadId when replying and threadId when resolving.")
        comments = thread.comments
        for comment_index, comment in enumerate(comments, start=1):
            author = comment.author_login or "unknown"
            write_line()
            write_line(f"----- COMMENT {comment_index}/{len(comments)} -----")
            write_line(f"Author: {author}")
            write_line(f"URL: {comment.url}")
            write_line(comment.body)
            write_line(f"----- END COMMENT {comment_index}/{len(comments)} -----")


def print_codex_review_action(review: CodexReview | None, pr: PullRequest) -> None:
    write_line("CODEX REVIEW ACTION")
    write_line(format_codex_review_state(review, pr.head_oid))
    write_line(f"URL: {review.url if review is not None else pr.url}")
    write_line("A completed Code Review is required for the current PR head.")


def print_next_action(
    *,
    has_ci_failures: bool,
    has_codex_threads: bool,
    has_codex_review_action: bool,
    ahead: int,
    pr_url: str,
) -> None:
    actions: list[str] = []
    if has_ci_failures:
        actions.append("Fix every listed CI failure.")
    if has_codex_threads:
        actions.append(
            "Inspect every listed thread against the current code. Fix valid findings; "
            "explain why invalid findings should not be applied; resolve every addressed thread."
        )
    if has_ci_failures or has_codex_threads or ahead:
        actions.extend([
            "Ensure just c passes for the resulting local HEAD; reuse a passing run when nothing changed.",
            "Commit resulting changes, if any, then push unpushed commits with git push.",
            (
                "If you pushed commits or Code Review is missing/stale, request a code review: "
                f"gh pr comment {pr_url} --body '@codex review'."
            ),
            "After requesting review, wait 3 minutes; otherwise rerun this script now.",
        ])
    elif has_codex_review_action:
        actions.extend([
            f"Request a code review: gh pr comment {pr_url} --body '@codex review'.",
            "Wait 3 minutes, then rerun this script.",
        ])
    write_line("NEXT ACTION")
    for index, action in enumerate(actions, start=1):
        write_line(f"{index}. {action}")


def print_report(
    snapshot: GateSnapshot,
    pr: PullRequest,
    ahead: int,
) -> None:
    failed_ci_checks = list_failed_ci_checks(snapshot.pr_checks)
    has_codex_review_action = snapshot.codex_state == "action"
    counts: list[str] = []
    if failed_ci_checks:
        counts.append(format_count(len(failed_ci_checks), "CI failure"))
    if snapshot.codex_threads:
        counts.append(format_count(len(snapshot.codex_threads), "unresolved Codex thread"))
    if has_codex_review_action:
        counts.append("Codex review action")
    if ahead:
        counts.append(format_count(ahead, "unpushed commit"))
    if not counts:
        raise_command_error("print action report", "no actionable state was supplied")
    print_step(40, "action required - " + ", ".join(counts))
    write_line()
    if failed_ci_checks:
        print_ci_failures(failed_ci_checks, pr.url)
        write_line()
    if snapshot.codex_threads:
        print_codex_threads(snapshot.codex_threads)
        write_line()
    if has_codex_review_action:
        print_codex_review_action(snapshot.codex_review, pr)
        write_line()
    print_next_action(
        has_ci_failures=bool(failed_ci_checks),
        has_codex_threads=bool(snapshot.codex_threads),
        has_codex_review_action=has_codex_review_action,
        ahead=ahead,
        pr_url=pr.url,
    )


def print_open_pr(pr: PullRequest) -> None:
    mode = "draft" if pr.is_draft else "ready"
    print_step(10, f"PR #{pr.number} is open and {mode} - {pr.url}")


def format_branch_position(branch_position: BranchPosition | None) -> str:
    if branch_position is None:
        return "working tree clean; branch relation to the PR branch at origin is unavailable"
    ahead = branch_position.ahead
    behind = branch_position.behind
    if ahead and behind:
        return "working tree clean; local branch has diverged from the PR branch at origin"
    if behind:
        return f"working tree clean; local branch is {format_count(behind, 'commit')} behind the PR branch at origin"
    if ahead:
        return f"working tree clean; local branch is {format_count(ahead, 'commit')} ahead of the PR branch at origin"
    return "working tree clean; local branch matches the PR branch at origin"


def is_branch_position_safe(
    branch_position: BranchPosition | None,
) -> TypeIs[BranchPosition]:
    return branch_position is not None and branch_position.behind == 0


def is_same_branch_position(first: BranchPosition, second: BranchPosition) -> bool:
    return (
        first.ahead == second.ahead and first.behind == second.behind and first.local_head_oid == second.local_head_oid
    )


def print_dirty_working_tree(pr: PullRequest) -> None:
    print_open_pr(pr)
    print_step(20, "working tree not clean")
    print_step(
        70,
        "if you recognise all local changes as yours, commit them without pushing and rerun "
        "this script; otherwise stop and inform the user",
    )


def print_unsafe_branch(
    pr: PullRequest,
    branch_position: BranchPosition | None,
) -> None:
    print_open_pr(pr)
    print_step(20, format_branch_position(branch_position))
    print_step(
        100,
        "STOP - inform the user; do not continue until the branch relation is safe",
    )


def format_gate_state(snapshot: GateSnapshot, head_oid: str) -> str:
    return "; ".join([
        format_ci_check_state(snapshot.ci_check),
        format_codex_review_state(snapshot.codex_review, head_oid),
    ])


def list_gate_states(snapshot: GateSnapshot) -> tuple[GateState, GateState]:
    return snapshot.ci_state, snapshot.codex_state


def list_terminated_gates(snapshot: GateSnapshot, head_oid: str) -> list[str]:
    gates = [
        (snapshot.ci_state, format_ci_check_state(snapshot.ci_check)),
        (
            snapshot.codex_state,
            format_codex_review_state(snapshot.codex_review, head_oid),
        ),
    ]
    return [summary for state, summary in gates if state == "terminated"]


def print_gate_recommendation(
    snapshot: GateSnapshot,
    pr: PullRequest,
    branch_position: BranchPosition,
) -> None:
    print_open_pr(pr)
    print_step(20, format_branch_position(branch_position))
    print_step(30, format_gate_state(snapshot, pr.head_oid))

    terminated_gates = list_terminated_gates(snapshot, pr.head_oid)
    if terminated_gates:
        print_step(
            100,
            "STOP - gate terminated without success: " + "; ".join(terminated_gates) + "; inform the user",
        )
        return

    gate_states = list_gate_states(snapshot)
    if "running" in gate_states:
        print_step(
            50,
            "wait for every running gate to finish; set a 60-second wake-up, then rerun "
            "this script for a fresh recommendation",
        )
        return

    if all(state == "green" for state in gate_states) and not snapshot.codex_threads and branch_position.ahead == 0:
        print_step(100, "STOP - ci and Codex review are green; no unresolved Codex threads; nothing to do")
        return

    print_report(snapshot, pr, branch_position.ahead)


def print_pr_loop_state() -> None:
    print_step(0, "started")
    validate_repo_root()
    for _ in range(SNAPSHOT_ATTEMPTS):
        pr = find_current_pr()
        if pr is None:
            print_step(10, "no open PR found for the current branch")
            print_step(100, "STOP - do nothing")
            return
        if pr.state != "OPEN":
            print_step(10, f"PR #{pr.number} is {pr.state.lower()} - {pr.url}")
            print_step(100, "STOP - the PR is not open; do nothing")
            return
        if not is_working_tree_clean():
            print_dirty_working_tree(pr)
            return

        branch_position = inspect_branch_position(pr.head_oid)
        if not is_branch_position_safe(branch_position):
            print_unsafe_branch(pr, branch_position)
            return

        owner, repo = parse_pr_repo(pr.url)
        snapshot = fetch_gate_snapshot(owner, repo, pr)

        confirmed_pr = find_current_pr()
        if confirmed_pr is None or confirmed_pr.number != pr.number or confirmed_pr.head_oid != pr.head_oid:
            continue
        if not is_working_tree_clean():
            print_dirty_working_tree(confirmed_pr)
            return
        confirmed_branch_position = inspect_branch_position(confirmed_pr.head_oid)
        if confirmed_branch_position is None or not is_same_branch_position(
            confirmed_branch_position,
            branch_position,
        ):
            continue

        print_gate_recommendation(snapshot, confirmed_pr, confirmed_branch_position)
        return

    raise_command_error(
        "print PR loop state",
        f"PR head changed during {SNAPSHOT_ATTEMPTS} consecutive snapshots; rerun this script",
    )


def parse_args() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect CI, Codex review progress and unresolved threads for the current branch's PR."
    )
    parser.parse_args()


def main() -> int:
    parse_args()
    try:
        print_pr_loop_state()
    except (CommandError, KeyError, TypeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
