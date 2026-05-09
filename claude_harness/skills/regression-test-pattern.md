---
name: regression-test-pattern
description: |
  How to write a regression test that locks a fixed bug into the suite.
---

# Regression test pattern

## File location

| Bug class | File |
|---|---|
| Parser / DSL syntax | `tests/test_v2_spec.py` or `tests/test_v2_parser.py` |
| Validator rejection | `tests/test_v2_validator.py` |
| Resolver / runtime targets | `tests/test_v2_runtime_targets.py` |
| Smart Mode entry extraction | `tests/test_v2_title_url_entries.py` |
| Daemon glue / cross-layer | `tests/test_v2_daemon_smoke.py` |
| Backend behaviour (osascript) | `tests/test_v2_app_control.py` etc. |
| Test redundancy / suite hygiene | (no regression tests; audit-driven) |

If the bug crosses layers, add tests at EACH layer plus a smoke test.

## Naming and tagging

```python
# v1.1.X — regression for: <one-line symptom>
#
# Bug report: <link or quote of user's reproduction>
# Root cause: <the actual fault, in one sentence>
def test_<symptom_in_snake_case>():
    ...
```

The `# v1.1.X — regression` comment is mandatory. It tells future readers
why this test exists and prevents it from being deleted in a future
"clean up the suite" pass.

## Style

- Plain `assert` (pytest-friendly) for new files
- One assertion per behaviour
- Generic placeholders for URLs / titles (`https://example.com`, `Standup`)
  — never the user's real data from the bug report

## Verify the test FAILS first

```bash
pytest tests/test_v2_<file>.py::test_<symptom> -v
# expected: FAILED
```

Only then make the fix. The test should go GREEN with no other change.

## Examples in the codebase

- `tests/test_v2_unknown_alias.py` — locks v1.1.14 (catastrophic hide-everything)
- `tests/test_v2_quote_tolerant_header.py` — locks v1.1.5 / v1.1.6 (Excel apostrophe)
- `tests/test_v2_daemon_smoke.py::test_title_url_event_with_empty_body_fires` — v1.1.23
