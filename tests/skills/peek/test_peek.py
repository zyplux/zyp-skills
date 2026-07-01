"""Tests for the peek CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent


# --- Preview (default mode) ---


def test_default_output(invoke):
    result = invoke()
    assert result.output == (
        "tourney_points[2]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "  Grand Slam,G2000,SF,4,800\n"
        "rows: 94\n"
    )


def test_n_1(invoke):
    result = invoke("-n", "1")
    assert result.output == (
        "tourney_points[1]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "rows: 94\n"
    )


def test_n_5(invoke):
    result = invoke("-n", "5")
    assert result.output == (
        "tourney_points[5]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "  Grand Slam,G2000,SF,4,800\n"
        "  Grand Slam,G2000,QF,8,400\n"
        "  Grand Slam,G2000,R16,16,200\n"
        "  Grand Slam,G2000,R32,32,100\n"
        "rows: 94\n"
    )


@pytest.mark.parametrize("n", [3, 50])
def test_preview_respects_n(invoke, decode, n):
    result = invoke("-n", str(n))
    assert len(decode(result.output.strip())["tourney_points"]) == min(n, 94)


@pytest.mark.parametrize("n", [94, 200], ids=["exact", "overshoot"])
def test_n_gte_total_hides_rows(invoke, n):
    result = invoke("-n", str(n))
    assert "rows" not in result.output


def test_types_flag(invoke):
    result = invoke("-t")
    assert result.output == (
        "tourney_points[2]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "  Grand Slam,G2000,SF,4,800\n"
        "types[5]: VARCHAR,VARCHAR,VARCHAR,INTEGER,INTEGER\n"
        "rows: 94\n"
    )


def test_all_rows_no_row_count(invoke, decode):
    result = invoke("-a")
    parsed = decode(result.output.strip())
    assert len(parsed["tourney_points"]) == 94
    assert "rows" not in parsed


# --- Column selection (--cols) ---


def test_cols_select(invoke):
    result = invoke("--cols", "round,points")
    assert result.output == (
        "tourney_points[2]{round,points}:\n  F,2000\n  SF,800\nrows: 94\n"
    )


def test_cols_with_n(invoke):
    result = invoke("--cols", "round,points", "-n", "5")
    assert result.output == (
        "tourney_points[5]{round,points}:\n"
        "  F,2000\n"
        "  SF,800\n"
        "  QF,400\n"
        "  R16,200\n"
        "  R32,100\n"
        "rows: 94\n"
    )


def test_cols_with_types(invoke):
    result = invoke("--cols", "round,points", "-t")
    assert result.output == (
        "tourney_points[2]{round,points}:\n"
        "  F,2000\n"
        "  SF,800\n"
        "types[2]: VARCHAR,INTEGER\n"
        "rows: 94\n"
    )


def test_cols_with_all_rows(invoke, decode):
    result = invoke("--cols", "round", "-a")
    parsed = decode(result.output.strip())
    assert len(parsed["tourney_points"]) == 94
    assert "rows" not in parsed


# --- Describe mode (-d) ---


def test_describe_mode(invoke):
    result = invoke("-d")
    assert result.output == (
        "tourney_points{5 cols, 94 rows}:\n"
        "  tourney_category(VARCHAR): unique=17 null=0%\n"
        "  tourney_level(VARCHAR): unique=13 null=0%\n"
        "  round(VARCHAR): unique=12 null=0%\n"
        "  round_of(INTEGER): min=0 max=256 avg=31 q25=4 q50=16 q75=40 null=0%\n"
        "  points(INTEGER): min=1 max=2000 avg=126.6 q25=8 q50=25 q75=100 null=0%\n"
    )


def test_describe_numeric_has_quartiles(invoke):
    result = invoke("-d")
    for key in ("q25=", "q50=", "q75="):
        assert key in result.output


def test_describe_glob_multiple(runner, peek):
    pattern = str(FIXTURE_DIR / "*.parquet")
    result = runner.invoke(peek.app, ["-d", pattern])
    assert result.exit_code == 0
    blocks = result.output.strip().split("\n\n")
    assert len(blocks) == 2
    assert blocks[0].startswith("players{3 cols, 3 rows}:")
    assert blocks[1].startswith("tourney_points{5 cols, 94 rows}:")


# --- Schema mode (-c) ---


def test_schema_mode(invoke):
    result = invoke("-c")
    assert result.output == (
        "tourney_points:\n"
        "  tourney_category: VARCHAR\n"
        "  tourney_level: VARCHAR\n"
        "  round: VARCHAR\n"
        "  round_of: INTEGER\n"
        "  points: INTEGER\n"
        "rows: 94\n"
    )


# --- Unique mode (-u) ---


def test_unique_single_column(invoke):
    result = invoke("-u", "round")
    assert result.output == "round[11]: F,Q1,Q2,Q3,QF,R128,R16,R32,R64,RR,SF\n"


def test_unique_multiple_columns(invoke):
    result = invoke("-u", "round,tourney_category")
    assert result.output == (
        "round[11]: F,Q1,Q2,Q3,QF,R128,R16,R32,R64,RR,SF\n"
        "tourney_category[15]: ATP 1000 56D,ATP 1000 96D,ATP 250 32D,"
        "ATP 250 48D,ATP 500 32D,ATP 500 48D,ATP Finals,"
        "Challenger 100,Challenger 125,Challenger 175,"
        "Challenger 50,Challenger 75,Grand Slam,ITF M15,ITF M25\n"
    )


# --- Group-by mode (-g) ---


def test_groupby_single_column(invoke):
    result = invoke("-g", "round")
    assert result.output == (
        "group[11]{round,len}:\n"
        "  F,15\n"
        "  Q1,12\n"
        "  Q2,12\n"
        "  Q3,1\n"
        "  QF,14\n"
        "  R128,2\n"
        "  R16,14\n"
        "  R32,5\n"
        "  R64,3\n"
        "  RR,1\n"
        "  SF,15\n"
    )


def test_groupby_multiple_columns(invoke):
    result = invoke("-g", "tourney_category,round")
    assert result.output.startswith("group[94]{tourney_category,round,len}:\n")
    assert "  Grand Slam,F,1\n" in result.output


# --- SQL mode (-q) ---


def test_sql_groupby(invoke):
    result = invoke(
        "-q",
        "SELECT round, COUNT(*) as cnt FROM t GROUP BY round ORDER BY cnt DESC, round",
    )
    assert result.output == (
        "result[11]{round,cnt}:\n"
        "  F,15\n"
        "  SF,15\n"
        "  QF,14\n"
        "  R16,14\n"
        "  Q1,12\n"
        "  Q2,12\n"
        "  R32,5\n"
        "  R64,3\n"
        "  R128,2\n"
        "  Q3,1\n"
        "  RR,1\n"
    )


def test_sql_where(invoke):
    result = invoke("-q", "SELECT * FROM t WHERE tourney_category = 'Grand Slam'")
    assert result.output == (
        "result[10]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "  Grand Slam,G2000,SF,4,800\n"
        "  Grand Slam,G2000,QF,8,400\n"
        "  Grand Slam,G2000,R16,16,200\n"
        "  Grand Slam,G2000,R32,32,100\n"
        "  Grand Slam,G2000,R64,64,50\n"
        "  Grand Slam,G2000,R128,128,10\n"
        "  Grand Slam,G2000,Q3,160,30\n"
        "  Grand Slam,G2000,Q2,192,16\n"
        "  Grand Slam,G2000,Q1,256,8\n"
    )


def test_sql_limit(invoke):
    result = invoke("-q", "SELECT * FROM t LIMIT 3")
    assert result.output == (
        "result[3]{tourney_category,tourney_level,round,round_of,points}:\n"
        "  Grand Slam,G2000,F,2,2000\n"
        "  Grand Slam,G2000,SF,4,800\n"
        "  Grand Slam,G2000,QF,8,400\n"
    )


# --- Multi-file SQL mode ---


def test_sql_multi_file_t1_t2(runner, peek):
    players = str(FIXTURE_DIR / "players.parquet")
    points = str(FIXTURE_DIR / "tourney_points.parquet")
    result = runner.invoke(
        peek.app,
        [
            "-q",
            "SELECT t1.player, t1.wins FROM t1 ORDER BY t1.wins DESC",
            players,
            points,
        ],
    )
    assert result.exit_code == 0
    assert result.output == (
        "result[3]{player,wins}:\n  Federer,103\n  Djokovic,98\n  Nadal,92\n"
    )


def test_sql_multi_file_cross_join(runner, peek):
    players = str(FIXTURE_DIR / "players.parquet")
    points = str(FIXTURE_DIR / "tourney_points.parquet")
    result = runner.invoke(
        peek.app,
        [
            "-q",
            "SELECT COUNT(*) as cnt FROM t1 CROSS JOIN t2",
            players,
            points,
        ],
    )
    assert result.exit_code == 0
    assert "cnt" in result.output
    assert "282" in result.output


def test_sql_single_file_t1_alias(invoke):
    result = invoke("-q", "SELECT COUNT(*) as cnt FROM t1")
    assert result.exit_code == 0
    assert "94" in result.output


# --- Glob support ---


def test_glob_schema_multiple(runner, peek):
    pattern = str(FIXTURE_DIR / "*.parquet")
    result = runner.invoke(peek.app, ["-c", pattern])
    assert result.output == (
        "players:\n"
        "  player: VARCHAR\n"
        "  wins: BIGINT\n"
        "  surface: VARCHAR\n"
        "rows: 3\n"
        "\n"
        "tourney_points:\n"
        "  tourney_category: VARCHAR\n"
        "  tourney_level: VARCHAR\n"
        "  round: VARCHAR\n"
        "  round_of: INTEGER\n"
        "  points: INTEGER\n"
        "rows: 94\n"
    )


def test_glob_preview_multiple(runner, peek):
    pattern = str(FIXTURE_DIR / "*.parquet")
    result = runner.invoke(peek.app, [pattern])
    assert result.exit_code == 0
    blocks = result.output.strip().split("\n\n")
    assert len(blocks) == 2
    assert blocks[0].startswith("players[2]")
    assert blocks[1].startswith("tourney_points[2]")


def test_glob_no_match(runner, peek):
    result = runner.invoke(peek.app, ["/nonexistent/*.parquet"])
    assert result.exit_code != 0


# --- Error handling ---


def test_no_path_exits_with_error(runner, peek):
    result = runner.invoke(peek.app, [])
    assert result.exit_code != 0


def test_nonexistent_file_exits_with_error(invoke):
    result = invoke(
        "--", "/nonexistent/file.parquet", use_fixture=False, expect_error=True
    )
    assert result.exit_code != 0


@pytest.mark.parametrize(
    "args",
    [
        ("-c", "-u", "round"),
        ("-c", "-g", "round"),
        ("-c", "-q", "SELECT * FROM t"),
        ("-d", "-c"),
        ("-d", "-u", "round"),
        ("-d", "-g", "round"),
        ("-d", "-q", "SELECT * FROM t"),
        ("-u", "round", "-g", "round"),
    ],
    ids=["c+u", "c+g", "c+q", "d+c", "d+u", "d+g", "d+q", "u+g"],
)
def test_mode_conflict(invoke, args):
    result = invoke(*args, expect_error=True)
    assert result.exit_code != 0


def test_sql_error_bad_column(invoke):
    result = invoke("-q", "SELECT nonexistent FROM t", expect_error=True)
    assert result.exit_code != 0


def test_sql_error_bad_table(runner, peek):
    points = str(FIXTURE_DIR / "tourney_points.parquet")
    result = runner.invoke(peek.app, ["-q", "SELECT * FROM t99", points])
    assert result.exit_code != 0
    assert "Available tables:" in result.output
