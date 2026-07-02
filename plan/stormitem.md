# stormitem — Plan

> **Status:** ready — readiness 95%
> **Last updated:** 2026-04-29
> **Walking skeleton:** Two-step deterministic CLI plus a thin SKILL.md storming wrapper. **Step 1:** SKILL.md calls `stormitem pull <repo> --kind K --feature F --title T`. The CLI fetches the target repo's matching `.github/ISSUE_TEMPLATE/*` (or falls back to a built-in skeleton), writes a populated `issue.md` (with stormitem metadata in YAML frontmatter) into a fresh `/tmp/stormitem-<slug>-XXXXXX/` dir, prints the path. **Step 2:** SKILL.md hands off to `/plan-storm` with a rich-prose seed mentioning the same dir; user storms; `plan.md` lands in the same dir. Two review gates (plan, then issue). After approval, SKILL.md calls `stormitem post <repo> <dir>` — the CLI reads `issue.md` frontmatter for kind/feature/title, posts the issue, creates branch `stormitem/<slug>`, commits `plan/<slug>/plan.md` from the local plan, opens a draft PR titled `<kind>(<feature>): <title>` with `Closes #N`, and links the issue back to the PR. Falls back to gist when push access is unavailable. Files in `/tmp/` are left to OS cleanup; non-`/tmp/` paths are deleted after success.

## 1. Vision

A skill that turns a rough thought (from the user) or a rich mid-task observation (from an agent) into a well-formed GitHub issue + draft PR + plan artifact, optimized for handoff to an auto-implementing agent. The CLI is deterministic and self-contained — it knows about repos, templates, branches, and Conventional Commits naming. SKILL.md only orchestrates the storming and the two human review gates.

## 2. Problem & motivation

Two failure modes exist today:

- **Agent-side:** when an agent writes a workaround or hits a bug it can't fix, the moment is lost — no lightweight path to capture it as a tracked issue.
- **User-side:** raising an issue against a repo means context-switching to GitHub, picking the right template, composing alone.
- **Future agent:** an auto-implementing agent will pick up issues and implement them; it benefits enormously from a pre-prepared workspace (draft PR + branch + plan) rather than just an issue body.

`stormitem` solves all three by composing with `plan-storm` for the storming phase and pushing all deterministic mechanics into a CLI.

## 3. Users & primary scenarios

- Primary user: realSergiy.
- Future user: auto-implementing agent that watches issues in supported repos.
- **Mode A — agent-originated.** Mid-task, an agent invokes `/stormitem <rich seed>`. SKILL.md derives repo/kind/feature/title from seed (asking only when ambiguous), calls `stormitem pull`, hands the resulting dir off to plan-storm, runs review gates, calls `stormitem post`.
- **Mode B — user-originated.** User types `/stormitem [rough idea]`. Same flow.
- **Both modes are interactive with two review gates.**

## 4. Goals

- [DECIDED] Skill kind: `cli` — ships a deterministic executable that does the heavy lifting; SKILL.md is thin orchestration.
- [DECIDED] **No autocomplete.** Users type repo, kind, feature, title at invocation. Registry exists for validation + per-repo metadata, not for shell completion.
- [DECIDED] **Three CLI subcommands:**
  - `stormitem pull <repo> --kind K --feature F --title T` — fetch template, populate frontmatter, write `issue.md` to a fresh `/tmp/stormitem-<slug>-XXXXXX/` dir, print the dir path as TOON.
  - `stormitem post <repo> <dir>` — read `issue.md` frontmatter for kind/feature/title; read `plan.md` from the same dir; create issue + branch + PR (or gist fallback); print TOON result; clean up if dir is not under `/tmp/`.
  - `stormitem registry` — list supported repos / features (one-shot inspection; no completion).
