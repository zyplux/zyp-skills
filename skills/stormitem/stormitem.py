#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["typer>=0.15", "toon-format>=0.9.0b1", "pyyaml>=6.0"]
# ///
"""stormitem — turn a rough thought into a tracked issue + draft PR + plan artifact."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from toon_format import encode

__version__ = "0.1.0"

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = SCRIPT_DIR / "registry.toml"
TEMPLATES_DIR = SCRIPT_DIR / "templates"
TMP_PREFIX = "stormitem-"

KIND_RE = re.compile(r"^[a-z][a-z0-9]*$")
ISSUE_URL_RE = re.compile(r"/issues/(\d+)\b")
PR_URL_RE = re.compile(r"/pull/(\d+)\b")

KIND_HINTS: dict[str, tuple[str, ...]] = {
    "feat": ("feat", "feature", "enhancement", "request"),
    "fix": ("bug", "fix"),
    "docs": ("doc",),
    "refactor": ("refactor",),
    "perf": ("perf",),
    "chore": ("chore",),
    "revert": ("revert",),
    "test": ("test",),
    "build": ("build",),
    "ci": ("ci",),
    "style": ("style",),
}

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        print(f"stormitem {__version__}")
        raise typer.Exit


@app.callback()
def _root(
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
    """stormitem — issue + draft PR + plan handoff for personal repos."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _load_registry() -> dict[str, Any]:
    return tomllib.loads(REGISTRY_PATH.read_text())


def _resolve_repo(short: str) -> tuple[str, list[str]]:
    reg = _load_registry()
    repos = reg.get("repos", {})
    if short not in repos:
        known = ", ".join(sorted(repos)) or "<empty>"
        raise typer.BadParameter(f"unknown repo: {short!r}. Known: {known}")
    info = repos[short]
    owner = info.get("owner")
    if not isinstance(owner, str) or not owner:
        raise typer.BadParameter(f"registry entry for {short!r} is missing `owner`")
    features = info.get("features") or []
    if not isinstance(features, list):
        raise typer.BadParameter(f"registry entry for {short!r}: `features` must be a list")
    return owner, [str(f) for f in features]


# ---------------------------------------------------------------------------
# Naming derivations (slug, branch, PR title)
# ---------------------------------------------------------------------------


def _slug(kind: str, feature: str, title: str) -> str:
    return f"{kind}_{feature}_{title.strip().replace(' ', '_')}"


def _pr_title(kind: str, feature: str, title: str) -> str:
    return f"{kind}({feature}): {title.strip().replace('_', ' ')}"


def _branch(slug: str) -> str:
    return f"stormitem/{slug}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_kind(kind: str) -> None:
    if not KIND_RE.match(kind):
        raise typer.BadParameter(
            f"kind must match Conventional Commits (lowercase ASCII identifier): got {kind!r}"
        )


def _validate_feature(feature: str, allowed: list[str]) -> None:
    if feature not in allowed:
        raise typer.BadParameter(
            f"feature {feature!r} is not registered. Known: {', '.join(allowed) or '<none>'}"
        )


# ---------------------------------------------------------------------------
# gh shell-out
# ---------------------------------------------------------------------------


def _gh(*args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=check,
    )


def _gh_json(*args: str) -> Any:
    res = _gh(*args)
    out = res.stdout.strip()
    if not out:
        return None
    return json.loads(out)


# ---------------------------------------------------------------------------
# Template fetch + parse
# ---------------------------------------------------------------------------


def _fetch_template(owner: str, repo: str, kind: str) -> tuple[str, str]:
    listing: list[dict[str, Any]] = []
    try:
        payload = _gh_json("api", f"repos/{owner}/{repo}/contents/.github/ISSUE_TEMPLATE")
    except subprocess.CalledProcessError:
        payload = None
    if isinstance(payload, list):
        listing = [item for item in payload if isinstance(item, dict) and item.get("type") == "file"]
    chosen = _match_template(listing, kind)
    if chosen is not None:
        body = _fetch_file(owner, repo, str(chosen["path"]))
        return f"remote:{chosen['name']}", body
    return _builtin_template(kind)


