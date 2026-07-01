"""Shared fixtures for skill tests.

Provides skill loading, CLI runner, exit-code-asserting invoke,
and TOON decoding. Skill-specific conftest files build on these
via fixture injection.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from toon_format import decode as _decode
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from typer.main import Typer
    from typer.testing import Result

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


@pytest.fixture(scope="session")
def skill_loader() -> Callable[[str], ModuleType]:
    """Load a skill module by name from the skills directory."""

    def _load(name: str) -> ModuleType:
        path = SKILLS_DIR / name / f"{name}.py"
        if not path.exists():
            pytest.fail(
                f"Skill '{name}' has no CLI module at {path.relative_to(SKILLS_DIR.parent)}. "
                f"CLI tests expect a typer app in <skill>.py; prompt-only skills should be "
                f"filtered out by the caller (e.g. via SKILL_NAMES that checks for the .py)."
            )
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    return _load


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def run(runner: CliRunner) -> Callable[..., Result]:
    """Invoke a Typer app with exit_code == 0 assertion by default.

    Skill-specific ``invoke`` fixtures delegate here, adding their own
    defaults (fixture paths, stdin input, etc.).
    """

    def _run(
        app: Typer, args: list[str], *, expect_error: bool = False, stdin: str | None = None
    ) -> Result:
        result = runner.invoke(app, list(args), input=stdin)
        if not expect_error:
            assert result.exit_code == 0, result.output
        return result

    return _run


@pytest.fixture
def decode() -> Callable[[str], dict[str, Any]]:
    """Return a typed TOON decode helper."""

    def _fn(text: str) -> dict[str, Any]:
        result = _decode(text)
        assert isinstance(result, dict)
        return result

    return _fn
