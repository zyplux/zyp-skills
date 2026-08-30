#!/usr/bin/env -S uv run -q --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Report the current branch's pull-request loop state and next action."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Never, TypedDict, TypeIs, cast
from urllib.parse import urlparse

CI_CHECK_NAME = "ci"
COPILOT_REVIEW_CHECK_NAME = "copilot-pull-request-reviewer"
COPILOT_REVIEW_STATUS_CONTEXT = "copilot-review-complete"
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
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100){
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


class CommandError(RuntimeError):
    """A required local command failed or returned invalid output."""

    def __init__(self, command: str, detail: str) -> None:
        super().__init__(f"`{command}` failed: {detail}")


Author = TypedDict("Author", {"login": str})
Comment = TypedDict(
    "Comment",
    {
        "body": str,
        "url": str,
        "author": Author | None,
    },
)
Comments = TypedDict("Comments", {"nodes": list[Comment]})
ReviewThread = TypedDict(
    "ReviewThread",
    {
        "id": str,
        "isResolved": bool,
        "path": str,
        "startLine": int | None,
        "line": int | None,
        "comments": Comments,
    },
)
ThreadConnection = TypedDict("ThreadConnection", {"nodes": list[ReviewThread]})
PullRequest = TypedDict(
    "PullRequest",
    {
        "headRefOid": str,
        "isDraft": bool,
        "number": int,
        "state": str,
        "url": str,
    },
)
PRCheck = TypedDict(
    "PRCheck",
    {
        "bucket": str,
        "link": str,
        "name": str,
        "state": str,
        "workflow": str,
    },
)
CopilotReviewCheck = TypedDict(
    "CopilotReviewCheck",
    {
        "conclusion": str | None,
        "details_url": str | None,
        "name": str,
        "status": str,
    },
)
CheckRunsResponse = TypedDict("CheckRunsResponse", {"check_runs": list[CopilotReviewCheck]})
CommitStatus = TypedDict(
    "CommitStatus",
    {
        "context": str,
        "description": str | None,
        "state": str,
        "target_url": str | None,
    },
)
BranchPosition = TypedDict(
    "BranchPosition",
    {
        "ahead": int,
        "behind": int,
        "local_head_oid": str,
    },
)


@dataclass(frozen=True, slots=True)
class GateSnapshot:
    pr_checks: list[PRCheck]
    ci_check: PRCheck | None
    ci_state: GateState
    copilot_review_check: CopilotReviewCheck | None
    copilot_review_check_state: GateState
    copilot_review_status: CommitStatus | None
    copilot_review_status_state: GateState
    copilot_threads: list[ReviewThread]


ThreadsPullRequest = TypedDict("ThreadsPullRequest", {"reviewThreads": ThreadConnection})
ThreadsRepository = TypedDict("ThreadsRepository", {"pullRequest": ThreadsPullRequest})
ThreadsData = TypedDict("ThreadsData", {"repository": ThreadsRepository})
ThreadsResponse = TypedDict("ThreadsResponse", {"data": ThreadsData})


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
        return cast("PullRequest", load_gh_json(arguments))
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
    return cast(
        "list[PRCheck]",
        load_gh_json(
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
        ),
    )


def find_ci_check(pr_checks: list[PRCheck]) -> PRCheck | None:
    return next(
        (check for check in pr_checks if check["name"].casefold() == CI_CHECK_NAME),
        None,
    )


def fetch_copilot_review_check(
    owner: str,
    repo: str,
    sha: str,
) -> CopilotReviewCheck | None:
    endpoint = f"repos/{owner}/{repo}/commits/{sha}/check-runs?check_name={COPILOT_REVIEW_CHECK_NAME}&per_page=100"
    response = cast(
        "CheckRunsResponse",
        load_gh_json(["api", endpoint]),
    )
    return next(
        (check for check in response["check_runs"] if check["name"] == COPILOT_REVIEW_CHECK_NAME),
        None,
    )


def fetch_copilot_review_status(
    owner: str,
    repo: str,
    sha: str,
) -> CommitStatus | None:
    statuses = cast(
        "list[CommitStatus]",
        load_gh_json(["api", f"repos/{owner}/{repo}/commits/{sha}/statuses?per_page=100"]),
    )
    return next(
        (status for status in statuses if status["context"] == COPILOT_REVIEW_STATUS_CONTEXT),
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
    return {
        "ahead": ahead,
        "behind": behind,
        "local_head_oid": local_head_oid,
    }


def is_copilot_comment(comment: Comment) -> bool:
    author = comment["author"]
    return author is not None and "copilot" in author["login"].casefold()


def fetch_unresolved_copilot_threads(owner: str, repo: str, pr_number: int) -> list[ReviewThread]:
    response = cast(
        "ThreadsResponse",
        load_gh_json([
            "api",
            "graphql",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={repo}",
            "-F",
            f"number={pr_number}",
            "-f",
            f"query={THREADS_QUERY}",
        ]),
    )
    copilot_threads: list[ReviewThread] = []
    threads = response["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    for thread in threads:
        comments = thread["comments"]["nodes"]
        if not thread["isResolved"] and comments and is_copilot_comment(comments[0]):
            copilot_threads.append(thread)
    return copilot_threads


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
    return f"{CI_CHECK_NAME}={ci_check['bucket']}"


def format_copilot_review_check_state(
    copilot_review_check: CopilotReviewCheck | None,
) -> str:
    if copilot_review_check is None:
        return f"{COPILOT_REVIEW_CHECK_NAME}=missing"
    status = copilot_review_check["status"]
    conclusion = copilot_review_check["conclusion"]
    suffix = f"/{conclusion}" if conclusion else ""
    return f"{COPILOT_REVIEW_CHECK_NAME}={status}{suffix}"


def format_copilot_review_status_state(
    copilot_review_status: CommitStatus | None,
) -> str:
    if copilot_review_status is None:
        return f"{COPILOT_REVIEW_STATUS_CONTEXT}=missing"
    return f"{COPILOT_REVIEW_STATUS_CONTEXT}={copilot_review_status['state']}"


def assess_ci_check(ci_check: PRCheck | None) -> GateState:
    if ci_check is None or ci_check["bucket"] == "pending":
        return "running"
    if ci_check["bucket"] == "pass":
        return "green"
    if ci_check["bucket"] == "fail":
        return "action"
    return "terminated"


def assess_copilot_review_check(
    copilot_review_check: CopilotReviewCheck | None,
    copilot_review_status: CommitStatus | None,
) -> GateState:
    status_state = copilot_review_status["state"] if copilot_review_status is not None else None
    if copilot_review_check is None:
        if status_state == "failure":
            return "action"
        if status_state in {"error", "success"}:
            return "terminated"
        return "running"
    if copilot_review_check["status"] != "completed":
        return "running"
    if copilot_review_check["conclusion"] == "success":
        return "green"
    return "terminated"


def assess_copilot_review_status(
    copilot_review_check: CopilotReviewCheck | None,
    copilot_review_status: CommitStatus | None,
) -> GateState:
    if copilot_review_status is None or copilot_review_status["state"] == "pending":
        return "running"
    if copilot_review_status["state"] == "success":
        return "green"
    if copilot_review_status["state"] != "failure":
        return "terminated"
    if copilot_review_check is None or copilot_review_check["status"] != "completed":
        return "action"
    if copilot_review_check["conclusion"] == "success":
        return "action"
    return "terminated"


def fetch_gate_snapshot(owner: str, repo: str, pr: PullRequest) -> GateSnapshot:
    pr_checks = fetch_pr_checks(owner, repo, pr["number"])
    ci_check = find_ci_check(pr_checks)
    copilot_review_check = fetch_copilot_review_check(owner, repo, pr["headRefOid"])
    copilot_review_status = fetch_copilot_review_status(owner, repo, pr["headRefOid"])
    ci_state = assess_ci_check(ci_check)
    copilot_review_check_state = assess_copilot_review_check(
        copilot_review_check,
        copilot_review_status,
    )
    copilot_review_status_state = assess_copilot_review_status(
        copilot_review_check,
        copilot_review_status,
    )
    gate_states = (
        ci_state,
        copilot_review_check_state,
        copilot_review_status_state,
    )
    copilot_threads: list[ReviewThread] = []
    if "running" not in gate_states and "terminated" not in gate_states and copilot_review_check_state == "green":
        copilot_threads = fetch_unresolved_copilot_threads(owner, repo, pr["number"])
    return GateSnapshot(
        pr_checks=pr_checks,
        ci_check=ci_check,
        ci_state=ci_state,
        copilot_review_check=copilot_review_check,
        copilot_review_check_state=copilot_review_check_state,
        copilot_review_status=copilot_review_status,
        copilot_review_status_state=copilot_review_status_state,
        copilot_threads=copilot_threads,
    )


def format_thread_location(thread: ReviewThread) -> str:
    start_line = thread["startLine"]
    end_line = thread["line"]
    if start_line is not None and end_line is not None and start_line != end_line:
        return f"{thread['path']}:{start_line}-{end_line}"
    line = end_line if end_line is not None else start_line
    return f"{thread['path']}:{line}" if line is not None else thread["path"]


def list_failed_ci_checks(pr_checks: list[PRCheck]) -> list[PRCheck]:
    return [
        check
        for check in pr_checks
        if check["bucket"] == "fail" and check["name"].casefold() != COPILOT_REVIEW_STATUS_CONTEXT
    ]


def print_ci_failures(failed_ci_checks: list[PRCheck], pr_url: str) -> None:
    write_line(f"CI FAILURES ({len(failed_ci_checks)})")
    for index, check in enumerate(failed_ci_checks, start=1):
        write_line()
        write_line(f"[{index}/{len(failed_ci_checks)}] {check['name']}")
        if check["workflow"]:
            write_line(f"Workflow: {check['workflow']}")
        write_line(f"State: {check['state'] or check['bucket'].upper()}")
        write_line(f"URL: {check['link'] or pr_url + '/checks'}")


def print_copilot_threads(threads: list[ReviewThread]) -> None:
    write_line(f"UNRESOLVED COPILOT THREADS({len(threads)})")
    for thread_index, thread in enumerate(threads, start=1):
        write_line()
        write_line(f"[{thread_index}/{len(threads)}] {format_thread_location(thread)}")
        write_line(f"Thread ID: {thread['id']}")
        write_line("Use this ID as pullRequestReviewThreadId when replying and threadId when resolving.")
        comments = thread["comments"]["nodes"]
        for comment_index, comment in enumerate(comments, start=1):
            author = comment["author"]["login"] if comment["author"] else "unknown"
            write_line()
            write_line(f"----- COMMENT {comment_index}/{len(comments)} -----")
            write_line(f"Author: {author}")
            write_line(f"URL: {comment['url']}")
            write_line(comment["body"])
            write_line(f"----- END COMMENT {comment_index}/{len(comments)} -----")


def print_copilot_review_action(
    copilot_review_check: CopilotReviewCheck | None,
    copilot_review_status: CommitStatus,
    pr_url: str,
) -> None:
    write_line("COPILOT REVIEW ACTION")
    write_line(f"Status: {COPILOT_REVIEW_STATUS_CONTEXT}={copilot_review_status['state']}")
    description = copilot_review_status.get("description")
    if description:
        write_line(f"Description: {description}")
    check_url = copilot_review_check.get("details_url") if copilot_review_check is not None else None
    write_line("URL: " + (copilot_review_status.get("target_url") or check_url or pr_url + "/checks"))


def print_next_action(
    *,
    has_ci_failures: bool,
    has_copilot_threads: bool,
    has_copilot_review_action: bool,
) -> None:
    actions: list[str] = []
    if has_ci_failures:
        actions.append("Fix every listed CI failure.")
    if has_copilot_threads:
        actions.append(
            "Inspect every listed thread against the current code. Fix valid findings; "
            "explain why invalid findings should not be applied; resolve every addressed thread."
        )
    if has_copilot_review_action:
        actions.append(f"Follow the {COPILOT_REVIEW_STATUS_CONTEXT} instruction above.")
    actions.extend([
        "Run just c until the full gate passes.",
        "Commit all resulting changes, if any.",
        "Run just pr to push and retrigger Copilot review.",
        "Set a 60-second wake-up; when it fires, rerun this script.",
    ])
    write_line("NEXT ACTION")
    for index, action in enumerate(actions, start=1):
        write_line(f"{index}. {action}")


def print_report(
    snapshot: GateSnapshot,
    pr_url: str,
    ahead: int,
) -> None:
    failed_ci_checks = list_failed_ci_checks(snapshot.pr_checks)
    has_copilot_review_action = (
        snapshot.copilot_review_status is not None
        and snapshot.copilot_review_status["state"] == "failure"
        and not snapshot.copilot_threads
    )
    counts: list[str] = []
    if failed_ci_checks:
        counts.append(format_count(len(failed_ci_checks), "CI failure"))
    if snapshot.copilot_threads:
        counts.append(format_count(len(snapshot.copilot_threads), "unresolved Copilot thread"))
    if has_copilot_review_action:
        counts.append(f"{COPILOT_REVIEW_STATUS_CONTEXT} action")
    if ahead:
        counts.append(format_count(ahead, "unpushed commit"))
    if not counts:
        raise_command_error("print action report", "no actionable state was supplied")
    print_step(40, "action required - " + ", ".join(counts))
    write_line()
    if failed_ci_checks:
        print_ci_failures(failed_ci_checks, pr_url)
        write_line()
    if snapshot.copilot_threads:
        print_copilot_threads(snapshot.copilot_threads)
        write_line()
    if has_copilot_review_action and snapshot.copilot_review_status is not None:
        print_copilot_review_action(
            snapshot.copilot_review_check,
            snapshot.copilot_review_status,
            pr_url,
        )
        write_line()
    print_next_action(
        has_ci_failures=bool(failed_ci_checks),
        has_copilot_threads=bool(snapshot.copilot_threads),
        has_copilot_review_action=has_copilot_review_action,
    )


def print_open_pr(pr: PullRequest) -> None:
    mode = "draft" if pr["isDraft"] else "ready"
    print_step(10, f"PR #{pr['number']} is open and {mode} - {pr['url']}")


def format_branch_position(branch_position: BranchPosition | None) -> str:
    if branch_position is None:
        return "working tree clean; branch relation to the PR branch at origin is unavailable"
    ahead = branch_position["ahead"]
    behind = branch_position["behind"]
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
    return branch_position is not None and branch_position["behind"] == 0


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


def format_gate_state(
    snapshot: GateSnapshot,
) -> str:
    return "; ".join([
        format_ci_check_state(snapshot.ci_check),
        format_copilot_review_check_state(snapshot.copilot_review_check),
        format_copilot_review_status_state(snapshot.copilot_review_status),
    ])


def list_gate_states(snapshot: GateSnapshot) -> tuple[GateState, GateState, GateState]:
    return (
        snapshot.ci_state,
        snapshot.copilot_review_check_state,
        snapshot.copilot_review_status_state,
    )


def list_terminated_gates(snapshot: GateSnapshot) -> list[str]:
    gates = [
        (snapshot.ci_state, format_ci_check_state(snapshot.ci_check)),
        (
            snapshot.copilot_review_check_state,
            format_copilot_review_check_state(snapshot.copilot_review_check),
        ),
        (
            snapshot.copilot_review_status_state,
            format_copilot_review_status_state(snapshot.copilot_review_status),
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
    print_step(30, format_gate_state(snapshot))

    terminated_gates = list_terminated_gates(snapshot)
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

    if (
        all(state == "green" for state in gate_states)
        and not snapshot.copilot_threads
        and branch_position["ahead"] == 0
    ):
        print_step(100, "STOP - all three gates are green; nothing to do")
        return

    print_report(snapshot, pr["url"], branch_position["ahead"])


def print_pr_loop_state() -> None:
    print_step(0, "started")
    validate_repo_root()
    for _ in range(SNAPSHOT_ATTEMPTS):
        pr = find_current_pr()
        if pr is None:
            print_step(10, "no open PR found for the current branch")
            print_step(100, "STOP - do nothing")
            return
        if pr["state"] != "OPEN":
            print_step(10, f"PR #{pr['number']} is {pr['state'].lower()} - {pr['url']}")
            print_step(100, "STOP - the PR is not open; do nothing")
            return
        if not is_working_tree_clean():
            print_dirty_working_tree(pr)
            return

        branch_position = inspect_branch_position(pr["headRefOid"])
        if not is_branch_position_safe(branch_position):
            print_unsafe_branch(pr, branch_position)
            return

        owner, repo = parse_pr_repo(pr["url"])
        snapshot = fetch_gate_snapshot(owner, repo, pr)

        confirmed_pr = find_current_pr()
        if (
            confirmed_pr is None
            or confirmed_pr["number"] != pr["number"]
            or confirmed_pr["headRefOid"] != pr["headRefOid"]
        ):
            continue
        if not is_working_tree_clean():
            print_dirty_working_tree(confirmed_pr)
            return
        confirmed_branch_position = inspect_branch_position(confirmed_pr["headRefOid"])
        if confirmed_branch_position is None or confirmed_branch_position != branch_position:
            continue

        print_gate_recommendation(snapshot, confirmed_pr, confirmed_branch_position)
        return

    raise_command_error(
        "print PR loop state",
        f"PR head changed during {SNAPSHOT_ATTEMPTS} consecutive snapshots; rerun this script",
    )


def parse_args() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the current branch's PR gates and unresolved Copilot threads, then direct the review loop."
        )
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