def _match_template(items: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    if not items:
        return None
    hints = KIND_HINTS.get(kind, (kind,))

    def score(item: dict[str, Any]) -> tuple[int, int]:
        name = str(item.get("name", "")).lower()
        ext_priority = 0 if name.endswith((".yml", ".yaml")) else 1
        for i, h in enumerate(hints):
            if h in name:
                return (i, ext_priority)
        return (len(hints), ext_priority)

    items_sorted = sorted(items, key=score)
    best = items_sorted[0]
    name = str(best.get("name", "")).lower()
    if any(h in name for h in hints):
        return best
    return None


def _fetch_file(owner: str, repo: str, path: str) -> str:
    payload = _gh_json("api", f"repos/{owner}/{repo}/contents/{path}")
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"unexpected response fetching {path!r}")
    if payload.get("encoding") == "base64":
        return base64.b64decode(payload["content"]).decode()
    return str(payload.get("content", ""))


def _builtin_template(kind: str) -> tuple[str, str]:
    candidate = TEMPLATES_DIR / f"{kind}.md"
    if candidate.exists():
        return f"builtin:{kind}", candidate.read_text()
    return "builtin:_default", (TEMPLATES_DIR / "_default.md").read_text()


def _parse_template(name: str, raw: str) -> tuple[dict[str, Any], str]:
    if name.lower().endswith((".yml", ".yaml")):
        return _parse_yml_form(raw)
    return _parse_md_template(raw)


def _parse_md_template(raw: str) -> tuple[dict[str, Any], str]:
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            fm_text = raw[4:end]
            after = raw[end + len("\n---") :]
            body = after[1:] if after.startswith("\n") else after
            try:
                fm = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError:
                fm = {}
            if isinstance(fm, dict):
                return fm, body.lstrip("\n")
    return {}, raw


def _parse_yml_form(raw: str) -> tuple[dict[str, Any], str]:
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, raw
    if not isinstance(data, dict):
        return {}, raw
    fm = {k: data[k] for k in ("labels", "assignees") if k in data}
    sections: list[str] = []
    body_items = data.get("body", [])
    if isinstance(body_items, list):
        for item in body_items:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            label = str(attrs.get("label") or "").strip()
            if not label:
                continue
            placeholder = str(attrs.get("placeholder") or attrs.get("description") or "").strip()
            sections.append(f"## {label}\n\n{placeholder}\n")
    body = "\n".join(sections) if sections else "## Details\n"
    return fm, body


# ---------------------------------------------------------------------------
# Issue.md rendering
# ---------------------------------------------------------------------------


def _render_issue(
    pr_title: str,
    template_meta: dict[str, Any],
    stormitem_meta: dict[str, Any],
    body: str,
) -> str:
    fm: dict[str, Any] = {"title": pr_title}
    if "labels" in template_meta:
        fm["labels"] = list(template_meta["labels"] or [])
    if "assignees" in template_meta:
        fm["assignees"] = list(template_meta["assignees"] or [])
    fm["stormitem"] = dict(stormitem_meta)
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{fm_text}\n---\n\n{body.lstrip()}"


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


@app.command()
def pull(
    repo: Annotated[str, typer.Argument(help="Short repo name (e.g. zyp-skills)")],
    kind: Annotated[str, typer.Option("--kind", help="Conventional Commits type (feat, fix, ...)")],
    feature: Annotated[str, typer.Option("--feature", help="Conventional Commits scope (per-repo)")],
    title: Annotated[str, typer.Option("--title", help="Issue title (raw text; spaces ok)")],
) -> None:
    """Fetch an issue template, populate frontmatter, and write issue.md to a fresh tmp dir."""
    _validate_kind(kind)
    owner, features = _resolve_repo(repo)
    _validate_feature(feature, features)

    slug = _slug(kind, feature, title)
    template_used, raw = _fetch_template(owner, repo, kind)
    _, source_name = template_used.split(":", 1)
    fm_meta, body = _parse_template(source_name, raw)

    work_dir = Path(tempfile.mkdtemp(prefix=f"{TMP_PREFIX}{slug}-"))
    issue_path = work_dir / "issue.md"
    stormitem_meta = {
        "repo": repo,
        "kind": kind,
        "feature": feature,
        "title": title.strip(),
        "slug": slug,
        "template_used": template_used,
    }
    issue_path.write_text(
        _render_issue(_pr_title(kind, feature, title), fm_meta, stormitem_meta, body)
    )
    print(
        encode(
            {
                "dir": str(work_dir),
                "slug": slug,
                "template_used": template_used,
                "issue_path": str(issue_path),
            }
        )
    )


