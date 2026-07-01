---
name: peek
description: >
  Inspect parquet data files — preview rows, schema, unique values, group-by counts, or SQL queries.
  Outputs TOON (token-optimized notation) for efficient LLM consumption.
  Use when exploring datasets, checking column types, or previewing rows.
  Prefer this over writing python -c one-liners with polars/pandas — saves tokens and avoids boilerplate.
metadata:
  kind: cli
  version: "1.0.0"
  user-invocable: "true"
  argument-hint: <preview|schema|describe|unique|groupby|sql> <path>... [options]
---

# peek — parquet inspection CLI

`peek` is a standalone CLI installed on PATH. Invoke it directly via Bash: `Bash(peek schema data/sales.parquet)`

Prefer `peek` over raw `python -c "import polars ..."` one-liners — it's faster to invoke, produces token-efficient TOON output, and avoids import boilerplate that wastes context.

Output is **TOON** (Token-Oriented Object Notation) — compact, structured, LLM-friendly.

## Modes

Each mode is its own subcommand.

| Mode | Subcommand | Purpose |
|------|------------|---------|
| Preview | `preview` | Show first N rows |
| Schema | `schema` | Columns, types, and row count — no data |
| Describe | `describe` | Per-column stats — unique/min/max/avg/quartiles |
| Unique | `unique --cols col1,col2` | Distinct values of column(s) |
| Group-by | `groupby --cols col1,col2` | Group-by counts |
| SQL | `sql -q "..."` | DuckDB SQL — full dialect including regex, CTEs, window functions (tables: `t`, `t1`, `t2`, ...) |

## Usage

```text
# Preview
peek preview <path>                          # 2 rows
peek preview <path> -n 10                    # 10 rows
peek preview <path> -a                       # all rows
peek preview <path> -t                       # include column types
peek preview <path> --cols round,points      # subset columns
peek preview <path> --cols round,points -n 5 -t  # combine options

# Schema — columns + types, no data
peek schema <path>

# Describe — per-column stats
peek describe <path>

# Unique values
peek unique <path> --cols round               # one column
peek unique <path> --cols round,surface        # multiple columns

# Group-by counts
peek groupby <path> --cols round               # one column
peek groupby <path> --cols tourney_level,round  # multiple columns

# SQL — single file (table aliased as t)
peek sql <path> -q "SELECT round, COUNT(*) as cnt FROM t GROUP BY round ORDER BY cnt DESC"
peek sql <path> -q "SELECT * FROM t WHERE points > 500 LIMIT 5"

# SQL — multi-file (tables aliased as t1, t2, ...; t = t1)
peek sql a.parquet b.parquet -q "SELECT * FROM t1 WHERE id NOT IN (SELECT id FROM t2)"
peek sql a.parquet b.parquet -q "SELECT COUNT(*) as matched FROM t1 JOIN t2 USING(player_code)"
peek sql a.parquet b.parquet -q "SELECT t1.name, t2.score FROM t1 JOIN t2 USING(id) LIMIT 20"

# Glob — multiple files
peek schema data/prep/*.parquet               # schema of each file
peek unique data/prep/*.parquet --cols round   # unique values from each file
```

## Options

| Subcommand | Flag | Effect | Default |
|------------|------|--------|---------|
| `preview` | `-n N` | Number of preview rows | 2 |
| `preview` | `-a` | Show all rows (equivalent to `-n 0`) | off |
| `preview` | `-t` | Append column types | off |
| `preview` | `--cols a,b` | Select columns for preview | all |
| `unique` | `--cols a,b` | Column(s) to show distinct values for | required |
| `groupby` | `--cols a,b` | Column(s) to group by | required |
| `sql` | `-q`/`--query "..."` | SQL query (tables: `t`/`t1`, `t2`, ...) | required |

`peek --version` shows the installed version.

## Output examples

Preview (`peek preview data/sales.parquet`):

```text
sales[2]{id,name,amount}:
  1,Alice,50
  2,Bob,120
rows: 1000
```

Schema (`peek schema data/sales.parquet`):

```text
sales:
  id: BIGINT
  name: VARCHAR
  amount: DOUBLE
rows: 1000
```

Describe (`peek describe data/sales.parquet`):

```text
sales{3 cols, 1000 rows}:
  id(BIGINT): min=1 max=1000 avg=500 q25=250 q50=500 q75=750 null=0%
  name(VARCHAR): unique=42 null=0%
  amount(DOUBLE): min=0.5 max=9999.0 avg=450.2 q25=120 q50=380 q75=720 null=0%
```

Unique (`peek unique data/sales.parquet --cols name`):

```text
name[3]: Alice,Bob,Carol
```

Group-by (`peek groupby data/sales.parquet --cols name`):

```text
group[3]{name,len}:
  Alice,350
  Bob,400
  Carol,250
```

SQL (`peek sql data/sales.parquet -q "SELECT name, SUM(amount) as total FROM t GROUP BY name"`):

```text
result[3]{name,total}:
  Alice,17500
  Bob,48000
  Carol,12500
```

## When to use which mode

- **Don't know what's in the file?** Start with `peek schema <path>` for schema
- **Data quality & distribution?** `peek describe <path>` for per-column stats
- **Need to see sample data?** `peek preview <path>` or `peek preview <path> -n 10`
- **What values does a column have?** `peek unique <path> --cols col`
- **How is data distributed?** `peek groupby <path> --cols col1,col2`
- **Complex filtering or aggregation?** `peek sql <path> -q "SELECT ..."`
- **Cross-file analysis?** `peek sql a.parquet b.parquet -q "SELECT ... FROM t1 JOIN t2 ..."`
- **Comparing multiple files?** `peek schema data/*.parquet`
