"""Common CLI tests for skills whose SKILL.md declares ``metadata.kind: cli``.

Prompt-only skills (kind == 'prompt', or omitted — prompt is the default) are
ignored here; they don't have an executable to exercise. The kind ⇔ file-layout
invariant is enforced by ``tests/test_skills_valid.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from skills_ref import read_properties

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def _is_cli(skill_dir: Path) -> bool:
    if not (skill_dir / "SKILL.md").exists():
        return False
    try:
        props = read_properties(skill_dir)
    except Exception:
        return False
    return (props.metadata or {}).get("kind", "prompt") == "cli"


SKILL_NAMES = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and _is_cli(p))


@pytest.fixture(params=[pytest.param(n, id=n) for n in SKILL_NAMES])
def skill(request, skill_loader):
    return skill_loader(request.param)


def test_help(skill, runner) -> None:
    result = runner.invoke(skill.app, ["--help"])
    assert result.exit_code == 0


def test_version(skill, runner) -> None:
    result = runner.invoke(skill.app, ["--version"])
    assert result.exit_code == 0
    assert skill.__version__ in result.output


def _skill_md_version(skill_dir: Path) -> str:
    text = (skill_dir / "SKILL.md").read_text()
    m = re.search(r'version:\s*"(.+?)"', text)
    return m.group(1) if m else ""


def test_version_consistent(skill, runner) -> None:
    skill_dir = SKILLS_DIR / skill.__name__
    py_version = skill.__version__
    md_version = _skill_md_version(skill_dir)
    pkg_version = json.loads((skill_dir / "package.json").read_text())["version"]
    assert py_version == md_version, f"__version__ ({py_version}) != SKILL.md ({md_version})"
    assert py_version == pkg_version, f"__version__ ({py_version}) != package.json ({pkg_version})"
