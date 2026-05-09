---
name: performance-budget
description: |
  Test suite + daemon performance budgets. CalFlow is a per-cycle daemon
  that runs every ~5 minutes; its budgets are tight.
---

# Performance budget

## Test suite

| Metric | Budget |
|---|---|
| Total runtime (`pytest tests/`) | <2 seconds for full suite |
| Per-test runtime | <50 ms typical, <200 ms hard cap |
| Slow markers | Use `@pytest.mark.slow` if a test takes >100 ms; skip in default run |

If a test exceeds the budget, the most likely cause is real I/O sneaking
in (subprocess, network, disk). Mock the boundary.

## Daemon (per-cycle)

| Phase | Budget |
|---|---|
| Calendar fetch (network) | up to 3 s (Google API) |
| State load + parse + dedup | <100 ms |
| Per-event parse | <5 ms |
| Per-event execution | up to 5 s (osascript subprocess) |
| Whole cycle | <30 s for typical 1–5 events |

The lock file's `MAX_RUNTIME = 180s` (3 minutes) backs this — anything
beyond that is treated as a stale lock.

## RAM

| Phase | Budget |
|---|---|
| Resident at idle | <40 MB |
| With Google API loaded | <60 MB |
| Peak during execution | <80 MB |

CalFlow is short-lived (one cycle = one process), so memory pressure
isn't a primary concern. But unbounded growth (a leak) over many cycles
would matter.

## Action backends

| Backend | Budget per call |
|---|---|
| `open_target` | <1.5 s (open + 0.8 s sleep) |
| `apply_layout` | <500 ms (osascript bounds set) |
| `hide_apps_on_display` | <2 s for ≤30 visible apps |
| `take_screenshot` | <500 ms (screencapture) |
| `trigger_autofill` | <300 ms (System Events keystroke) |

## Anti-patterns to avoid

- Per-call calls to `enumerate_displays()` (use the 30s cache)
- Loading full Google API client when only state-only operations are needed
- Pure-Python loops over event data when a list comprehension would do
- Spawning new osascript subprocesses for each window when a single
  multi-window script could batch them

## Measuring

```bash
# Test suite
time python -m unittest discover tests/    # expect <2s

# Daemon cycle (with debug)
time python -m cli.main --debug              # expect <30s
```

If a regression breaks budget, find it before merging.
