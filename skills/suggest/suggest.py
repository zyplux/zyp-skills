#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["typer>=0.15", "toon-format>=0.9.0b1"]
# ///
"""Submit structured improvement suggestions for CLI skills — bugs, gaps, inefficiencies."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from toon_format import encode

__version__ = "0.5.0"

app = typer.Typer()


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(f"suggest {__version__}")
        raise typer.Exit


_DEFAULT_DIR = Path.home() / "Documents" / "skill-suggestions"
SKILL_SUGGEST_DIR = Path(os.environ["SKILL_SUGGEST_DIR"]) if "SKILL_SUGGEST_DIR" in os.environ else _DEFAULT_DIR


def _save(skill: str, text: str) -> Path:
    """Save suggestion markdown to timestamped file. Returns the path."""
    skill_dir = SKILL_SUGGEST_DIR / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = skill_dir / f"suggestion_{ts}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


@app.command()
def main(
    skill: Annotated[str, typer.Argument(help="Name of the skill to improve")],
    text: Annotated[
        str | None,
        typer.Argument(help="Markdown: Context, Gap, Responsibility, Suggestion, Impact. Use '-' to read from stdin."),
    ] = None,
    _version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """Submit a structured improvement suggestion for a skill — what fell short and what should change."""
    if skill == ".." or Path(skill).name != skill:
        msg = f"invalid skill name: {skill!r}"
        raise typer.BadParameter(msg)
    if text is None or text == "-":
        text = sys.stdin.read()
    if not text.strip():
        msg = "Suggestion text cannot be empty"
        raise typer.BadParameter(msg)
    path = _save(skill, text)
    typer.echo(encode({"saved": str(path)}))


if __name__ == "__main__":
    app()
