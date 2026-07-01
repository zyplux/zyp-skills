#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["duckdb>=1.0", "typer>=0.15", "toon-format>=0.9.0b1"]
# ///
"""Quick parquet inspection CLI."""

from __future__ import annotations

import glob as globmod
from pathlib import Path
from typing import Annotated

import duckdb
import typer
from toon_format import encode

__version__ = "0.8.0"

app = typer.Typer()


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(f"peek {__version__}")
        raise typer.Exit


def _split_cols(s: str) -> list[str]:
    return [c.strip() for c in s.split(",")]


def _resolve_paths(pattern: str) -> list[Path]:
    matches = sorted(globmod.glob(pattern))
    if not matches:
        msg = f"No files match: {pattern}"
        raise typer.BadParameter(msg)
    paths = [Path(m) for m in matches]
    for p in paths:
        if not p.is_file():
            msg = f"Not a file: {p}"
            raise typer.BadParameter(msg)
    return paths


def _escape_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{_escape_path(path)}')")
    return con


def _to_dicts(con: duckdb.DuckDBPyConnection) -> list[dict]:
    columns = [desc[0] for desc in con.description]
    return [dict(zip(columns, row, strict=False)) for row in con.fetchall()]


def _describe(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    rows = con.execute("DESCRIBE t").fetchall()
    return [(row[0], row[1]) for row in rows]


def _validate_columns(available: list[str], columns: list[str]) -> None:
    bad = [c for c in columns if c not in available]
    if bad:
        msg = f"Column(s) not found: {', '.join(bad)}. Available: {', '.join(available)}"
        raise typer.BadParameter(msg)


def _count(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT COUNT(*) FROM t").fetchone()
    assert row is not None
    return row[0]


def _preview(
    con: duckdb.DuckDBPyConnection,
    stem: str,
    n: int,
    *,
    all_rows: bool,
    types: bool,
    cols: str | None,
) -> dict:
    desc = _describe(con)
    col_names = [name for name, _ in desc]
    if cols:
        col_list = _split_cols(cols)
        _validate_columns(col_names, col_list)
        col_expr = ", ".join(f'"{c}"' for c in col_list)
        desc_map = dict(desc)
        desc = [(name, desc_map[name]) for name in col_list]
    else:
        col_expr = "*"
    total = _count(con)
    limit = "" if all_rows else f" LIMIT {n}"
    con.execute(f"SELECT {col_expr} FROM t{limit}")
    output: dict = {stem: _to_dicts(con)}
    if types:
        output["types"] = [dtype for _, dtype in desc]
    if not all_rows and n < total:
        output["rows"] = total
    return output


def _schema(con: duckdb.DuckDBPyConnection, stem: str) -> dict:
    desc = _describe(con)
    total = _count(con)
    return {stem: dict(desc), "rows": total}


def _fmt_num(s: str) -> str:
    val = float(s)
    rounded = round(val, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _describe_stats(con: duckdb.DuckDBPyConnection, stem: str) -> str:
    rows = con.execute("SUMMARIZE t").fetchall()
    total = rows[0][10] if rows else 0
    lines = [f"{stem}{{{len(rows)} cols, {total} rows}}:"]
    for row in rows:
        name, dtype = row[0], row[1]
        null_val = float(row[11])
        null_str = f"{int(null_val)}%" if null_val == int(null_val) else f"{null_val:.1f}%"
        if row[5] is not None:
            parts = [
                f"min={_fmt_num(row[2])}",
                f"max={_fmt_num(row[3])}",
                f"avg={_fmt_num(row[5])}",
                f"q25={_fmt_num(row[7])}",
                f"q50={_fmt_num(row[8])}",
                f"q75={_fmt_num(row[9])}",
                f"null={null_str}",
            ]
        else:
            parts = [f"unique={row[4]}", f"null={null_str}"]
        lines.append(f"  {name}({dtype}): {' '.join(parts)}")
    return "\n".join(lines)


def _unique(con: duckdb.DuckDBPyConnection, columns: str) -> dict:
    col_list = _split_cols(columns)
    desc = _describe(con)
    _validate_columns([name for name, _ in desc], col_list)
    output: dict = {}
    for col_name in col_list:
        rows = con.execute(
            f'SELECT DISTINCT "{col_name}" FROM t WHERE "{col_name}" IS NOT NULL ORDER BY "{col_name}"'
        ).fetchall()
        output[col_name] = [r[0] for r in rows]
    return output


def _groupby(con: duckdb.DuckDBPyConnection, columns: str) -> dict:
    col_list = _split_cols(columns)
    desc = _describe(con)
    _validate_columns([name for name, _ in desc], col_list)
    col_expr = ", ".join(f'"{c}"' for c in col_list)
    con.execute(f"SELECT {col_expr}, COUNT(*) as len FROM t GROUP BY {col_expr} ORDER BY {col_expr}")
    return {"group": _to_dicts(con)}


def _register_tables(con: duckdb.DuckDBPyConnection, paths: list[Path]) -> list[str]:
    names = ["t"]
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{_escape_path(paths[0])}')")
    for i, p in enumerate(paths, 1):
        name = f"t{i}"
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{_escape_path(p)}')")
        names.append(name)
    return names


def _sql_error_hint(msg: str, table_names: list[str]) -> str:
    lower = msg.lower()
    if "table" in lower and ("does not exist" in lower or "not found" in lower):
        return f"{msg}\nAvailable tables: {', '.join(table_names)}"
    if "column" in lower and "not found" in lower:
        return f"{msg}\nHint: use peek <path> -c to list columns"
    return msg


def _sql(con: duckdb.DuckDBPyConnection, query: str, table_names: list[str]) -> dict:
    try:
        con.execute(query)
        return {"result": _to_dicts(con)}
    except duckdb.Error as e:
        msg = _sql_error_hint(str(e), table_names)
        typer.echo(msg, err=True)
        raise typer.Exit(1)


@app.command()
def main(
    path: Annotated[list[str], typer.Argument(help="Path(s) or glob pattern(s) for parquet file(s)")],
    n: Annotated[int, typer.Option("-n", help="Number of preview rows")] = 2,
    all_rows: Annotated[bool, typer.Option("-a", help="Show all rows")] = False,
    types: Annotated[bool, typer.Option("-t", help="Include column types")] = False,
    schema: Annotated[bool, typer.Option("-c", help="Show columns and types only")] = False,
    describe: Annotated[bool, typer.Option("-d", help="Describe columns with stats")] = False,
    unique: Annotated[str | None, typer.Option("-u", help="Show unique values of column(s)")] = None,
    group: Annotated[str | None, typer.Option("-g", help="Group-by column(s) with counts")] = None,
    query: Annotated[str | None, typer.Option("-q", help="SQL query (tables: t, t1, t2, ...)")] = None,
    cols: Annotated[str | None, typer.Option("--cols", help="Select columns for preview")] = None,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """Inspect parquet files — preview, schema, unique values, group-by, or SQL."""
    modes = [describe, schema, unique is not None, group is not None, query is not None]
    if sum(modes) > 1:
        msg = "Use only one mode at a time: -c, -d, -u, -g, or -q"
        raise typer.BadParameter(msg)

    paths: list[Path] = []
    for p in path:
        paths.extend(_resolve_paths(p))

    if query is not None:
        con = duckdb.connect()
        table_names = _register_tables(con, paths)
        typer.echo(encode(_sql(con, query, table_names)))
        return

    for i, p in enumerate(paths):
        con = _connect(p)
        stem = p.stem

        if describe:
            typer.echo(_describe_stats(con, stem))
        elif schema:
            typer.echo(encode(_schema(con, stem)))
        elif unique is not None:
            typer.echo(encode(_unique(con, unique)))
        elif group is not None:
            typer.echo(encode(_groupby(con, group)))
        else:
            typer.echo(encode(_preview(con, stem, n, all_rows=all_rows, types=types, cols=cols)))

        if i < len(paths) - 1:
            typer.echo()


if __name__ == "__main__":
    app()
