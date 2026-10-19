from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "skills" / "resolve-pr-gate" / "scripts" / "pr_loop_state.py"
HEAD_OID = "a" * 40

GIT_STUB = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

snapshot = json.loads(Path(os.environ["FAKE_GITHUB_RESPONSES"]).read_text())
arguments = sys.argv[1:]
if arguments == ["rev-parse", "--show-toplevel"]:
    print(os.environ["FAKE_REPO_ROOT"])
elif arguments == ["rev-parse", "HEAD"]:
    print(snapshot.get("local_head_oid", snapshot["head_oid"]))
elif arguments[:3] == ["status", "--porcelain=v1", "--untracked-files=all"]:
    if snapshot.get("dirty"):
        print(" M example.py")
elif arguments[:3] == ["rev-list", "--left-right", "--count"]:
    pr_head = arguments[-1].split("...")[0]
    default_counts = "0 0" if pr_head == snapshot["head_oid"] else "1 0"
    print(snapshot.get("branch_counts", default_counts))
else:
    raise SystemExit(f"unexpected git arguments: {arguments}")
"""

GH_STUB = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

responses_path = Path(os.environ["FAKE_GITHUB_RESPONSES"])
snapshot = json.loads(responses_path.read_text())
arguments = sys.argv[1:]
with Path(os.environ["FAKE_COMMAND_LOG"]).open("a") as log:
    log.write(json.dumps(arguments) + "\n")
if arguments[:2] == ["pr", "view"]:
    if snapshot.get("no_pr"):
        sys.stderr.write("no pull requests found")
        raise SystemExit(1)
    counter = responses_path.with_suffix(".reads")
    reads = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(reads + 1))
    heads = snapshot.get("head_reads", [snapshot["head_oid"]])
    states = snapshot.get("pr_states", [snapshot.get("pr_state", "OPEN")])
    drafts = snapshot.get("draft_reads", [snapshot.get("is_draft", False)])
    payload = {
        "headRefOid": heads[min(reads, len(heads) - 1)],
        "isDraft": drafts[min(reads, len(drafts) - 1)],
        "number": 13,
        "state": states[min(reads, len(states) - 1)],
        "url": "https://github.com/zyplux/zyp-skills/pull/13",
    }
elif arguments[:2] == ["pr", "checks"]:
    payload = snapshot["checks"]
elif arguments[:2] == ["api", "graphql"]:
    if "--paginate" not in arguments or "--slurp" not in arguments:
        raise SystemExit("review threads must use pagination")
    query = next(argument for argument in arguments if argument.startswith("query="))
    if "pageInfo" not in query or "$endCursor" not in query or "after:$endCursor" not in query:
        raise SystemExit("review threads must expose the pagination cursor")
    if snapshot.get("graphql_errors"):
        payload = [{"errors": [{"message": "API denied"}]}]
    else:
        payload = [
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}
            for nodes in snapshot["thread_pages"]
        ]
elif arguments[0] == "api" and "/statuses?" in arguments[1]:
    if "--paginate" not in arguments or "--slurp" not in arguments:
        raise SystemExit("commit statuses must use pagination")
    if f"/commits/{snapshot['head_oid']}/statuses?" not in arguments[1]:
        raise SystemExit("status must be fetched for the PR head")
    payload = snapshot["status_pages"]
else:
    raise SystemExit(f"unexpected gh arguments: {arguments}")

print(json.dumps(payload))
"""


def save_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def build_status(state: str, description: str = "Bot review verdict") -> dict[str, object]:
    return {
        "context": "bot-review-complete",
        "description": description,
        "state": state,
        "target_url": "review-url",
    }


def build_thread(author: str, *, is_resolved: bool = False) -> dict[str, object]:
    return {
        "id": f"{author}-thread",
        "isResolved": is_resolved,
        "path": "example.py",
        "startLine": 10,
        "line": 10,
        "comments": {"nodes": [{"body": "Review finding", "url": "thread-url", "author": {"login": author}}]},
    }


