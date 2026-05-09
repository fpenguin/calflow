---
name: no-silent-fallthrough
description: |
  Every reject / skip path in CalFlow MUST log an actionable hint.
  Never `return None` silently when input was clearly intended to do
  something. The user must be able to read the log and know what to fix.
---

# No silent fallthroughs

## Rule

If a function rejects, skips, or fails to act on a non-trivial input, it
MUST log a `[WARN]` describing both:
- What it received (inputs verbatim)
- What it expected (or how to fix the input)

## Examples (do)

```python
# v1.1.19 — when a layout tag doesn't parse
log(f"[WARN] Unrecognised layout tag {tag!r} — expected "
    f"`#grid(<cell>@<cols>x<rows>)`, e.g. #grid(1@3x2)")

# v1.1.14 — when an alias resolves to nothing
log(f"[WARN] Unknown @alias {token!r}; treating as a literal "
    f"app name ({literal!r}). Add it to TARGETS in "
    f"config/settings.py to silence this warning.")

# v1.1.21 — when grid layout is malformed
log(f"[WARN] {tag!r} uses the legacy grid order — canonical is "
    f"`#grid(<cell>@<cols>x<rows>)` (v1.1.19+). Interpreting "
    f"as #grid({m.group(3)}@{m.group(1)}x{m.group(2)}).")
```

## Anti-pattern (don't)

```python
# ❌ Silent — user has no idea why nothing happened
def parse_layout_tag(tag):
    if not tag:
        return None
    m = _GRID_RE.match(tag)
    if not m:
        return None  # silent failure
    ...

# ❌ Same shape — empty parse with no diagnostic
def extract_url_entries(text, title=None):
    if not text:
        return []   # what about title?
```

## Past costs

- v1.1.21: parser short-circuit silently dropped title-only events.
  10+ minutes of debugging, then a fix.
- v1.1.19: malformed `grid()` returned `None` with no warning.
  User couldn't tell their syntax was wrong.

## Format conventions

```
[WARN] <action>: <observed input>; <hint or expected form>
```

The hint should be actionable — name the file or doc reference, or the
literal correct form. Don't say "invalid syntax" without saying what
WOULD be valid.

## Where this rule applies

- Every parse / validate / resolve function
- Every action backend (`runtime/actions/*`)
- Every executor dispatch case (no `_dispatch(unknown)` without a warn)
- Every config-load step
- Every state-load corruption recovery

## Where this rule does NOT apply

- Pure-data utilities (`_strip_quotes`, `_unquote`, `_classify_primary`) —
  these have well-defined return values for all inputs.
- Internal helpers prefixed with `_` (caller has the context).
- Test fixtures and mocks.
