"""Tests for the stormitem CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# --- Pure helpers ----------------------------------------------------------


def test_slug_simple(stormitem):
    assert stormitem._slug("feat", "peek", "support_julia") == "feat_peek_support_julia"


def test_slug_converts_spaces(stormitem):
    assert stormitem._slug("fix", "h2md", "handle empty body") == "fix_h2md_handle_empty_body"


def test_slug_strips_whitespace(stormitem):
    assert stormitem._slug("feat", "peek", "  julia support  ") == "feat_peek_julia_support"


def test_pr_title_converts_underscores(stormitem):
    assert stormitem._pr_title("feat", "peek", "support_julia") == "feat(peek): support julia"


def test_pr_title_keeps_existing_spaces(stormitem):
    assert stormitem._pr_title("fix", "h2md", "handle empty body") == "fix(h2md): handle empty body"


def test_branch_prefixed(stormitem):
    assert stormitem._branch("feat_peek_x") == "stormitem/feat_peek_x"


# --- Validation ------------------------------------------------------------


@pytest.mark.parametrize("kind", ["feat", "fix", "docs", "refactor", "perf", "chore", "revert", "ci"])
def test_validate_kind_accepts_conv_commits(stormitem, kind):
    stormitem._validate_kind(kind)


@pytest.mark.parametrize("kind", ["Feat", "FEAT", "feat ", "feat-x", "1feat", "", "feat!"])
def test_validate_kind_rejects_invalid(stormitem, kind):
    with pytest.raises(Exception):
        stormitem._validate_kind(kind)


def test_validate_feature_accepts(stormitem):
    stormitem._validate_feature("peek", ["peek", "h2md"])


def test_validate_feature_rejects(stormitem):
    with pytest.raises(Exception):
        stormitem._validate_feature("bogus", ["peek", "h2md"])


# --- Registry --------------------------------------------------------------


def test_resolve_repo_known(stormitem):
    owner, features = stormitem._resolve_repo("zyp-skills")
    assert owner == "zyplux"
    assert "stormitem" in features


def test_resolve_repo_unknown(stormitem):
    with pytest.raises(Exception):
        stormitem._resolve_repo("does-not-exist")


# --- Template matching -----------------------------------------------------


def test_match_template_substring_feat(stormitem):
    items = [
        {"name": "bug_report.md", "path": ".github/ISSUE_TEMPLATE/bug_report.md"},
        {"name": "feature_request.md", "path": ".github/ISSUE_TEMPLATE/feature_request.md"},
    ]
    chosen = stormitem._match_template(items, "feat")
    assert chosen is not None
    assert chosen["name"] == "feature_request.md"


def test_match_template_substring_fix(stormitem):
    items = [
        {"name": "bug_report.md", "path": "x"},
        {"name": "feature_request.md", "path": "y"},
    ]
    chosen = stormitem._match_template(items, "fix")
    assert chosen is not None
    assert chosen["name"] == "bug_report.md"


def test_match_template_prefers_yml_over_md(stormitem):
    items = [
        {"name": "bug_report.md", "path": "x"},
        {"name": "bug_report.yml", "path": "y"},
    ]
    chosen = stormitem._match_template(items, "fix")
    assert chosen is not None
    assert chosen["name"] == "bug_report.yml"


def test_match_template_no_hit_returns_none(stormitem):
    items = [{"name": "config.yml", "path": "x"}]
    assert stormitem._match_template(items, "feat") is None


def test_match_template_empty_returns_none(stormitem):
    assert stormitem._match_template([], "feat") is None


# --- Parsing ---------------------------------------------------------------


def test_parse_md_with_frontmatter(stormitem):
    raw = "---\nlabels: [bug]\nassignees: [alice]\n---\n\n## What\n\nA bug.\n"
    fm, body = stormitem._parse_md_template(raw)
    assert fm == {"labels": ["bug"], "assignees": ["alice"]}
    assert body == "## What\n\nA bug.\n"


def test_parse_md_without_frontmatter(stormitem):
    raw = "## Title\n\nBody only.\n"
    fm, body = stormitem._parse_md_template(raw)
    assert fm == {}
    assert body == raw


def test_parse_md_malformed_frontmatter_returns_empty(stormitem):
    raw = "---\nnot: ok: [\n---\n\nbody\n"
    fm, _ = stormitem._parse_md_template(raw)
    assert fm == {}


def test_parse_yml_form_extracts_labels_and_sections(stormitem):
    raw = (
        "name: Bug report\n"
        "description: Report a bug\n"
        "labels: [bug, triage]\n"
        "body:\n"
        "  - type: textarea\n"
        "    attributes:\n"
        "      label: What happened?\n"
        "      placeholder: Describe the bug\n"
        "  - type: textarea\n"
        "    attributes:\n"
        "      label: Expected behavior\n"
        "      description: What you expected to happen.\n"
    )
    fm, body = stormitem._parse_yml_form(raw)
    assert fm == {"labels": ["bug", "triage"]}
    assert "## What happened?" in body
    assert "Describe the bug" in body
    assert "## Expected behavior" in body


def test_parse_yml_form_no_body_falls_back_to_details(stormitem):
    raw = "name: x\nlabels: [a]\n"
    fm, body = stormitem._parse_yml_form(raw)
    assert fm == {"labels": ["a"]}
    assert "## Details" in body


# --- Issue rendering -------------------------------------------------------


def test_render_issue_includes_stormitem_block(stormitem):
    rendered = stormitem._render_issue(
        "feat(peek): julia",
        {"labels": ["enhancement"]},
        {
            "repo": "zyp-skills",
            "kind": "feat",
            "feature": "peek",
            "title": "julia",
            "slug": "feat_peek_julia",
            "template_used": "builtin:feat",
        },
        "## Summary\n\nAdd Julia.\n",
    )
    assert rendered.startswith("---\n")
    fm_text, _, body = rendered.partition("\n---\n")
    fm = yaml.safe_load(fm_text[len("---\n"):])
    assert fm["title"] == "feat(peek): julia"
    assert fm["labels"] == ["enhancement"]
    assert fm["stormitem"]["repo"] == "zyp-skills"
    assert fm["stormitem"]["slug"] == "feat_peek_julia"
    assert "Add Julia." in body


def test_render_issue_skips_absent_metadata(stormitem):
    rendered = stormitem._render_issue(
        "feat(peek): x",
        {},
        {"repo": "zyp-skills", "kind": "feat", "feature": "peek", "title": "x", "slug": "s", "template_used": "builtin:feat"},
        "body\n",
    )
    fm_text = rendered.split("\n---\n", 1)[0][len("---\n"):]
    fm = yaml.safe_load(fm_text)
    assert "labels" not in fm
    assert "assignees" not in fm


# --- Pull command ----------------------------------------------------------


def test_pull_writes_issue_md_with_frontmatter(invoke, builtin_only, decode, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    result = invoke("pull", "zyp-skills", "--kind", "feat", "--feature", "peek", "--title", "support julia")
    parsed = decode(result.output.strip())
    assert isinstance(parsed, dict)
    assert parsed["slug"] == "feat_peek_support_julia"
    assert parsed["template_used"] == "builtin:feat"
    issue_path = Path(parsed["issue_path"])
    assert issue_path.is_file()
    content = issue_path.read_text()
    assert content.startswith("---\n")
    fm_text = content.split("\n---\n", 1)[0][len("---\n"):]
    fm = yaml.safe_load(fm_text)
    assert fm["title"] == "feat(peek): support julia"
    assert fm["stormitem"]["slug"] == "feat_peek_support_julia"
    assert fm["stormitem"]["template_used"] == "builtin:feat"


def test_pull_dir_starts_with_prefix(invoke, builtin_only, decode, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    result = invoke("pull", "zyp-skills", "--kind", "fix", "--feature", "h2md", "--title", "empty body")
    parsed = decode(result.output.strip())
    assert Path(parsed["dir"]).name.startswith("stormitem-fix_h2md_empty_body-")
    assert parsed["template_used"] == "builtin:fix"


def test_pull_uses_default_template_for_unknown_kind(invoke, builtin_only, decode, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    result = invoke("pull", "zyp-skills", "--kind", "perf", "--feature", "peek", "--title", "speed up")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "builtin:_default"


def test_pull_unknown_repo_fails(invoke):
    result = invoke("pull", "bogus-repo", "--kind", "feat", "--feature", "x", "--title", "y", expect_error=True)
    assert result.exit_code != 0


def test_pull_unknown_feature_fails(invoke):
    result = invoke("pull", "zyp-skills", "--kind", "feat", "--feature", "nope", "--title", "y", expect_error=True)
    assert result.exit_code != 0


def test_pull_invalid_kind_fails(invoke):
    result = invoke("pull", "zyp-skills", "--kind", "FEAT", "--feature", "peek", "--title", "y", expect_error=True)
    assert result.exit_code != 0


# --- Post command ----------------------------------------------------------


def _make_workdir(tmp_path: Path, *, slug: str = "feat_peek_julia", repo: str = "zyp-skills") -> Path:
    work = tmp_path / "stormitem-work"
    work.mkdir(parents=True)
    fm = {
        "title": "feat(peek): julia",
        "labels": ["enhancement"],
        "stormitem": {
            "repo": repo,
            "kind": "feat",
            "feature": "peek",
            "title": "julia",
            "slug": slug,
            "template_used": "builtin:feat",
        },
    }
    body = "## Summary\n\nAdd Julia support.\n"
    fm_text = yaml.safe_dump(fm, sort_keys=False).rstrip()
    (work / "issue.md").write_text(f"---\n{fm_text}\n---\n\n{body}")
    (work / "plan.md").write_text("# Plan\n\nA detailed plan paragraph.\n\n## Section\n\nMore.\n")
    return work


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def make(self, name: str, *, returns):
        def fn(*args, **kwargs):
            self.calls.append((name, args + tuple(kwargs.values())))
            return returns

        return fn


def test_post_pr_mode_full_flow(invoke, stormitem, decode, monkeypatch, tmp_path):
    work = _make_workdir(tmp_path)
    rec = _Recorder()
    monkeypatch.setattr(stormitem, "_detect_push", lambda owner, repo: True)
    monkeypatch.setattr(
        stormitem,
        "_create_issue",
        rec.make("issue", returns="https://github.com/zyplux/zyp-skills/issues/42"),
    )
    monkeypatch.setattr(stormitem, "_default_branch", rec.make("default", returns="main"))
    monkeypatch.setattr(stormitem, "_ref_sha", rec.make("sha", returns="abc123"))
    monkeypatch.setattr(stormitem, "_create_branch", rec.make("branch", returns=None))
    monkeypatch.setattr(stormitem, "_put_file", rec.make("commit", returns=None))
    monkeypatch.setattr(
        stormitem,
        "_create_pr",
        rec.make("pr", returns="https://github.com/zyplux/zyp-skills/pull/43"),
    )
    monkeypatch.setattr(stormitem, "_edit_issue", rec.make("link", returns=None))

    result = invoke("post", "zyp-skills", str(work))
    parsed = decode(result.output.strip())
    assert parsed == {
        "number": 42,
        "url": "https://github.com/zyplux/zyp-skills/issues/42",
        "plan_url": "https://github.com/zyplux/zyp-skills/pull/43",
        "pr_number": 43,
        "mode": "pr",
        "template_used": "builtin:feat",
    }
    names = [c[0] for c in rec.calls]
    assert names == ["issue", "default", "sha", "branch", "commit", "pr", "link"]
    branch_call = rec.calls[3]
    assert "stormitem/feat_peek_julia" in branch_call[1]
    commit_call = rec.calls[4]
    assert "plan/feat_peek_julia/plan.md" in commit_call[1]


def test_post_pr_mode_cleans_non_tmp_dir(invoke, stormitem, monkeypatch, tmp_path):
    fake_tmp = tmp_path / "fake-tmp"
    fake_tmp.mkdir()
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_tmp))
    work = _make_workdir(tmp_path / "elsewhere")
    monkeypatch.setattr(stormitem, "_detect_push", lambda owner, repo: True)
    monkeypatch.setattr(stormitem, "_create_issue", lambda *a, **k: "https://github.com/zyplux/zyp-skills/issues/1")
    monkeypatch.setattr(stormitem, "_default_branch", lambda *a, **k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *a, **k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *a, **k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *a, **k: None)
    monkeypatch.setattr(stormitem, "_create_pr", lambda *a, **k: "https://github.com/zyplux/zyp-skills/pull/2")
    monkeypatch.setattr(stormitem, "_edit_issue", lambda *a, **k: None)

    invoke("post", "zyp-skills", str(work))
    assert not work.exists()


def test_post_pr_mode_keeps_tmp_dir(invoke, stormitem, monkeypatch, tmp_path):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    work = tmp_path / "stormitem-work"
    work.mkdir()
    fm = {
        "title": "feat(peek): julia",
        "stormitem": {
            "repo": "zyp-skills",
            "kind": "feat",
            "feature": "peek",
            "title": "julia",
            "slug": "feat_peek_julia",
            "template_used": "builtin:feat",
        },
    }
    fm_text = yaml.safe_dump(fm, sort_keys=False).rstrip()
    (work / "issue.md").write_text(f"---\n{fm_text}\n---\n\nbody\n")
    (work / "plan.md").write_text("plan\n")

    monkeypatch.setattr(stormitem, "_detect_push", lambda owner, repo: True)
    monkeypatch.setattr(stormitem, "_create_issue", lambda *a, **k: "https://github.com/zyplux/zyp-skills/issues/1")
    monkeypatch.setattr(stormitem, "_default_branch", lambda *a, **k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *a, **k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *a, **k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *a, **k: None)
    monkeypatch.setattr(stormitem, "_create_pr", lambda *a, **k: "https://github.com/zyplux/zyp-skills/pull/2")
    monkeypatch.setattr(stormitem, "_edit_issue", lambda *a, **k: None)

    invoke("post", "zyp-skills", str(work))
    assert work.exists()


def test_post_gist_mode_full_flow(invoke, stormitem, decode, monkeypatch, tmp_path):
    work = _make_workdir(tmp_path)
    rec = _Recorder()
    monkeypatch.setattr(stormitem, "_detect_push", lambda owner, repo: False)
    monkeypatch.setattr(
        stormitem,
        "_create_gist",
        rec.make("gist", returns="https://gist.github.com/realSergiy/abcdef"),
    )
    monkeypatch.setattr(
        stormitem,
        "_create_issue",
        rec.make("issue", returns="https://github.com/zyplux/zyp-skills/issues/77"),
    )

    result = invoke("post", "zyp-skills", str(work))
    parsed = decode(result.output.strip())
    assert parsed == {
        "number": 77,
        "url": "https://github.com/zyplux/zyp-skills/issues/77",
        "plan_url": "https://gist.github.com/realSergiy/abcdef",
        "pr_number": None,
        "mode": "gist",
        "template_used": "builtin:feat",
    }
    issue_call = next(c for c in rec.calls if c[0] == "issue")
    issue_body = issue_call[1][3]
    assert "https://gist.github.com/realSergiy/abcdef" in issue_body
    assert "Storming plan" in issue_body


def test_post_missing_issue_md_fails(invoke, tmp_path):
    work = tmp_path / "incomplete"
    work.mkdir()
    (work / "plan.md").write_text("plan\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_missing_plan_md_fails(invoke, tmp_path):
    work = tmp_path / "incomplete"
    work.mkdir()
    (work / "issue.md").write_text("---\nstormitem: {repo: zyp-skills}\n---\n\nbody\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_repo_mismatch_fails(invoke, tmp_path):
    work = _make_workdir(tmp_path, repo="other-repo")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_missing_stormitem_block_fails(invoke, tmp_path):
    work = tmp_path / "bare"
    work.mkdir()
    (work / "issue.md").write_text("---\ntitle: x\n---\n\nbody\n")
    (work / "plan.md").write_text("plan\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


# --- URL parsing -----------------------------------------------------------


def test_issue_number_parses(stormitem):
    assert stormitem._issue_number("https://github.com/owner/repo/issues/42") == 42


def test_pr_number_parses(stormitem):
    assert stormitem._pr_number("https://github.com/owner/repo/pull/9") == 9


def test_issue_number_missing_fails(stormitem):
    with pytest.raises(Exception):
        stormitem._issue_number("https://example.com/no-number")


# --- Summary line ----------------------------------------------------------


def test_summary_line_skips_headers_and_blanks(stormitem):
    plan = "# Title\n\n> blockquote\n\nThe first real prose line.\n\n- bullet\n"
    assert stormitem._summary_line(plan) == "The first real prose line."


def test_summary_line_fallback_when_only_headers(stormitem):
    plan = "# Title\n\n## Section\n"
    assert stormitem._summary_line(plan) == "Storming plan attached."


# --- Cleanup ---------------------------------------------------------------


def test_cleanup_skips_tmp(stormitem, monkeypatch, tmp_path):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    work = tmp_path / "child"
    work.mkdir()
    stormitem._cleanup(work)
    assert work.exists()


def test_cleanup_deletes_non_tmp(stormitem, monkeypatch, tmp_path):
    fake_tmp = tmp_path / "tmp"
    fake_tmp.mkdir()
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_tmp))
    work = tmp_path / "elsewhere"
    work.mkdir()
    stormitem._cleanup(work)
    assert not work.exists()


# --- Registry command ------------------------------------------------------


def test_registry_command_lists_repos(invoke, decode):
    result = invoke("registry")
    parsed = decode(result.output.strip())
    assert "repos" in parsed
    names = {row["repo"] for row in parsed["repos"]}
    assert "zyp-skills" in names
    totvibe = next(row for row in parsed["repos"] if row["repo"] == "zyp-skills")
    assert totvibe["owner"] == "zyplux"
    assert "stormitem" in totvibe["features"]


# --- Registry sync ---------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"


def test_registry_features_match_skills_dir(stormitem):
    """The registry's `zyp-skills` features must match `os.listdir(skills/)`."""
    on_disk = sorted(
        p.name for p in SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    )
    _, registered = stormitem._resolve_repo("zyp-skills")
    assert sorted(registered) == on_disk, (
        f"registry/zyp-skills features {sorted(registered)} drifted from "
        f"on-disk skills {on_disk}. Update skills/stormitem/registry.toml."
    )


def test_registry_sane_owner(stormitem):
    owner, _ = stormitem._resolve_repo("zyp-skills")
    assert owner == "zyplux"
