from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "skills" / "resolve-pr-codex-threads" / "scripts" / "pr_loop_state.py"
)
HEAD_OID = "a" * 40
CODEX_SUMMARY = """<!-- codex-pull-request-review-summary -->
<!-- codex-security-review:v1 {"status":"completed"} -->
## Codex Review Summary

| Review | Status | Commit | Review trigger |
| --- | --- | --- | --- |
| 📝 **Code Review** | ✅ **Completed** | `aaaaaaa` | New commits |
| 🔒 **Security Review** | ✅ **Completed** | `aaaaaaa` | New commits |
"""

GIT_STUB = f"""#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
if arguments == ["rev-parse", "--show-toplevel"]:
    print(os.environ["FAKE_REPO_ROOT"])
elif arguments == ["rev-parse", "HEAD"]:
    print("{HEAD_OID}")
elif arguments[:3] == ["status", "--porcelain=v1", "--untracked-files=all"]:
    pass
elif arguments[:3] == ["rev-list", "--left-right", "--count"]:
    print("0 0")
else:
    raise SystemExit(f"unexpected git arguments: {{arguments}}")
"""

GH_STUB = f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

responses = json.loads(Path(os.environ["FAKE_GITHUB_RESPONSES"]).read_text())
arguments = sys.argv[1:]
if arguments[:2] == ["pr", "view"]:
    payload = {{
        "headRefOid": "{HEAD_OID}",
        "isDraft": False,
        "number": 13,
        "state": "OPEN",
        "url": "https://github.com/zyplux/zyp-skills/pull/13",
    }}
elif arguments[:2] == ["pr", "checks"]:
    payload = responses["checks"]
elif arguments[:2] == ["api", "graphql"]:
    if "--paginate" not in arguments or "--slurp" not in arguments:
        raise SystemExit("GraphQL connections must use pagination")
    query = next(argument for argument in arguments if argument.startswith("query="))
    connection = "reviewThreads" if "reviewThreads(" in query else "comments"
    payload = [
        {{"data": {{"repository": {{"pullRequest": {{connection: {{"nodes": nodes}}}}}}}}}}
        for nodes in responses[connection]
    ]
else:
    raise SystemExit(f"unexpected gh arguments: {{arguments}}")

