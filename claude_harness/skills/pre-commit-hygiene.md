---
name: pre-commit-hygiene
description: |
  What runs locally vs in CI, and what's gating vs advisory in CalFlow.
---

# Pre-commit hygiene

## What's installed

`.pre-commit-config.yaml` runs on every `git commit`:

| Hook | Gating? | Note |
|---|---|---|
| trailing-whitespace, EOF | yes | mechanical |
| check-yaml, check-toml, check-merge-conflict | yes | sanity |
| check-added-large-files (500 KB) | yes | accidental binary push protection |
| ruff (check + format) | yes | from `pyproject.toml` config |
| mypy | advisory | strict gate planned post-v1.1.29 |

## What CI runs

`.github/workflows/ci.yml` matrix on Python 3.10 / 3.11 / 3.12:

| Job | Gating? | Note |
|---|---|---|
| `pytest tests/` | yes | 450+ tests, ~70 ms |
| `ruff check` | advisory (`continue-on-error`) | shows in PR |
| `ruff format --check` | advisory | shows in PR |

## When a hook is gating, it MUST pass

- ruff check / format failures block the commit
- pytest red blocks CI
- The user can `--no-verify` only as an emergency

## Adding a new hook

1. Edit `.pre-commit-config.yaml`
2. Pin to a specific revision (`rev: vX.Y.Z`); never `master`
3. Test locally: `pre-commit run --all-files`
4. If noisy on first run, set `continue-on-error: true` (advisory) for
   one or two release cycles, then flip to gating once the noise is fixed

## Local typecheck

```bash
./scripts/typecheck.sh        # full strict pass
./scripts/typecheck.sh core/  # one package
./scripts/typecheck.sh --report   # save log to scripts/typecheck.log
```

This is NOT in pre-commit because the strict pass is still being tightened.
Run before tagging a release.

## What lives WHERE

| Concern | File |
|---|---|
| Style rules (line length, naming) | `pyproject.toml::[tool.ruff]` |
| Import sorting | `pyproject.toml::[tool.ruff.lint]` (`I` rule) |
| Type strictness | `pyproject.toml::[tool.mypy]` |
| Pre-commit hook list | `.pre-commit-config.yaml` |
| CI matrix | `.github/workflows/ci.yml` |
| Test runner config | `pyproject.toml::[tool.pytest.ini_options]` |
