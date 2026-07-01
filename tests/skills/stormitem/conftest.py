from __future__ import annotations

from typing import TYPE_CHECKING, Any, Never

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(scope="session")
def stormitem(skill_loader):
    return skill_loader("stormitem")


@pytest.fixture
def invoke(run, stormitem) -> Callable[..., Any]:
    """Invoke the stormitem CLI app."""

    def _invoke(*args: str, **kwargs):
        return run(stormitem.app, args, **kwargs)

    return _invoke


@pytest.fixture
def builtin_only(monkeypatch, stormitem):
    """Force `_fetch_template` to skip the remote listing and use built-ins."""
    import subprocess

    def fake_gh_json(*args: str) -> Never:
        raise subprocess.CalledProcessError(1, ["gh", *args])

    monkeypatch.setattr(stormitem, "_gh_json", fake_gh_json)
    return stormitem
