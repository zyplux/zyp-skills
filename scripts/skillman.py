"""skillman — install, uninstall, and inspect totvibe skills.

A skill may declare per-machine environment variables in `skills/<name>/env.toml`:

    [env]
    SKILL_SUGGEST_DIR = "{repo_root}/plan/skill-suggestions"

On install, each variable is rendered (with `{repo_root}` and `{skill_dir}` placeholders),
written to `~/.config/environment.d/skill_<name>.conf`, and exported in `~/.bashrc`.
On uninstall, the conf file and the matching `~/.bashrc` lines are removed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import NamedTuple

import typer
from skills_ref import read_properties

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
INSTALL_ROOT = Path.home() / ".agents" / "skills"
ENV_D_DIR = Path.home() / ".config" / "environment.d"
BASHRC = Path.home() / ".bashrc"
ENV_FILE = "env.toml"
DEFAULT_SOURCE = "github:zyplux/zyp-skills"


class Runner(NamedTuple):
    dlx: str
    link: tuple[str, ...]
    unlink: tuple[str, ...]


RUNNERS: tuple[Runner, ...] = (
    Runner("npx", ("npm", "link"), ("npm", "unlink")),
    Runner("bunx", ("bun", "link"), ("bun", "unlink")),
    Runner("pnpx", ("pnpm", "link", "--global"), ("pnpm", "unlink", "--global")),
)


def _find_runner() -> Runner:
    for runner in RUNNERS:
        if shutil.which(runner.dlx):
            return runner
    tried = ", ".join(r.dlx for r in RUNNERS)
    raise typer.BadParameter(f"no JS package runner found on PATH; tried: {tried}")


app = typer.Typer(add_completion=False, no_args_is_help=True)


def _conf_path(skill: str) -> Path:
    return ENV_D_DIR / f"skill_{skill.replace('-', '_')}.conf"


def _version(skill_dir: Path) -> str | None:
    return read_properties(skill_dir).metadata.get("version")


def _all_skills() -> list[str]:
    return sorted(
        p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    )


def _stale_skills(force: bool) -> list[str]:
    if force:
        return _all_skills()
    out: list[str] = []
    for name in _all_skills():
        installed = INSTALL_ROOT / name
        if not (installed / "SKILL.md").exists() or _version(
            SKILLS_DIR / name
        ) != _version(installed):
            out.append(name)
    return out


def _resolve_env(skill: str) -> dict[str, str]:
    """Return rendered env vars from the installed copy's env.toml, or {} if absent.

    Reads from the installed location so the same logic works whether the install
    material came from a local path or a remote source like `github:user/repo`.
    """
    path = INSTALL_ROOT / skill / ENV_FILE
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text()).get("env", {})
    if not isinstance(raw, dict):
        raise typer.BadParameter(f"{path}: top-level [env] must be a table")
    ctx = {"repo_root": str(REPO_ROOT), "skill_dir": str(INSTALL_ROOT / skill)}
    return {k: str(v).format(**ctx) for k, v in raw.items()}


def _rewrite_bashrc(updates: dict[str, str], remove: set[str]) -> None:
    if not updates and not remove:
        return
    lines = BASHRC.read_text().splitlines() if BASHRC.exists() else []
    drop = remove | set(updates)
    pat = {var: re.compile(rf"^\s*export\s+{re.escape(var)}=") for var in drop}
    kept = [line for line in lines if not any(p.match(line) for p in pat.values())]
    if updates:
        if kept and kept[-1]:
            kept.append("")
        kept.extend(f"export {k}={v}" for k, v in updates.items())
    BASHRC.write_text("\n".join(kept) + "\n")


def _apply_env(skill: str) -> None:
    env = _resolve_env(skill)
    if not env:
        return
    ENV_D_DIR.mkdir(parents=True, exist_ok=True)
    conf = _conf_path(skill)
    conf.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    _rewrite_bashrc(env, set())
    typer.echo(f"  env → {conf} ({', '.join(env)})")


def _remove_env(skill: str) -> None:
    conf = _conf_path(skill)
    declared = _resolve_env(skill)
    leftover = _parse_conf(conf) if conf.exists() else {}
    if conf.exists():
        conf.unlink()
        typer.echo(f"  env ← removed {conf}")
    _rewrite_bashrc({}, set(declared) | set(leftover))


def _parse_conf(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


class ToolNotFoundError(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"`{tool}` not found on PATH")


def _run(*args: str, cwd: Path | None = None, check: bool = True) -> None:
    """The single audited subprocess boundary for skillman.

    `args[0]` is resolved to an absolute path via PATH, the remaining args are
    program-constructed (never user-derived), and the shell is never invoked, so
    there is no command-injection surface.
    """
    executable = shutil.which(args[0])
    if executable is None:
        raise ToolNotFoundError(args[0])
    subprocess.run([executable, *args[1:]], cwd=cwd, check=check)


def _install_one(name: str, source: str) -> None:
    if not (SKILLS_DIR / name / "SKILL.md").exists():
        raise typer.BadParameter(f"unknown skill: {name}")
    runner = _find_runner()
    typer.echo(f"==> installing {name} (source: {source}, runner: {runner.dlx})")
    _run(
        runner.dlx, "skills", "add", source, "-g", "--skill", name, "-y", cwd=REPO_ROOT
    )
    target = INSTALL_ROOT / name
    py_path = target / f"{name}.py"
    if py_path.exists():
        py_path.chmod(py_path.stat().st_mode | 0o111)
    if (target / "package.json").exists():
        _run(*runner.link, cwd=target)
    _apply_env(name)


def _force_default() -> bool:
    return os.environ.get("FORCE", "0") == "1"


@app.command()
def install(
    name: str = typer.Argument(
        "", help="Skill to install. Omit to install every stale skill."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Reinstall even if version matches (or set FORCE=1).",
    ),
    source: str = typer.Option(
        DEFAULT_SOURCE,
        "--source",
        "-s",
        envvar="SKILLMAN_SOURCE",
        help='Where `skills add` reads from. Defaults to the GitHub repo (always main). Pass "." to install from the local working tree.',
    ),
) -> None:
    """Install one skill, or every skill whose source version differs from the installed copy."""
    if name:
        _install_one(name, source)
        return
    targets = _stale_skills(force=force or _force_default())
    if not targets:
        typer.echo("All skills are up-to-date.")
        return
    for n in targets:
        _install_one(n, source)


@app.command()
def uninstall(name: str = typer.Argument(..., help="Skill to uninstall.")) -> None:
    """Uninstall a skill and clean up its env vars / conf file."""
    target = INSTALL_ROOT / name
    if (target / "package.json").exists():
        for runner in RUNNERS:
            if shutil.which(runner.unlink[0]):
                _run(*runner.unlink, cwd=target, check=False)
    _run(_find_runner().dlx, "skills", "remove", name, "-g", "-y")
    _remove_env(name)


@app.command("list-stale")
def list_stale(
    force: bool = typer.Option(
        False, "--force", "-f", help="List every skill regardless of version match."
    ),
) -> None:
    """Print skills whose source version differs from the installed copy, one per line."""
    for name in _stale_skills(force=force or _force_default()):
        typer.echo(name)


if __name__ == "__main__":
    app()
