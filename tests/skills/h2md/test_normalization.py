from __future__ import annotations


def test_h1_injected_from_metadata(pipeline) -> None:
    html = """<!DOCTYPE html><html><head><title>My Title</title></head>
    <body><article><p>No heading here, just text that should still be extracted properly.</p></article></body></html>"""
    r = pipeline(html)
    assert "# My Title" in r.md


def test_h1_not_duplicated(pipeline) -> None:
    html = """<!DOCTYPE html><html><head><title>Existing Title</title></head>
    <body><article><h1>Existing Title</h1><p>Body paragraph with enough content.</p></article></body></html>"""
    r = pipeline(html)
    lines = [ln for ln in r.md.split("\n") if ln.startswith("# ")]
    assert len(lines) <= 1


def test_bold_headings_promoted(pipeline) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p><strong>RFC 6455 Compliant Subprotocol Negotiation</strong></p>
    <p>Some text after the bold heading.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "#### RFC 6455 Compliant Subprotocol Negotiation" in r.md
    assert "**RFC 6455" not in r.md


def test_empty_fences_removed(pipeline) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <pre><code>
    </code></pre>
    <p>Keep this text in the final output.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert "Keep this" in r.md


def test_excessive_blank_lines_collapsed(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert "\n\n\n" not in r.md
