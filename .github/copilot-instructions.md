# Copilot review instructions

- The mandatory `ci` check runs the full quality gate on every push: ruff (`select = ["ALL"]`), pyrefly, vulture, knip, tsc, eslint, rumdl, and both test suites. Do not report syntax, typechecking and linting errors - leave these to the deterministic ci gate.
- Before claiming a library invokes user code with a specific calling convention (positional vs keyword, argument order), verify against that library's own adapter layer, not the underlying framework's convention. Example: Typer wraps `typer.Option` callbacks via signature inspection and calls them with keyword arguments, so keyword-only parameters (`*, value`) are valid even though raw Click callbacks are positional.
