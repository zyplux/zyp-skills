"""Validate every skill in the repo against the Agent Skills spec."""

import re
from pathlib import Path

import pytest
from skills_ref import read_properties, validate

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
SKILL_DIRS = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


@pytest.fixture(params=[pytest.param(d, id=d.name) for d in SKILL_DIRS])
def skill_dir(request: pytest.FixtureRequest) -> Path:
    return request.param


def test_skill_validates(skill_dir: Path) -> None:
    errors = validate(skill_dir)
    assert errors == [], f"Validation errors in {skill_dir.name}: {errors}"


def test_skill_has_required_properties(skill_dir: Path) -> None:
    props = read_properties(skill_dir)
    assert props.name, "name must be non-empty"
    assert props.description, "description must be non-empty"


def test_skill_has_semver_version(skill_dir: Path) -> None:
    """metadata.version must be present and follow MAJOR.MINOR.PATCH (no pre-release)."""
    metadata = read_properties(skill_dir).metadata or {}
    version = metadata.get("version")
    assert version is not None, (
        f"Skill '{skill_dir.name}' is missing metadata.version. "
        f'Add a semver string (e.g. version: "0.1.0") to the frontmatter.'
    )
    assert SEMVER_RE.match(version), (
        f"Skill '{skill_dir.name}' has metadata.version={version!r}; "
        f"expected MAJOR.MINOR.PATCH with no pre-release suffix."
    )


def test_skill_kind_matches_layout(skill_dir: Path) -> None:
    """metadata.kind agrees with the on-disk layout.

    kind == 'cli'    ⇒ <name>.py must exist (it's the executable the skill ships).
    kind == 'prompt' ⇒ <name>.py must NOT exist (prompt-only skills are SKILL.md-driven).
    kind omitted     ⇒ treated as 'prompt' (default).
    """
    props = read_properties(skill_dir)
    kind = (props.metadata or {}).get("kind", "prompt")
    py_path = skill_dir / f"{skill_dir.name}.py"

    if kind == "cli":
        assert py_path.exists(), (
            f"Skill '{skill_dir.name}' declares metadata.kind=cli but {py_path.name} is missing. "
            f"Either add the executable or change the kind to 'prompt'."
        )
    elif kind == "prompt":
        assert not py_path.exists(), (
            f"Skill '{skill_dir.name}' declares metadata.kind=prompt (or omitted) but ships "
            f"{py_path.name}. Either remove the file or set metadata.kind: cli."
        )
    else:
        pytest.fail(
            f"Skill '{skill_dir.name}' has unknown metadata.kind={kind!r}. Valid values: 'cli', 'prompt' (default)."
        )