def run_script(tmp_path: Path, changes: dict[str, object] | None = None) -> subprocess.CompletedProcess[str]:
    commands_dir = tmp_path / "bin"
    commands_dir.mkdir()
    save_command(commands_dir / "git", GIT_STUB)
    save_command(commands_dir / "gh", GH_STUB)
    responses_path = tmp_path / "github.json"
    thread_pages: list[list[dict[str, object]]] = [[]]
    snapshot = {
        "head_oid": HEAD_OID,
        "checks": [
            {"bucket": "pass", "link": "ci-url", "name": "ci", "state": "SUCCESS", "workflow": "ci"},
            {
                "bucket": "fail",
                "link": "copilot-url",
                "name": "copilot-pull-request-reviewer",
                "state": "FAILURE",
                "workflow": "Copilot code review",
            },
        ],
        "status_pages": [[build_status("success")]],
        "thread_pages": thread_pages,
    } | (changes or {})
    responses_path.write_text(json.dumps(snapshot), encoding="utf-8")
    environment = os.environ | {
        "FAKE_REPO_ROOT": str(tmp_path),
        "FAKE_GITHUB_RESPONSES": str(responses_path),
        "FAKE_COMMAND_LOG": str(tmp_path / "commands.jsonl"),
        "PATH": os.pathsep.join([str(commands_dir), os.environ["PATH"]]),
    }
    return subprocess.run(
        [SCRIPT_PATH],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize(
    "description",
    [
        "Copilot and Codex reviews are clean",
        "Copilot quota exhausted; Codex review clean",
        "Copilot review clean; Codex quota exhausted",
    ],
)
def test_aggregate_success_completes_despite_a_native_bot_failure(tmp_path: Path, description: str) -> None:
    completed = run_script(tmp_path, {"status_pages": [[build_status("success", description)]]})

    assert completed.returncode == 0, completed.stderr
    assert "ci=pass; bot-review-complete=success" in completed.stdout
    assert "STOP - ci and bot-review-complete are green; no unresolved bot threads; nothing to do" in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


@pytest.mark.parametrize(
    "status_pages",
    [
        [[]],
        [[build_status("pending")]],
        [
            [build_status("pending")],
            [build_status("success")],
        ],
    ],
)
def test_missing_pending_and_superseded_success_never_complete(
    tmp_path: Path,
    status_pages: list[list[dict[str, object]]],
) -> None:
    completed = run_script(tmp_path, {"status_pages": status_pages})

    assert completed.returncode == 0, completed.stderr
    assert "wait for the pending gates" in completed.stdout
    assert "are green" not in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_review_status_is_found_on_later_pages(tmp_path: Path) -> None:
    unrelated = build_status("failure") | {"context": "another-check"}
    completed = run_script(tmp_path, {"status_pages": [[unrelated] * 100, [build_status("success")]]})

    assert completed.returncode == 0, completed.stderr
    assert "are green" in completed.stdout


def test_findings_from_both_bots_are_reported_across_pages(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        {
            "status_pages": [[build_status("failure")]],
            "thread_pages": [
                [build_thread("copilot-pull-request-reviewer[bot]"), build_thread("copilot", is_resolved=True)],
                [build_thread("chatgpt-codex-connector"), build_thread("copilot-imposter")],
            ],
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert "UNRESOLVED BOT THREADS (2)" in completed.stdout
    assert "Author: copilot-pull-request-reviewer[bot]" in completed.stdout
    assert "Author: chatgpt-codex-connector" in completed.stdout
    assert "copilot-imposter" not in completed.stdout
    assert "gh workflow run org_gate.yml --repo zyplux/zyp-skills -f pr=13" in completed.stdout
    assert "are green" not in completed.stdout


def test_unresolved_threads_block_a_previously_successful_verdict(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"thread_pages": [[build_thread("chatgpt-codex-connector[bot]")]]})

    assert completed.returncode == 0, completed.stderr
    assert "UNRESOLVED BOT THREADS (1)" in completed.stdout
    assert "are green" not in completed.stdout


def test_both_reviewers_unavailable_reports_the_gate_failure(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        {
            "status_pages": [
                [
                    build_status(
                        "failure",
                        "Both review bots are unavailable; a clean review is required",
                    )
                ]
            ]
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert "BOT REVIEW ACTION" in completed.stdout
    assert "Both review bots are unavailable" in completed.stdout
    assert "stop and report unavailable reviewers" in completed.stdout
    assert "are green" not in completed.stdout


def test_ci_failures_are_actionable_while_review_is_pending(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        {
            "checks": [{"bucket": "fail", "link": "ci-url", "name": "ci", "state": "FAILURE", "workflow": "ci"}],
            "status_pages": [[build_status("pending")]],
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert "CI FAILURES (1)\n\n[1/1] ci" in completed.stdout
    assert "NEXT ACTION" in completed.stdout
    assert "wait for the pending gates" not in completed.stdout


def test_watcher_failure_is_actionable_when_no_status_was_published(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        {
            "checks": [
                {"bucket": "pass", "link": "ci-url", "name": "ci", "state": "SUCCESS", "workflow": "ci"},
                {
                    "bucket": "fail",
                    "link": "watcher-url",
                    "name": "org_gate_base / bot_review_watcher",
                    "state": "FAILURE",
                    "workflow": "org_gate",
                },
            ],
            "status_pages": [[]],
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert "CI FAILURES (1)\n\n[1/1] org_gate_base / bot_review_watcher" in completed.stdout
    assert "URL: watcher-url" in completed.stdout
    assert "NEXT ACTION" in completed.stdout


def test_gate_error_is_actionable_without_reporting_success(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"status_pages": [[build_status("error")]]})

    assert completed.returncode == 0, completed.stderr
    assert "BOT REVIEW ACTION\nStatus: bot-review-complete=error" in completed.stdout
    assert "NEXT ACTION" in completed.stdout
    assert "are green" not in completed.stdout


def test_unknown_gate_states_stop_without_reporting_success(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"status_pages": [[build_status("unknown")]]})

    assert completed.returncode == 0, completed.stderr
    assert "STOP - gate terminated without success: bot-review-complete=unknown" in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_pending_verdict_explains_which_review_is_missing(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"status_pages": [[build_status("pending", "Waiting for Codex review")]]})

    assert completed.returncode == 0, completed.stderr
    assert "bot-review-complete=pending (Waiting for Codex review)" in completed.stdout
    assert "are green" not in completed.stdout


@pytest.mark.parametrize("branch_counts", ["1 0", "1 1", ""])
def test_unsafe_branch_relations_stop_before_gate_actions(tmp_path: Path, branch_counts: str) -> None:
    completed = run_script(tmp_path, {"branch_counts": branch_counts})

    assert completed.returncode == 0, completed.stderr
    assert "STOP - inform the user; do not continue until the branch relation is safe" in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_dirty_working_tree_stops_before_gate_actions(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"dirty": True})

    assert completed.returncode == 0, completed.stderr
    assert "70: if you recognise all local changes as yours, commit them without pushing" in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_unpushed_commits_require_checks_and_push(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"local_head_oid": "b" * 40, "branch_counts": "0 1"})

    assert completed.returncode == 0, completed.stderr
    assert "1 unpushed commit" in completed.stdout
    assert "run just c" in completed.stdout
    assert "run just pr to push and request review" in completed.stdout
    assert "are green" not in completed.stdout


def test_head_changes_invalidate_the_snapshot(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"head_reads": [HEAD_OID, "b" * 40]})

    assert completed.returncode == 0, completed.stderr
    assert "branch relation is safe" in completed.stdout
    assert "are green" not in completed.stdout


def test_closed_pr_changes_invalidate_the_snapshot(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"pr_states": ["OPEN", "MERGED"]})

    assert completed.returncode == 0, completed.stderr
    assert "STOP - the PR is not open" in completed.stdout
    assert "are green" not in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


@pytest.mark.parametrize("drafts", [[True], [False, True]])
def test_draft_pull_requests_need_a_ready_transition(tmp_path: Path, drafts: list[bool]) -> None:
    completed = run_script(tmp_path, {"draft_reads": drafts})

    assert completed.returncode == 0, completed.stderr
    assert "gh pr ready https://github.com/zyplux/zyp-skills/pull/13" in completed.stdout
    assert "are green" not in completed.stdout


@pytest.mark.parametrize("changes", [{"no_pr": True}, {"pr_state": "MERGED"}])
def test_absent_or_closed_pull_requests_stop(tmp_path: Path, changes: dict[str, object]) -> None:
    completed = run_script(tmp_path, changes)

    assert completed.returncode == 0, completed.stderr
    assert "STOP - " in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_unreadable_threads_cannot_complete_the_gate(tmp_path: Path) -> None:
    completed = run_script(tmp_path, {"graphql_errors": True})

    assert completed.returncode == 1
    assert "are green" not in completed.stdout
