from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path
    from types import ModuleType

    from typer.testing import Result


@pytest.fixture(scope="session")
def suggest(skill_loader: Callable[[str], ModuleType]) -> ModuleType:
    return skill_loader("suggest")


@pytest.fixture(autouse=True)
def suggest_dir(suggest: ModuleType, tmp_path: Path) -> Generator[Path]:
    """Redirect SKILL_SUGGEST_DIR to tmp_path for test isolation.

    In production, the directory is configured via the SKILL_SUGGEST_DIR env var
    (defaulting to ~/Documents/skill-suggestions). Tests override the module
    attribute directly for simplicity.
    """
    original = suggest.SKILL_SUGGEST_DIR
    suggest.SKILL_SUGGEST_DIR = tmp_path
    yield tmp_path
    suggest.SKILL_SUGGEST_DIR = original


@pytest.fixture
def invoke(run: Callable[..., Result], suggest: ModuleType) -> Callable[..., Result]:
    """Invoke the suggest CLI app."""

    def _invoke(*args: str, expect_error: bool = False, stdin: str | None = None) -> Result:
        return run(suggest.app, args, expect_error=expect_error, stdin=stdin)

    return _invoke
