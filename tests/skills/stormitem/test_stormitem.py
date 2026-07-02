"""Tests for the stormitem CLI.

Every test drives the CLI through the `invoke` fixture (a thin wrapper over
`typer.testing.CliRunner`) and asserts on exit code, TOON output, or on-disk
effects — see tests/CLAUDE.md. Private helpers (`_slug`, `_match_template`,
`_cleanup`, ...) are only ever used as monkeypatch targets to stub the `gh`
subprocess boundary, never as the thing under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from typer.testing import Result

# --- pull: slug / PR title derivation ---------------------------------------


class _SlugCase(NamedTuple):
    kind: str
    feature: str
    title: str
    expected_slug: str
    expected_pr_title: str


SLUG_CASES = [
    _SlugCase("feat", "peek", "support_julia", "feat_peek_support_julia", "feat(peek): support julia"),
    _SlugCase("fix", "h2md", "handle empty body", "fix_h2md_handle_empty_body", "fix(h2md): handle empty body"),
    _SlugCase("feat", "peek", "  julia support  ", "feat_peek_julia_support", "feat(peek): julia support"),
]


@pytest.mark.parametrize("case", SLUG_CASES, ids=lambda c: c.expected_slug)
def test_pull_derives_slug_and_pr_title(
    invoke: Callable[..., Result],
    builtin_only: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
    case: _SlugCase,
) -> None:
    del builtin_only, tmp_workdir
    result = invoke("pull", "zyp-skills", "--kind", case.kind, "--feature", case.feature, "--title", case.title)
    parsed = decode(result.output.strip())
    assert parsed["slug"] == case.expected_slug
    issue_path = Path(parsed["issue_path"])
    fm_text = issue_path.read_text(encoding="utf-8").split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert fm["title"] == case.expected_pr_title
    assert fm["stormitem"]["slug"] == case.expected_slug


# --- pull: kind validation ---------------------------------------------------


@pytest.mark.parametrize("kind", ["feat", "fix", "docs", "refactor", "perf", "chore", "revert", "ci"])
def test_pull_accepts_conv_commits_kind(
    invoke: Callable[..., Result],
    builtin_only: ModuleType,
    tmp_workdir: Path,
    kind: str,
) -> None:
    del builtin_only, tmp_workdir
    result = invoke("pull", "zyp-skills", "--kind", kind, "--feature", "peek", "--title", "x")
    assert result.exit_code == 0


@pytest.mark.parametrize("kind", ["Feat", "FEAT", "feat ", "feat-x", "1feat", "", "feat!"])
def test_pull_rejects_invalid_kind(invoke: Callable[..., Result], kind: str) -> None:
    result = invoke("pull", "zyp-skills", "--kind", kind, "--feature", "peek", "--title", "y", expect_error=True)
    assert result.exit_code != 0


def test_pull_unknown_feature_fails(invoke: Callable[..., Result]) -> None:
    result = invoke(
        "pull",
        "zyp-skills",
        "--kind",
        "feat",
        "--feature",
        "nope",
        "--title",
        "y",
        expect_error=True,
    )
    assert result.exit_code != 0


def test_pull_unknown_repo_fails(invoke: Callable[..., Result]) -> None:
    result = invoke(
        "pull",
        "bogus-repo",
        "--kind",
        "feat",
        "--feature",
        "x",
        "--title",
        "y",
        expect_error=True,
    )
    assert result.exit_code != 0


# --- registry ----------------------------------------------------------------


def test_registry_command_lists_repos(invoke: Callable[..., Result], decode: Callable[[str], dict[str, Any]]) -> None:
    result = invoke("registry")
    parsed = decode(result.output.strip())
    assert "repos" in parsed
    names = {row["repo"] for row in parsed["repos"]}
    assert "zyp-skills" in names
    zyp_skills = next(row for row in parsed["repos"] if row["repo"] == "zyp-skills")
    assert zyp_skills["owner"] == "zyplux"
    assert "stormitem" in zyp_skills["features"]


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"


def test_registry_features_match_skills_dir(
    invoke: Callable[..., Result], decode: Callable[[str], dict[str, Any]]
) -> None:
    """The registry's `zyp-skills` features must match `os.listdir(skills/)`."""
    on_disk = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
    result = invoke("registry")
    parsed = decode(result.output.strip())
    zyp_skills = next(row for row in parsed["repos"] if row["repo"] == "zyp-skills")
    assert sorted(zyp_skills["features"]) == on_disk, (
        f"registry/zyp-skills features {sorted(zyp_skills['features'])} drifted from "
        f"on-disk skills {on_disk}. Update skills/stormitem/registry.toml."
    )


