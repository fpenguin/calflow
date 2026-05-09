---
name: smoke-test-pattern
description: |
  Daemon-style integration smoke tests. Apply when adding a new pipeline
  path that crosses ≥3 layers (parser → resolver → executor → action).
---

# Smoke test pattern

## What it tests

Glue between layers, not units. Mocks the IO boundary; runs everything
in between for real; asserts on the boundary calls.

```
fetch (Google API) ──┐
calendar list ───────┼──► main() ──► open_target / execute
state I/O ───────────┘                  (captured)
```

## Where it goes

`tests/test_v2_daemon_smoke.py`. New cases extend the existing pattern.

## Established pattern (the v1.1.24 harness)

```python
class _DaemonHarness:
    def __init__(self, events: list, prior_state: dict = None):
        self.events = events
        self.opens = []
        self.state = prior_state or {}
        self._patchers = []

    def __enter__(self):
        # Mock IO boundaries
        self._patch("cli.main.build_service", return_value=object())
        self._patch("cli.main.get_selected_calendars", return_value=["test"])
        self._patch("cli.main.get_upcoming_events",
                    side_effect=lambda *a, **kw: list(self.events))
        self._patch("cli.main.load_state", return_value=self.state)
        self._patch("cli.main.save_state", side_effect=lambda *a, **kw: None)
        # Capture action layer
        self._patch("runtime.executor.open_target",
                    side_effect=lambda **kw: self.opens.append(kw))
        self._patch("runtime.command_executor.open_target",
                    side_effect=lambda **kw: self.opens.append(kw))
        # Skip waits
        self._patch("time.sleep", side_effect=lambda *a, **kw: None)
        for p in self._patchers: p.start()
        return self

    def __exit__(self, *_):
        for p in self._patchers: p.stop()
```

## Required mock list (for daemon path)

- Calendar IO: `build_service`, `get_selected_calendars`, `get_upcoming_events`
- State IO: `load_state`, `save_state`, optionally `is_done` / `mark_done`
- Action layer: `open_target` (both `runtime.executor` and
  `runtime.command_executor` import sites)
- Side-effects: `trigger_autofill`, `take_screenshot`
- `time.sleep` to keep the test fast

## Sandbox-friendliness

The smoke tests stub `sys.modules['google.auth']` etc. at the top of the
file so they run even without google-auth installed. See
`tests/test_v2_daemon_smoke.py` for the canonical stub block.

## When to add a new smoke test

ANY new public function in `runtime/actions/` that's reachable from the
daemon path must have a smoke case asserting it's actually called for a
representative input. Unit tests of the function alone are not enough —
v1.1.23 proved unit tests can all pass while the daemon never calls the
function.
