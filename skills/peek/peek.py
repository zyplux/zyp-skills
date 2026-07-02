#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["duckdb>=1.0", "typer>=0.15", "toon-format>=0.9.0b1"]
# ///
"""Quick parquet inspection CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NamedTuple

import duckdb
import typer
from toon_format import encode

if TYPE_CHECKING:
    from collections.abc import Callable

__version__ = "1.0.0"

app = typer.Typer()

PathArgument = Annotated[list[str], typer.Argument(help="Path(s) or glob pattern(s) for parquet file(s)")]

DuckDBRows = duckdb.DuckDBPyConnection | duckdb.DuckDBPyRelation


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(f"peek {__version__}")
        raise typer.Exit


def _split_cols(s: str) -> list[str]:
    return [c.strip() for c in s.split(",")]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _resolve_paths(pattern: str) -> list[Path]:
    candidate = Path(pattern)
    root = Path(candidate.anchor) if candidate.is_absolute() else Path()
    rel = candidate.relative_to(root) if candidate.is_absolute() else candidate
    matches = sorted(root.glob(str(rel)))
    if not matches:
        msg = f"No files match: {pattern}"
        raise typer.BadParameter(msg)
    for p in matches:
        if not p.is_file():
            msg = f"Not a file: {p}"
            raise typer.BadParameter(msg)
    return matches


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.read_parquet(str(path)).create_view("t")
    return con


def _to_dicts(rows: DuckDBRows) -> list[dict[str, Any]]:
    columns = [desc[0] for desc in rows.description]
    return [dict(zip(columns, row, strict=False)) for row in rows.fetchall()]


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
    if row is None:
        msg = "COUNT(*) returned no result"
        raise RuntimeError(msg)
    return row[0]


class PreviewOptions(NamedTuple):
    all_rows: bool
    types: bool
    cols: str | None


def _preview(con: duckdb.DuckDBPyConnection, stem: str, n: int, opts: PreviewOptions) -> dict[str, Any]:
    desc = _describe(con)
    col_names = [name for name, _ in desc]
    rel = con.table("t")
    if opts.cols:
        col_list = _split_cols(opts.cols)
        _validate_columns(col_names, col_list)
        rel = rel.project(", ".join(_quote_ident(c) for c in col_list))
        desc_map = dict(desc)
        desc = [(name, desc_map[name]) for name in col_list]
    total = _count(con)
    if not opts.all_rows:
        rel = rel.limit(n)
    output: dict[str, Any] = {stem: _to_dicts(rel)}
    if opts.types:
        output["types"] = [dtype for _, dtype in desc]
    if not opts.all_rows and n < total:
        output["rows"] = total
    return output


def _schema(con: duckdb.DuckDBPyConnection, stem: str) -> dict[str, Any]:
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


def _unique(con: duckdb.DuckDBPyConnection, columns: str) -> dict[str, Any]:
    col_list = _split_cols(columns)
    desc = _describe(con)
    _validate_columns([name for name, _ in desc], col_list)
    output: dict[str, Any] = {}
    rel = con.table("t")
    for col_name in col_list:
        quoted = _quote_ident(col_name)
        rows = rel.filter(f"{quoted} IS NOT NULL").project(quoted).distinct().order(quoted).fetchall()
        output[col_name] = [r[0] for r in rows]
    return output


def _groupby(con: duckdb.DuckDBPyConnection, columns: str) -> dict[str, Any]:
    col_list = _split_cols(columns)
    desc = _describe(con)
    _validate_columns([name for name, _ in desc], col_list)
    col_expr = ", ".join(_quote_ident(c) for c in col_list)
    rel = con.table("t").aggregate(f"{col_expr}, COUNT(*) as len", col_expr).order(col_expr)
    return {"group": _to_dicts(rel)}


def _register_tables(con: duckdb.DuckDBPyConnection, paths: list[Path]) -> list[str]:
    names = ["t"]
    for i, p in enumerate(paths, 1):
        rel = con.read_parquet(str(p))
        if i == 1:
            rel.create_view("t")
        name = f"t{i}"
        rel.create_view(name)
        names.append(name)
    return names


def _sql_error_hint(msg: str, table_names: list[str]) -> str:
    lower = msg.lower()
    if "table" in lower and ("does not exist" in lower or "not found" in lower):
        return f"{msg}\nAvailable tables: {', '.join(table_names)}"
    if "column" in lower and "not found" in lower:
        return f"{msg}\nHint: use peek schema <path> to list columns"
    return msg


def _sql(con: duckdb.DuckDBPyConnection, query: str, table_names: list[str]) -> dict[str, Any]:
    try:
        con.execute(query)
        return {"result": _to_dicts(con)}
    except duckdb.Error as e:
        msg = _sql_error_hint(str(e), table_names)
        typer.echo(msg, err=True)
        raise typer.Exit(1) from e


@app.callback()
def _cli(
    *,
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


def _resolve_all(path_patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for p in path_patterns:
        paths.extend(_resolve_paths(p))
    return paths


def _run_per_path(paths: list[Path], render: Callable[[duckdb.DuckDBPyConnection, str], str]) -> None:
    for i, p in enumerate(paths):
        with _connect(p) as con:
            typer.echo(render(con, p.stem))
        if i < len(paths) - 1:
            typer.echo()


@app.command()
def preview(
    path: PathArgument,
    *,
    n: Annotated[int, typer.Option("-n", help="Number of preview rows")] = 2,
    all_rows: Annotated[bool, typer.Option("-a", help="Show all rows")] = False,
    types: Annotated[bool, typer.Option("-t", help="Include column types")] = False,
    cols: Annotated[str | None, typer.Option("--cols", help="Select columns for preview")] = None,
) -> None:
    """Show the first N rows of parquet file(s)."""
    opts = PreviewOptions(all_rows=all_rows, types=types, cols=cols)
    _run_per_path(_resolve_all(path), lambda con, stem: encode(_preview(con, stem, n, opts)))


@app.command()
def schema(path: PathArgument) -> None:
    """Show columns and types, with row count — no data."""
    _run_per_path(_resolve_all(path), lambda con, stem: encode(_schema(con, stem)))


@app.command()
def describe(path: PathArgument) -> None:
    """Describe columns with unique/min/max/avg/quartile stats."""
    _run_per_path(_resolve_all(path), _describe_stats)


@app.command()
def unique(
    path: PathArgument,
    *,
    cols: Annotated[str, typer.Option("--cols", help="Column(s) to show distinct values for")],
) -> None:
    """Show distinct values of column(s)."""
    _run_per_path(_resolve_all(path), lambda con, _stem: encode(_unique(con, cols)))


@app.command()
def groupby(
    path: PathArgument,
    *,
    cols: Annotated[str, typer.Option("--cols", help="Column(s) to group by")],
) -> None:
    """Group by column(s) with counts."""
    _run_per_path(_resolve_all(path), lambda con, _stem: encode(_groupby(con, cols)))


@app.command()
def sql(
    path: PathArgument,
    *,
    query: Annotated[str, typer.Option("-q", "--query", help="SQL query (tables: t, t1, t2, ...)")],
) -> None:
    """Run a DuckDB SQL query against the file(s) (tables: t, t1, t2, ...)."""
    with duckdb.connect() as con:
        table_names = _register_tables(con, _resolve_all(path))
        typer.echo(encode(_sql(con, query, table_names)))


if __name__ == "__main__":
    app()
