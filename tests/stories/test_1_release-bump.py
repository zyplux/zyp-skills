"""Story 1: bumping a skill release version through the `release.py bump` CLI."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    from typer.testing import CliRunner


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _skill_md(name: str, version_line: str) -> str:
    return f"---\nname: {name}\ndescription: test skill\nmetadata:\n{version_line}---\n"


@pytest.fixture
def skill_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, release: ModuleType) -> Callable[..., Path]:
    """Init a tmp git repo with `main` and return a factory that commits a skill into it."""
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(release, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(release, "BASE_REF", "main")
    _git(tmp_path, "init", "-b", "main", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")

    def commit_skill(name: str, version: str, *, with_py: bool = False, with_package_json: bool = False) -> Path:
        skill_dir = tmp_path / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill_md(name, f'  version: "{version}"\n'), encoding="utf-8")
        if with_py:
            (skill_dir / f"{name}.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        if with_package_json:
            (skill_dir / "package.json").write_text(json.dumps({"name": name, "version": version}) + "\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", f"add {name}", "-q")
        return skill_dir

    return commit_skill


def test_1_1_1_updates_skill_md_py_module_and_package_json_together(
    skill_repo: Callable[..., Path], release: ModuleType, runner: CliRunner
) -> None:
    skill_dir = skill_repo("peek", "1.2.3", with_py=True, with_package_json=True)

    result = runner.invoke(release.app, ["bump", "peek"])

    assert result.exit_code == 0, result.output
    assert 'version: "1.3.0"' in (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert (skill_dir / "peek.py").read_text(encoding="utf-8") == '__version__ = "1.3.0"\n'
    assert json.loads((skill_dir / "package.json").read_text())["version"] == "1.3.0"


def test_1_2_1_rejects_a_skill_md_version_that_is_not_semver(
    skill_repo: Callable[..., Path], release: ModuleType, runner: CliRunner
) -> None:
    skill_dir = skill_repo("peek", "1.0.0")
    (skill_dir / "SKILL.md").write_text(_skill_md("peek", "  version: banana\n"), encoding="utf-8")

    result = runner.invoke(release.app, ["bump", "peek"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)


def test_1_2_2_rejects_a_skill_md_with_no_version_field(
    skill_repo: Callable[..., Path], release: ModuleType, runner: CliRunner
) -> None:
    skill_dir = skill_repo("peek", "1.0.0")
    (skill_dir / "SKILL.md").write_text(_skill_md("peek", ""), encoding="utf-8")

    result = runner.invoke(release.app, ["bump", "peek"])

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)


def test_1_3_1_fails_when_git_is_missing_from_path(
    skill_repo: Callable[..., Path],
    release: ModuleType,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_repo("peek", "1.0.0")
    monkeypatch.setattr("shutil.which", Mock(return_value=None))

    result = runner.invoke(release.app, ["bump", "peek"])

    assert result.exit_code != 0
    assert isinstance(result.exception, release.ToolNotFoundError)


def test_1_4_1_rejects_a_changed_skill_whose_version_still_matches_its_latest_tag(
    skill_repo: Callable[..., Path], release: ModuleType
) -> None:
    skill_dir = skill_repo("peek", "1.2.3", with_py=True)
    _git(skill_dir.parents[1], "tag", "peek-v1.2.3")
    (skill_dir / "peek.py").write_text('__version__ = "1.2.3"\nprint("changed")\n', encoding="utf-8")

    with pytest.raises(release.ReleaseValidationError, match=r"peek changed since peek-v1\.2\.3"):
        release.validate_release_versions()


def test_1_4_2_accepts_a_changed_skill_whose_version_is_ahead_of_its_latest_tag(
    skill_repo: Callable[..., Path], release: ModuleType
) -> None:
    skill_dir = skill_repo("peek", "1.2.3", with_py=True)
    _git(skill_dir.parents[1], "tag", "peek-v1.2.3")
    (skill_dir / "SKILL.md").write_text(_skill_md("peek", '  version: "1.3.0"\n'), encoding="utf-8")
    (skill_dir / "peek.py").write_text('__version__ = "1.3.0"\nprint("changed")\n', encoding="utf-8")

    release.validate_release_versions()


def test_1_4_3_rejects_a_skill_version_below_its_latest_tag(
    skill_repo: Callable[..., Path], release: ModuleType
) -> None:
    skill_dir = skill_repo("peek", "1.2.3")
    _git(skill_dir.parents[1], "tag", "peek-v1.2.3")
    (skill_dir / "SKILL.md").write_text(_skill_md("peek", '  version: "1.2.2"\n'), encoding="utf-8")

    with pytest.raises(release.ReleaseValidationError, match=r"peek version 1\.2\.2 is below peek-v1\.2\.3"):
        release.validate_release_versions()


def test_1_4_4_accepts_a_new_skill_without_a_release_tag(skill_repo: Callable[..., Path], release: ModuleType) -> None:
    skill_repo("new-skill", "0.1.0")

    release.validate_release_versions()


def test_1_4_5_check_command_reports_the_release_violation(
    skill_repo: Callable[..., Path], release: ModuleType, runner: CliRunner
) -> None:
    skill_dir = skill_repo("peek", "1.2.3", with_py=True)
    _git(skill_dir.parents[1], "tag", "peek-v1.2.3")
    (skill_dir / "peek.py").write_text('__version__ = "1.2.3"\nprint("changed")\n', encoding="utf-8")

    result = runner.invoke(release.app, ["check"])

    assert result.exit_code != 0
    assert "peek changed since peek-v1.2.3" in result.output
