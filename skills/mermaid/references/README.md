# Mermaid references

The files under `syntax/` are sourced from the official Mermaid project docs and are the authoritative syntax reference the skill consults when generating diagrams.

## Upstream

- Repository: <https://github.com/mermaid-js/mermaid>
- Source path: `docs/syntax/` at the `mermaid@<version>` release tag matching `metadata.mermaid-version`
- Direct browse: <https://github.com/mermaid-js/mermaid/tree/mermaid%4011.17.2/docs/syntax>

## Pinned version

The current Mermaid version this skill targets is in `../SKILL.md` frontmatter under `metadata.mermaid-version` — that is the single source of truth.

## How to refresh on a Mermaid upgrade

1. **Sync syntax first.** Check out the exact latest stable `mermaid@<version>` tag, then replace `syntax/*.md` with its complete `docs/syntax/*.md` set.

2. **Inspect the syntax diff.** Inventory every added, removed, or changed feature only after the sync.

3. **Update `../SKILL.md` from that diff.** Integrate the current capabilities into its selection guidance, examples, heuristics, and pitfalls; then set `metadata.mermaid-version` to the upstream release.

4. **Bump and validate.** Bump both `metadata.version` and the `version` in the `../SKILL.md`. Minor and patch must match between the two.
