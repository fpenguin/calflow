# CalFlow menubar companion (v1.3.x)

A native macOS menubar app that surfaces today's events, missed events
in the last 12 h, lifetime stats, one-click "Run now" buttons, an
interactive Recipes editor, and an editable Settings page.

## Version timeline

- **v1.3.0** — popover (status, upcoming, missed, stats).
- **v1.3.1** — Recipes window (3-col: categories / list / sandbox) and
  Settings window (2-col, read-only display).
- **v1.3.2** — Singleton lock + interactive Settings (Apply writes back to
  `config/settings.py`, with backup, validation, launchd-safe handling).
- **v1.3.3** — Pages render structure on boot before bridge resolves
  (no more blank panes during slow subprocess starts).
- **v1.3.4** — Diagnostics panel + clearer Apply feedback (Saving… toasts,
  longer timeouts, in-page bridge log).
- **v1.3.5** — Bridge response routing fix: each WKWebView now receives
  its own responses (was previously routing every reply to the popover,
  causing Settings/Recipes promises to hang).
- **v1.3.6** — Native daemon control: Auto-start toggle and the Pause /
  Restart buttons actually run `launchctl` instead of printing copy-this
  hints. CLAUDE.md's "no auto launchctl" rule applies to the AI agent;
  a UI button is explicit user approval.
- **v1.3.7** — Settings audit: removed Show menu bar icon / Theme rows,
  removed Notifications section, real permission probes (Accessibility,
  Apple Events, Google account email from token).
