#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx>=0.28",
#     "beautifulsoup4>=4.13",
#     "lxml>=5.0",
#     "markdownify>=0.14",
#     "typer>=0.15",
#     "toon-format>=0.9.0b1",
# ]
# ///
"""Convert web articles to clean, faithful markdown."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlparse

import httpx
import typer
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from markdownify import MarkdownConverter
from toon_format import decode, encode

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from toon_format.types import JsonValue

__version__ = "0.7.0"

app = typer.Typer()

USER_AGENT = f"Mozilla/5.0 (compatible; h2md/{__version__}; +https://github.com/zyplux/zyp-skills)"

STRIP_TAGS = {"script", "style", "button", "svg", "nav", "footer", "header", "noscript"}
INLINE_TAGS = {
    "span",
    "a",
    "em",
    "strong",
    "b",
    "i",
    "code",
    "abbr",
    "time",
    "small",
    "sub",
    "sup",
}


# ---------------------------------------------------------------------------
# Stage 1: Fetch
# ---------------------------------------------------------------------------


def _fetch(workspace: Path, url: str) -> None:
    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
    (workspace / "raw.html").write_bytes(resp.content)
    headers_data = {
        "status_code": resp.status_code,
        "final_url": str(resp.url),
        "headers": dict(resp.headers),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    (workspace / "raw.headers.toon").write_text(encode(headers_data) + "\n")


# ---------------------------------------------------------------------------
# Shared: tab-flattening helper
# ---------------------------------------------------------------------------


def _build_flat_tabs(soup: BeautifulSoup, labels: list[str], panels: Sequence[Tag | None]) -> Tag:
    replacement = soup.new_tag("div", attrs={"class": "h2md-flattened-tabs"})
    for label, panel in zip(labels, panels, strict=False):
        if not panel:
            continue
        heading = soup.new_tag("h4")
        heading.string = label
        replacement.append(heading)
        for child in list(panel.children):
            if isinstance(child, Tag) or (isinstance(child, NavigableString) and child.strip()):
                replacement.append(child.extract())
    return replacement


# ---------------------------------------------------------------------------
# Stage 2: Extract (structural preprocessing + article extraction + metadata)
# ---------------------------------------------------------------------------


def _extract_line_span_text(line_span: Tag) -> str:
    parts: list[str] = []
    for child in line_span.children:
        if isinstance(child, Tag):
            parts.append(child.get_text())
        elif isinstance(child, NavigableString) and not child.isspace():
            parts.append(str(child))
    return "".join(parts)


def _collapse_code_spans(soup: BeautifulSoup) -> None:
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if not code or not isinstance(code, Tag):
            continue
        if not code.find("span"):
            continue
        lang_classes = [c for c in _classes_from_tag(code) if c.startswith(("language-", "lang-", "highlight-"))]
        line_spans = code.find_all("span", class_="line")
        text = "\n".join(_extract_line_span_text(ls) for ls in line_spans) if len(line_spans) else code.get_text()
        code.clear()
        code.string = text
        if lang_classes:
            code["class"] = " ".join(lang_classes)


def _insert_span_whitespace(tag: Tag) -> None:
    for child in list(tag.descendants):
        if not isinstance(child, Tag) or child.name not in INLINE_TAGS:
            continue
        prev = child.previous_sibling
        if isinstance(prev, Tag) and prev.name in INLINE_TAGS:
            prev_text = prev.get_text()
            curr_text = child.get_text()
            if (
                prev_text
                and curr_text
                and not prev_text.endswith((" ", "\n"))
                and not curr_text.startswith((" ", "\n"))
            ):
                child.insert_before(" ")


def _flatten_tablists(soup: BeautifulSoup) -> None:
    for tablist in soup.find_all(role="tablist"):
        tab_elements = tablist.find_all(role="tab")
        labels = [t.get_text(strip=True) for t in tab_elements]
        panel_ids = [t.get("aria-controls", "") for t in tab_elements]

        panels: list[Tag | None] = []
        for pid in panel_ids:
            if pid:
                panel = soup.find(id=pid)
                if panel and isinstance(panel, Tag):
                    panels.append(panel)
                    continue
            panels.append(None)

        if not panels or all(p is None for p in panels):
            siblings = []
            node = tablist.next_sibling
            while node:
                if isinstance(node, Tag) and node.get("role") == "tabpanel":
                    siblings.append(node)
                node = node.next_sibling if node else None
            panels = siblings + [None] * (len(labels) - len(siblings))

        replacement = _build_flat_tabs(soup, labels, panels)
        tablist.replace_with(replacement)
        for panel in panels:
            if panel and isinstance(panel, Tag) and panel.parent:
                panel.decompose()


_TAB_CONTAINER_CLS = {
    "codetabs",
    "tabs",
    "code-tabs",
    "tabbed-content",
    "code-group",
    "tabbed-set",
}
_TAB_BUTTON_CLS = {
    "codeblocktab",
    "tabs__item",
    "tab-button",
    "tab",
    "code-group-tab",
    "codetab",
    "tabbed-set--tab",
}
_TAB_PANEL_CLS = {
    "codeblockcontent",
    "tabitem",
    "tab-panel",
    "tab-content",
    "tab-pane",
    "code-group-panel",
    "codetabitem",
    "codetabcontent",
    "tabbed-block",
}


def _has_any_class(tag: Tag, class_set: set[str]) -> bool:
    return any(c.lower() in class_set for c in _classes_from_tag(tag))


def _flatten_class_tabs(soup: BeautifulSoup) -> None:
    for container in soup.find_all(lambda t: isinstance(t, Tag) and _has_any_class(t, _TAB_CONTAINER_CLS)):
        if container.find(role="tablist"):
            continue

        buttons = container.find_all(lambda t: isinstance(t, Tag) and _has_any_class(t, _TAB_BUTTON_CLS))
        if not buttons:
            all_children = [c for c in container.children if isinstance(c, Tag)]
            nav = next(
                (c for c in all_children if c.name in {"nav", "ul", "div"} and not c.find("pre")),
                None,
            )
            if nav:
                buttons = [c for c in nav.descendants if isinstance(c, Tag) and c.string and c.string.strip()]

        labels = [b.get_text(strip=True) for b in buttons]
        if not labels:
            continue

        panels = container.find_all(lambda t: isinstance(t, Tag) and _has_any_class(t, _TAB_PANEL_CLS))
        if not panels:
            panels = [c for c in container.children if isinstance(c, Tag) and c.find("pre")]

        if not panels:
            continue

        replacement = _build_flat_tabs(soup, labels, panels)
        container.replace_with(replacement)


def _reconstruct_terminal_regions(soup: BeautifulSoup) -> None:
    terminal_keywords = {"terminal", "output", "console", "command", "shell"}
    for region in soup.find_all(role="region"):
        aria_label = str(region.get("aria-label") or "").lower()
        if not any(kw in aria_label for kw in terminal_keywords):
            continue
        texts: list[str] = []
        for el in region.descendants:
            if isinstance(el, NavigableString):
                text = str(el).strip()
                if text:
                    texts.append(text)
        if texts:
            pre = soup.new_tag("pre")
            code = soup.new_tag("code", attrs={"class": "language-text"})
            code.string = " ".join(texts)
            pre.append(code)
            region.replace_with(pre)


_MIN_SIBLING_TAGS_TO_CLEAN = 2


def _clean_code_containers(soup: BeautifulSoup) -> None:
    for pre in soup.find_all("pre"):
        parent = pre.parent
        if not parent or not isinstance(parent, Tag):
            continue
        if parent.name in {"body", "article", "main", "section"}:
            continue
        children = [c for c in parent.children if isinstance(c, Tag)]
        if len(children) < _MIN_SIBLING_TAGS_TO_CLEAN:
            continue
        for sibling in list(parent.children):
            if sibling is pre or not isinstance(sibling, Tag):
                continue
            if sibling.name in {"code", "pre"}:
                continue
            if sibling.find("pre"):
                continue
            sib_text = sibling.get_text(strip=True)
            if not sib_text:
                sibling.decompose()


_COPY_CLS = {
    "copy",
    "copyicon",
    "copy-icon",
    "copy-button",
    "clipboard",
    "clipboard-copy",
    "copy-code",
}


def _strip_copy_elements(soup: BeautifulSoup) -> None:
    for pre in soup.find_all("pre"):
        container = pre.parent if pre.parent and isinstance(pre.parent, Tag) else pre
        for el in container.find_all(lambda t: isinstance(t, Tag) and _has_any_class(t, _COPY_CLS)):
            el.decompose()


def _preprocess_dom(soup: BeautifulSoup) -> BeautifulSoup:
    _flatten_tablists(soup)
    _flatten_class_tabs(soup)
    _reconstruct_terminal_regions(soup)

    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(role="button"):
        if isinstance(tag, Tag):
            tag.decompose()

    _strip_copy_elements(soup)
    _clean_code_containers(soup)
    _collapse_code_spans(soup)
    _insert_span_whitespace(soup)
    return soup


_MIN_ARTICLE_TEXT_LENGTH = 100


def _find_best_div(soup: BeautifulSoup) -> Tag | None:
    best: Tag | None = None
    best_score = 0
    for div in soup.find_all("div"):
        if not isinstance(div, Tag):
            continue
        p_count = len(div.find_all("p", recursive=False))
        text_len = len(div.get_text(strip=True))
        score = p_count * 100 + text_len
        if score > best_score:
            best_score = score
            best = div
    return best


def _extract_article(soup: BeautifulSoup, selector: str | None) -> str:
    if selector:
        el = soup.select_one(selector)
        if el:
            return str(el)

    article = soup.find("article")
    if article and isinstance(article, Tag):
        text = article.get_text(strip=True)
        if len(text) > _MIN_ARTICLE_TEXT_LENGTH:
            return str(article)

    main = soup.find("main")
    if main and isinstance(main, Tag):
        text = main.get_text(strip=True)
        if len(text) > _MIN_ARTICLE_TEXT_LENGTH:
            return str(main)

    best = _find_best_div(soup)
    if best:
        return str(best)

    return str(soup.body) if soup.body else str(soup)


_JSONLD_ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle", "TechArticle"}

_OG_MAP = {
    "og:title": "title",
    "og:description": "description",
    "og:url": "canonical_url",
    "og:image": "og_image",
    "og:site_name": "site_name",
    "og:locale": "lang",
    "article:author": "author",
    "article:published_time": "date",
}

_TW_MAP = {
    "twitter:title": "title",
    "twitter:description": "description",
    "twitter:image": "og_image",
}


def _extract_jsonld_metadata(soup: BeautifulSoup, meta: dict[str, Any]) -> None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError, TypeError:
            continue
        if isinstance(data, list):
            fallback_article: dict[str, Any] = {}
            data = next((d for d in data if d.get("@type") in _JSONLD_ARTICLE_TYPES), fallback_article)
        if data.get("@type") not in _JSONLD_ARTICLE_TYPES:
            continue
        meta.setdefault("title", data.get("headline"))
        author = data.get("author")
        if isinstance(author, dict):
            meta.setdefault("author", author.get("name"))
        elif isinstance(author, list) and author:
            names = [a.get("name", str(a)) if isinstance(a, dict) else str(a) for a in author]
            meta.setdefault("author", ", ".join(n for n in names if n))
        meta.setdefault("date", data.get("datePublished"))
        meta.setdefault("description", data.get("description"))
        meta.setdefault("canonical_url", data.get("url"))


def _extract_meta_tags(soup: BeautifulSoup, meta: dict[str, Any]) -> None:
    for tag in soup.find_all("meta"):
        prop = str(tag.get("property", ""))
        name = str(tag.get("name", "")).lower()
        content = str(tag.get("content", ""))
        if not content:
            continue
        if prop in _OG_MAP:
            meta.setdefault(_OG_MAP[prop], content)
        if name in _TW_MAP:
            meta.setdefault(_TW_MAP[name], content)
        if name == "author":
            meta.setdefault("author", content)
        elif name == "description":
            meta.setdefault("description", content)


def _extract_fallback_metadata(soup: BeautifulSoup, meta: dict[str, Any]) -> None:
    title_tag = soup.find("title")
    if title_tag:
        meta.setdefault("title", title_tag.get_text(strip=True))

    canonical = soup.find("link", attrs={"rel": "canonical"})
    if canonical and isinstance(canonical, Tag):
        meta.setdefault("canonical_url", str(canonical.get("href", "")))

    lang_tag = soup.find("html")
    if lang_tag and isinstance(lang_tag, Tag) and lang_tag.get("lang"):
        meta["lang"] = lang_tag["lang"]


def _extract_metadata(soup: BeautifulSoup) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    _extract_jsonld_metadata(soup, meta)
    _extract_meta_tags(soup, meta)
    _extract_fallback_metadata(soup, meta)
    return meta


def _extract(workspace: Path, selector: str | None) -> None:
    raw_html = (workspace / "raw.html").read_text(errors="replace")
    raw_soup = BeautifulSoup(raw_html, "lxml")
    meta = _extract_metadata(raw_soup)

    soup = _preprocess_dom(raw_soup)
    article_html = _extract_article(soup, selector)
    (workspace / "article.html").write_text(article_html)

    article_text = BeautifulSoup(article_html, "lxml").get_text(" ", strip=True)
    words = len(article_text.split())
    meta["word_count"] = words
    meta["reading_time_minutes"] = max(1, round(words / 250))

    (workspace / "meta.toon").write_text(encode(meta) + "\n")


# ---------------------------------------------------------------------------
# Stage 3: Assets
# ---------------------------------------------------------------------------


def _assets(workspace: Path, *, no_assets: bool) -> None:
    if no_assets:
        return
    article_path = workspace / "article.html"
    html = article_path.read_text(errors="replace")
    soup = BeautifulSoup(html, "lxml")
    imgs = soup.find_all("img")
    if not imgs:
        return

    assets_dir = workspace / "assets"
    assets_dir.mkdir(exist_ok=True)
    downloaded = 0

    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        for img in imgs:
            src = str(img.get("src", ""))
            if not src or src.startswith("data:"):
                continue
            try:
                resp = client.get(src)
                resp.raise_for_status()
            except httpx.HTTPError, httpx.InvalidURL:
                continue
            ext = Path(urlparse(src).path).suffix or ".bin"
            filename = re.sub(r"[^a-zA-Z0-9]", "_", src)[-40:] + ext
            (assets_dir / filename).write_bytes(resp.content)
            img["src"] = f"assets/{filename}"
            downloaded += 1

    if downloaded:
        article_path.write_text(str(soup))


# ---------------------------------------------------------------------------
# Stage 4: Convert (HTML -> Markdown)
# ---------------------------------------------------------------------------

LANG_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\[[\w.-]+\]", re.MULTILINE), "toml"),
    (
        re.compile(r"^(curl|bun|npm|npx|docker|brew|apt|pip|yarn|pnpm|deno)\b", re.MULTILINE),
        "bash",
    ),
    (re.compile(r"^\s*[\[{]"), "json"),
    (re.compile(r"<[A-Z][a-zA-Z]*[\s/>]"), "tsx"),
    (
        re.compile(
            r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "sql",
    ),
    (
        re.compile(
            r":\s*(string|number|boolean|void|any)\b|^interface\s|^type\s+\w+\s*=",
            re.MULTILINE,
        ),
        "typescript",
    ),
    (
        re.compile(
            r"^import\s.+\sfrom\s+['\"]|^export\s+(default\s+)?(function|class|const|let|var|async)\s",
            re.MULTILINE,
        ),
        "javascript",
    ),
    (
        re.compile(r"^(def \w+\(|class \w+[:(]|from \w+ import )", re.MULTILINE),
        "python",
    ),
    (re.compile(r"(function\s|const\s|let\s|=>|module\.exports)"), "javascript"),
    (re.compile(r"^(html|body|div|span|\.|#|@media)\s*\{", re.MULTILINE), "css"),
]


def _sniff_language(code: str) -> str:
    code = code.strip()
    if not code:
        return "text"
    for pattern, lang in LANG_PATTERNS:
        if pattern.search(code):
            return lang
    return "text"


def _classes_from_tag(tag: Tag) -> list[str]:
    raw = tag.get("class")
    if raw is None:
        return []
    if isinstance(raw, str):
        return raw.split()
    return list(raw)


_KNOWN_LANGS = {
    "javascript",
    "typescript",
    "python",
    "bash",
    "sh",
    "shell",
    "zsh",
    "json",
    "toml",
    "yaml",
    "yml",
    "html",
    "css",
    "scss",
    "sql",
    "rust",
    "go",
    "java",
    "kotlin",
    "swift",
    "ruby",
    "php",
    "c",
    "cpp",
    "tsx",
    "jsx",
    "xml",
    "graphql",
    "diff",
    "markdown",
    "text",
    "powershell",
    "dockerfile",
    "makefile",
    "lua",
    "perl",
    "r",
    "zig",
}

_EXT_TO_LANG = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".md": "markdown",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
}


def _lang_from_data_attrs(el: Tag) -> str | None:
    for tag in [el] + ([el.parent] if el.parent and isinstance(el.parent, Tag) else []):
        for attr in ("data-language", "data-lang"):
            val = str(tag.get(attr, "")).strip().lower()
            if val and val in _KNOWN_LANGS:
                return val
    return None


def _lang_from_siblings(el: Tag) -> str | None:
    parent = el.parent
    if not parent or not isinstance(parent, Tag):
        return None
    for sibling in parent.children:
        if sibling is el or not isinstance(sibling, Tag):
            continue
        text = sibling.get_text(strip=True).lower()
        if text in _KNOWN_LANGS:
            return text
        for ext, lang in _EXT_TO_LANG.items():
            if text.endswith(ext):
                return lang
    return None


def _code_language_callback(el: Tag) -> str:
    candidates = [el]
    code_child = el.find("code")
    if code_child and isinstance(code_child, Tag):
        candidates.insert(0, code_child)
    for tag in candidates:
        for cls in _classes_from_tag(tag):
            for prefix in ("language-", "lang-", "highlight-"):
                if cls.startswith(prefix):
                    lang = cls[len(prefix) :]
                    if lang and lang != "text":
                        return lang

    from_data = _lang_from_data_attrs(el)
    if from_data:
        return from_data

    from_sibling = _lang_from_siblings(el)
    if from_sibling:
        return from_sibling

    code = el.get_text()
    return _sniff_language(code)


def _convert(workspace: Path) -> None:
    article_html = (workspace / "article.html").read_text(errors="replace")
    converter = MarkdownConverter(
        heading_style="ATX",
        code_language="text",
        code_language_callback=_code_language_callback,
        strip=["button", "svg", "nav"],
        escape_misc=False,
    )
    md = converter.convert(article_html)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.strip() + "\n"
    (workspace / "article.raw.md").write_text(md)


# ---------------------------------------------------------------------------
# Stage 5: Postprocess (normalize + lint + detect)
# ---------------------------------------------------------------------------

_BOLD_HEADING_RE = re.compile(r"^\*\*([A-Z][^*]{3,80})\*\*$")
_EMPTY_FENCE_RE = re.compile(r"```[a-z]*\n\s*\n?```", re.MULTILINE)

_FUSED_RE = re.compile(r"\S{80,}")
_HTML_LEAK_RE = re.compile(r"<(svg|button|input|form)\b|role=[\"']")
_EMPTY_BLOCK_RE = re.compile(r"```[a-z]*\n\s*\n?```")
_TAB_LABEL_RE = re.compile(r"^[a-z]{2,15}$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[^\n]*\n.*?^```", re.MULTILINE | re.DOTALL)
_FENCE_LANG_RE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
_MD_LINK_URL_RE = re.compile(r"\]\([^\)]+\)")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?^---", re.MULTILINE | re.DOTALL)

_MIN_SNIFFABLE_CODE_LENGTH = 8


def _exclusion_zones(md: str) -> list[tuple[int, int]]:
    zones: list[tuple[int, int]] = []
    for pattern in (_FENCE_RE, _MD_LINK_URL_RE, _INLINE_CODE_RE, _FRONTMATTER_RE):
        zones.extend((m.start(), m.end()) for m in pattern.finditer(md))
    zones.sort()
    return zones


def _in_exclusion_zone(start: int, end: int, zones: list[tuple[int, int]]) -> bool:
    for zs, ze in zones:
        if zs > end:
            break
        if start < ze and end > zs:
            return True
    return False


def _context_around(text: str, start: int, end: int, ctx: int = 40) -> str:
    s = max(0, start - ctx)
    e = min(len(text), end + ctx)
    return text[s:e].replace("\n", "\\n")


def _normalize(workspace: Path) -> None:
    md = (workspace / "article.raw.md").read_text()
    meta_path = workspace / "meta.toon"
    decoded_meta: JsonValue = decode(meta_path.read_text()) if meta_path.exists() else {}
    meta: dict[str, Any] = decoded_meta if isinstance(decoded_meta, dict) else {}

    frontmatter_lines = ["---"]
    if meta.get("title"):
        safe_title = meta["title"].replace('"', '\\"')
        frontmatter_lines.append(f'title: "{safe_title}"')
    if meta.get("author"):
        frontmatter_lines.append(f'author: "{meta["author"]}"')
    if meta.get("date"):
        frontmatter_lines.append(f'date: "{meta["date"]}"')
    if meta.get("canonical_url"):
        frontmatter_lines.append(f'source: "{meta["canonical_url"]}"')
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    md = _EMPTY_FENCE_RE.sub("", md)

    lines = md.split("\n")
    normalized: list[str] = []
    for line in lines:
        m = _BOLD_HEADING_RE.match(line.strip())
        if m:
            normalized.append(f"#### {m.group(1)}")
        else:
            normalized.append(line.rstrip())
    md = "\n".join(normalized)

    content_lines = md.lstrip().split("\n")
    first_content = next((ln for ln in content_lines if ln.strip()), "")
    if not first_content.startswith("# ") and meta.get("title"):
        md = f"# {meta['title']}\n\n{md}"

    md = re.sub(r"\n{3,}", "\n\n", md)
    md = frontmatter + "\n\n" + md.strip() + "\n"

    (workspace / "article.prelint.md").write_text(md)


def _lint(workspace: Path) -> None:
    prelint = workspace / "article.prelint.md"
    article = workspace / "article.md"
    shutil.copy2(prelint, article)

    rumdl = shutil.which("rumdl")
    if rumdl is None:
        (workspace / "lint.report.txt").write_text("rumdl not found on PATH, skipping lint\n")
        return

    config = Path(__file__).resolve().parent / ".rumdl.toml"
    cfg_args = ["--config", str(config)] if config.exists() else []

    subprocess.run(
        [rumdl, "check", "--fix", *cfg_args, str(article)],
        capture_output=True,
        text=True,
        check=False,
    )

    result = subprocess.run(
        [rumdl, "check", *cfg_args, str(article)],
        capture_output=True,
        text=True,
        check=False,
    )
    (workspace / "lint.report.txt").write_text(result.stdout + result.stderr)


def _detect_fused_text(md: str, zones: list[tuple[int, int]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for m in _FUSED_RE.finditer(md):
        if _in_exclusion_zone(m.start(), m.end(), zones):
            continue
        line_num = md[: m.start()].count("\n") + 1
        ctx = _context_around(md, m.start(), m.end())
        issues.append({
            "type": "fused text",
            "line": line_num,
            "find": ctx,
            "fix": "verify whitespace between tokens",
        })
    return issues


def _detect_html_leakage(md: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for m in _HTML_LEAK_RE.finditer(md):
        line_num = md[: m.start()].count("\n") + 1
        ctx = _context_around(md, m.start(), m.end())
        issues.append({
            "type": "HTML leakage",
            "line": line_num,
            "find": ctx,
            "fix": "remove or convert to markdown",
        })
    return issues


def _detect_empty_blocks(md: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for m in _EMPTY_BLOCK_RE.finditer(md):
        line_num = md[: m.start()].count("\n") + 1
        ctx = _context_around(md, m.start(), m.end(), 20)
        issues.append({
            "type": "empty code block",
            "line": line_num,
            "find": ctx,
            "fix": "remove empty fence",
        })
    return issues


def _detect_wrong_language(md: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for m in _FENCE_LANG_RE.finditer(md):
        lang = m.group(1)
        if lang and lang != "text":
            continue
        content = m.group(2).strip()
        if not content or len(content) < _MIN_SNIFFABLE_CODE_LENGTH:
            continue
        sniffed = _sniff_language(content)
        if sniffed != "text":
            line_num = md[: m.start()].count("\n") + 1
            issues.append({
                "type": "wrong language",
                "line": line_num,
                "detected": sniffed,
                "fix": f"change fence to ```{sniffed}",
            })
    return issues


def _detect_suspicious_tab_labels(md: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lines = md.split("\n")
    for i, line in enumerate(lines[:-1]):
        if _TAB_LABEL_RE.match(line.strip()) and i + 1 < len(lines) and lines[i + 1].strip().startswith("```"):
            ctx = f"{line.strip()}\\n{lines[i + 1].strip()}"
            issues.append({
                "type": "suspicious tab label",
                "line": i + 1,
                "find": ctx,
                "fix": "merge as prose prefix or remove",
            })
    return issues


def _detect(workspace: Path) -> list[dict[str, Any]]:
    article = workspace / "article.md"
    if not article.exists():
        return []
    md = article.read_text()
    zones = _exclusion_zones(md)
    return [
        *_detect_fused_text(md, zones),
        *_detect_html_leakage(md),
        *_detect_empty_blocks(md),
        *_detect_wrong_language(md),
        *_detect_suspicious_tab_labels(md),
    ]


def _build_sections(workspace: Path) -> list[dict[str, Any]]:
    article = workspace / "article.md"
    if not article.exists():
        return []
    md = article.read_text()
    lines = md.split("\n")

    sections: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            sections.append({"title": m.group(2).strip(), "line": i + 1})

    for idx, sec in enumerate(sections):
        start = sec["line"]
        end = sections[idx + 1]["line"] - 1 if idx + 1 < len(sections) else len(lines)
        section_text = "\n".join(lines[start : min(end, len(lines))])
        sec["tokens"] = len(section_text) // 4

    return sections


def _postprocess(workspace: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _normalize(workspace)
    _lint(workspace)
    issues = _detect(workspace)
    sections = _build_sections(workspace)
    return issues, sections


# ---------------------------------------------------------------------------
# Stage 6: Handoff
# ---------------------------------------------------------------------------


def _handoff(workspace: Path, url: str, issues: list[dict[str, Any]], sections: list[dict[str, Any]]) -> None:
    meta_path = workspace / "meta.toon"
    decoded_meta: JsonValue = decode(meta_path.read_text()) if meta_path.exists() else {}
    meta: dict[str, Any] = decoded_meta if isinstance(decoded_meta, dict) else {}
    lint_path = workspace / "lint.report.txt"
    lint_text = lint_path.read_text() if lint_path.exists() else ""
    lint_remaining = len([ln for ln in lint_text.strip().split("\n") if ln.strip() and "not found" not in ln.lower()])

    output: dict[str, Any] = {
        "h2md": {
            "url": url,
            "workspace": str(workspace),
            "article": "article.md",
            "title": meta.get("title", ""),
            "tokens": sum(s.get("tokens", 0) for s in sections),
            "lint_remaining": lint_remaining,
        },
        "sections": sections,
    }
    if issues:
        output["issues"] = issues
        output["next"] = "Edit article.md to fix issues. Cross-reference article.html for fidelity."
    else:
        output["next"] = "Article is clean. Read article.md."
    typer.echo(encode(output))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(f"h2md {__version__}")
        raise typer.Exit


@app.command()
def main(
    url: Annotated[str, typer.Argument(help="URL of the article to convert")],
    *,
    no_assets: Annotated[bool, typer.Option("--no-assets", help="Skip image download")] = False,
    js: Annotated[bool, typer.Option("--js", help="JS rendering (requires playwright)")] = False,
    selector: Annotated[str | None, typer.Option("--selector", help="CSS selector for extraction")] = None,
    copy_to: Annotated[str | None, typer.Option("--copy-to", help="Copy article.md to this path")] = None,
    _version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version"),
    ] = None,
) -> None:
    """Convert a web article to clean, faithful markdown."""
    if js:
        msg = "JS rendering requires playwright which is not installed"
        raise typer.BadParameter(msg)

    workspace = Path(tempfile.mkdtemp(prefix="h2md_"))

    stages: list[tuple[str, Callable[[], None]]] = [
        ("fetch", lambda: _fetch(workspace, url)),
        ("extract", lambda: _extract(workspace, selector)),
        ("assets", lambda: _assets(workspace, no_assets=no_assets)),
        ("convert", lambda: _convert(workspace)),
    ]

    for name, fn in stages:
        try:
            fn()
        except Exception as exc:
            typer.echo(f"Stage '{name}' failed: {exc}", err=True)
            raise typer.Exit(1) from exc

    try:
        issues, sections = _postprocess(workspace)
    except Exception as exc:
        typer.echo(f"Stage 'postprocess' failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    if copy_to:
        shutil.copy2(workspace / "article.md", copy_to)

    _handoff(workspace, url, issues, sections)


if __name__ == "__main__":
    app()
