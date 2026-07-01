"""Tests for the suggest skill."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from toon_format import decode


def test_saves_suggestion_file(invoke, suggest_dir) -> None:
    result = invoke("peek", "## Bug\n\nSomething broke")
    assert result.output.strip()
    files = list((suggest_dir / "peek").glob("suggestion_*.md"))
    assert len(files) == 1
    assert files[0].read_text() == "## Bug\n\nSomething broke\n"


def test_output_is_toon(invoke, suggest_dir) -> None:
    result = invoke("peek", "test text")
    parsed = decode(result.output.strip())
    assert isinstance(parsed, dict)
    assert "saved" in parsed
    assert Path(parsed["saved"]).exists()


def test_creates_skill_subdirectory(invoke, suggest_dir) -> None:
    invoke("newskill", "some suggestion")
    assert (suggest_dir / "newskill").is_dir()


def test_multiple_suggestions_unique_files(invoke, suggest_dir) -> None:
    invoke("peek", "first")
    invoke("peek", "second")
    files = sorted((suggest_dir / "peek").glob("suggestion_*.md"))
    assert len(files) == 2
    contents = {f.read_text() for f in files}
    assert "first\n" in contents
    assert "second\n" in contents


def test_missing_args_fails(invoke) -> None:
    result = invoke(expect_error=True)
    assert result.exit_code != 0


@pytest.mark.parametrize(
    ("args", "stdin"),
    [
        (["peek"], "from stdin\n"),
        (["peek", "-"], "piped content\n"),
    ],
    ids=["omitted", "dash"],
)
def test_reads_stdin(invoke, suggest_dir, args, stdin) -> None:
    invoke(*args, stdin=stdin)
    files = list((suggest_dir / "peek").glob("suggestion_*.md"))
    assert len(files) == 1
    assert files[0].read_text() == stdin + "\n"


def test_markdown_content_preserved(invoke, suggest_dir) -> None:
    md = "## Feature request\n\n- bullet one\n- bullet two\n\n```python\nprint('hello')\n```"
    invoke("peek", md)
    files = list((suggest_dir / "peek").glob("suggestion_*.md"))
    assert files[0].read_text() == md + "\n"


def test_suggest_dir_from_env(tmp_path, monkeypatch) -> None:
    """SKILL_SUGGEST_DIR env var overrides the default directory."""
    custom = tmp_path / "custom-suggestions"
    monkeypatch.setenv("SKILL_SUGGEST_DIR", str(custom))
    spec = importlib.util.spec_from_file_location(
        "suggest_env",
        Path(__file__).resolve().parents[3] / "skills" / "suggest" / "suggest.py",
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert custom == mod.SKILL_SUGGEST_DIR


def test_suggest_dir_default_without_env(monkeypatch) -> None:
    """Without SKILL_SUGGEST_DIR env var, falls back to ~/Documents/skill-suggestions."""
    monkeypatch.delenv("SKILL_SUGGEST_DIR", raising=False)
    spec = importlib.util.spec_from_file_location(
        "suggest_default",
        Path(__file__).resolve().parents[3] / "skills" / "suggest" / "suggest.py",
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert Path.home() / "Documents" / "skill-suggestions" == mod.SKILL_SUGGEST_DIR
