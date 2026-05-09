---
name: test-mock-currency
description: |
  Keep test mocks in sync with the real function signatures they fake.
  Apply when adding or changing keyword arguments to any function in
  `runtime/actions/`, `core/resolver/`, or anywhere with `monkeypatch`
  call sites.
---

# Mock signature currency

When you add a new keyword argument to a public function, EVERY mock
that fakes it must update too. Otherwise the mock silently drops the
new argument and tests pass while production paths are broken.

## How to find affected mocks

```bash
# 1. Identify the function
FUNC=open_target

# 2. Find every mock / fake / monkeypatch that names it
grep -rn "$FUNC" tests/

# 3. For each, verify the signature matches:
grep -A 2 "def fake_$FUNC\|def $FUNC" tests/
grep -A 2 "monkeypatch.setattr.*$FUNC" tests/
```

## Examples of mock patterns in this repo

```python
# Pattern 1: a fake module-level function
def fake_open(url=None, app=None, layout=None, display_spec=None,
              chrome_profile=None, new_window=False):
    captured.append({...})

# Pattern 2: a class with the same shape
class _Capture:
    def open_target(self, url=None, ..., new_window=False):
        self.opens.append({...})

# Pattern 3: monkeypatch lambda
monkeypatch.setattr(
    "runtime.actions.browser.open_target",
    lambda **kw: captured.append(kw),
)
```

Pattern 3 (`**kw`) is the most resilient — it accepts any future kwargs
without breaking. Pattern 1 / 2 (named args) are stricter but more readable.

## When you change a public function

1. Edit the real function's signature.
2. `grep -rn "<func_name>" tests/` to find every mock.
3. Update each mock signature so the new kwarg has a default value
   (so old test cases that don't pass it still work).
4. Run the suite. If a test breaks, the mock signature was incomplete.

## Past misses

- v1.1.20: adding `new_window=False` to `open_target` broke 3 mocks
  (`test_v2_executor.py`, `test_v2_dynamic.py`, `test_v2_no_cross_contamination.py`).
- v1.1.7: adding `chrome_profile=None` had a similar miss earlier.

The pattern is consistent: kwargs added to backend functions silently
break mocks that were written before the kwarg existed. Always grep
before declaring a backend change done.
