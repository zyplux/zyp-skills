"""pusher — push the current branch and either open a draft PR or mark it ready.

Default flow (no flags) pushes the current branch and opens a draft PR against
`main`, or leaves an existing draft alone. Pass `--ready` (or `-r`) to mark the
PR ready and enable auto-merge: GitHub will squash-merge and delete the branch
once required checks pass and review conversations are resolved.

Only committed changes are pushed; staged-but-uncommitted changes stay local.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LEADING_H1_RE = re.compile(r"\A\s*#\s.*?(?:\n|\Z)")
BLANK_RUN_RE = re.compile(r"\n{2,}")


class ToolNotFoundError(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"`{tool}` not found on PATH")


def _run(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """The single audited subprocess boundary for pusher.

    `args[0]` is resolved to an absolute path via PATH, the remaining args are
    program-constructed (never user-derived), and the shell is never invoked, so
    there is no command-injection surface.
    """
    executable = shutil.which(args[0])
    if executable is None:
        raise ToolNotFoundError(args[0])
    return subprocess.run([executable, *args[1:]], cwd=REPO_ROOT, text=True, check=check, capture_output=capture)


def _git(*args: str) -> str:
    return _run("git", *args, capture=True).stdout.strip()


def _gh(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("gh", *args, capture=capture, check=check)


def _current_branch() -> str:
    return _git("branch", "--show-current")


def _pr_view() -> dict | None:
    proc = _gh("pr", "view", "--json", "number,url,isDraft,state,body", check=False)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)


def _clean_body(body: str) -> str:
    body = HTML_COMMENT_RE.sub("", body)
    body = LEADING_H1_RE.sub("", body, count=1)
    body = BLANK_RUN_RE.sub("\n", body)
    return body.strip()


def main(
    ready: bool = typer.Option(False, "--ready", "-r", help="Mark PR ready and enable auto-merge."),
) -> None:
    """Push the current branch and either open a draft PR or mark it ready."""
    branch = _current_branch()
    if not branch:
        typer.echo("not on any branch (detached HEAD?)", err=True)
        raise typer.Exit(1)
    if branch == "main":
        typer.echo("refusing to run on main", err=True)
        raise typer.Exit(1)

    pr = _pr_view()
    if pr is not None and pr.get("state") == "MERGED":
        typer.echo(f"PR #{pr['number']} merged; switching to main and deleting local branch '{branch}'")
        _run("git", "checkout", "main")
        _run("git", "pull", "--ff-only")
        _run("git", "branch", "-D", branch)
        return

    _run("git", "push", "-u", "origin", branch)

    if pr is None:
        template_path = REPO_ROOT / ".github" / "pull_request_template.md"
        draft_flag = [] if ready else ["--draft"]
        _gh(
            "pr",
            "create",
            "--base",
            "main",
            "--title",
            branch,
            "--body-file",
            str(template_path),
            *draft_flag,
            capture=False,
        )
        pr = _pr_view()
        assert pr is not None, "PR creation succeeded but `gh pr view` failed"
    elif ready:
        original_body = pr.get("body") or ""
        cleaned = _clean_body(original_body)
        if cleaned != original_body.strip():
            _gh("pr", "edit", str(pr["number"]), "--body", cleaned, capture=False)
        if pr.get("isDraft"):
            _gh("pr", "ready", check=False, capture=False)
            pr = _pr_view() or pr

    url = pr["url"]
    number = pr["number"]

    if not ready:
        typer.echo(f"PR (draft): {url}")
        return

    _gh(
        "pr",
        "merge",
        str(number),
        "--auto",
        "--squash",
        "--delete-branch",
        check=False,
        capture=False,
    )
    typer.echo(f"PR (ready, auto-merge enabled): {url}")


if __name__ == "__main__":
    try:
        typer.run(main)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
