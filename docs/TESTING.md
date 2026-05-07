# 🧪 CalFlow Testing Guide

This document describes how the test suite is organised and what
conventions to follow when writing new tests.

---

## Running tests

Single command, all 450 tests in <100 ms:

```bash
pytest tests/                        # full suite
pytest tests/test_v2_spec.py -v      # one file
pytest tests/ -k "title_url"         # by name pattern
pytest tests/ -x --tb=short          # stop on first failure
```

The `pytest` config lives in `pyproject.toml` (`[tool.pytest.ini_options]`).

You can also still run the whole thing with stdlib `unittest`:

```bash
python -m unittest discover tests/   # works, slower CLI but identical results
```

---

## Test framework — pytest, with unittest fallback

**Adopted in v1.1.28.** CI runs `pytest tests/` against Python 3.10 / 3.11 / 3.12.

pytest auto-discovers and runs both styles transparently:

| Style | When to use |
|---|---|
| `unittest.TestCase` subclasses with `self.assertX(...)` | Legacy — most v1.1.x tests are this style. **Don't rewrite working tests.** |
| Plain `def test_x():` + `assert ...` | **Preferred for all new tests** — shorter, better failure messages, parametrize cleanly |

### New-test template

```python
import pytest
from core.parser.parser import parse


def test_title_url_becomes_entry():
    result = parse("", title="https://zoom.us/j/123")
    assert result.mode == "smart"
    assert len(result.entries) == 1


@pytest.mark.parametrize("input,expected_mode", [
    ("",                              "none"),
    ("+CalFlow+\nopen x",             "plus"),
    ("https://zoom.us",               "smart"),
    ("'+CalFlow+\nopen x",            "plus"),   # v1.1.5 quote-tolerant
])
def test_mode_detection(input, expected_mode):
    assert parse(input).mode == expected_mode
```

### Fixtures vs setUp / tearDown

For new tests use `@pytest.fixture` instead of `setUp` / `tearDown`:

```python
@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    # Isolated state.json per test, no global cleanup needed.
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("config.config.STATE_PATH", str(state_file))
    yield state_file
```

---

## Layered test organization

Tests are split by layer, not by feature. Each layer has its own
`test_v2_*.py` file.

| Layer | File | What it covers |
|---|---|---|
| **Spec conformance** | `test_v2_spec.py` | The DSL spec — every documented behaviour must be covered here. Authoritative. |
| **Parser** | `test_v2_parser.py`, `test_v2_*_parser.py` | Parser produces the right AST for given input |
| **Validator** | `test_v2_validator.py` | Validator catches bad syntax before AST construction |
| **Resolver** | `test_v2_resolver.py` (TBD) | Tag → param resolution |
| **Executor** | `test_v2_executor.py` | Command dispatch, with mocked side effects |
| **Backends** | `test_v2_app_control.py`, `test_v2_window.py`, `test_v2_autofill.py` | macOS subprocess / osascript shape checks |
| **Daemon smoke** | `test_v2_daemon_smoke.py` | End-to-end daemon main() with mocked IO. Catches glue regressions. |
| **Regression locks** | `test_v2_unknown_alias.py`, `test_v2_quote_tolerant_header.py`, etc. | Specific bugs that must never come back. |

### When you fix a bug

1. **Add a regression test in `tests/test_v2_<topic>.py`** that fails on the current code.
2. Fix the code.
3. Verify the new test passes.
4. Comment-tag the test with the version that introduced it (`# v1.1.X — …`).

---

## Coverage philosophy

We don't chase a coverage percentage. Aim for these signals instead:

- **Every public function** has at least one unit test on its happy path.
- **Every documented behaviour** in `docs/DSL_SPEC.md` is covered in `test_v2_spec.py`.
- **Every fixed bug** has a regression test that would have caught it.
- **Every cross-layer integration** (parser → executor) has a smoke test.

If a test would only catch the same bug as another test, delete the duplicate.

---

## Tests that mock IO

Several test files patch the IO boundary:

```python
from unittest.mock import patch

with patch("runtime.actions.browser.open_target", side_effect=...):
    ...
```

In pytest style, prefer `monkeypatch` from the fixture:

```python
def test_open_routes_correctly(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "runtime.actions.browser.open_target",
        lambda **kw: captured.append(kw),
    )
    # ...
    assert captured[0]["url"] == "https://example.com"
```

`monkeypatch` auto-undoes after the test, no `with` block, no teardown.

---

## CI

`.github/workflows/ci.yml` runs on every push and PR:

- Tests on Python 3.10, 3.11, 3.12 (matrix)
- `ruff check` + `ruff format --check` (advisory while codebase is being cleaned up)

Local pre-commit hooks run the same checks before each commit. Install once:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

---

## Related docs

- [`docs/DSL_SPEC.md`](DSL_SPEC.md) — what the test suite is asserting against
- [`docs/QA.md`](QA.md) — manual QA recipes for things tests can't cover
- [`docs/menubar_readiness.md`](menubar_readiness.md) — future test surfaces
