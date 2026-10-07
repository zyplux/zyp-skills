---
name: resolve-pr-codex-threads
description: >
  Use the bundled live-state script to resolve CI failures and Codex review
  findings. Repeat until ci passes, chatgpt-codex-connector completes Code Review
  for the current PR head, and every unresolved Codex thread is addressed.
  Run only through an explicit /resolve-pr-codex-threads invocation; never
  trigger from a natural-language request.
metadata:
  kind: prompt
  version: "0.1.0"
  user-invocable: "true"
---

# Resolve PR Codex Threads

1. Resolve the directory containing this `SKILL.md` as `THIS_SKILL_MD_DIR`.
2. With the repo root as `cwd`, execute the bundled script:

```bash
<THIS_SKILL_MD_DIR>/scripts/pr_loop_state.py
```

3. Follow its recommendation. After requesting review, wait 3 minutes before the first rerun. For later waits, set a 60-second wake-up, then rerun the script.

## Constraints

- Gate on `ci`, the Codex summary's Code Review entry for the current PR head, and unresolved threads authored by `chatgpt-codex-connector`. Security Review completion alone does not establish Code Review completion.
- Validate every finding against the current code. Fix valid findings with minimal maintained code; explain why invalid findings should not be applied. Resolve every addressed thread, including older findings that still apply.
- For fixes or unpushed commits, ensure `just c` passes for the resulting local HEAD. Reuse a passing run when nothing changed. Commit resulting changes, push unpushed commits with `git push`, and request review with `@codex review`.
- For a missing or stale Codex review, follow the script's request to post `@codex review`. Review requests alone do not require another local test run or an empty commit.
- Do not treat a running review as stuck before 12 minutes. Then inspect its progress; stop and inform the user if it is stuck or broken.
- The script checks working-tree cleanliness and branch safety before reporting review actions. Commit recognized local changes without pushing when instructed; stop on unfamiliar changes or an unsafe branch relation.
- A separate human-review gate may prevent final auto-merge.
