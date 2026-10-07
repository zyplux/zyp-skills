# BASELINE
set shell := ["bash", "-euo", "pipefail", "-c"]

alias i := install
alias k := knip
alias tc := typecheck
alias l := lint
alias t := test
alias c := check
alias u := upgrade
alias ui := upgrade-interactive
alias p := push
alias pr := push-ready

# List available recipes.
default:
    @just --list

# Install both workspaces: pnpm + uv.
install:
    pnpm install
    uv sync --all-packages --all-groups

# Report unused files, deps, and exports: knip (JS workspace) + vulture (Python).
knip:
    pnpm run knip
    uv run vulture

# Type-check both workspaces: tsc/Node for .ts, pyrefly for .py.
typecheck:
    pnpm run typecheck
    uv run pyrefly check

# Lint and format both workspaces with autofix.
lint:
    pnpm run lint:fix
    pnpm run format
    uv run rumdl check --fix --no-cache
    uv run rumdl fmt
    uv run ruff check --fix
    uv run ruff format

# Run tests for both workspaces. Optional arg filters by test name; never fails when nothing matches.
test name='':
    pnpm run test {{ if name == '' { '' } else { '-- -t ' + quote(name) + ' --passWithNoTests' } }}
    uv run pytest {{ if name == '' { '' } else { '-k ' + quote(name) } }} || [ "$?" -eq 5 ]

# Verify applicable org invariants with cerberus, over the coverage reports `test` regenerates.
cerberus:
    uv run cerberus --fix

# Full gate across both workspaces: install, knip, typecheck, lint, test, cerberus — autofix throughout.
check: install knip typecheck lint test cerberus

# Upgrade the pinned toolchain plus JavaScript and Python workspace dependencies through cz.
upgrade *args='':
    pnpm run --silent cz upgrade {{ args }}

# Interactively select toolchain and JavaScript upgrades; Python upgrades remain non-interactive.
upgrade-interactive:
    @pnpm run --silent cz upgrade --interactive

# Push the current branch and open a draft PR (-r/--ready marks it ready and enables auto-merge).
push *flags:
    pnpm run cz push-branch {{ flags }}

# Push the current branch and open a PR marked ready, enabling auto-merge.
push-ready: (push "--ready")

# Remove gitignored build artifacts and caches from all workspaces.
clean *flags:
    pnpm run cz clean {{ flags }}

# CUSTOM

# Bump <skill>'s version (default --minor; -p/--patch, --major). Idempotent + higher-wins.
bump *args:
    @uv run scripts/release.py bump {{ args }}
