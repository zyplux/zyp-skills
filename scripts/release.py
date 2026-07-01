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
from typing import Literal

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
    text = (skill_dir / "SKILL.md").read_text()
    m = SKILL_MD_VERSION_READ_RE.search(text)
    return m.group(1) if m else None


class ToolNotFoundError(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"`{tool}` not found on PATH")


def _git_show(ref: str, path: str) -> str | None:
    """The single audited subprocess boundary for release.

    `git` is resolved to an absolute path via PATH, the remaining args are
    program-constructed (never user-derived), and the shell is never invoked, so
    there is no command-injection surface.
    """
    executable = shutil.which("git")
    if executable is None:
        msg = "git"
        raise ToolNotFoundError(msg)
    proc = subprocess.run(
        [executable, "show", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
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
    bM, bn, bp = (int(g) for g in bm.groups())
    cM, cn, cp = (int(g) for g in cm.groups())
    if (cM, cn, cp) < (bM, bn, bp):
        msg = f"current {current} is below base {base}"
        raise ValueError(msg)
    if cM != bM:
        return "major"
    if cn != bn:
        return "minor"
    if cp != bp:
        return "patch"
    return "none"


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
def bump(
    skill: str = typer.Argument(..., help="Skill to bump."),
    patch_: bool = typer.Option(False, "--patch", "-p"),
    minor: bool = typer.Option(False, "--minor"),
    major: bool = typer.Option(False, "--major"),
) -> None:
    """Bump <skill>'s version (default minor). Idempotent + higher-wins."""
    if sum([patch_, minor, major]) > 1:
        msg = "pass at most one of --patch / --minor / --major"
        raise typer.BadParameter(msg)
    requested: BumpKind = "major" if major else "patch" if patch_ else "minor"
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
