from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import SimpleNamespace


def test_aria_tablist_flattened(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("tabbed_code.html"))
    assert "curl -fsSL" in r.md
    assert "npm install" in r.md
    assert "brew install" in r.md


def test_class_based_tabs_flattened(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("class_tabs.html"))
    assert "curl -fsSL" in r.md
    assert "npm install" in r.md
    assert "brew install" in r.md


def test_terminal_regions_reconstructed(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("terminal_output.html"))
    assert "Bun" in r.md
    assert "v1.3.12" in r.md


def test_nav_wrapper_tabs_flattened(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Install</h1>
    <p>Pick a language:</p>
    <div class="tabs">
        <nav><span>Python</span><span>Ruby</span></nav>
        <div class="tab-content"><pre><code>print("hi")</code></pre></div>
        <div class="tab-content"><pre><code>puts "hi"</code></pre></div>
    </div>
    </article></body></html>"""
    r = pipeline(html)
    assert 'print("hi")' in r.md
    assert 'puts "hi"' in r.md


def test_codetab_class_pattern_flattened(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Install</h1>
    <p>Pick a method:</p>
    <div class="CodeTabs">
        <div class="CodeTabsHeader">
            <div class="CodeTab active">curl</div>
            <div class="CodeTab">npm</div>
        </div>
        <div class="CodeTabItem active"><pre><code>curl -fsSL https://example.com</code></pre></div>
        <div class="CodeTabItem"><pre><code>npm install example</code></pre></div>
    </div>
    </article></body></html>"""
    r = pipeline(html)
    assert "curl -fsSL" in r.md
    assert "npm install" in r.md
