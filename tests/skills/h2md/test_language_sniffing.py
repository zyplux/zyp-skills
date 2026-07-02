from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import SimpleNamespace


def _code_block_html(code: str) -> str:
    return f"""<!DOCTYPE html><html><body><article>
    <h1>Code Example</h1>
    <p>Example:</p>
    <pre><code>{code}</code></pre>
    </article></body></html>"""


def test_toml(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("[package]\nname = 'foo'"))
    assert "```toml" in r.md


def test_bash_curl(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("curl -fsSL https://example.com"))
    assert "```bash" in r.md


def test_bash_npm(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("npm install express"))
    assert "```bash" in r.md


def test_json(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html('{"key": "value"}'))
    assert "```json" in r.md


def test_python(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("from fastapi import FastAPI\n\napp = FastAPI()"))
    assert "```python" in r.md


def test_javascript(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("const app = () => {}"))
    assert "```javascript" in r.md


def test_tsx(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("&lt;Button onClick={handler}&gt;Click&lt;/Button&gt;"))
    assert "```tsx" in r.md


def test_sql(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("SELECT * FROM users WHERE id = 1"))
    assert "```sql" in r.md
    r = pipeline(_code_block_html("CREATE TABLE users (id INT)"))
    assert "```sql" in r.md


def test_typescript(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("interface User {\n  name: string;\n}"))
    assert "```typescript" in r.md
    r = pipeline(_code_block_html("type Foo = string | number"))
    assert "```typescript" in r.md


def test_es6_import_is_javascript_not_python(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("import express from 'express'\nconst app = express()"))
    assert "```javascript" in r.md
    r = pipeline(_code_block_html('import { useState } from "react"'))
    assert "```javascript" in r.md


def test_es6_export_is_javascript(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("export default function handler(req, res) {}"))
    assert "```javascript" in r.md
    r = pipeline(_code_block_html("export const config = { runtime: 'edge' }"))
    assert "```javascript" in r.md


def test_default_text(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html("some plain text output"))
    assert "```text" in r.md


def test_empty_code_block_does_not_crash_pipeline(pipeline: Callable[..., SimpleNamespace]) -> None:
    r = pipeline(_code_block_html(""))
    assert "```" not in r.md
    assert "Example:" in r.md
