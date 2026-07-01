from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import SimpleNamespace


def test_language_from_class_preserved(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code Example</h1>
    <p>Example code:</p>
    <pre><code class="language-python">print("hi")</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    assert "```python" in r.md
    assert 'print("hi")' in r.md


def test_language_sniffed_when_no_class(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code Example</h1>
    <p>Run this:</p>
    <pre><code>curl -fsSL https://example.com/install.sh | bash</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    assert "```bash" in r.md


def test_headings_preserved(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <h2>Section</h2>
    <p>Content paragraph with enough words to pass extraction.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "# Title" in r.md
    assert "## Section" in r.md


def test_links_preserved(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Links</h1>
    <p>Visit <a href="https://example.com">our site</a> for more info and details.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "[our site](https://example.com)" in r.md


def test_shiki_spans_produce_clean_code(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("shiki_code.html"))
    assert "```javascript" in r.md
    assert "express()" in r.md or "express();" in r.md
    assert "Response. json" not in r.md
    assert "<span" not in r.md


def test_shiki_interspan_whitespace_stripped(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("shiki_whitespace.html"))
    assert 'import homepage from "./index.html";' in r.md
    assert "const app = express();" in r.md


def test_code_chrome_removed(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code Example</h1>
    <p>Here is some Python code with UI chrome around it:</p>
    <figure class="code-block">
        <span class="copy-indicator"></span>
        <div class="toolbar"></div>
        <pre><code class="language-python">print("hello world")</code></pre>
    </figure>
    <p>And another example with a filename label:</p>
    <div class="highlight-wrapper">
        <div class="filename-label"></div>
        <pre><code class="language-bash">npm start</code></pre>
    </div>
    </article></body></html>"""
    r = pipeline(html)
    assert 'print("hello world")' in r.md
    assert "npm start" in r.md


def test_copy_button_elements_stripped(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code Examples With Copy Buttons</h1>
    <p>Here is some Python code with a copy icon overlay that should be stripped from the output entirely:</p>
    <div class="code-wrapper">
        <div class="CopyIcon">Copy</div>
        <pre><code class="language-python">print("hello")</code></pre>
    </div>
    <p>And another example with a clipboard copy button that should also be removed:</p>
    <div class="highlight">
        <div class="clipboard-copy">Copy to clipboard</div>
        <pre><code class="language-bash">curl https://example.com</code></pre>
    </div>
    </article></body></html>"""
    r = pipeline(html)
    assert 'print("hello")' in r.md
    assert "curl https://example.com" in r.md


def test_data_language_attribute_detected(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code</h1>
    <p>Rust example:</p>
    <pre data-language="rust"><code>fn main() {}</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    assert "```rust" in r.md


def test_class_prefix_wins_over_data_attr(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Code</h1>
    <p>Example:</p>
    <div data-language="go"><pre><code class="language-rust">fn main()</code></pre></div>
    </article></body></html>"""
    r = pipeline(html)
    assert "```rust" in r.md


def test_text_class_overridden_by_sniffed_language(pipeline: Callable[..., SimpleNamespace]) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text explaining this JavaScript code example for developers.</p>
    <pre><code class="language-text">const app = express()
app.listen(3000)</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    assert "```javascript" in r.md
    assert "```text" not in r.md
