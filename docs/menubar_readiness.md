# 🍎 Menubar Companion — Architectural Readiness

This document is **planning only** — no menubar app is being built yet.
The goal is to make sure the v2.0 architecture doesn't paint us into a
corner when the menubar app does land.

The menubar app will be a thin GUI shell. The actual logic must live in
the existing Python packages, exposed as **library-callable APIs** that
the GUI layer (e.g. `rumps`, `PyQt`, or a Swift app shelling out to
Python) can drive.

---

# 1. Feature audit (per the 8 requested features)

| # | Feature | What exists today | What's missing for the GUI |
|---|---------|-------------------|----------------------------|
| 1 | Welcome screen | static text in `cli/onboarding.run_onboarding()` | content extraction (see §3.1) |
| 2 | Connect Google Calendar | `infra.calendar.calendar_client.build_service()` runs OAuth | OAuth callback URL is `localhost:0` — works headless. Need a `connection_status() → dict` accessor. |
| 3 | Select calendars | `cli.onboarding.ensure_calendar_selection(service)` | currently uses `input()` for picking; need a headless `list_calendars(service) → list[dict]` + `set_selected_calendars(ids)` pair |
| 4 | Change settings | `config/settings.py` is a Python module, hand-edited | need a JSON overlay (`data/user_settings.json`) and a settings-reader API that merges Python defaults + JSON overrides |
| 5 | Change status (Running / Paused / Stopped) | `cli/onboarding.{start,stop,restart,status}_launchd()` | need a unified `daemon_status() → {state, pid, last_run, next_run}` accessor |
| 6 | Test +CalFlow+ script | `core.parser.parser.parse(text)` + `runtime.command_executor.execute_commands(...)` | already library-callable; just needs a `dry_run(text) → ExecutionTrace` that returns what would happen instead of doing it |
| 7 | List upcoming events + manual run | `infra.calendar.calendar_client.get_upcoming_events()` works; `cli/main.py::main()` is the trigger logic but coupled to its own state loop | need `list_upcoming(calendar_ids, hours) → list[Event]` + `run_event(event_id) → ExecutionTrace` extracted from `main()` body |
| 8 | Tip the developer | trivial — `webbrowser.open(URL)` | none |

---

# 2. Big-picture architectural moves

These are the **only structural changes** the menubar future asks of us.
None require giving up the v2.0 architecture; they're additive.

## 2.1 Split `cli/onboarding.py` → headless logic + interactive prompts

Today every onboarding step bundles `print()`/`input()` with the
actual work. The menubar will need the work without the prompts.

**Recommended structure (when we do it):**

```
cli/onboarding.py                 # CLI entry — keeps the prompts
core/onboarding/
    google_oauth.py               # ensure_credentials_logic(json_str)
    calendar_select.py            # list_calendars(svc), save_selection(ids)
    daemon_install.py             # install_launchd(interval), uninstall_launchd(full)
```

The CLI version becomes a thin wrapper that handles I/O and calls
`core/onboarding/*`. The menubar imports `core/onboarding/*` directly.

**No change needed for v2.0.1** — flag this for v2.x.

## 2.2 Add a JSON settings overlay

