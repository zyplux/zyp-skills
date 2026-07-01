"""Contract tests for language sniffing.

These test a pure function with a stable interface. The function name
(_sniff_language) is treated as a stable contract — renaming it is
expected to require updating these tests. The tradeoff is worthwhile
because testing 10+ edge cases through the full pipeline would be
expensive and indirect.
"""

from __future__ import annotations


def test_toml(h2md):
    assert h2md._sniff_language("[package]\nname = 'foo'") == "toml"


def test_bash_curl(h2md):
    assert h2md._sniff_language("curl -fsSL https://example.com") == "bash"


def test_bash_npm(h2md):
    assert h2md._sniff_language("npm install express") == "bash"


def test_json(h2md):
    assert h2md._sniff_language('{"key": "value"}') == "json"


def test_python(h2md):
    assert (
        h2md._sniff_language("from fastapi import FastAPI\n\napp = FastAPI()")
        == "python"
    )


def test_javascript(h2md):
    assert h2md._sniff_language("const app = () => {}") == "javascript"


def test_tsx(h2md):
    assert h2md._sniff_language("<Button onClick={handler}>Click</Button>") == "tsx"


def test_sql(h2md):
    assert h2md._sniff_language("SELECT * FROM users WHERE id = 1") == "sql"
    assert h2md._sniff_language("CREATE TABLE users (id INT)") == "sql"


def test_typescript(h2md):
    assert h2md._sniff_language("interface User {\n  name: string;\n}") == "typescript"
    assert h2md._sniff_language("type Foo = string | number") == "typescript"


def test_es6_import_is_javascript_not_python(h2md):
    assert (
        h2md._sniff_language("import express from 'express'\nconst app = express()")
        == "javascript"
    )
    assert h2md._sniff_language('import { useState } from "react"') == "javascript"


def test_es6_export_is_javascript(h2md):
    assert (
        h2md._sniff_language("export default function handler(req, res) {}")
        == "javascript"
    )
    assert (
        h2md._sniff_language("export const config = { runtime: 'edge' }")
        == "javascript"
    )


def test_default_text(h2md):
    assert h2md._sniff_language("some plain text output") == "text"
    assert h2md._sniff_language("") == "text"
