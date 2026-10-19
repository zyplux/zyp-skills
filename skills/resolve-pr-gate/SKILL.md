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
  version: "0.1.0"
  user-invocable: "true"
---

# Resolve PR Gate

With the repository root as `cwd`, run `scripts/pr_loop_state.py` from the directory containing this `SKILL.md`. Follow its recommendation and rerun it after each action to obtain a fresh snapshot. Wait 60 seconds between polls while gates are pending.

## Constraints

- Completion requires `ci` and `bot-review-complete` for the current PR head, with no unresolved threads from Copilot or `chatgpt-codex-connector`. The shared gate owns review completion and quota fallback; use its aggregate verdict.
- Preserve the repository's automatic-review trigger. When the gate waits for Codex, inspect its summary and recent review requests. Post `@codex review` once if the current head has no running review or pending request, including when Smart detection has not requested a fresh review.
- Validate findings against the current code. Fix valid findings, explain why invalid findings should not be applied, and resolve every addressed thread, including findings on earlier commits.
- Run the full `just c` gate for fixes or unpushed commits. Reuse a passing run when HEAD is unchanged. Commit resulting changes and use `just pr` when commits need pushing and review needs requesting.
- After resolving threads without a push, use the script's `gh workflow run org_gate.yml` command to refresh the verdict. Refreshing alone requires no empty commit or repeat local test run.
- Missing or pending review evidence remains blocking. Inspect the linked workflow when progress stops; report unavailable reviewers or access/configuration failures that cannot be cleared by a code fix. Inspect review progress after 12 minutes before treating it as stuck.
- Commit recognized local changes without pushing when instructed. Stop on unfamiliar changes or an unsafe branch relation. A separate human-review gate may prevent merging.
- Update `.github/copilot-instructions.md` only when a concise, general instruction would prevent a demonstrated recurring false positive.
