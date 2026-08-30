from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "skills" / "resolve-pr-review-comments" / "scripts" / "pr_loop_state.py"
)
HEAD_OID = "a" * 40

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
import sys

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
    payload = [
        {{"bucket": "fail", "link": "ci-url", "name": "ci", "state": "FAILURE", "workflow": "ci"}},
        {{
            "bucket": "fail",
            "link": "review-url",
            "name": "copilot-pull-request-reviewer",
            "state": "FAILURE",
            "workflow": "",
        }},
        {{
            "bucket": "fail",
            "link": "status-url",
            "name": "copilot-review-complete",
            "state": "FAILURE",
            "workflow": "",
        }},
    ]
elif arguments[0] == "api" and "check-runs" in arguments[1]:
    payload = {{
        "check_runs": [{{
            "conclusion": "success",
            "details_url": "review-url",
            "name": "copilot-pull-request-reviewer",
            "status": "completed",
        }}]
    }}
elif arguments[0] == "api" and "statuses" in arguments[1]:
    payload = [{{
        "context": "copilot-review-complete",
        "description": "Resolve review comments",
        "state": "failure",
        "target_url": "status-url",
    }}]
elif arguments[:2] == ["api", "graphql"]:
    payload = {{
        "data": {{
            "repository": {{
                "pullRequest": {{
                    "reviewThreads": {{
                        "nodes": [{{
                            "id": "thread-id",
                            "isResolved": False,
                            "path": "example.py",
                            "startLine": 10,
                            "line": 10,
                            "comments": {{
                                "nodes": [{{
                                    "body": "Review finding",
                                    "url": "thread-url",
                                    "author": {{"login": "copilot-pull-request-reviewer"}},
                                }}]
                            }},
                        }}]
                    }}
                }}
            }}
        }}
    }}
else:
    raise SystemExit(f"unexpected gh arguments: {{arguments}}")

print(json.dumps(payload))
"""


def save_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def test_action_report_separates_copilot_gates(tmp_path: Path) -> None:
    commands_dir = tmp_path / "bin"
    commands_dir.mkdir()
    save_command(commands_dir / "git", GIT_STUB)
    save_command(commands_dir / "gh", GH_STUB)
    environment = os.environ | {
        "FAKE_REPO_ROOT": str(tmp_path),
        "PATH": os.pathsep.join([str(commands_dir), os.environ["PATH"]]),
    }

    completed = subprocess.run(
        [SCRIPT_PATH],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "CI FAILURES (1)\n\n[1/1] ci" in completed.stdout
    assert "[2/" not in completed.stdout
    assert "UNRESOLVED COPILOT THREADS (1)" in completed.stdout
    assert "Wait 3 minutes, then rerun this script." in completed.stdout
