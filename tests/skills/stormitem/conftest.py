from __future__ import annotations

import base64
import subprocess
from typing import TYPE_CHECKING, Any, Never

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    from typer.testing import Result


@pytest.fixture(scope="session")
def stormitem(skill_loader: Callable[[str], ModuleType]) -> ModuleType:
    return skill_loader("stormitem")


@pytest.fixture
def invoke(run: Callable[..., Result], stormitem: ModuleType) -> Callable[..., Result]:
    """Invoke the stormitem CLI app."""

    def _invoke(*args: str, expect_error: bool = False) -> Result:
        return run(stormitem.app, list(args), expect_error=expect_error)

    return _invoke


@pytest.fixture
def tmp_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect `tempfile.gettempdir()` to an isolated per-test directory.

    `pull` creates its scratch dir under the process tempdir, and `post`'s
    cleanup only deletes work dirs that live under it — tests need a sandboxed
    stand-in for both.
    """
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture
def builtin_only(monkeypatch: pytest.MonkeyPatch, stormitem: ModuleType) -> ModuleType:
    """Force `_fetch_template` to skip the remote listing and use built-ins."""

    def fake_gh_json(*args: str) -> Never:
        raise subprocess.CalledProcessError(1, ["gh", *args])

    monkeypatch.setattr(stormitem, "_gh_json", fake_gh_json)
    return stormitem


@pytest.fixture
def remote_templates(monkeypatch: pytest.MonkeyPatch, stormitem: ModuleType) -> Callable[..., None]:
    """Stub the `gh api` boundary so `pull` serves a fake `.github/ISSUE_TEMPLATE`
    listing and file contents, exercising the real template-matching and
    template-parsing code through the CLI instead of calling it directly.

    `listing` is the raw GitHub contents-API listing (list of `{"name", "path",
    "type": "file"}` dicts); `contents` maps each entry's `path` to its raw text.
    """

    def _install(listing: list[dict[str, Any]], contents: dict[str, str]) -> None:
        def fake_gh_json(*args: str) -> object:
            path = args[-1]
            if path.endswith("contents/.github/ISSUE_TEMPLATE"):
                return listing
            for entry_path, raw in contents.items():
                if path.endswith(f"contents/{entry_path}"):
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(raw.encode()).decode(),
                    }
            msg = f"unmocked _gh_json call: {args}"
            raise AssertionError(msg)

        monkeypatch.setattr(stormitem, "_gh_json", fake_gh_json)

    return _install
