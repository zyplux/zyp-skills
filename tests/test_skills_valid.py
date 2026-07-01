"""Validate every skill in the repo against the Agent Skills spec."""

import re
import subprocess
from pathlib import Path

import pytest
from skills_ref import read_properties, validate

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_MD_VERSION_READ_RE = re.compile(r'^\s*version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
SKILL_DIRS = sorted(
    p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
)
BASE_REF = "origin/main"


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


def test_skill_changes_require_version_bump(skill_dir: Path) -> None:
    """If the skill changed vs origin/main, its SKILL.md version must too.

    Run `just bump <skill>` to bump (default minor; -p for patch, --major).
    The bump is idempotent + higher-wins, so re-running won't double-bump.
    """
    has_base = subprocess.run(
        ["git", "rev-parse", "--verify", BASE_REF],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if has_base.returncode != 0:
        pytest.skip(f"{BASE_REF} not fetched; run `git fetch origin main` to enable")
    rel = skill_dir.relative_to(REPO_ROOT).as_posix()
    diff = subprocess.run(
        ["git", "diff", "--quiet", BASE_REF, "--", rel],
        cwd=REPO_ROOT,
    )
    if diff.returncode == 0:
        return
    main_md = subprocess.run(
        ["git", "show", f"{BASE_REF}:{rel}/SKILL.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if main_md.returncode != 0:
        return
    main_match = SKILL_MD_VERSION_READ_RE.search(main_md.stdout)
    if main_match is None:
        return
    main_version = main_match.group(1)
    current_match = SKILL_MD_VERSION_READ_RE.search(
        (skill_dir / "SKILL.md").read_text()
    )
    assert current_match is not None, f"{skill_dir.name}/SKILL.md has no version field"
    current_version = current_match.group(1)
    assert current_version != main_version, (
        f"{skill_dir.name} has changes vs {BASE_REF} but version is still {current_version}. "
        f"Run `just bump {skill_dir.name}` (default minor; -p for patch, --major)."
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
            f"Skill '{skill_dir.name}' has unknown metadata.kind={kind!r}. "
            f"Valid values: 'cli', 'prompt' (default)."
        )