- [DECIDED] **Kinds follow Conventional Commits types** — `feat`, `fix`, `docs`, `refactor`, `perf`, `chore`, `revert`, etc. CLI accepts any string that matches the Conventional Commits spec; doesn't enforce a curated subset.
- [DECIDED] **Repo identifier is the short name** (e.g. `zyp-skills`), not `owner/name`. The registry maps short name → owner. Simplifies the CLI surface; assumes no name collisions across the user's personal repos.
- [DECIDED] **Feature is the Conventional Commits scope.** Per-repo features are pre-registered; CLI accepts only registered features for known repos (errors otherwise so typos don't sneak through to PR titles).
- [DECIDED] **Slug derivation: `<kind>_<feature>_<title_snake>`.** E.g. kind=`feat`, feature=`peek`, title=`support_julia` → slug `feat_peek_support_julia`. Used for branch name, plan dir name, and tmp dir prefix.
- [DECIDED] **Branch name: `stormitem/<slug>`.** Fixed convention.
- [DECIDED] **PR title: `<kind>(<feature>): <title-with-spaces>`** (Conventional Commits). E.g. `feat(peek): support julia`. Underscores in the raw title are converted to spaces.
- [DECIDED] **Plan path inside target repo: `plan/<slug>/plan.md`.** Subdirectory mirrors the local `/tmp/` layout and avoids collision with plan-storm's flat `plan/<name>.md` files.
- [DECIDED] **Submission shape for the plan artifact: PR+branch by default; gist fallback when push access unavailable.** Detected via `gh api repos/{owner}/{repo} --jq '.permissions.push'`. Determined entirely inside the CLI; SKILL.md never thinks about it. The issue body is always just the template-mapped sections + a link to the plan artifact — never inflated with plan content.
- [DECIDED] **Metadata convention: YAML frontmatter in `issue.md`** under a `stormitem:` namespace, plus standard issue-template frontmatter (`title`, `labels`, `assignees`). `stormitem post` reads `stormitem.repo` / `stormitem.kind` / `stormitem.feature` / `stormitem.title` to drive the post.
- [DECIDED] **TOON output** for both `pull` and `post`.
- [DECIDED] Auth via `gh` CLI shell-out only (including `gh api` for branch/file/PR creation).
- [DECIDED] Both invocation modes are interactive storming sessions with two on-disk review gates.
- [DECIDED] **Plan-storm reuse: composition with rich-prose seed only.** No directives.
- [DECIDED] **Default file location: `/tmp/stormitem-<slug>-XXXXXX/`** (random suffix via `tempfile.mkdtemp`). OS handles cleanup; CLI does not delete `/tmp/` paths.
- [DECIDED] **Cleanup rule: CLI deletes input dir on success unless under `/tmp/`.**
- [DECIDED] **Stop threshold: plan-storm's default 95%.** The plan-review gate is the human safety net.
- [DECIDED] **Registry layering: shipped-only (PR adds a repo).** No user-config layer in v1 — stormitem supports a small handful of personal repos, all of which warrant a versioned PR to add. Pre-registers `zyp-skills` only.
- [DECIDED] **Branch and plan-path conventions are fixed across all repos** in v1 — predictable for the future auto-implementing agent. Per-repo overrides deferred to v2 if real-world friction shows up.
- [DECIDED] Sync test enforces that `registry.toml`'s `zyp-skills` features match `os.listdir(skills/)`.
- [DECIDED] **Frontmatter parser: PyYAML.** Added to inline PEP 723 deps as `pyyaml>=6.0`.
- [DECIDED] **Optimistic posting; fail-loud.** No partial-failure recovery, idempotency tracking, or resume logic in v1. On any error, the CLI prints the error and the last-successful step, leaves the temp dir intact, and exits non-zero. The user resolves repo-side state manually and re-runs `stormitem post`.

## 5. Non-goals (current scope)

- Shell autocomplete.
- One-shot CLI posting without storming (CLI itself supports this — but SKILL.md always uses both gates).
- Auto-creating labels in target repos.
- Editing/closing existing issues.
- EDITOR-based body composition.
- Issue search / dedup.
- Modifying plan-storm's core protocol.
- Per-repo branch/path convention overrides.
- Supporting third-party / external repos in the registry.

## 6. Constraints

- Repo conventions: PEP 723 single-file CLI, `package.json` with matching `version`, validation via `tests/test_skills_valid.py`, version-bump rule.
- Python 3.14+; deps `typer` + `toon-format`.
- `gh` must be installed and authenticated.
- Hard dependency on `/plan-storm` (composition).
- PR+branch flow requires push permission; detected per-call.
- Issue body is always just the template-mapped sections + a link to the plan artifact (PR or gist). No length concerns.

## 7. Functional requirements

### SKILL.md (orchestration)

- [DECIDED] FR-S1 — On `/stormitem [seed]` invocation: parse seed; clarify repo / kind / feature / title via short clarification interactions if missing or ambiguous.
- [DECIDED] FR-S2 — Call `stormitem pull <repo> --kind K --feature F --title T`. Capture the returned `/tmp/stormitem-<slug>-XXXXXX/` dir path.
- [DECIDED] FR-S3 — Hand off to `/plan-storm` with a rich-prose seed that naturally mentions the save path `<dir>/plan.md`. No directives.
- [DECIDED] FR-S4 — When plan-storm stops, **gate 1 (plan review):** print the plan.md path; user opens in editor; reply approve / edit / abort. On `edit`, hand back to plan-storm with the user's notes.
- [DECIDED] FR-S5 — On plan approval: post-process `plan.md` content into the issue.md template body sections (using the issue.md template body as a guide to which sections need filling). Update `issue.md` in place. Then **gate 2 (issue review):** print the issue.md path; user reviews; reply approve / edit / abort.
- [DECIDED] FR-S6 — On issue approval: call `stormitem post <repo> <dir>`. Print the resulting `{number, url, plan_url, mode}` to the user.

### CLI — `pull`

- [DECIDED] FR-C1 — Args: `<repo>` (positional, short name), `--kind` (required), `--feature` (required), `--title` (required, raw text).
- [DECIDED] FR-C2 — Validate: repo is in registry; feature is in registry's feature list for that repo; kind is a non-empty Conventional Commits identifier (lowercase, no spaces).
- [DECIDED] FR-C3 — Fetch the target repo's `.github/ISSUE_TEMPLATE/` listing via `gh api`. Pick the template whose name or filename best matches kind (substring heuristic: `feat`/`feature`/`request` for `feat`; `bug`/`fix` for `fix`; etc.). Prefer `.yml` over `.md`. On miss, use the shipped fallback `templates/<kind>.md` (or `templates/_default.md` if kind has no specific shipped template).
- [DECIDED] FR-C4 — Create `/tmp/stormitem-<slug>-XXXXXX/` via `tempfile.mkdtemp(prefix=f"stormitem-{slug}-")`. Slug = `<kind>_<feature>_<title_snake>` where `title_snake = title.replace(' ', '_')`.
- [DECIDED] FR-C5 — Render `issue.md` with YAML frontmatter:
  ```yaml
  ---
  title: "<kind>(<feature>): <title-with-spaces>"
  labels: [<from-template-frontmatter-if-present>]
  assignees: [<from-template-frontmatter-if-present>]
  stormitem:
    repo: <repo>
    kind: <kind>
    feature: <feature>
    title: <title>
    slug: <slug>
    template_used: remote:<filename> | builtin:<kind>
  ---

  <template body>
  ```
- [DECIDED] FR-C6 — Print TOON: `{dir, slug, template_used, issue_path}` so SKILL.md can pick up the dir.

### CLI — `post`

- [DECIDED] FR-C7 — Args: `<repo>` (positional, short name), `<dir>` (positional, path containing `issue.md` and `plan.md`).
- [DECIDED] FR-C8 — Validate: dir exists; both files exist; issue.md has valid stormitem frontmatter with matching repo.
- [DECIDED] FR-C9 — Detect push access: `gh api repos/{owner}/{repo} --jq '.permissions.push'`. Choose mode `pr` (true) or `gist` (false).
- [DECIDED] FR-C10 — **PR mode flow:**
  1. Strip frontmatter from issue.md → final issue body.
  2. `gh issue create --repo <owner>/<repo> --title <frontmatter.title> --body @<stripped-body> [--label …] [--assignee …]` → returns issue number `N` and URL.
  3. Get default branch sha: `gh api repos/<owner>/<repo>/git/ref/heads/<default>`.
  4. Create branch `stormitem/<slug>`: `gh api repos/<owner>/<repo>/git/refs -X POST -f ref=refs/heads/stormitem/<slug> -f sha=<base-sha>`.
  5. Commit plan: `gh api repos/<owner>/<repo>/contents/plan/<slug>/plan.md -X PUT -f message="plan: <kind>(<feature>): <title>" -f content=<base64> -f branch=stormitem/<slug>`.
  6. Create draft PR: `gh pr create --repo <owner>/<repo> --base <default> --head stormitem/<slug> --title "<frontmatter.title>" --body "Closes #N\n\n<one-line summary derived from plan>" --draft` → returns PR number `M` and URL.
  7. Append linkback to issue: `gh issue edit N --body-file -` with original body + a "Plan PR: #M" footer.
- [DECIDED] FR-C11 — **Gist fallback flow** (used when push access is unavailable):
  1. `gh gist create --filename plan.md <dir>/plan.md` → returns gist URL.
  2. Strip frontmatter from issue.md → final issue body. Append ```📋 [Storming plan](<gist-url>)``` footer.
  3. `gh issue create` with the augmented body.

  Issue body is still just template-mapped sections; the plan content lives in the gist.

- [DECIDED] FR-C12 — Cleanup: if `<dir>` is under `/tmp/` (resolved via `os.path.realpath`), skip; otherwise `shutil.rmtree(<dir>)`.
- [DECIDED] FR-C13 — Output TOON: `{number, url, plan_url, pr_number, mode, template_used}` (`plan_url` = PR URL in PR mode, gist URL in gist mode; `pr_number` = null in gist mode).

### CLI — `registry`

- [DECIDED] FR-C14 — `stormitem registry` prints the supported repos and their features as TOON. One-shot inspection; not used at runtime.

## 8. Walking skeleton (v1 / MVP)

- `/stormitem [seed]` → SKILL.md clarifies args → calls `stormitem pull` → hands off to plan-storm → review gate 1 → maps plan to issue body → review gate 2 → calls `stormitem post`.
- `stormitem pull` and `stormitem post` are deterministic; neither knows about plan-storm.
- Registry: `skills/stormitem/registry.toml` pre-registers `zyp-skills` with all skill-dir names as features.
- Built-in fallback templates at `skills/stormitem/templates/{feat,fix,refactor,_default}.md`.
- Sync test: registry's `zyp-skills` features = `os.listdir(skills/)`.
- PR+branch flow with gist fallback. End-to-end tested against a sandbox repo before v1 ships.

## 9. Architecture sketch

Three layers:

- **SKILL.md (thin orchestrator)** — frames the session, derives args from seed, calls `pull`, hands off to `/plan-storm`, runs both review gates, calls `post`. Knows nothing about templates, frontmatter, branches, PRs, or gists. Knows only: kind/feature/title shape, the two CLI calls, and the two review gates.
- **plan-storm (composed, unmodified)** — runs its own protocol; writes the plan to the path mentioned in the rich-prose seed.
- **CLI `stormitem.py` (deterministic)** — three subcommands (`pull`, `post`, `registry`). Owns: registry parsing, template fetching + matching, frontmatter rendering + parsing, slug derivation, push-access detection, PR+branch flow, gist fallback, cleanup rule.

The CLI is the only component that talks to GitHub. SKILL.md only invokes the CLI and waits for the user's review-gate replies.

## 10. Tech stack

- [DECIDED] Python 3.14, typer, toon-format.
- [DECIDED] `gh` shell-out via `subprocess.run` (issue create, gist create, `gh api` for refs/contents/PR).
- [DECIDED] Stdlib `tomllib` for the registry.
- [DECIDED] PyYAML for frontmatter — `pyyaml>=6.0` added to PEP 723 deps.
- [DECIDED] Markdown skeletons over YAML form templates for built-in fallbacks.

## 11. Roadmap

- **v1 / walking skeleton:** SKILL.md orchestration + `pull` + `post` + `registry` + shipped registry with `zyp-skills` + PR+branch with gist fallback + sync test + end-to-end test against a sandbox repo.
- **v2:** more personal repos in the registry; per-repo branch/path overrides if needed; richer agent-seed parsing (auto-extract title from seed); richer frontmatter (e.g. milestone, project).
- **v3+:** issue dedup search; idempotency / resume support for partial-failure recovery (the PR mode has 5–7 API calls); multi-issue batch.

## 12. Decisions log

- Chose `gh` shell-out over direct API.
- Chose three CLI subcommands (`pull`, `post`, `registry`) — `pull` and `post` deterministic, `registry` informational.
- Chose markdown skeletons over YAML form templates for built-in fallbacks.
- Chose hardcoded registry + sync test.
- Chose interactive storming for both invocation modes.
- Chose composition with `/plan-storm` (no inheritance, no protocol changes).
- Chose rich-prose seeding over directive-passing to plan-storm.
- Chose two on-disk review gates.
- Chose post-success cleanup with the `/tmp/`-skip rule.
- Chose PR+branch as default submission shape over gist+link, optimized for the future auto-implementing agent. Gist is the fallback for read-only repos.
- Chose to decouple the CLI from the storming protocol — the user can invoke `stormitem post` with hand-rolled files.
- **Chose to push *all* deterministic mechanics into the CLI** — repo identifier resolution, template fetching + matching, frontmatter rendering, slug derivation, branch naming, PR title format, push-access detection, gist fallback, cleanup. SKILL.md knows only the high-level flow. This minimizes the SKILL.md surface that has to be perfectly specified in prose.
- **Chose YAML frontmatter in `issue.md` (`stormitem:` namespace)** as the metadata-passing convention between `pull` and `post`. One file, machine-readable, editor-friendly, doesn't pollute the visible markdown.
- **Chose Conventional Commits naming for kind / scope / PR title / branch** — `<kind>(<feature>): <title>` for PR; `stormitem/<kind>_<feature>_<title>` for branch. Aligns with how PRs are titled across this codebase already.
- **Chose short repo names** in the CLI (e.g. `zyp-skills`) over `owner/name` because the registry resolves the owner. Cleaner CLI usage. Acceptable because the registry is a small curated set of personal repos.
- **Chose to drop autocomplete** — the registry is small enough that typing a repo or feature is not a friction point, and removing autocomplete cuts complexity.
- **Chose registry-shipped only** (no user-config layer) for v1 — registry is small, repos are personal, version-controlled additions are appropriate.
- **Chose fixed branch / plan-path conventions across all repos** for v1 — predictable for the future auto-implementing agent.
- **Chose PyYAML over a hand-rolled frontmatter parser** because frontmatter has nested tables (`stormitem:`), arrays (`labels:`), and quoting — all things hand parsers get subtly wrong. The dep cost is one line in the inline `# /// script` block.
- **Chose optimistic posting with no partial-failure recovery** — these are the user's own repos, the failure rate will be tiny, and recovery logic is meaningful complexity. On error: print, keep temp dir, exit non-zero. User retries manually after resolving repo-side state.
- **Chose to keep the issue body always small** (just template-mapped sections + a link to the plan artifact). The plan content lives only in the PR branch or the gist. This dissolves any body-size concerns and keeps the issue surface clean.

## 13. Open questions

*All resolved. Plan is ready for implementation.*

## 14. Known unknowns

- Whether plan-storm reliably honors a path mention encoded as prose in the rough idea (it should per its existing rule, but worth a smoke test before v1 ships).
- Whether the post-processing step (plan.md → issue.md) reliably produces good template-shaped sections, or whether real-world plans need a manual mapping pass via the issue-review gate. The gate is the safety net either way.
- Whether `gh issue create --template` + `--body` can be used to inherit template metadata (labels, assignees) without opening an editor — if yes, simplifies FR-C5.
- How often the auto-implementing agent will actually exist. If always present in target repos, PR+branch is right forever. If rare, a simpler gist-only mode might be fine — but supporting both is cheap.
- Whether the slug suffix from `tempfile.mkdtemp` will confuse the user when they look at multiple in-flight stormitem sessions. Mitigation: print the slug separately so the user can tell sessions apart even if the dir paths look similar.