`config/settings.py` stays as the **default** (Python module, version-
controlled). Add `data/user_settings.json` as the **overlay**
(written by the menubar's "Change Settings" pane, not committed).

```python
# config/settings.py — last 5 lines
from .runtime_overlay import apply_overlay
apply_overlay(globals())   # mutates module globals from data/user_settings.json
```

This keeps the existing `from config.settings import …` API unchanged.
The menubar writes JSON; on next import (or after the daemon restarts)
the override takes effect.

**Estimated effort**: ~50 lines, can ship in v2.0.2.

## 2.3 Extract the per-event run from `cli/main.py::main()`

The menubar's "manually trigger this event" feature wants a function
like:

```python
def run_event(event: dict, debug: bool = False) -> ExecutionTrace:
    """Run a single calendar event through the v2.0 pipeline.
    Returns a trace dict (mode, commands run, errors, timestamps)."""
```

The current `main()` is a loop that does fetch + filter + dispatch.
The body of the inner loop (`for event in events: ...`) is what we
want to factor out.

**Estimated effort**: ~30 lines + an `ExecutionTrace` dataclass.
Can ship in v2.0.2.

## 2.4 `dry_run(text) → ExecutionTrace` for the script tester

```python
def dry_run(text: str, *, title: Optional[str] = None) -> ExecutionTrace:
    """Parse + resolve `text`, but DON'T execute side effects.
    Returns what would have happened, including resolved params,
    bundle expansions, and dynamic substitutions."""
```

Useful for the menubar's "Test +CalFlow+ script" pane and for the REPL.
The pieces all exist — `parse()` returns the AST, `resolve_command()`
returns the param dict — we just need to bundle them into a trace
without invoking `runtime.command_executor.execute_commands()`.

**Estimated effort**: ~40 lines + dataclasses. Can ship in v2.0.2.

## 2.5 Daemon status accessor

Today `cli.onboarding.status_launchd()` prints the status. The menubar
needs it as data:

```python
def daemon_status() -> dict:
    return {
        "loaded":     bool,                 # is the plist loaded?
        "running":    bool,                 # is a process active?
        "pid":        Optional[int],
        "last_exit":  Optional[int],
        "interval":   int,                  # from data/daemon.json
        "next_run":   Optional[datetime],
    }
```

`launchctl list com.calflow` already returns enough info to populate
this. Wrap the existing logic into a return-rather-than-print function.

**Estimated effort**: ~25 lines. Can ship in v2.0.2.

---

# 3. What the menubar app is responsible for

(Not us — the menubar layer.)

- Cocoa / SwiftUI / `rumps` shell
- Status item icon and color (Running = green, Paused = yellow, Stopped = grey)
- Native sheets / windows for each pane
- Calling the headless Python APIs (subprocess or direct import)
- Persisting the menubar's own preferences (e.g. "show last-run timestamp")

---

# 4. Concrete API contract the menubar will rely on

These names are **provisional**; they're what we'll commit to when the
menubar build starts. Documented here so future PRs don't accidentally
break them.

```python
# core/onboarding/google_oauth.py
def has_credentials() -> bool: ...
def save_credentials_from_json(json_str: str) -> None: ...
def has_token() -> bool: ...
def run_oauth_flow() -> None: ...

# core/onboarding/calendar_select.py
def list_calendars(service) -> list[dict]: ...
def get_selected_calendars() -> list[str]: ...
def save_selected_calendars(ids: list[str]) -> None: ...

# core/onboarding/daemon_install.py
def install_launchd(interval_seconds: int) -> None: ...
def uninstall_launchd(full: bool = False) -> None: ...
def daemon_status() -> dict: ...

# core/runner.py  (extracted from cli/main.py)
def list_upcoming(calendar_ids: list[str], hours: int = 2) -> list[Event]: ...
def run_event(event: Event, debug: bool = False) -> ExecutionTrace: ...
def dry_run(text: str, title: str | None = None) -> ExecutionTrace: ...

# core/settings_overlay.py
def load_overlay() -> dict: ...
def save_overlay(overrides: dict) -> None: ...
```

---

# 5. What we should NOT do now

- **Don't import `rumps` or any GUI lib** anywhere in v2.0 packages.
- **Don't add menubar-only fields to ParseResult / BaseCommand** — keep
  the AST runtime-agnostic; the menubar can map AST → display however
  it wants.
- **Don't move `cli/onboarding.py` yet** — refactor when the menubar
  build actually starts; meanwhile the daemon must keep working.

---

# 6. Quick win we CAN do in v2.0.2

Without building any GUI, we can already extract `dry_run()` and the
status accessor. Both improve the **REPL** today:

- `:dry` REPL command that prints the ExecutionTrace without running
- `:status` REPL command that prints `daemon_status()` JSON

Both are zero-dependency and prove the APIs work end-to-end before the
menubar layer arrives.

---

# 7. Permission UX — assisted grants (v1.1.9+ memo)

Two macOS permission flows currently friction the CLI experience and
need a first-class menubar pane when it lands:

## 7.1 Accessibility for `/usr/bin/osascript`

CalFlow needs the **Accessibility** TCC bucket (separate from
**Automation / Apple Events**) for any verb that reads or writes
window geometry:

| Verb | Needs |
|------|-------|
| `hide @app`, `hide all`, `close @app`, `close all` | Apple Events to System Events (Automation) — ✅ usually granted on first prompt |
| `hide display(N)` | **Accessibility** — needs the explicit per-binary grant |
| `focus @app display(N)` | **Accessibility** |
| Future click / type / press backends (v2.x) | **Accessibility** |

The CLI's v1.1.9 onboarding step opens System Settings to the
Accessibility pane and gives copy-pasteable steps:

  1. Click [+]
  2. ⌘⇧G to type a path
  3. Paste `/usr/bin/osascript`
  4. Toggle ON

The menubar should:

- **Detect missing Accessibility on launch** by probing one cheap AX
  read (e.g. `position of front window of process "Finder"`). If it
  errors with `assistive access`, show a banner with a "Grant…" button
  that opens the Accessibility pane via the
  `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`
  URL.
- **Offer to add osascript automatically** — the URL above scrolls the
  user there but doesn't add the binary. macOS doesn't let third-party
  apps add entries to Accessibility; the user must click [+] themselves.
  Provide a one-screen tutorial with screenshots / a short loom.
- **Re-probe periodically** so the banner clears when permission is
  granted, no app restart required.

## 7.2 Menu-bar app hide nuance + cross-display app windows

`hide @app` (and the per-display variant) sets `visible of process` to
false. For a normal app this hides every window. For a **menu-bar-
resident app** (BetterDisplay, Shottr, Bartender, Bitwarden, etc.) the
menu-bar item itself isn't a "window" — and any popover or settings
window the app currently has open won't always go away with
`set visible to false`.

Observed in the wild (v1.1.8 QA pass):

```text
hide display(1)
→ everything on display 1 hidden EXCEPT BetterDisplay's settings popup
  (BetterDisplay is a menu-bar app)
```

### Cross-display apps (v1.1.10 QA pass)

Same scenario, different cause: an app whose **main window is on
display 2** but whose **Settings panel was just opened on display 1**:

```text
hide display(1)
→ cmux NOT hidden (main window on display 2; Settings panel on display 1)
→ kept = [..., cmux, ...]
```

Cause: `p.windows()` from System Events typically returns top-level
NSWindows only. NSPanel-derived Settings windows (AXSheet / AXPanel)
are often filtered out. So our centre-test only checks the main
window's position, finds it on display 2, and keeps the app — even
though visually the user has a panel open on display 1.

Two fixes to evaluate (post v1.1.10 diagnostic):
  - **Deep AX traversal** (`entire contents of process`) to enumerate
    AXSheets / AXPanels alongside windows. Costs latency; risks
    false-matching invisible AX containers.
  - **Filter by AXSubrole** (`AXSystemDialog`, `AXFloatingWindow`) and
    add to the window list. Lower false-positive risk; may miss
    unusual app architectures.

Either way, `hide display(N)` operates at the **app** level — when an
app qualifies, the WHOLE app is hidden, including its windows on
other displays. Per-window hide (just hide the panel on display 1,
keep the main window on display 2 visible) requires much more
invasive AX writes and is deferred to v2.x.

When the menubar app is built we should:

- Detect menu-bar-only apps via `LSUIElement` in their `Info.plist`
  and surface them differently in the picker (separate "menu-bar apps"
  section).
- For `hide`, also try `tell application "<X>" to close every window`
  before / instead of `set visible`. Falls back gracefully on apps
  that don't expose `close window`.
- Consider an explicit `close popups` verb for power users who want
  to clear settings panes without quitting menu-bar agents.

## 7.3 Future Apple Events / Automation auto-prompt

Some operations (like quitting a not-yet-running app) trigger the
Automation prompt the first time. The menubar can pre-warm by issuing
a no-op Apple Event (`tell application "X" to get name`) for each
known TARGET app on first run, so users approve all required apps in
one batch rather than one prompt per script execution.

## 7.4 Missed-events pane (sleep-recovery surface)

CalFlow's daemon trigger window is:

    [event_time − ALERT_OFFSET − EARLY_TOLERANCE,
     event_time − ALERT_OFFSET + GRACE_SECONDS]

…with defaults `ALERT_OFFSET=300s`, `EARLY_TOLERANCE=30s`,
`GRACE_SECONDS=600s` — so the daemon catches events firing in a
roughly 10½-minute window centred 5 minutes before start.

**Sleep gap:** if the lid is closed before that window opens and the
laptop wakes after it closes, the event is **silently skipped**. There's
no backfill — `get_upcoming_events()` only queries `[now, now+
FETCH_WINDOW_HOURS]`, and the trigger window check (`cli/main.py:185`)
runs **before** `is_done()`, so missed events never reach the state
check that could resurrect them.

This is invisible to the user today — they only notice when "the thing
didn't open."

**The menubar should expose a "Missed events" pane:**

- Default look-back window: **past 12 hours** (configurable; long
  enough to cover an overnight sleep, short enough that the list
  doesn't become noise after a long weekend).
- Source data: re-query Google Calendar with `timeMin=now-12h`,
  `timeMax=now`. (Existing `get_upcoming_events` is forward-only;
  add a sibling `get_recent_events(hours)`.)
- Filter to events where:
    - the description has a `+CalFlow+` block OR at least one Smart-
      mode URL, AND
    - the trigger window has already closed (`now > event_time +
      GRACE_SECONDS - ALERT_OFFSET`), AND
    - the event is NOT in `state["done"]` (so we don't surface things
      that DID fire).
- Each row shows:
    - title + scheduled start
    - parsed mode (Smart / Plus) + verb count
    - `[Run now]` button → calls the same `run_event(ev)` dry-runnable
      entry point the menubar will use for manual triggers (§2.3).
    - `[Dismiss]` → marks done in state without executing, suppresses
      future surfacing.
- Background ping every ~5 min while the menubar is open so the list
  refreshes without the user clicking around.

**Why a manual "Run now" button instead of auto-firing on wake:**

- Some events are time-bound (a 9 AM standup is irrelevant at 10 AM).
- Auto-firing missed events on wake violates the principle of least
  surprise — the user expects "the calendar event opened my Zoom
  link" to mean "right around the meeting time", not "any time the
  laptop comes back".
- The pane gives the user agency: see what was missed, decide what's
  still useful, click through.

Lightweight CLI fallback (could ship before the menubar):
`python3 -m cli.main missed [--hours 12]` listing the same data and
offering an interactive `[r]un / [d]ismiss / [s]kip` prompt per row.

---

# 💡 Principle

> **The menubar is a view layer. Make every action it needs callable
> as a Python function returning data, not stdout.**