# --- pull: template matching (remote listing over `gh api`) -----------------

BUG_REPORT_MD = ".github/ISSUE_TEMPLATE/bug_report.md"
FEATURE_REQUEST_MD = ".github/ISSUE_TEMPLATE/feature_request.md"
BUG_REPORT_YML = ".github/ISSUE_TEMPLATE/bug_report.yml"
CONFIG_YML = ".github/ISSUE_TEMPLATE/config.yml"

PLAIN_BODY = "## Body\n\nSome text.\n"


def _pull_zyp_skills(invoke: Callable[..., Result], tmp_workdir: Path, *, kind: str = "feat") -> Result:
    del tmp_workdir
    return invoke("pull", "zyp-skills", "--kind", kind, "--feature", "peek", "--title", "x")


def test_pull_remote_template_matches_feat(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    listing = [
        {"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"},
        {"name": "feature_request.md", "path": FEATURE_REQUEST_MD, "type": "file"},
    ]
    remote_templates(listing, {BUG_REPORT_MD: PLAIN_BODY, FEATURE_REQUEST_MD: PLAIN_BODY})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="feat")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "remote:feature_request.md"


def test_pull_remote_template_matches_fix(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    listing = [
        {"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"},
        {"name": "feature_request.md", "path": FEATURE_REQUEST_MD, "type": "file"},
    ]
    remote_templates(listing, {BUG_REPORT_MD: PLAIN_BODY, FEATURE_REQUEST_MD: PLAIN_BODY})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "remote:bug_report.md"


def test_pull_remote_template_prefers_yml_over_md(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    listing = [
        {"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"},
        {"name": "bug_report.yml", "path": BUG_REPORT_YML, "type": "file"},
    ]
    remote_templates(listing, {BUG_REPORT_MD: PLAIN_BODY, BUG_REPORT_YML: "name: x\nlabels: [a]\n"})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "remote:bug_report.yml"


def test_pull_remote_template_no_hit_falls_back_to_builtin(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    listing = [{"name": "config.yml", "path": CONFIG_YML, "type": "file"}]
    remote_templates(listing, {CONFIG_YML: PLAIN_BODY})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="feat")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "builtin:feat"


def test_pull_remote_listing_empty_falls_back_to_builtin(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    remote_templates([], {})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="feat")
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "builtin:feat"


# --- pull: template parsing (.md frontmatter, .yml issue forms) -------------


def test_pull_remote_md_frontmatter_becomes_issue_labels(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    raw = "---\nlabels: [bug]\nassignees: [alice]\n---\n\n## What\n\nA bug.\n"
    listing = [{"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"}]
    remote_templates(listing, {BUG_REPORT_MD: raw})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    fm_text = content.split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert fm["labels"] == ["bug"]
    assert fm["assignees"] == ["alice"]
    assert "A bug." in content


def test_pull_remote_md_without_frontmatter_keeps_body_verbatim(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    raw = "## Title\n\nBody only.\n"
    listing = [{"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"}]
    remote_templates(listing, {BUG_REPORT_MD: raw})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    fm_text = content.split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert "labels" not in fm
    assert "assignees" not in fm
    assert raw in content


def test_pull_remote_md_malformed_frontmatter_yields_no_labels(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    raw = "---\nnot: ok: [\n---\n\nbody\n"
    listing = [{"name": "bug_report.md", "path": BUG_REPORT_MD, "type": "file"}]
    remote_templates(listing, {BUG_REPORT_MD: raw})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    fm_text = content.split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert "labels" not in fm
    assert "assignees" not in fm


def test_pull_remote_yml_form_extracts_labels_and_sections(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
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
    listing = [{"name": "bug_report.yml", "path": BUG_REPORT_YML, "type": "file"}]
    remote_templates(listing, {BUG_REPORT_YML: raw})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    fm_text = content.split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert fm["labels"] == ["bug", "triage"]
    assert "## What happened?" in content
    assert "Describe the bug" in content
    assert "## Expected behavior" in content


def test_pull_remote_yml_form_no_body_falls_back_to_details(
    invoke: Callable[..., Result],
    remote_templates: Callable[..., None],
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    raw = "name: x\nlabels: [a]\n"
    listing = [{"name": "bug_report.yml", "path": BUG_REPORT_YML, "type": "file"}]
    remote_templates(listing, {BUG_REPORT_YML: raw})
    result = _pull_zyp_skills(invoke, tmp_workdir, kind="fix")
    parsed = decode(result.output.strip())
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    assert "## Details" in content


# --- pull: issue rendering (builtin templates, incl. absent metadata) ------


def test_pull_dir_starts_with_prefix(
    invoke: Callable[..., Result],
    builtin_only: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    del builtin_only, tmp_workdir
    result = invoke(
        "pull",
        "zyp-skills",
        "--kind",
        "fix",
        "--feature",
        "h2md",
        "--title",
        "empty body",
    )
    parsed = decode(result.output.strip())
    assert Path(parsed["dir"]).name.startswith("stormitem-fix_h2md_empty_body-")
    assert parsed["template_used"] == "builtin:fix"


def test_pull_uses_default_template_for_unknown_kind(
    invoke: Callable[..., Result],
    builtin_only: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    del builtin_only, tmp_workdir
    result = invoke(
        "pull",
        "zyp-skills",
        "--kind",
        "perf",
        "--feature",
        "peek",
        "--title",
        "speed up",
    )
    parsed = decode(result.output.strip())
    assert parsed["template_used"] == "builtin:_default"
    content = Path(parsed["issue_path"]).read_text(encoding="utf-8")
    fm_text = content.split("\n---\n", 1)[0].removeprefix("---\n")
    fm = yaml.safe_load(fm_text)
    assert "labels" not in fm
    assert "assignees" not in fm
    assert fm["stormitem"]["template_used"] == "builtin:_default"


def test_pull_writes_issue_md_with_frontmatter(
    invoke: Callable[..., Result],
    builtin_only: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    tmp_workdir: Path,
) -> None:
    del builtin_only, tmp_workdir
    result = invoke(
        "pull",
        "zyp-skills",
        "--kind",
        "feat",
        "--feature",
        "peek",
        "--title",
        "support julia",
    )
    parsed = decode(result.output.strip())
    assert isinstance(parsed, dict)
    assert parsed["slug"] == "feat_peek_support_julia"
    assert parsed["template_used"] == "builtin:feat"
    issue_path = Path(parsed["issue_path"])
    assert issue_path.is_file()
    content = issue_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    fm_text = content.split("\n---\n", 1)[0][len("---\n") :]
    fm = yaml.safe_load(fm_text)
    assert fm["title"] == "feat(peek): support julia"
    assert fm["labels"] == ["enhancement"]
    assert fm["stormitem"]["repo"] == "zyp-skills"
    assert fm["stormitem"]["slug"] == "feat_peek_support_julia"
    assert fm["stormitem"]["template_used"] == "builtin:feat"


# --- Post command ------------------------------------------------------------


def _make_workdir(
    tmp_path: Path,
    *,
    slug: str = "feat_peek_julia",
    repo: str = "zyp-skills",
    plan_text: str = "# Plan\n\nA detailed plan paragraph.\n\n## Section\n\nMore.\n",
) -> Path:
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
    (work / "plan.md").write_text(plan_text)
    return work


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def make(self, name: str, *, returns: object) -> Callable[..., object]:
        def fn(*args: object, **kwargs: object) -> object:
            self.calls.append((name, args + tuple(kwargs.values())))
            return returns

        return fn


def test_post_pr_mode_full_flow(
    invoke: Callable[..., Result],
    stormitem: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    work = _make_workdir(tmp_path)
    rec = _Recorder()
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
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
    pr_call = rec.calls[5]
    assert any("A detailed plan paragraph." in str(arg) for arg in pr_call[1])


def test_post_pr_body_falls_back_when_plan_has_only_headers(
    invoke: Callable[..., Result], stormitem: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = _make_workdir(tmp_path, plan_text="# Title\n\n## Section\n")
    rec = _Recorder()
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
    monkeypatch.setattr(stormitem, "_create_issue", lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/issues/1")
    monkeypatch.setattr(stormitem, "_default_branch", lambda *_a, **_k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *_a, **_k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_create_pr", rec.make("pr", returns="https://github.com/zyplux/zyp-skills/pull/2"))
    monkeypatch.setattr(stormitem, "_edit_issue", lambda *_a, **_k: None)

    invoke("post", "zyp-skills", str(work))
    pr_call = next(c for c in rec.calls if c[0] == "pr")
    assert any("Storming plan attached." in str(arg) for arg in pr_call[1])


def test_post_pr_mode_cleans_non_tmp_dir(
    invoke: Callable[..., Result], stormitem: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_tmp = tmp_path / "fake-tmp"
    fake_tmp.mkdir()
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_tmp))
    work = _make_workdir(tmp_path / "elsewhere")
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
    monkeypatch.setattr(
        stormitem,
        "_create_issue",
        lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/issues/1",
    )
    monkeypatch.setattr(stormitem, "_default_branch", lambda *_a, **_k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *_a, **_k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *_a, **_k: None)
    monkeypatch.setattr(
        stormitem,
        "_create_pr",
        lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/pull/2",
    )
    monkeypatch.setattr(stormitem, "_edit_issue", lambda *_a, **_k: None)

    invoke("post", "zyp-skills", str(work))
    assert not work.exists()


def test_post_pr_mode_keeps_tmp_dir(
    invoke: Callable[..., Result], stormitem: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_workdir: Path
) -> None:
    work = _make_workdir(tmp_workdir)

    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
    monkeypatch.setattr(
        stormitem,
        "_create_issue",
        lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/issues/1",
    )
    monkeypatch.setattr(stormitem, "_default_branch", lambda *_a, **_k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *_a, **_k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *_a, **_k: None)
    monkeypatch.setattr(
        stormitem,
        "_create_pr",
        lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/pull/2",
    )
    monkeypatch.setattr(stormitem, "_edit_issue", lambda *_a, **_k: None)

    invoke("post", "zyp-skills", str(work))
    assert work.exists()


def test_post_gist_mode_full_flow(
    invoke: Callable[..., Result],
    stormitem: ModuleType,
    decode: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    work = _make_workdir(tmp_path)
    rec = _Recorder()
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: False)
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
    issue_body = cast("Any", issue_call[1][1]).body
    assert "https://gist.github.com/realSergiy/abcdef" in issue_body
    assert "Storming plan" in issue_body


def test_post_missing_issue_md_fails(invoke: Callable[..., Result], tmp_path: Path) -> None:
    work = tmp_path / "incomplete"
    work.mkdir()
    (work / "plan.md").write_text("plan\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_missing_plan_md_fails(invoke: Callable[..., Result], tmp_path: Path) -> None:
    work = tmp_path / "incomplete"
    work.mkdir()
    (work / "issue.md").write_text("---\nstormitem: {repo: zyp-skills}\n---\n\nbody\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_repo_mismatch_fails(invoke: Callable[..., Result], tmp_path: Path) -> None:
    work = _make_workdir(tmp_path, repo="other-repo")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_missing_stormitem_block_fails(invoke: Callable[..., Result], tmp_path: Path) -> None:
    work = tmp_path / "bare"
    work.mkdir()
    (work / "issue.md").write_text("---\ntitle: x\n---\n\nbody\n")
    (work / "plan.md").write_text("plan\n")
    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


# --- Post: malformed GitHub URLs from a (mocked) `gh` response --------------


def test_post_issue_url_without_number_fails(
    invoke: Callable[..., Result], stormitem: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = _make_workdir(tmp_path)
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
    monkeypatch.setattr(stormitem, "_create_issue", lambda *_a, **_k: "https://example.com/no-number")

    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0


def test_post_pr_url_without_number_fails(
    invoke: Callable[..., Result], stormitem: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = _make_workdir(tmp_path)
    monkeypatch.setattr(stormitem, "_detect_push", lambda _target: True)
    monkeypatch.setattr(stormitem, "_create_issue", lambda *_a, **_k: "https://github.com/zyplux/zyp-skills/issues/1")
    monkeypatch.setattr(stormitem, "_default_branch", lambda *_a, **_k: "main")
    monkeypatch.setattr(stormitem, "_ref_sha", lambda *_a, **_k: "sha")
    monkeypatch.setattr(stormitem, "_create_branch", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_put_file", lambda *_a, **_k: None)
    monkeypatch.setattr(stormitem, "_create_pr", lambda *_a, **_k: "https://example.com/no-number")

    result = invoke("post", "zyp-skills", str(work), expect_error=True)
    assert result.exit_code != 0