- **v1.3.8** — **Apply & restart** combined button (replaces "Restart
  daemon now"); native folder picker for the screenshot directory;
  copyable Python binary path for manual Accessibility grant.
- **v2.0.2-dev** — LaunchAgent lifecycle commands for the menu bar
  companion (`menubar-install`, `menubar-start`, `menubar-stop`,
  `menubar-status`, `menubar-uninstall`).
- **v2.0.2-dev** — Dynamic month/day menu bar icon with Calendar Plus
  fallback.
- **v2.0.3-dev** — Dynamic popover sizing (shrinks to content;
  timeline and missed-events sections get internal scroll if they
  overflow 320 px).

## Install / Run

Recommended:

```bash
python3 -m cli.main menubar-install
python3 -m cli.main menubar-status
```

`menubar-install` writes and loads:

```text
~/Library/LaunchAgents/com.calflow.menubar.plist
```

A dynamic date icon appears in the menu bar, showing the current month
and day, e.g. `JUN` over `3`. Click it to open the popover. The
approved Calendar Plus icon is the fallback if dynamic rendering fails.
The menu bar companion is separate from the background daemon:

- `python3 -m cli.main start|stop|restart|status` controls the calendar
  automation daemon (`com.calflow`).
- `python3 -m cli.main menubar-start|menubar-stop|menubar-status`
  controls the visible menu bar companion (`com.calflow.menubar`).

Developer foreground run:

```bash
python3 -m cli.main menubar
```

This also shows the date icon, but only while that process stays running.

The CLI keeps working when the menubar deps aren't installed:

```bash
$ python3 -m cli.main menubar
{
  "error": "menubar deps missing: No module named 'AppKit'",
  "install": "pip install rumps pyobjc-framework-WebKit pyobjc-framework-Cocoa"
}
```

## Singleton lock (v1.3.2)

Only one menubar instance can run at a time. A second
`python -m cli.main menubar` sees the existing PID at
`/tmp/calflow_menubar.lock` and exits cleanly with a message:

```
CalFlow menubar is already running (PID 12345).
  • To stop it:    pkill -f 'cli.main menubar'
  • To replace it: pkill -f 'cli.main menubar' && python -m cli.main menubar &
```

Stale locks (process dead OR > 7 days old) are silently overwritten.

## Architecture

```
NSStatusItem          ←  cli/menubar.py
   │ click
   ▼
NSPopover (transient) ──── popover.html  (status / upcoming / missed / stats)
   │
   │ "Recipes" / "Settings" footer button
   ▼
NSWindow (resizable) ──── recipes.html   /   settings.html
   │
   ▼
WKScriptMessageHandler   ◄── shared by all webviews; v1.3.5 routes
   │  routes op           replies to the originating webview
   ▼
subprocess: python -m cli.main {status|stats|upcoming|missed|run-event|
                                recipes|save-recipe|delete-recipe|
                                run-script|settings|apply-settings|
                                daemon-start|daemon-stop|daemon-restart|
                                menubar-start|menubar-stop|menubar-status|
                                open-system-prefs|edit-settings-file} --json
   │  stdout JSON
   ▼
evaluateJavaScript("window.cf_resolve(id, payload)")
   │
   ▼
JS Promise resolves → re-render
```

Popover refresh runs on open and every 30 seconds while it's open. The
Settings and Recipes windows refresh on every show via `cf_onShow()`.

The popover is dynamically sized (v2.0.3-dev). Every `render()`
schedules `resizePopover()` (100 ms debounced), which reads
`document.body.scrollHeight` inside a `requestAnimationFrame` and
calls the `resize-popover` bridge op. Python clamps the requested
height to `[_POPOVER_MIN_H, _POPOVER_MAX_H]` and applies it via
`NSPopover.setContentSize_` + `WKWebView.setFrame_`. Width stays
canonical at `_POPOVER_W` so the menubar-arrow anchor doesn't shift.
The `.timeline-card` and `.missed-card` sections scroll internally
past 320 px to keep the popover's height-clamp lean.

## JSON API

All endpoints print one JSON object to stdout, exit 0 on success.

### Status / events

| Subcommand | Since | Notes |
|------------|-------|-------|
| `cli.main status --json` | v1.1.27 | Daemon state + next event + version |
| `cli.main stats --json` | v1.3.0 | Lifetime action counter + time saved |
| `cli.main upcoming --json [--hours N]` | v1.3.0 | Default 24 h |
| `cli.main missed --json [--hours N]` | v1.3.0 | Default 12 h, most recent first |
| `cli.main run-event <id> --json` | v1.3.0 | Manual run-now overrides idempotency |

### Recipes (v1.3.1)

| Subcommand | Notes |
|------------|-------|
| `cli.main recipes --json` | Stock catalog + user recipes |
| `cli.main save-recipe` | Reads JSON payload from **stdin** |
| `cli.main delete-recipe <id>` | Returns `{"ok": false, "error": "id not found"}` for unknown ids |
| `cli.main run-script` | Executes a literal script body from **stdin** through the parser → executor pipeline |

The script body is **never logged** — only `[INFO] Sandbox run from
menubar Recipes window`. Same execution surface as a calendar event;
no new permissions.

### Settings (v1.3.2 / v1.3.7)

| Subcommand | Notes |
|------------|-------|
| `cli.main settings --json` | Beginner-friendly view; runs Accessibility + Apple Events probes |
| `cli.main apply-settings` | Reads JSON `{ui_key: value}` from **stdin**, writes via the whitelist |
| `cli.main edit-settings-file` | Opens settings.py in the user's default editor |

### Daemon control (v1.3.6)

| Subcommand | Notes |
|------------|-------|
| `cli.main daemon-start` | `launchctl load -w …com.calflow.daemon.plist` |
| `cli.main daemon-stop` | `launchctl unload -w …com.calflow.daemon.plist` |
| `cli.main daemon-restart` | stop + start in sequence |
| `cli.main pause` / `cli.main resume` | Back-compat aliases for `daemon-stop` / `daemon-start` |

### Menu bar lifecycle (v2.0.2-dev)

| Subcommand | Notes |
|------------|-------|
| `cli.main menubar-install` | Writes the LaunchAgent and starts the icon now + at login |
| `cli.main menubar-start` | Loads the existing LaunchAgent; creates it if missing |
| `cli.main menubar-stop` | Unloads the LaunchAgent; icon disappears |
| `cli.main menubar-restart` | Stop + start |
| `cli.main menubar-status` | JSON status, plist path, logs, lock PID, and icon label |
| `cli.main menubar-uninstall` | Unloads and removes the LaunchAgent |

Daemon controls return `{"action": "...", "ok": true, "loaded_after": bool}`
or `{"ok": false, "error": "..."}`. The popover's Pause button uses
`loaded_after` to reconcile its optimistic UI flip with the real
daemon launchctl state.

Menu bar lifecycle commands return the LaunchAgent status object:
`loaded`, `raw_line`, `plist_path`, `lock`, `stdout_log`, and
`stderr_log`.

### Permissions / OS deep-links (v1.3.7)

| Subcommand | Notes |
|------------|-------|
| `cli.main open-system-prefs <pane>` | `pane` ∈ `accessibility / automation / appleevents / calendar` |

Used by the Settings page to deep-link into Privacy & Security panes
via `x-apple.systempreferences:` URLs. Falls back to opening the root
Privacy & Security pane on unknown panes.

## Settings writes

The Settings window's **Apply & restart** button writes user changes
back to `config/settings.py` and (when a settings.py value actually
changed) restarts the daemon so it picks up the new value immediately.

- A whitelist (see `core.settings_writer.EDITABLE_SETTINGS`) defines
  which UI keys are writable. Non-whitelisted keys are rejected with
  `"not editable from UI"`.
- Each value is type-coerced + range-checked + (for strings)
  quote/newline-stripped *before* any disk write.
- A backup is created at `config/settings.py.bak` on every successful
  write batch.
- Launchd-controlled toggles (`Auto-start at login`) **execute natively**
  via `launchctl load -w` / `unload -w` (v1.3.6 — was a copy-this-into-
  Terminal hint in v1.3.2-v1.3.5).
- Bool toggles backing string settings (e.g. `Autofill on open` ↔
  `AUTOFILL_MODE`) are auto-mapped via `from_bool: True` in the spec.

### Editable keys (v1.3.7)

| UI key                                  | settings.py constant      | Type / range |
|-----------------------------------------|---------------------------|--------------|
| events.open_minutes_early               | DEFAULT_ALERT_SECONDS     | int 0–60 min |
| events.fetch_window_hours               | FETCH_WINDOW_HOURS        | int 1–24 h |
| events.status_lookahead_h               | STATUS_LOOKAHEAD_HOURS    | int 1–168 h |
| title_links.open_mode                   | TITLE_URL_OPEN_DEFAULT    | tab / window |
| title_links.autofill                    | TITLE_URL_AUTOFILL_DEFAULT | none / fill / submit |
| passwords.provider                      | AUTOFILL_PROVIDER         | apple / 1password / bitwarden / default |
| passwords.autofill_on_open              | AUTOFILL_MODE             | bool → "semi-auto" / "off" |
| advanced.trigger_grace_seconds          | GRACE_SECONDS             | int 0–3600 |
| advanced.early_tolerance_sec            | EARLY_TOLERANCE           | int 0–600 |
| advanced.max_urls_per_event             | MAX_URLS                  | int 1–50 |
| advanced.log_mode                       | LOG_MODE                  | stdout / stderr / both |
| advanced.plus_max_commands              | PLUS_MAX_COMMANDS         | int 1–200 |
| advanced.plus_inter_command_delay_sec   | PLUS_INTER_COMMAND_DELAY  | float 0–10 |
| advanced.plus_screenshot_dir            | PLUS_SCREENSHOT_DIR       | string (folder picker) |

UI-only daemon control (no settings.py write):

| UI key                          | What it does |
|---------------------------------|--------------|
| general.auto_start_at_login     | Runs `launchctl load -w` / `unload -w` |

### `cli.main apply-settings`

Reads a JSON object of `{ui_key: value}` from **stdin**:

```bash
echo '{"events.fetch_window_hours": 4, "advanced.log_mode": "stderr"}' \
  | python3 -m cli.main apply-settings
```

```json
{
  "applied":           ["events.fetch_window_hours", "advanced.log_mode"],
  "rejected":          [],
  "requires_terminal": [],
  "daemon_actions":    [],
  "backup_path":       "/Users/.../config/settings.py.bak"
}
```

Mixed payloads (some valid, some invalid, some launchd) are partially
applied — valid keys land on disk; rejected keys come back with reasons;
launchd keys produce a `daemon_actions` entry.

`requires_terminal` is empty in v1.3.6+ (kept for back-compat).

## Native bridge ops (no subprocess)

Some bridge ops are handled in-process by the menubar app itself.

| Op | Args | Returns | Notes |
|----|------|---------|-------|
| `pick-folder` | `{title?, prompt?, current?}` | `{ok, path}` | NSOpenPanel modal (v1.3.8) |
| `copy-to-clipboard` | `{text}` | `{ok}` | pbcopy fallback |
| `open-system-prefs` | `{pane}` | `{ok, opened}` | Deep-links via `x-apple.systempreferences:` |
| `show-recipes-window` / `show-settings-window` | — | `{shown}` | Lazy-create or focus secondary window |

## Stats: how time saved is calculated

Each successful executor action increments a counter in `data/stats.json`.
At display time, the counts are weighted by action type.

| Action key      | Seconds | What this represents |
|-----------------|---------|---------------------|
| `open_url`      | 5       | Open URL in default browser (Cmd+T + paste + Enter) |
| `open_profile`  | 8       | Open URL in specific browser/profile (extra clicks) |
| `arrange`       | 4       | Drag-snap a window to a half/grid cell |
| `hide`          | 2       | Cmd+H or click-away (also `close`) |
| `focus`         | 1       | Cmd+Tab cycle |
| `autofill`      | 8       | Password manager lookup + paste |
| `screenshot`    | 3       | Cmd+Shift+4 + drag + click |
| `wait`          | 0       | Doesn't save user time — not counted |

**Override the weights** in `config/settings.py`:

```python
STATS_ACTION_WEIGHTS = {
    "open_url":  10,    # If you find 5s undersells your situation
    "autofill":  15,
}
```

Partial dicts are fine — missing keys keep their default. Unknown keys
are ignored (we don't extend the weight surface from settings).

## Stats schema (`data/stats.json`)

```json
{
  "first_run_date": "2024-07-28T14:32:01+00:00",
  "actions_run":    12546,
  "actions_failed": 87,
  "by_type": {
    "open_url":     6500,
    "open_profile": 1500,
    "arrange":      2000,
    "hide":         1000,
    "focus":         300,
    "autofill":     1200,
    "screenshot":     46
  },
  "schema_version": 1
}
```

`first_run_date` is set on first executor call and never changed.
Atomic writes via tmp + os.replace; the daemon and the menubar may
interleave but worst case is a single lost increment per collision.

## Recipes window (v1.3.1)

3-column layout — categories sidebar / recipe list / sandbox playground.
Pick a stock recipe → tweak it → **Try it** runs it through the live
executor. **Save as mine** persists to `data/my_recipes.json`.

Keyboard:
- `⌘ S` — save (or save-as-mine if a stock recipe is selected)
- `⌘ ↵` — Try it (run the editor body)

Stock recipes live in `core/recipes.py::STOCK_RECIPES`. Add or remove
by editing that file; ids are stable so the user's "save as mine"
copies don't break. Bodies must be ≤ 8 lines so the editor preview
stays uncluttered.

## Settings window (v1.3.2 / v1.3.7 / v1.3.8)

2-column layout — left sidebar grouped under General / Behaviour /
Power user + scrollable right pane. Click a section in the left → the
right scrolls smoothly to the anchor; scroll-spy updates the sidebar
selection as you scroll.

Each row shows label + plain-language description + control. Edit any
toggle / dropdown / number / text field; the row turns amber with an
"edited" badge. The bottom action bar shows the dirty-count and
**Apply & restart** ↗ Discard.

**Apply & restart** in v1.3.8:
1. POSTs the dirty diff to `cli.main apply-settings`.
2. If any settings.py value actually changed, runs `daemon-restart` so
   the running daemon picks up the new value immediately.
3. Toast confirms `"Saved N changes · daemon restarted · backup at config/settings.py.bak"`.

If `Auto-start at login` was the only change, only the `launchctl`
toggle runs (no double restart).

## Native folder picker (v1.3.8)

The screenshot directory row in Advanced now shows a 📁 button next to
the text input. Clicking it opens `NSOpenPanel` for directory selection.
On pick: input updates, row marks dirty, Apply & restart commits.

## Permissions help (v1.3.8)

When `Accessibility` or `Apple Events` is **Denied** or **Unknown**:

- An **Open System Settings** button deep-links to the right Privacy
  pane via `x-apple.systempreferences:`.
- A **Python binary path** row appears below with the absolute path
  (e.g. `/Users/.../calflow/.venv/bin/python3`) and a **Copy** button —
  paste this into the System Settings + button if the OS hasn't
  auto-listed Python yet.

## Files

| File | Purpose |
|------|---------|
| `cli/menubar.py` | NSStatusItem + NSPopover + NSWindow + WKWebView + JS bridge |
| `runtime/menubar/popover.html` | The popover UI (CSS + JS, single file) |
| `runtime/menubar/recipes.html` | The Recipes window (v1.3.1) |
| `runtime/menubar/settings.html` | The Settings window (v1.3.2 / v1.3.7 / v1.3.8) |
| `runtime/menubar/__init__.py` | exports `POPOVER_HTML`, `RECIPES_HTML`, `SETTINGS_HTML` |
| `core/stats.py` | `ACTION_WEIGHTS`, `format_time_saved`, `compute_time_saved` |
| `core/recipes.py` | stock catalog + `data/my_recipes.json` store (v1.3.1) |
| `core/settings_writer.py` | `EDITABLE_SETTINGS` + `apply_settings()` (v1.3.2) |
| `state/stats_store.py` | `load_stats`, `save_stats`, `record_action`, `snapshot` |
| `tests/test_v3_menubar_stats.py` | Stats backend + JSON contract tests |
| `tests/test_v3_menubar_launchd.py` | Menu bar LaunchAgent lifecycle tests |
| `tests/test_v3_recipes.py` | Recipe catalog + my_recipes round-trip tests (v1.3.1) |
| `tests/test_v3_settings_writer.py` | Whitelist + validation + backup + bool-mapping tests (v1.3.2 / v1.3.7) |

## Roadmap (v1.3.9+)

Deferred from the v1.3.x audit:

- **Default browser editable**: add `DEFAULT_BROWSER_ALIAS` setting +
  parser change so URLs without `@target` route through it. Today
  unrouted URLs go to macOS's default browser.
- **TARGETS / aliases editor**: in-UI editor for adding / removing /
  editing the `@alias` → app(s) mapping. Today: edit `TARGETS` in
  settings.py manually.
- **Calendars-to-watch picker**: sub-window with checkboxes per Google
  calendar. Today: re-run `python -m cli.main setup`.
- **Blocked URL patterns** + **Ignored protocols** list editors.
- **Notifications** (sound on trigger, missed-event push) — needs the
  UserNotifications framework + permission grant flow.
- **Auto-trigger Accessibility prompt**: use
  `AXIsProcessTrustedWithOptions(prompt=true)` from PyObjC so macOS
  auto-adds Python to the Accessibility list. Requires
  `pyobjc-framework-ApplicationServices`.
