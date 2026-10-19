# zyp-skills

Reusable skills for Codex and Claude Code.

## Skills

| Skill | Kind | Description |
|-------|------|-------------|
| [peek](skills/peek/SKILL.md) | cli | Inspect parquet files — preview, schema, unique values, group-by, SQL |
| [h2md](skills/h2md/SKILL.md) | cli | Convert web articles to clean, faithful markdown |
| [suggest](skills/suggest/SKILL.md) | cli | Submit structured improvement suggestions for skills |
| [gen-commit-message](skills/gen-commit-message/SKILL.md) | prompt | Generate a Conventional Commits message for the current project |
| [mermaid](skills/mermaid/SKILL.md) | prompt | Pick the right Mermaid diagram type and render it correctly |
| [plan-storm](skills/plan-storm/SKILL.md) | prompt | Brainstorm a `plan.md` through option-rich rounds before any code |
| [resolve-pr-gate](skills/resolve-pr-gate/SKILL.md) | prompt | Resolve CI failures and findings from Copilot and Codex until the aggregate PR gate passes |

Each skill declares `metadata.kind` in its SKILL.md: `cli` skills ship an executable; `prompt` skills are SKILL.md-driven with no binary. Omitting `metadata.kind` defaults to `prompt`.

## Development

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and the [GitHub CLI](https://cli.github.com/) (`gh`).

```bash
just i           # install all deps
just c           # full gate: install, knip (vulture), typecheck, lint, test — autofix
just l           # lint (autofixes)
just tc          # typecheck
just t           # test
just p           # push branch + open draft PR (-r marks ready, waits, squash-merges)
```

## GitHub reviews

The org gate requires `ci` and `bot-review-complete` for the current PR head. The shared bot gate accepts clean reviews from both bots, or one clean review when the other explicitly reports a quota limit. Unresolved findings from either bot block the gate.

Enable automatic Copilot reviews through the org ruleset and [Codex Code Review](https://learn.chatgpt.com/docs/third-party/github) for all PRs and new pushes in Codex settings.
