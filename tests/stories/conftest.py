"""Shared fixtures for user-story tests.

Loads each CLI under test from its file path and provides the Typer runner;
story tests drive the public CLI surface only (see tests/CLAUDE.md).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_cli_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def release() -> ModuleType:
    return _load_cli_module(REPO_ROOT / "scripts" / "release.py")


@pytest.fixture(scope="session")
def stormitem() -> ModuleType:
    return _load_cli_module(REPO_ROOT / "skills" / "stormitem" / "stormitem.py")


@pytest.fixture(scope="session")
def h2md() -> ModuleType:
    return _load_cli_module(REPO_ROOT / "skills" / "h2md" / "h2md.py")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
