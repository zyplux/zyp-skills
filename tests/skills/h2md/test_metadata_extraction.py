from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import SimpleNamespace


def test_jsonld_takes_priority(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["title"] == "JSON-LD Headline"
    assert r.meta["author"] == "JSON-LD Author"
    assert r.meta["date"] == "2026-01-20T08:00:00Z"


def test_og_fills_gaps(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["og_image"] == "https://example.com/og-image.jpg"
    assert r.meta["site_name"] == "Example Site"


def test_lang_detected_from_html_tag(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("metadata_rich.html"))
    assert r.meta["lang"] == "fr"


WORD_COUNT = 500
WORD_COUNT_MAX = 510
EXPECTED_READING_TIME_MINUTES = 2


def test_word_count_and_reading_time(pipeline: Callable[..., SimpleNamespace]) -> None:
    words = " ".join(["word"] * WORD_COUNT)
    html = f"""<!DOCTYPE html><html><head><title>Test</title></head>
    <body><article><h1>Test</h1><p>{words}</p></article></body></html>"""
    r = pipeline(html)
    assert WORD_COUNT <= r.meta["word_count"] <= WORD_COUNT_MAX
    assert r.meta["reading_time_minutes"] == EXPECTED_READING_TIME_MINUTES


def test_frontmatter_generated(pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert r.md.startswith("---\n")
    assert 'title: "Getting Started with FastAPI"' in r.md
    assert "---" in r.md


def test_canonical_url_in_metadata(
    pipeline: Callable[..., SimpleNamespace], read_fixture: Callable[[str], str]
) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert "canonical_url" in r.meta or "og_image" in r.meta
