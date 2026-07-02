# Mermaid references

The files under `syntax/` are sourced from the official Mermaid project docs and are the authoritative syntax reference the skill consults when generating diagrams.

## Upstream

- Repository: <https://github.com/mermaid-js/mermaid>
- Source path: `docs/syntax/` on the `develop` branch
- Direct browse: <https://github.com/mermaid-js/mermaid/tree/develop/docs/syntax>

## Pinned version

The current Mermaid version this skill targets is in `../SKILL.md` frontmatter under `metadata.mermaid-version` — that is the single source of truth.

## How to refresh on a Mermaid upgrade

1. **Download** the latest stable syntax docs from upstream — e.g. shallow-clone the repo and copy `docs/syntax/*.md` into `syntax/`, or fetch each file directly from the GitHub raw URL. Diff against the current files; note all changes.

2. **Review `../SKILL.md`** — and update it for all the changes you have spotted.

3. **Bump both versions** in `../SKILL.md` frontmatter:
   - `metadata.mermaid-version` — to the new Mermaid release (e.g. `"11.15.0"`).
   - `metadata.version` — patch for syntax-only refreshes, minor when new diagram types or workflow changes land.
