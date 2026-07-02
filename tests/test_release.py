"""End-to-end tests for `release.py bump` driven through its typer CLI."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from typer.testing import Result

RELEASE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
VERSION_RE = re.compile(r'version:\s*"?([^"\s]+)"?')


def _load_release_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release", RELEASE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["release"] = mod
    spec.loader.exec_module(mod)
    return mod


release = _load_release_module()
runner = CliRunner()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _read_version(skill_md: Path) -> str:
    m = VERSION_RE.search(skill_md.read_text(encoding="utf-8"))
    assert m is not None, f"no version field in {skill_md}"
    return m.group(1)


def _write_skill(path: Path, version: str) -> None:
    path.write_text(
        f'---\nname: {path.parent.name}\ndescription: test skill\nmetadata:\n  version: "{version}"\n---\n',
        encoding="utf-8",
    )


@pytest.fixture
def make_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Init a tmp git repo with `main` and return a factory that places skills in it."""
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(release, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(release, "BASE_REF", "main")
    _git(tmp_path, "init", "-b", "main", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init", "-q")

    def factory(name: str, base: str | None = None, current: str | None = None) -> Path:
        skill_md = tmp_path / "skills" / name / "SKILL.md"
        skill_md.parent.mkdir(parents=True)
        if base is not None:
            _write_skill(skill_md, base)
            _git(tmp_path, "add", ".")
            _git(tmp_path, "commit", "-m", f"add {name}", "-q")
            if current is not None and current != base:
                _write_skill(skill_md, current)
        else:
            _write_skill(skill_md, current or "0.1.0")
        return skill_md

    return factory


def _bump(skill: str, *flags: str) -> Result:
    return runner.invoke(release.app, ["bump", skill, *flags])


@pytest.mark.parametrize(
    ("base", "current", "flag", "expected"),
    [
        ("1.2.3", "1.2.3", "--patch", "1.2.4"),
        ("1.2.3", "1.2.3", "--minor", "1.3.0"),
        ("1.2.3", "1.2.3", "--major", "2.0.0"),
        ("1.2.3", "1.2.4", "--patch", "1.2.4"),
        ("1.2.3", "1.3.0", "--minor", "1.3.0"),
        ("1.2.3", "2.0.0", "--major", "2.0.0"),
        ("1.2.3", "1.3.0", "--patch", "1.3.0"),
        ("1.2.3", "2.0.0", "--minor", "2.0.0"),
        ("1.2.3", "2.0.0", "--patch", "2.0.0"),
        ("1.2.3", "1.2.4", "--minor", "1.3.0"),
        ("1.2.3", "1.2.4", "--major", "2.0.0"),
        ("1.2.3", "1.3.0", "--major", "2.0.0"),
        ("1.2.3", "1.5.0", "--major", "2.0.0"),
        ("9.9.9", "9.9.9", "--patch", "9.9.10"),
        ("9.9.9", "9.9.9", "--minor", "9.10.0"),
        ("9.9.9", "9.9.9", "--major", "10.0.0"),
    ],
)
def test_bump(make_skill: Callable[..., Path], base: str, current: str, flag: str, expected: str) -> None:
    skill_md = make_skill("foo", base, current)
    result = _bump("foo", flag)
    assert result.exit_code == 0, result.output
    assert _read_version(skill_md) == expected


def test_default_bump_is_minor(make_skill: Callable[..., Path]) -> None:
    skill_md = make_skill("foo", "1.2.3")
    result = _bump("foo")
    assert result.exit_code == 0, result.output
    assert _read_version(skill_md) == "1.3.0"


def test_short_patch_flag(make_skill: Callable[..., Path]) -> None:
    skill_md = make_skill("foo", "1.2.3")
    result = _bump("foo", "-p")
    assert result.exit_code == 0, result.output
    assert _read_version(skill_md) == "1.2.4"


def test_unknown_skill_errors(make_skill: Callable[..., Path]) -> None:
    make_skill("foo", "1.0.0")
    result = _bump("ghost", "--patch")
    assert result.exit_code != 0
    assert "unknown skill" in result.output.lower()


def test_skill_not_on_base_ref_is_no_op(make_skill: Callable[..., Path]) -> None:
    skill_md = make_skill("newbie", base=None, current="0.1.0")
    result = _bump("newbie", "--patch")
    assert result.exit_code == 0, result.output
    assert _read_version(skill_md) == "0.1.0"


@pytest.mark.parametrize("skill", ["../evil", "evil/../evil", "..", "sub/evil"])
def test_skill_name_with_path_separators_errors(
    make_skill: Callable[..., Path], tmp_path: Path, skill: str
) -> None:
    make_skill("evil", "1.0.0")
    (tmp_path / "evil").mkdir()
    _write_skill(tmp_path / "evil" / "SKILL.md", "1.0.0")
    result = _bump(skill, "--patch")
    assert result.exit_code != 0
    assert "invalid skill name" in result.output.lower()


def test_conflicting_flags_error(make_skill: Callable[..., Path]) -> None:
    make_skill("foo", "1.0.0")
    result = _bump("foo", "--patch", "--minor")
    assert result.exit_code != 0


def test_help_lists_bump_subcommand() -> None:
    """`release.py --help` must list `bump` as a subcommand.

    Single-command typer apps collapse the subcommand into the root parser by
    default, which would make `release.py bump <skill>` treat `bump` as the
    SKILL argument. The help output is the cheapest signal that subcommand
    mode is intact.
    """
    result = runner.invoke(release.app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "bump" in result.output.lower()
    assert "skill" in result.output.lower()
