"""Story 2: posting a storm item to GitHub through the `stormitem post` CLI.

The `gh` binary is faked at the subprocess boundary — the lowest seam — so the
real argument building for every GitHub call is exercised end to end.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from toon_format import decode

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from typer.testing import CliRunner

ISSUE_URL = "https://github.com/zyplux/zyp-skills/issues/42"
PR_URL = "https://github.com/zyplux/zyp-skills/pull/43"
GIST_URL = "https://gist.github.com/zyplux/0123abc"


class FakeGh:
    """Canned `gh` responses served through a fake `subprocess.run`."""

    def __init__(self, *, push_permission: str = "true", fail_on: str | None = None) -> None:
        self.push_permission = push_permission
        self.fail_on = fail_on
        self.calls: list[list[str]] = []
        self.stdins: list[str | None] = []

    def run(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        args = argv[1:]
        self.calls.append(args)
        self.stdins.append(cast("str | None", kwargs.get("input")))
        if self.fail_on and self.fail_on in " ".join(args):
            raise subprocess.CalledProcessError(1, argv, output="", stderr="boom")
        return subprocess.CompletedProcess(argv, 0, stdout=self._stdout_for(args), stderr="")

    def _stdout_for(self, args: list[str]) -> str:
        joined = " ".join(args)
        canned = [
            (".permissions.push" in joined, f"{self.push_permission}\n"),
            (".default_branch" in joined, "main\n"),
            (".object.sha" in joined, "0123abc\n"),
            (args[:2] == ["issue", "create"], f"{ISSUE_URL}\n"),
            (args[:2] == ["pr", "create"], f"{PR_URL}\n"),
            (args[:2] == ["gist", "create"], f"{GIST_URL}\n"),
        ]
        return next((stdout for matches, stdout in canned if matches), "")

    def call_verbs(self) -> list[str]:
        return [" ".join(call[:2]) for call in self.calls]


@pytest.fixture
def work_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A populated stormitem work dir living under the (redirected) tempdir."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    work = tmp_path / "stormitem-work"
    work.mkdir()
    frontmatter = {
        "title": "feat(peek): julia",
        "labels": ["enhancement"],
        "stormitem": {
            "repo": "zyp-skills",
            "kind": "feat",
            "feature": "peek",
            "title": "julia",
            "slug": "feat_peek_julia",
            "template_used": "builtin:feat",
        },
    }
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False).rstrip()
    (work / "issue.md").write_text(f"---\n{fm_text}\n---\n\n## Summary\n\nAdd Julia support.\n")
    (work / "plan.md").write_text("# Plan\n\nA detailed plan paragraph.\n")
    return work


@pytest.fixture
def install_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")


def _post(runner: CliRunner, stormitem: ModuleType, work_dir: Path) -> object:
    result = runner.invoke(stormitem.app, ["post", "zyp-skills", str(work_dir)])
    assert result.exit_code == 0, result.output
    return decode(result.output.strip())


@pytest.mark.usefixtures("install_gh")
def test_2_1_1_creates_issue_plan_branch_commit_and_draft_pr_through_gh(
    stormitem: ModuleType, runner: CliRunner, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = FakeGh()
    monkeypatch.setattr("subprocess.run", gh.run)

    parsed = _post(runner, stormitem, work_dir)

    assert parsed == {
        "number": 42,
        "url": ISSUE_URL,
        "plan_url": PR_URL,
        "pr_number": 43,
        "mode": "pr",
        "template_used": "builtin:feat",
    }
    assert gh.call_verbs() == [
        "api repos/zyplux/zyp-skills",
        "issue create",
        "api repos/zyplux/zyp-skills",
        "api repos/zyplux/zyp-skills/git/ref/heads/main",
        "api -X",
        "api -X",
        "pr create",
        "issue edit",
    ]
    branch_payload = next(stdin for stdin in gh.stdins if stdin and "refs/heads/" in stdin)
    assert "refs/heads/stormitem/feat_peek_julia" in branch_payload
    plan_commit = next(call for call in gh.calls if any("contents/plan/" in arg for arg in call))
    assert any(arg.endswith("contents/plan/feat_peek_julia/plan.md") for arg in plan_commit)
    pr_create = next(call for call in gh.calls if call[:2] == ["pr", "create"])
    assert "--draft" in pr_create
    assert any("Closes #42" in arg for arg in pr_create)


@pytest.mark.usefixtures("install_gh")
def test_2_1_2_falls_back_to_a_gist_when_push_permission_is_missing(
    stormitem: ModuleType, runner: CliRunner, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = FakeGh(push_permission="false")
    monkeypatch.setattr("subprocess.run", gh.run)

    parsed = _post(runner, stormitem, work_dir)

    assert parsed == {
        "number": 42,
        "url": ISSUE_URL,
        "plan_url": GIST_URL,
        "pr_number": None,
        "mode": "gist",
        "template_used": "builtin:feat",
    }
    gist_create = next(call for call in gh.calls if call[:2] == ["gist", "create"])
    assert str(work_dir / "plan.md") in gist_create
    issue_create = next(call for call in gh.calls if call[:2] == ["issue", "create"])
    assert any(GIST_URL in arg for arg in issue_create)


@pytest.mark.usefixtures("install_gh")
def test_2_2_1_reports_the_failing_step_when_a_gh_call_errors(
    stormitem: ModuleType, runner: CliRunner, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = FakeGh(fail_on="issue create")
    monkeypatch.setattr("subprocess.run", gh.run)

    result = runner.invoke(stormitem.app, ["post", "zyp-skills", str(work_dir)])

    assert result.exit_code == 1
    assert "failed at step 'issue create'" in result.output + result.stderr
    assert "boom" in result.output + result.stderr


def test_2_2_2_fails_when_gh_is_missing_from_path(
    stormitem: ModuleType, runner: CliRunner, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _tool: None)

    result = runner.invoke(stormitem.app, ["post", "zyp-skills", str(work_dir)])

    assert result.exit_code != 0
    assert isinstance(result.exception, stormitem.ToolNotFoundError)
