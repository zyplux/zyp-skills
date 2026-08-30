"""release — bump a skill's version with idempotent, higher-wins semantics.

The bump is anchored to `origin/main`:

- If the skill's version on the current branch is unchanged from `main`,
  apply the requested bump (default: minor).
- If the version is already bumped at the requested kind, do nothing.
- If a strictly-higher kind has already been applied, do nothing
  (higher-wins; lower requests never downgrade).
- If the requested kind is strictly higher than the current bump, reset
  to `main`'s version and apply the new kind (so patch → minor cleans
  up the patch increment).

This makes repeated bumps idempotent: re-running `just b <skill>` and pushing
again won't grow the version past one step. PR scope changes (chore → feat
→ feat!) are handled by re-running with `--minor` or `--major`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Literal

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
BASE_REF = "origin/main"

SKILL_MD_VERSION_RE = re.compile(r"^(\s*version:\s*).*$", re.MULTILINE)
PY_VERSION_RE = re.compile(r"^(__version__\s*=\s*).*$", re.MULTILINE)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SKILL_MD_VERSION_READ_RE = re.compile(r'^\s*version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)

BumpKind = Literal["patch", "minor", "major"]
DiffKind = Literal["none", "patch", "minor", "major"]
RANK: dict[str, int] = {"none": 0, "patch": 1, "minor": 2, "major": 3}

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _cli() -> None:
    """Skill release tooling."""


def read_skill_md_version(skill_dir: Path) -> str | None:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    m = SKILL_MD_VERSION_READ_RE.search(text)
    return m.group(1) if m else None


class ToolNotFoundError(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"`{tool}` not found on PATH")


class ReleaseValidationError(RuntimeError):
    pass


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """The single audited subprocess boundary for release operations.

    `git` is resolved to an absolute path via PATH and args are passed as a
    list, so the shell is never invoked and nothing is shell-interpreted.
    """
    executable = shutil.which("git")
    if executable is None:
        msg = "git"
        raise ToolNotFoundError(msg)
    return subprocess.run(
        [executable, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _git_show(ref: str, path: str) -> str | None:
    proc = run_git("show", f"{ref}:{path}", check=False)
    return proc.stdout if proc.returncode == 0 else None


def base_skill_md_version(skill: str) -> str | None:
    text = _git_show(BASE_REF, f"skills/{skill}/SKILL.md")
    if text is None:
        return None
    m = SKILL_MD_VERSION_READ_RE.search(text)
    return m.group(1) if m else None


def bump_semver(current: str, kind: BumpKind) -> str:
    m = SEMVER_RE.match(current)
    if not m:
        msg = f"not a semver: {current!r}"
        raise ValueError(msg)
    major, minor, patch = (int(g) for g in m.groups())
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def diff_kind(base: str, current: str) -> DiffKind:
    """Classify how `current` differs from `base` along the semver axes."""
    bm = SEMVER_RE.match(base)
    cm = SEMVER_RE.match(current)
    if not bm or not cm:
        msg = f"non-semver: {base!r} or {current!r}"
        raise ValueError(msg)
    base_major, base_minor, base_patch = (int(g) for g in bm.groups())
    current_major, current_minor, current_patch = (int(g) for g in cm.groups())
    if (current_major, current_minor, current_patch) < (base_major, base_minor, base_patch):
        msg = f"current {current} is below base {base}"
        raise ValueError(msg)
    if current_major != base_major:
        return "major"
    if current_minor != base_minor:
        return "minor"
    if current_patch != base_patch:
        return "patch"
    return "none"


def parse_semver(version: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.fullmatch(version)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def find_latest_release(skill: str) -> tuple[tuple[int, int, int], str] | None:
    prefix = f"{skill}-v"
    releases = [
        (semver, tag)
        for tag in run_git("tag", "--list", f"{prefix}*").stdout.splitlines()
        if (semver := parse_semver(tag.removeprefix(prefix))) is not None
    ]
    return max(releases) if releases else None


def has_skill_changes(skill: str, tag: str) -> bool:
    path = f"skills/{skill}"
    tracked = run_git("diff", "--name-only", tag, "--", path).stdout
    untracked = run_git("ls-files", "--others", "--exclude-standard", "--", path).stdout
    return bool(tracked or untracked)


def find_release_errors() -> list[str]:
    errors: list[str] = []
    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if (path / "SKILL.md").is_file()):
        skill = skill_dir.name
        version = read_skill_md_version(skill_dir)
        current = parse_semver(version) if version is not None else None
        if current is None:
            errors.append(f"{skill} has no valid semantic version in SKILL.md")
            continue
        latest = find_latest_release(skill)
        if latest is None:
            continue
        released, tag = latest
        if current < released:
            errors.append(f"{skill} version {version} is below {tag}")
        elif current == released and has_skill_changes(skill, tag):
            errors.append(f"{skill} changed since {tag} but remains at version {version}; run `just bump {skill}`")
    return errors


def validate_release_versions() -> None:
    errors = find_release_errors()
    if errors:
        raise ReleaseValidationError("\n".join(errors))


def decide_bump(base: str, current: str, requested: BumpKind) -> str | None:
    """Return the new version, or None if the existing one already wins."""
    current_kind = diff_kind(base, current)
    if RANK[requested] <= RANK[current_kind]:
        return None
    return bump_semver(base, requested)


def _set_version_in(path: Path, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if path.name == "SKILL.md":
        new_text = SKILL_MD_VERSION_RE.sub(rf'\1"{new}"', text, count=1)
    elif path.name == "package.json":
        data = json.loads(text)
        data["version"] = new
        new_text = json.dumps(data, indent=2) + "\n"
    elif path.suffix == ".py":
        new_text = PY_VERSION_RE.sub(rf'\1"{new}"', text, count=1)
    else:
        msg = f"don't know how to update version in {path}"
        raise ValueError(msg)
    if new_text == text:
        msg = f"no version field updated in {path}"
        raise RuntimeError(msg)
    path.write_text(new_text, encoding="utf-8")


def _apply_version_bump(skill: str, new_version: str) -> None:
    skill_dir = SKILLS_DIR / skill
    targets = [skill_dir / "SKILL.md"]
    py = skill_dir / f"{skill}.py"
    pkg = skill_dir / "package.json"
    if py.exists():
        targets.append(py)
    if pkg.exists():
        targets.append(pkg)
    for t in targets:
        _set_version_in(t, new_version)


@app.command()
def check() -> None:
    """Require every changed, released skill to carry a version bump."""
    try:
        validate_release_versions()
    except ReleaseValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def bump(
    skill: str = typer.Argument(..., help="Skill to bump."),
    *,
    patch_: Annotated[bool, typer.Option("--patch", "-p")] = False,
    minor: Annotated[bool, typer.Option("--minor")] = False,
    major: Annotated[bool, typer.Option("--major")] = False,
) -> None:
    """Bump <skill>'s version (default minor). Idempotent + higher-wins."""
    if sum([patch_, minor, major]) > 1:
        msg = "pass at most one of --patch / --minor / --major"
        raise typer.BadParameter(msg)
    requested: BumpKind = "major" if major else "patch" if patch_ else "minor"
    if skill == ".." or Path(skill).name != skill:
        msg = f"invalid skill name: {skill!r}"
        raise typer.BadParameter(msg)
    skill_dir = SKILLS_DIR / skill
    if not (skill_dir / "SKILL.md").exists():
        msg = f"unknown skill: {skill}"
        raise typer.BadParameter(msg)
    base = base_skill_md_version(skill)
    if base is None:
        typer.echo(f"{skill}: not on {BASE_REF} (new skill?). Set the initial version manually.")
        return
    current = read_skill_md_version(skill_dir)
    if current is None:
        msg = f"{skill}: SKILL.md has no version"
        raise RuntimeError(msg)
    new = decide_bump(base, current, requested)
    if new is None:
        kind = diff_kind(base, current)
        typer.echo(f"{skill}: {current} (already {kind}-bumped from {base}). no change.")
        return
    _apply_version_bump(skill, new)
    typer.echo(f"{skill}: {current} → {new} ({requested}, base {base})")


if __name__ == "__main__":
    app()
