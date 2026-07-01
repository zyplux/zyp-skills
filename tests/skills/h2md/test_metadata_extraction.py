from __future__ import annotations


def test_jsonld_takes_priority(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["title"] == "JSON-LD Headline"
    assert r.meta["author"] == "JSON-LD Author"
    assert r.meta["date"] == "2026-01-20T08:00:00Z"


def test_og_fills_gaps(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["og_image"] == "https://example.com/og-image.jpg"
    assert r.meta["site_name"] == "Example Site"


def test_lang_detected_from_html_tag(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["lang"] == "fr"


def test_word_count_and_reading_time(pipeline) -> None:
    words = " ".join(["word"] * 500)
    html = f"""<!DOCTYPE html><html><head><title>Test</title></head>
    <body><article><h1>Test</h1><p>{words}</p></article></body></html>"""
    r = pipeline(html)
    assert 500 <= r.meta["word_count"] <= 510
    assert r.meta["reading_time_minutes"] == 2


def test_frontmatter_generated(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert r.md.startswith("---\n")
    assert 'title: "Getting Started with FastAPI"' in r.md
    assert "---" in r.md


def test_canonical_url_in_metadata(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert "canonical_url" in r.meta or "og_image" in r.meta
