from __future__ import annotations


def test_fused_text_detected(pipeline) -> None:
    fused = "a" * 90
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text {fused} more text in this article paragraph.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert any(i["type"] == "fused text" for i in r.issues)


def test_html_leakage_detected(pipeline) -> None:
    html = """<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text <svg viewBox="0 0 10 10"><path d="M0"/></svg> leftover content.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert any(i["type"] == "HTML leakage" for i in r.issues) or "svg" not in r.md.lower()


def test_clean_content_no_issues(pipeline, read_fixture) -> None:
    r = pipeline(read_fixture("simple_article.html"))
    assert r.issues == []


def test_url_in_markdown_link_not_flagged_as_fused(pipeline) -> None:
    long_url = "https://github.com/microsoft/TypeScript/pull/62243/files/very-long-path"
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p><a href="{long_url}">This change was provided</a> thanks to the work on this project.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert all(i["type"] != "fused text" for i in r.issues)


def test_medium_string_not_flagged_as_fused(pipeline) -> None:
    medium = "a" * 60
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text {medium} more text in this article paragraph.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert all(i["type"] != "fused text" for i in r.issues)


def test_long_string_inside_code_fence_not_flagged(pipeline) -> None:
    long_import = "a" * 90
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Some text.</p>
    <pre><code class="language-python">import {long_import}</code></pre>
    </article></body></html>"""
    r = pipeline(html)
    assert all(i["type"] != "fused text" for i in r.issues)


def test_inline_code_not_flagged_as_fused(pipeline) -> None:
    long_id = "x" * 90
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Run <code>{long_id}</code> to start the process.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert all(i["type"] != "fused text" for i in r.issues)


def test_multiple_links_zero_false_positives(pipeline) -> None:
    links = " ".join(
        f'<a href="https://example.com/very/long/path/to/resource/number/{i}">link{i}</a>' for i in range(10)
    )
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Many links: {links}</p>
    </article></body></html>"""
    r = pipeline(html)
    assert all(i["type"] != "fused text" for i in r.issues)


def test_issues_have_anchors(pipeline) -> None:
    fused = "x" * 90
    html = f"""<!DOCTYPE html><html><body><article>
    <h1>Title</h1>
    <p>Before the problem {fused} after it in the text.</p>
    </article></body></html>"""
    r = pipeline(html)
    assert r.issues
    assert all("find" in i or "detected" in i for i in r.issues)