# ---------------------------------------------------------------------------
# post helpers
# ---------------------------------------------------------------------------


def _detect_push(owner: str, repo: str) -> bool:
    try:
        out = _gh("api", f"repos/{owner}/{repo}", "--jq", ".permissions.push").stdout.strip()
    except subprocess.CalledProcessError:
        return False
    return out.lower() == "true"


def _default_branch(owner: str, repo: str) -> str:
    out = _gh("api", f"repos/{owner}/{repo}", "--jq", ".default_branch").stdout.strip()
    if not out:
        raise typer.BadParameter(f"could not resolve default branch for {owner}/{repo}")
    return out


def _ref_sha(owner: str, repo: str, branch: str) -> str:
    out = _gh(
        "api",
        f"repos/{owner}/{repo}/git/ref/heads/{branch}",
        "--jq",
        ".object.sha",
    ).stdout.strip()
    if not out:
        raise typer.BadParameter(f"could not resolve sha for {owner}/{repo}@{branch}")
    return out


def _create_branch(owner: str, repo: str, branch: str, sha: str) -> None:
    payload = json.dumps({"ref": f"refs/heads/{branch}", "sha": sha})
    _gh(
        "api",
        "-X",
        "POST",
        f"repos/{owner}/{repo}/git/refs",
        "--input",
        "-",
        stdin=payload,
    )


def _put_file(owner: str, repo: str, path: str, message: str, content: str, branch: str) -> None:
    payload = json.dumps(
        {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
    )
    _gh(
        "api",
        "-X",
        "PUT",
        f"repos/{owner}/{repo}/contents/{path}",
        "--input",
        "-",
        stdin=payload,
    )


def _create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
) -> str:
    args = ["issue", "create", "--repo", f"{owner}/{repo}", "--title", title, "--body", body]
    for label in labels:
        args += ["--label", label]
    for assignee in assignees:
        args += ["--assignee", assignee]
    return _gh(*args).stdout.strip().splitlines()[-1]


def _create_pr(
    owner: str,
    repo: str,
    base: str,
    head: str,
    title: str,
    body: str,
) -> str:
    args = [
        "pr",
        "create",
        "--repo",
        f"{owner}/{repo}",
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body",
        body,
        "--draft",
    ]
    return _gh(*args).stdout.strip().splitlines()[-1]


def _edit_issue(owner: str, repo: str, number: int, body: str) -> None:
    _gh(
        "issue",
        "edit",
        str(number),
        "--repo",
        f"{owner}/{repo}",
        "--body",
        body,
    )


def _create_gist(plan_path: Path) -> str:
    return _gh("gist", "create", "--filename", "plan.md", str(plan_path)).stdout.strip().splitlines()[-1]


def _issue_number(url: str) -> int:
    m = ISSUE_URL_RE.search(url)
    if m is None:
        raise typer.BadParameter(f"could not parse issue number from {url!r}")
    return int(m.group(1))


def _pr_number(url: str) -> int:
    m = PR_URL_RE.search(url)
    if m is None:
        raise typer.BadParameter(f"could not parse PR number from {url!r}")
    return int(m.group(1))


def _summary_line(plan_text: str) -> str:
    for raw in plan_text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ">", "-", "*", "`")):
            continue
        return line
    return "Storming plan attached."


def _cleanup(work_dir: Path) -> None:
    real = Path(os.path.realpath(work_dir))
    tmp_root = Path(os.path.realpath(tempfile.gettempdir()))
    try:
        real.relative_to(tmp_root)
    except ValueError:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# post
# ---------------------------------------------------------------------------


