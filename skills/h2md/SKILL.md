---
name: h2md
description: >
  Convert a web article to clean, faithful markdown with metadata extraction, lint fixes, and artifact detection.
  Creates a workspace with raw HTML, extracted article, and intermediate files for debugging.
  Use this whenever you need article content as markdown — blog posts, docs, release notes, changelogs.
  Never manually fetch+parse HTML or use WebFetch for article extraction when h2md is available.
metadata:
  kind: cli
  version: "0.6.2"
  user-invocable: "true"
  argument-hint: <url> [--no-assets] [--selector SEL] [--copy-to PATH]
---

# h2md -- article-to-markdown converter

`h2md` is a standalone CLI on PATH. Invoke via Bash: `Bash(h2md https://example.com/blog/post)`

Use `h2md` instead of WebFetch or manual HTML parsing for article extraction. WebFetch paraphrases
content through a small summarizer model and loses code blocks, exact wording, and structure.
`h2md` does deterministic extraction preserving every word, code example, and heading from the source.

## Usage

```text
h2md <url>                                # convert article, workspace in /tmp/h2md_*/
h2md <url> --no-assets                    # skip image download
h2md <url> --selector "div.post-body"     # CSS selector override for extraction
h2md <url> --copy-to ./article.md         # copy final article.md to a local path
```

## Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--no-assets` | off | Skip image download |
| `--js` | off | JS rendering (requires playwright) |
| `--selector SEL` | auto-detect | CSS selector for extraction |
| `--copy-to PATH` | none | Copy final article.md to this path |

## Workspace layout

Each run creates a fresh temporary workspace in `/tmp/h2md_*/`:

```text
<workspace>/
  raw.html                # exact server response
  raw.headers.toon        # response headers, final URL, timestamps
  article.html            # extracted article (post structural preprocessing)
  meta.toon               # title, author, date, canonical_url, og_image, word_count
  assets/                 # downloaded images (if not --no-assets)
  article.raw.md          # converter output (pre-normalization)
  article.prelint.md      # post-normalization, pre-rumdl
  article.md              # final output (post-rumdl) — edit this file
  lint.report.txt         # remaining rumdl violations after --fix
```

## Agent workflow

The h2md output is self-contained — it includes the full section map and any detected issues.
No extra file reads are needed for planning.

1. **Read the output.** Sections show every heading with line number and token count.
   Issues (if any) list the type, line number, and suggested fix. Use this to plan targeted edits.
2. **Edit `article.md`** to fix issues. Use Edit, not Write — preserve the deterministic
   conversion as the base. Use line numbers from sections and issues for targeted
   `Read(offset=, limit=)` calls instead of reading the full article.
3. **Cross-reference `article.html`** when a passage looks wrong. The extracted HTML is the
   source of truth for wording. Grep it to verify whether text was dropped or garbled.
4. **Do not paraphrase.** Priority is wording fidelity over layout fidelity. Content must
   match the source exactly. Allowed edits: fix converter artifacts, restructure headings,
   correct code fence languages, apply lint fixes.
5. **Run `rumdl check article.md`** after editing to verify no new violations.

## Output

When issues are detected:

```text
h2md:
  url: https://example.com/blog/post
  workspace: /tmp/h2md_a1b2c3d4
  article: article.md
  title: Getting Started with FastAPI
  tokens: 812
  lint_remaining: 0
sections:
  - title: Getting Started with FastAPI
    line: 5
    tokens: 45
  - title: Installation
    line: 12
    tokens: 120
  - title: Usage
    line: 30
    tokens: 500
issues:
  - type: fused text
    line: 35
    find: thewordswerejoined
    fix: verify whitespace between tokens
  - type: wrong language
    line: 52
    detected: javascript
    fix: change fence to ```javascript
next: Edit article.md to fix issues. Cross-reference article.html for fidelity.
```

When clean (no `issues` key):

```text
h2md:
  url: https://example.com/blog/post
  workspace: /tmp/h2md_a1b2c3d4
  article: article.md
  title: Getting Started with FastAPI
  tokens: 812
  lint_remaining: 0
sections:
  - title: Getting Started with FastAPI
    line: 5
    tokens: 812
next: Article is clean. Read article.md.
```
