set shell := ["bash", "-euo", "pipefail", "-c"]

alias i := install
alias k := knip
alias tc := typecheck
alias l := lint
alias t := test
alias c := check
alias si := skill-install
alias su := skill-uninstall
alias u := upgrade
alias p := push
alias b := bump

# List available recipes.
default:
    @just --list

# Install Python dependencies (all groups).
install:
    uv sync --all-groups

# Upgrade all dependencies to latest compatible versions and reinstall.
upgrade:
    uv sync --all-groups --upgrade

# Find dead code via vulture.
knip:
    uv run --group lint vulture

# Type-check via pyrefly.
typecheck:
    uv run --group typecheck pyrefly check

# Lint with autofix: rumdl + ruff.
lint:
    uv run --group lint rumdl check --fix
    uv run --group lint ruff check --fix

# Run tests via pytest. Use `--` to forward dash-flagged args (e.g. `just t -- -k expr`).
test *args:
    uv run --group test pytest {{ args }}

# Full gate: install, knip, typecheck, lint, test — autofix throughout.
check: install knip typecheck lint test

# Install a skill globally (omit name to install all stale skills; FORCE=1 reinstalls all)
skill-install name="":
    @uv run scripts/skillman.py install {{ name }}

# Uninstall a skill globally
skill-uninstall name:
    @uv run scripts/skillman.py uninstall {{ name }}

# Push current branch; opens a draft PR (-r marks ready and enables auto-merge)
push *flags:
    @uv run scripts/pusher.py {{ flags }}

# Bump <skill>'s version (default --minor; -p/--patch, --major). Idempotent + higher-wins.
bump *args:
    @uv run scripts/release.py bump {{ args }}
