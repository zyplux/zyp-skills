# zyp-skills

A collection of skills for Claude Code.

## Skills

| Skill | Kind | Description |
|-------|------|-------------|
| [peek](skills/peek/SKILL.md) | cli | Inspect parquet files — preview, schema, unique values, group-by, SQL |
| [h2md](skills/h2md/SKILL.md) | cli | Convert web articles to clean, faithful markdown |
| [suggest](skills/suggest/SKILL.md) | cli | Submit structured improvement suggestions for skills |
| [gen-commit-message](skills/gen-commit-message/SKILL.md) | prompt | Generate a Conventional Commits message for the current project |
| [mermaid](skills/mermaid/SKILL.md) | prompt | Pick the right Mermaid diagram type and render it correctly |
| [plan-storm](skills/plan-storm/SKILL.md) | prompt | Brainstorm a `plan.md` through option-rich rounds before any code |

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

## GitHub apps

Three apps must be installed on the repo for the workflows to work end-to-end:

- [Claude Code](https://github.com/apps/claude) — powers PR review, draft-PR summary, and `@claude` mentions.
- GitHub Copilot — second AI reviewer, enabled in repo settings.
