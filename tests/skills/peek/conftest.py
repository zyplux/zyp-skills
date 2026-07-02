from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from typer.testing import Result

FIXTURE_PATH = Path(__file__).parent / "tourney_points.parquet"


@pytest.fixture(scope="session")
def peek(skill_loader: Callable[[str], ModuleType]) -> ModuleType:
    return skill_loader("peek")


@pytest.fixture(scope="session")
def fixture_path() -> Path:
    return FIXTURE_PATH


@pytest.fixture
def invoke(run: Callable[..., Result], peek: ModuleType, fixture_path: Path) -> Callable[..., Result]:
    """Invoke the peek CLI app with default fixture path appended."""

    def _invoke(*args: str, use_fixture: bool = True, expect_error: bool = False) -> Result:
        cmd = list(args)
        if use_fixture:
            cmd.append(str(fixture_path))
        return run(peek.app, cmd, expect_error=expect_error)

    return _invoke
