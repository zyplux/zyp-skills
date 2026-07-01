from __future__ import annotations


def test_article_tag_content_extracted(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert "FastAPI" in r.md
    assert "pip install fastapi" in r.md


def test_fallback_extraction_without_article_tag(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("no_article_tag.html"))
    assert "Async Patterns" in r.md or "asynchronous" in r.md.lower()


def test_selector_override(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("no_article_tag.html"), selector="div.post-body")
    assert "Async Patterns" in r.md
    assert "Recent Posts" not in r.md


def test_scripts_and_styles_excluded(pipeline) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <script>alert(1)</script>
    <style>.x{color:red}</style>
    <p>Keep this content.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "alert(1)" not in r.md
    assert ".x{" not in r.md
    assert "Keep this content" in r.md


def test_nav_footer_header_excluded(pipeline) -> None:
    html = """<!DOCTYPE html><html><body>
    <nav>Menu links</nav>
    <header>Site header</header>
    <article><p>Body content here with enough text to be extracted properly by readability.</p></article>
    <footer>Footer content</footer>
    </body></html>"""
    r = pipeline(html)
    assert "Body content" in r.md
    assert "Menu links" not in r.md
    assert "Footer content" not in r.md


def test_buttons_and_svgs_excluded(pipeline) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <button>Copy</button>
    <svg><path d="M0 0"/></svg>
    <p>Visible paragraph with real content for the article.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "Visible paragraph" in r.md
    assert "Copy" not in r.md
