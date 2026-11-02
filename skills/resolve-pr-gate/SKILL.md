---
name: resolve-pr-gate
description: >
  Use the bundled live-state script to fix CI failures and address Copilot and
  Codex review findings until ci and bot-review-complete pass for the current PR
  head and every unresolved bot thread is addressed.
  Run only through an explicit /resolve-pr-gate invocation; never trigger from
  a natural-language request.
metadata:
  kind: prompt
  version: "0.1.2"
  user-invocable: "true"
---

# Resolve PR Gate

With the repository root as `cwd`, run `scripts/pr_loop_state.py` from the directory containing this `SKILL.md`. Follow its recommendation and rerun it after each action to obtain a fresh snapshot. Wait 60 seconds between polls while gates are pending.

## Constraints

- Completion requires `ci` and `bot-review-complete` for the current PR head, with no unresolved threads from Copilot or `chatgpt-codex-connector`. The shared gate owns review completion and quota fallback; use its aggregate verdict.
- Preserve the repository's automatic-review trigger, including Smart review detection. Let Smart detection decide whether trivial changes need a fresh review; an older reviewed commit or no new review is not by itself evidence of a stuck gate.
- Validate findings against the current code. Fix valid findings, explain why invalid findings should not be applied, and resolve every addressed thread, including findings on earlier commits.
- Before pushing, run applicable linting and typechecking for the whole change, plus targeted tests when they take under 15 seconds in total, including startup. Commit prepared fixes and use `just pr` to start CI/reviews.
- Minimize local test runs: prefer targeted tests and reuse passing checks for unaffected code and configuration. Wording, docs and PR metadata alone do not warrant a full local gate.
- Inspect actual CI and local gate definitions. Rely on CI for equivalent coverage. After pushing, run slower local tests only when warranted by the change and absent from CI, or explicitly requested. Report which checks actually ran and where.
- After resolving threads without a push, use the script's `gh workflow run org_gate.yml` command to refresh the verdict. Refreshing alone requires no empty commit or repeat local test run.
- Missing or pending review evidence remains blocking. After 12 minutes without progress, inspect the gate reason, linked workflow, review progress and pending requests. Post `@codex review` once only for a demonstrably stuck review gate with no running review or pending request; elapsed time alone does not establish a stall. Report unavailable reviewers or access/configuration failures that cannot be cleared by a code fix.
- Commit recognized local changes without pushing when instructed. Stop on unfamiliar changes or an unsafe branch relation. A separate human-review gate may prevent merging.
- Update `.github/copilot-instructions.md` only when a concise, general instruction would prevent a demonstrated recurring false positive.
