---
name: menubar-readiness
description: |
  Menubar app architecture readiness. Read before designing any GUI surface.
  Status: deferred — no GUI exists yet, but every backend should be
  library-callable so the menubar slots in cleanly when built.
---

# Menubar readiness

The future macOS menubar app is the primary GUI consumer. Every backend
in CalFlow should be **library-callable** (returns data, not side effects)
so the GUI can drive it.

## Authoritative document

`docs/menubar_readiness.md` contains:
- §1 Feature audit (what exists vs what's missing)
- §2 Architectural moves needed (split CLI from logic, JSON settings overlay,
  extract per-event run, dry-run API)
- §7 Permission UX (assisted Accessibility grants, menu-bar app hide nuance,
  Apple Events pre-warm)
- §7.4 Missed-events pane spec (12-hour look-back, manual run/dismiss)

Read those sections BEFORE designing any GUI feature.

## Library-callable principle

Every action that the menubar needs must be reachable as a Python function
returning data, not via stdout-printing CLI command.

```python
# ❌ Hard for the menubar to consume
def print_status_summary():
    print("🟢 CalFlow active...")

# ✅ The menubar can call this directly
def collect_status() -> Dict:
    return {"version": "...", "daemon": {...}, ...}

def print_status_summary():
    s = collect_status()
    # ... rendering
```

The v1.1.27 `cli.main status --json` is the canonical example.

## When to add a `--json` flag

Whenever a CLI command produces information the menubar will display:

- `cli.main status` → `--json` ✓ (v1.1.27)
- `cli.main display` → `--json` (TODO)
- `cli.main test` → `--json` (TODO; would dump the picker candidates)
- `cli.main missed` → `--json` (TODO; future v1.1.X)

Each `--json` output is a stable contract — version it via the
`version` field in the output.

## When the menubar work starts

The 8 features listed in `menubar_readiness.md §1` need their library-
callable APIs first. The Swift / SwiftUI layer comes second. Don't build
the Swift app until each capability is reachable from Python.

## Permission UX

The menubar has two permission dialogues to handle:
1. **Accessibility for /usr/bin/osascript** — covered by v1.1.9 onboarding
   step. Menubar version: probe-on-launch + banner with "Grant…" button.
2. **Apple Events to System Events** — covered by macOS first-prompt flow.
   Menubar version: pre-warm with no-op Apple Event for each TARGET app.

## Out of scope (until further notice)

- iOS / iPadOS apps (menubar is the priority)
- Cross-platform GUI (CalFlow is macOS-first)
- Web dashboard (file storage / settings sync is a v3.x concern)
