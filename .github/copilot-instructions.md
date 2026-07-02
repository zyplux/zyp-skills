# Copilot review instructions

- Branch protection, required reviews, and required status checks for this repo are enforced by
  org-level GitHub rulesets, not by files in the repository. Do not flag the absence or removal of
  in-repo protection config (e.g. a Settings-app `settings.yml` or a branch-protection block) as a
  loss of protection.
- The `ci` check runs the full quality gate on every push: ruff (`select = ["ALL"]`), pyrefly,
  vulture, knip, tsc, eslint, rumdl, and both test suites. Do not claim that code already on a
  green head "will fail" lint or typechecking by one of these tools — a green `ci` check proves
  it does not.