print(json.dumps(payload))
"""


def save_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def build_comment(body: str, author_login: str = "chatgpt-codex-connector") -> dict[str, object]:
    return {"body": body, "url": "summary-url", "author": {"login": author_login}}


def build_thread(author_login: str, *, is_resolved: bool = False) -> dict[str, object]:
    return {
        "id": "thread-id",
        "isResolved": is_resolved,
        "path": "example.py",
        "startLine": 10,
        "line": 10,
        "comments": {"nodes": [build_comment("Review finding", author_login)]},
    }


def run_script(
    tmp_path: Path,
    *,
    ci_bucket: str = "pass",
    comment_pages: list[list[dict[str, object]]] | None = None,
    thread_pages: list[list[dict[str, object]]] | None = None,
) -> subprocess.CompletedProcess[str]:
    commands_dir = tmp_path / "bin"
    commands_dir.mkdir()
    save_command(commands_dir / "git", GIT_STUB)
    save_command(commands_dir / "gh", GH_STUB)
    responses_path = tmp_path / "github.json"
    responses_path.write_text(
        json.dumps({
            "checks": [
                {"bucket": ci_bucket, "link": "ci-url", "name": "ci", "state": ci_bucket.upper(), "workflow": "ci"},
                {
                    "bucket": "fail",
                    "link": "copilot-url",
                    "name": "copilot-pull-request-reviewer",
                    "state": "FAILURE",
                    "workflow": "",
                },
                {
                    "bucket": "fail",
                    "link": "copilot-status-url",
                    "name": "copilot-review-complete",
                    "state": "FAILURE",
                    "workflow": "",
                },
            ],
            "comments": [[build_comment(CODEX_SUMMARY)]] if comment_pages is None else comment_pages,
            "reviewThreads": [[]] if thread_pages is None else thread_pages,
        }),
        encoding="utf-8",
    )
    environment = os.environ | {
        "FAKE_REPO_ROOT": str(tmp_path),
        "FAKE_GITHUB_RESPONSES": str(responses_path),
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


def test_action_report_collects_codex_findings_across_pages(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        ci_bucket="fail",
        comment_pages=[
            [build_comment("An ordinary discussion"), build_comment(CODEX_SUMMARY, "another-user")],
            [build_comment(CODEX_SUMMARY, "chatgpt-codex-connector[bot]")],
        ],
        thread_pages=[
            [build_thread("copilot-pull-request-reviewer"), build_thread("chatgpt-codex-connector", is_resolved=True)],
            [build_thread("chatgpt-codex-connector")],
        ],
    )

    assert completed.returncode == 0, completed.stderr
    assert "CI FAILURES (1)\n\n[1/1] ci" in completed.stdout
    assert "UNRESOLVED CODEX THREADS (1)\n\n[1/1] example.py:10\nThread ID: thread-id" in completed.stdout
    assert "Author: chatgpt-codex-connector\nURL: summary-url\nReview finding" in completed.stdout
    assert "Commit resulting changes, if any, then push unpushed commits with git push." in completed.stdout
    assert "gh pr comment https://github.com/zyplux/zyp-skills/pull/13 --body '@codex review'." in completed.stdout
    assert "After requesting review, wait 3 minutes; otherwise rerun this script now." in completed.stdout
    assert "just pr" not in completed.stdout
    assert "copilot" not in completed.stdout


def test_completed_current_review_finishes_without_copilot(tmp_path: Path) -> None:
    completed = run_script(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "ci=pass; codex-review=completed (aaaaaaa)" in completed.stdout
    assert "STOP - ci and Codex review are green; no unresolved Codex threads; nothing to do" in completed.stdout


def test_completed_security_review_does_not_finish_running_code_review(tmp_path: Path) -> None:
    summary = CODEX_SUMMARY.replace("📝 **Code Review** | ✅ **Completed**", "📝 **Code Review** | 🔄 **Running**")
    completed = run_script(tmp_path, comment_pages=[[build_comment(summary)]])

    assert completed.returncode == 0, completed.stderr
    assert "ci=pass; codex-review=running (aaaaaaa)" in completed.stdout
    assert "wait for every running gate to finish; set a 60-second wake-up" in completed.stdout
    assert "are green" not in completed.stdout
    assert "@codex review" not in completed.stdout


@pytest.mark.parametrize(
    ("comment_pages", "expected_state"),
    [
        ([[]], "codex-review=missing"),
        ([[build_comment(CODEX_SUMMARY.replace("aaaaaaa", "bbbbbbb"))]], "codex-review=stale (bbbbbbb)"),
    ],
)
def test_missing_or_stale_review_requests_current_review(
    tmp_path: Path, comment_pages: list[list[dict[str, object]]], expected_state: str
) -> None:
    completed = run_script(tmp_path, comment_pages=comment_pages)

    assert completed.returncode == 0, completed.stderr
    assert expected_state in completed.stdout
    assert "CODEX REVIEW ACTION" in completed.stdout
    assert (
        "Request a code review: gh pr comment https://github.com/zyplux/zyp-skills/pull/13 --body '@codex review'."
        in completed.stdout
    )
    assert "just c" not in completed.stdout
    assert "just pr" not in completed.stdout


def test_failed_code_review_stops_the_loop(tmp_path: Path) -> None:
    summary = CODEX_SUMMARY.replace("📝 **Code Review** | ✅ **Completed**", "📝 **Code Review** | ❌ **Failed**")
    completed = run_script(tmp_path, comment_pages=[[build_comment(summary)]])

    assert completed.returncode == 0, completed.stderr
    assert "STOP - gate terminated without success: codex-review=failed (aaaaaaa); inform the user" in completed.stdout
    assert "NEXT ACTION" not in completed.stdout


def test_unreadable_codex_summary_reports_an_error(tmp_path: Path) -> None:
    completed = run_script(
        tmp_path,
        comment_pages=[[build_comment("<!-- codex-pull-request-review-summary -->\nUnexpected format")]],
    )

    assert completed.returncode == 1
    assert (
        "error: `parse Codex summary` failed: Code Review status or commit is unavailable: summary-url"
        in completed.stderr
    )
    assert "are green" not in completed.stdout