@app.command()
def post(
    repo: Annotated[str, typer.Argument(help="Short repo name (e.g. zyp-skills)")],
    work_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the dir containing issue.md and plan.md",
            exists=True,
            file_okay=False,
            dir_okay=True,
        ),
    ],
) -> None:
    """Read the populated dir and create issue + branch + draft PR (or gist fallback)."""
    issue_path = work_dir / "issue.md"
    plan_path = work_dir / "plan.md"
    if not issue_path.is_file():
        raise typer.BadParameter(f"missing issue.md in {work_dir}")
    if not plan_path.is_file():
        raise typer.BadParameter(f"missing plan.md in {work_dir}")

    fm, body = _parse_md_template(issue_path.read_text())
    stormitem_meta = fm.get("stormitem")
    if not isinstance(stormitem_meta, dict):
        raise typer.BadParameter("issue.md is missing the `stormitem:` frontmatter block")
    if stormitem_meta.get("repo") != repo:
        raise typer.BadParameter(
            f"issue.md was prepared for repo {stormitem_meta.get('repo')!r}, not {repo!r}"
        )
    kind = str(stormitem_meta["kind"])
    feature = str(stormitem_meta["feature"])
    title = str(stormitem_meta["title"])
    slug = str(stormitem_meta["slug"])
    template_used = str(stormitem_meta.get("template_used", ""))

    pr_title = str(fm.get("title") or _pr_title(kind, feature, title))
    labels = [str(x) for x in (fm.get("labels") or [])]
    assignees = [str(x) for x in (fm.get("assignees") or [])]

    owner, _features = _resolve_repo(repo)
    push = _detect_push(owner, repo)

    if push:
        result = _post_pr(
            owner=owner,
            repo=repo,
            slug=slug,
            pr_title=pr_title,
            body=body,
            labels=labels,
            assignees=assignees,
            plan_text=plan_path.read_text(),
        )
    else:
        result = _post_gist(
            owner=owner,
            repo=repo,
            plan_path=plan_path,
            issue_title=pr_title,
            body=body,
            labels=labels,
            assignees=assignees,
        )

    result["template_used"] = template_used
    _cleanup(work_dir)
    print(encode(result))


def _post_pr(
    *,
    owner: str,
    repo: str,
    slug: str,
    pr_title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
    plan_text: str,
) -> dict[str, Any]:
    last_step = "init"
    try:
        last_step = "issue create"
        issue_url = _create_issue(owner, repo, pr_title, body, labels, assignees)
        issue_number = _issue_number(issue_url)

        last_step = "default branch lookup"
        default_branch = _default_branch(owner, repo)

        last_step = "base sha lookup"
        base_sha = _ref_sha(owner, repo, default_branch)

        branch = _branch(slug)
        last_step = "branch create"
        _create_branch(owner, repo, branch, base_sha)

        last_step = "plan commit"
        _put_file(
            owner,
            repo,
            f"plan/{slug}/plan.md",
            f"plan: {pr_title}",
            plan_text,
            branch,
        )

        last_step = "PR create"
        pr_body = f"Closes #{issue_number}\n\n{_summary_line(plan_text)}"
        pr_url = _create_pr(owner, repo, default_branch, branch, pr_title, pr_body)
        pr_number = _pr_number(pr_url)

        last_step = "issue linkback"
        new_body = body.rstrip() + f"\n\nPlan PR: #{pr_number}\n"
        _edit_issue(owner, repo, issue_number, new_body)

        return {
            "number": issue_number,
            "url": issue_url,
            "plan_url": pr_url,
            "pr_number": pr_number,
            "mode": "pr",
        }
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip() or str(e)
        typer.echo(f"stormitem post failed at step {last_step!r}: {stderr}", err=True)
        raise typer.Exit(1) from e


def _post_gist(
    *,
    owner: str,
    repo: str,
    plan_path: Path,
    issue_title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
) -> dict[str, Any]:
    last_step = "init"
    try:
        last_step = "gist create"
        gist_url = _create_gist(plan_path)

        last_step = "issue create"
        augmented = body.rstrip() + f"\n\n📋 [Storming plan]({gist_url})\n"
        issue_url = _create_issue(owner, repo, issue_title, augmented, labels, assignees)
        issue_number = _issue_number(issue_url)

        return {
            "number": issue_number,
            "url": issue_url,
            "plan_url": gist_url,
            "pr_number": None,
            "mode": "gist",
        }
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip() or str(e)
        typer.echo(f"stormitem post failed at step {last_step!r}: {stderr}", err=True)
        raise typer.Exit(1) from e


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


@app.command()
def registry() -> None:
    """Print the supported repos and their features as TOON."""
    reg = _load_registry()
    repos = reg.get("repos", {})
    rows = [
        {"repo": name, "owner": info.get("owner", ""), "features": list(info.get("features", []))}
        for name, info in sorted(repos.items())
    ]
    print(encode({"repos": rows}))


if __name__ == "__main__":
    app()
