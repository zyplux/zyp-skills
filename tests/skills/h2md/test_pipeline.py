from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import SimpleNamespace

    from typer.testing import Result


def test_full_pipeline_produces_expected_outputs(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    h = r.toon["h2md"]
    assert h["tokens"] > 0
    assert h["article"] == "article.md"
    assert "title" in h
    assert "lint_remaining" in h
    assert len(r.sections) > 0
    assert r.issues == []
    assert "clean" in r.toon["next"].lower()
    assert r.md
    assert r.meta


def test_pipeline_workspace_has_final_files(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    for name in ["article.md", "meta.toon", "article.html"]:
        assert (r.workspace / name).exists(), f"Missing: {name}"


def test_sections_structure(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert len(r.sections) > 0
    assert set(r.sections[0].keys()) == {"title", "line", "tokens"}


def test_sections_token_counts(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Guide</h1>
    <p>This guide shows how to use the API with several code examples and explanations for developers.</p>
    <h2>Setup</h2>
    <p>Install the package first before proceeding with configuration for the project.</p>
    <pre><code class="language-bash">npm install example</code></pre>
    <h2>Usage</h2>
    <p>First import the package into your application code for the main feature:</p>
    <pre><code class="language-javascript">import { foo } from 'example'</code></pre>
    <p>Then call the function to get the result you need from the library:</p>
    <pre><code class="language-javascript">const result = foo()</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    titles = [s["title"] for s in r.sections]
    assert "Guide" in titles
    assert "Setup" in titles
    assert "Usage" in titles
    assert all(s["tokens"] > 0 for s in r.sections)
    assert r.toon["h2md"]["tokens"] == sum(s["tokens"] for s in r.sections)


def test_js_flag_errors(invoke: Callable[..., Result]) -> None:
    result = invoke("https://example.com", "--js", expect_error=True)
    assert "playwright" in result.output.lower()


def test_copy_to_flag(
    invoke: Callable[..., Result],
    serve_html: Callable[..., str],
    read_fixture: Callable[[str], str],
    tmp_path: Path,
    mock_lint: None,
) -> None:
    del mock_lint
    url = serve_html(read_fixture("simple_article.html"))
    dest = tmp_path / "output.md"
    result = invoke(url, "--no-assets", "--copy-to", str(dest))
    assert result.exit_code == 0
    assert dest.exists()
    assert dest.read_text().strip()


def test_issues_absent_when_clean(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert "issues" not in r.toon


def test_issues_present_when_detected(pipeline: Callable[..., SimpleNamespace]) -> None:
    fused = "x" * 90
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text {fused} more text in this article paragraph.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "issues" in r.toon
    assert r.toon["issues"][0]["type"] == "fused text"
    assert "fix" in r.toon["next"].lower()
