# 🗺️ CalFlow Roadmap (post-v2.0)

## What v2.0 ships (fully real, not stubbed)

- **Smart Mode** — every documented Smart Mode behavior is real:
  URL extraction (now including URLs with embedded `{…}` blocks),
  normalization, tag merging, global tag/target state with
  same-category-last-wins / cross-category-merge resolution, `##`
  comments, `#left/#right/#middle/#top/#bottom/#full/#area/#grid`
  layout parsing, `#display`, `#alert=Ns/Nm`, `#fill`/`#submit`/
  `#slow`/`#no-autofill`, title-URL whitelist, blacklist, map filter,
  protocol filter, `MAX_URLS` cap.
- **Dynamic expressions** — `{now > … > YYYY-MM-DD}` is real in
  **both Smart Mode and Plus Mode**. Bases (`now ± N{s,m,h,d,w,mo,y}`),
  transforms (`start_of_*`, `end_of_*` for day/week/month/year),
  format tokens (`YYYY/YY/MM/DD/HH/hh/mm/ss`), shorthand and
  `format("…")` forms, default `YYYY-MM-DD`, single `>` operator,
  whitespace tolerance.
- **Plus Mode parser, validator, resolver, dispatcher** — all 13
  verbs parse and route. `#grid(NxM@D)` and `#area(x,y,w,h)` parse
  to typed dicts.
- **Calendar layer** — multi-calendar polling, OAuth flow, event
  dedup, idempotent state, lock file, launchd install.
- **Onboarding** — `python3 -m cli.main setup` (4 steps: Google credentials, calendar selection, daemon install, password manager).
- **Autofill keystrokes** — `#fill` and `#submit` send the configured keystroke via osascript + `System Events`. Provider chosen during onboarding (Apple Passwords / 1Password / Bitwarden / None).
- **Trusted run backends** — `run btt(...)`, `run shortcut(...)`,
  `run alfred(...)`, and `run applescript` execute behind the event trust
  gate and per-trust-level backend allowlists. Arbitrary script/path
  execution remains disabled by default.
- **REPL** — Smart + Plus Mode interactive testing.

## What v2.1+ defers — and why

This document lists features that are **specified in the v2.0 docs**
but **deliberately deferred** to a future release. They fall into
three categories:

1. **Hard to implement well** — needs platform-specific APIs we don't
   want to commit to until the architecture is stable.
2. **Hard to QA** — UI-driven; flaky to test in CI; needs an
   integration harness CalFlow doesn't have yet.
3. **Security-sensitive** — needs a permission/policy model first.

Everything deferred is **already wired through parser → validator →
resolver → dispatcher** — only the **side-effect backend** is stubbed.
The pipeline runs to completion, the action logs `(stub)`, nothing
crashes.

> **No Smart Mode feature is deferred. No dynamic-expression base
> feature is deferred.**

---

# v1.5 — Multi-account Google Calendar (designed · tabled)

> **Status:** spec written, decisions locked, **implementation tabled.**
> Full design: `_workspace/specs/v1.5.0-multi-account-calendar.md`.

## Goal
Watch calendars across **N independent Google accounts**, each with its own
OAuth token — connect/disconnect accounts and pick per-account calendars from
the Settings UI without Terminal. Today CalFlow authenticates as exactly one
Google identity (`secrets/token.json`); calendars from other accounts only work
if they're *shared into* that one login.

## Shape (why it's not a small change)
- Unit of work shifts from a bare `calendar_id` to an **(account, calendar_id)**
  pair — the same shared calendar can appear under two logins.
- Storage: `secrets/token.json` → `secrets/tokens/<email>.json` (one per account)
  + a `data/accounts.json` registry. Reuses the [[v1.4.0-user-settings-json]]
  sidecar pattern.
- `build_service()` (one service) → `build_services()` (one per account); 8
  fetch sites in `cli/main.py` rewrite to nest account → calendar.
- Dedup merged streams by `(calendar_id, event_id)`.
- Settings Calendar section becomes a custom renderer (account cards +
  per-account calendar checklists), like the Aliases editor.

## Decisions locked (2026-06-17)
- **In-app OAuth** on a background thread (`account-add` bridge op, cancel +
  120 s timeout) — no Terminal.
- **Add `userinfo.email` + `openid` scope** for reliable account labels; legacy
  token keeps fetching, wider scope acquired lazily on reconnect (zero upgrade
  friction).
- Email-named token files; soft cap of 5 accounts.

## Phasing (2 PRs)
1. Data model + migration + widened scopes + `build_services()` + fetch-loop
   rewrite + dedup + background-thread OAuth backend + `account add/remove/list`
   CLI. Ships standalone; existing installs migrate transparently.
2. Settings UI: Calendar custom renderer, in-app Connect/Disconnect, per-account
   calendar pickers.

## Why tabled
Designed but not yet scheduled. Resume from the spec when prioritized; no code
exists yet.

---

# v2.1 — UI Action Backends

## Goal
Make Plus Mode actually drive the GUI on macOS.

## Scope
| Verb | Backend needed | Difficulty | QA risk |
|------|----------------|-----------|---------|
| `click text("…")` | AXUIElement (Accessibility API) text search | hard | high — depends on app + accessibility permissions |
| `click selector("…")` | DOM-driving via AppleScript / WebDriver / browser CDP | hard | high — browser-specific |
| `click position(x,y)` | CGEventCreateMouseEvent (Quartz) | easy | medium — coordinate drift across displays |
| `type("…")` | CGEventKeyboardSetUnicodeString | easy | medium — focus-dependent |
| `press {…}` | Keycode mapping + CGEventCreateKeyboardEvent | medium | medium |
| `press [{…},({…})x5,{…}]` | Sequence orchestration with key-down/key-up state | medium | high |
| `focus title("Inbox")` | AXUIElement window enumeration + title match | hard | high — title text changes |
| `hide @app`, `close @app` | AppleScript `tell application` | easy | low |

## Why deferred
- `pyobjc` is a 100+ MB dependency tree; we want it **optional**.
- Accessibility permissions require a one-time macOS prompt — onboarding
  needs to walk the user through granting access in System Settings.
- Reliable QA requires either a real macOS runner with a logged-in
  session or VM screenshots — neither exists in v2.0's CI.

## Deliverables
- `runtime/actions/quartz.py` — thin wrapper over Quartz mouse/key events
- `runtime/actions/axui.py` — wrapper over AXUIElement (FOCUS, CLICK by text)
- Onboarding adds an "Accessibility permissions" step
- Integration tests that run on a real macOS workstation (opt-in via env var)

---

# v2.2 — Layout Application Backend

## Goal
Make `#left(50%)`, `#right(50%)`, `#grid(1@3x2)`, `#area(...)`, `#display(N)`
actually move + resize windows. Currently they parse cleanly and the
resolver returns the right dict — but the action layer logs `[INFO]
Applying layout` and stops.

## Scope
- `#left/#right/#middle/#top/#bottom` — single-axis split
- `#full` — maximize on the active display
- `#grid(NxM@D)` — divide screen into N×M cells, place window in cell D
- `#area(x,y,w,h)` — absolute pixel/% positioning
- `#display(N)` — move to display N before applying layout

## Why deferred
- Needs Quartz `CGWindowListCreate` + AXUIElement to query/move windows.
- Multi-monitor coordinate space is fiddly (origin at primary, negative
  coordinates for displays to the left, fractional scaling on Retina).
- Accessibility permissions required.

## Deliverables
- `runtime/actions/window.py` — `move_window(app, layout, display)`
- Test fixtures for grid math (no real display needed)
- Integration tests opt-in (real display required)

---

# v2.3 — Clipboard + Save

## Goal
Make `copy`, `paste`, and `save source(clipboard) to("…")` actually
move bytes.

## Scope
- `copy` — read selection from frontmost app to clipboard
  (or wrap `cmd+c` synthesizer — see v2.1)
- `paste` — synthesize `cmd+v`
- `save source(clipboard) to("…")` — read clipboard (text **or** image)
  via NSPasteboard, write to file
- File-write failures → `[ERROR]` + skip (already documented in
  validation.md §6.3)

## Why deferred
- Clipboard image writes need `pyobjc-framework-Cocoa`.
- Behavior depends on what's currently on the clipboard — empty
  clipboard handling is documented but needs real-clipboard tests.

## Deliverables
- `runtime/actions/clipboard.py` (read / write text + image)
- Validation: `save source(clipboard)` requires non-empty clipboard
  (semantic error → skip + warn)

---

# v2.4 — shell/script backend

## Goal
Design an explicit function-style shell/script backend if CalFlow needs
one later.

## Scope
- Execute the script in a subprocess
- Capture stdout/stderr to `data/launchd.out.log`
- Apply a timeout (default 60s; configurable)
- Return code logged

## Why deferred — security
Arbitrary shell exec from a calendar event is an obvious foot-gun.
Before shipping, we need:
- **whitelist mode (default)**: only paths matching `RUN_WHITELIST_GLOBS`
  in `config/settings.py` are allowed to run; everything else is rejected
  with `[WARN]`
- **explicit opt-in setting** `ALLOW_RUN = False` (default off); setting
  it to `True` doesn't bypass the whitelist
- Onboarding adds a yes/no question about enabling `run`
- Documentation calls out the security model

## Deliverables
- `runtime/actions/runner.py`
- `RUN_WHITELIST_GLOBS = []` in settings.py with documentation
- Whitelist matching tests
- README "Safety model" section expanded

---

# v2.5 — Screenshot Variants

## Goal
Implement the `display(N)`, `window("…")`, `area(x,y,w,h)` modifiers
that already parse cleanly into the AST.

## Scope
| Variant | macOS API | Difficulty |
|---------|-----------|-----------|
| `screenshot display(2)` | `screencapture -D 2 file.png` | easy |
| `screenshot window("Slack")` | window-id lookup + `screencapture -l <id>` | medium |
| `screenshot area(0,0,1920,1080)` | `screencapture -R x,y,w,h file.png` | easy |
| `screenshot to clipboard` | `screencapture -c` (no file) | easy |

Currently `screenshot` always writes to a file under `PLUS_SCREENSHOT_DIR`.

## Why deferred
- Window-id lookup requires `CGWindowListCopyWindowInfo` (Quartz).
- Display indexing differs from human numbering on multi-monitor setups
  — needs onboarding-time display map.

## Deliverables
- `runtime/actions/screenshot.py` extended with the four variants
- Onboarding "preferred display" question

---

# v2.6 — Dynamic Expression Polish (the BASE feature shipped in v2.0)

> ⚠️ **The dynamic-expression base feature shipped in v2.0.**
> `{now}`, `{now-7d}`, `{now > end_of_month > YYYY-MM-DD}`, multi-block
> URLs, default format, whitespace tolerance — all real today, in
> both Smart Mode and Plus Mode.
>
> v2.6 is **polish only**, not the feature itself.

## Goal
Production-grade dynamic expressions on top of the v2.0 base.

## Scope
- **Timezone awareness** — `{now}` currently uses naive local time;
  add `{now > tz("America/New_York")}` (consistent with the single
  `>` pipeline operator)
- **Custom transforms** — allow users to register simple transforms
  in `config/settings.py` (e.g. `next_business_day`)
- **Locale-aware formatting** — `MMM` for "Apr", `Mon` for "Monday";
  needs `babel` or careful strftime
- **Calendar-event-relative bases** — `{event_start}`, `{event_end}`,
  `{event_start - 5m}` — useful inside playbooks attached to events

## Why deferred
- v2.0's `core/dynamic.py` is intentionally minimal and deterministic.
- Locale + timezone semantics need design before code.

---

# v2.x — Other ideas (no commitment)

- **Smart Mode global modifier categories** — currently we hand-classify
  tags as layout/display/session/behavior in `smart_parser._tag_category`.
  Replace with a registered handler table so users can add categories.
- **Plus Mode `if` / `when`** — conditional execution based on dynamic
  expressions or app state. Big language addition; only if user demand
  appears.
- **REPL improvements** — autocomplete, history file, multi-line paste.
- **Web UI mirror** of the menubar app (Linux/Windows users).
- **Apple Calendar / iCloud Calendar** as alternative event sources.
- **Outlook Calendar** as alternative event source.

---

# What's NOT on the roadmap

These are **out of scope** for any near-term release:

- **Linux / Windows backends** — CalFlow is macOS-first; cross-platform
  is a v3 conversation.
- **Cloud sync of state.json** — local-only by design.
- **Server / shared automation** — calendar is per-user; there's no
  authentication story for shared playbooks.
- **AI-generated playbooks** — outside the determinism principle.

---

# Status table (at v2.0)

| Component | Parses | Validates | Resolves | Executes |
|-----------|:------:|:---------:|:--------:|:--------:|
| **Smart Mode — full pipeline** | ✅ | ✅ | ✅ | ✅ (real) |
| Smart Mode global tag state | ✅ | n/a | ✅ | ✅ (real) |
| Smart Mode tag conflict (last wins) | ✅ | ✅ | ✅ | ✅ (real) |
| Smart Mode `##` comments | ✅ | ✅ | n/a | ✅ (real) |
| Smart Mode dynamic in URLs | ✅ | ✅ | ✅ | ✅ (real) |
| OPEN (URL) | ✅ | ✅ | ✅ | ✅ (real, with `#profile(N)` for Chrome) |
| OPEN (app) — `open "App Name"` | ✅ | ✅ | ✅ | ✅ (real, `open -a` launch) |
| OPEN (file) — `open "~/path"` | ✅ | ✅ | ✅ | ✅ (real, OS default app) |
| OPEN (@bundle) — multi-item expansion | ✅ | ✅ | ✅ | ✅ (real — each item dispatched by its own type) |
| Chrome `#profile(N)` | ✅ | ✅ | ✅ | ✅ (real, `--profile-directory=…`) |
| WAIT | ✅ | ✅ | ✅ | ✅ (real) |
| SCREENSHOT (path) | ✅ | ✅ | ✅ | ✅ (real on macOS) |
| **Dynamic `{now > … > fmt}`** | ✅ | ✅ | ✅ | ✅ (real) |
| Layout `#left/#right/#middle/#top/#bottom/#full` | ✅ | ✅ | ✅ | ✅ (real on macOS via osascript) |
| Layout `#grid` / `#area` | ✅ | ✅ | ✅ | ✅ (real on macOS via osascript) |
| `#display` / `#display(ext)` / `#display(N)` / `#display("…")` | ✅ | ✅ | ✅ | ✅ (real on macOS via osascript + JXA) |
| Autofill `#fill` / `#submit` (Apple Passwords / 1Password / Bitwarden) | ✅ | ✅ | ✅ | ✅ (real on macOS via osascript + System Events; Accessibility permission required first time) |
| FOCUS — `focus @app` | ✅ | ✅ | ✅ | ✅ (real, `tell app to activate`) |
| FOCUS — `focus @app title("…")` | ✅ | ✅ | ✅ | ✅ (real, AXRaise on matching window) |
| CLOSE — `close "X"` / `close [a, b]` | ✅ | ✅ | ✅ | ✅ (real, `tell app to quit`, only if running) |
| HIDE — `hide @app` / `hide [a, b]` | ✅ | ✅ | ✅ | ✅ (real, System Events `set visible to false`) |
| HIDE — `hide active` / `hide all` (runtime targets, v1.1.2) | ✅ | ✅ | ✅ | ✅ (real, frontmost lookup + iterate) |
| HIDE — `hide except(<…>)` (incl. `except(active)`) | ✅ | ✅ | ✅ | ✅ (real, iterates processes; keeps frontmost) |
| HIDE — `display(N)` / `display("name")` filter | ✅ | ✅ | ✅ | ✅ (real, v1.1.7 — JXA + window-centre test; needs Accessibility) |
| CLOSE — `close except(<…>)` / `close active` / `close all` | ✅ | ✅ | ✅ | ✅ (real, iterates processes; keeps frontmost; v1.1.2) |
| FOCUS — `focus @app display(N)` / `display("name")` (v1.1.2) | ✅ | ✅ | ✅ | ✅ (real — activate + JXA enumerate + AppleScript bounds set) |
| FOCUS — `focus active` (v1.1.2 no-op) | ✅ | ✅ | ✅ | ✅ (real — log-only) |
| SCREENSHOT — `screenshot to("…")` (v1.1.2 canonical) | ✅ | ✅ | ✅ | ✅ (real, screencapture) |
| SCREENSHOT — `screenshot active` (frontmost window) | ✅ | ✅ | ✅ | 🚧 stub — falls back to full screen |
| CLICK | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| TYPE | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| PRESS (single / combo / sequence) | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| SCREENSHOT (display/window/area variants) | ✅ | ✅ | ✅ | 🚧 stub (v2.5) |
| COPY / PASTE | ✅ | ✅ | ✅ | 🚧 stub (v2.3) |
| SAVE | ✅ | ✅ | ✅ | 🚧 stub (v2.3) |
| RUN trusted backends (`-btt`, `-shortcut`, `-alfred`, `-applescript`) | ✅ | ✅ | ✅ | ✅ (real, gated by event trust + backend allowlists) |
| RUN arbitrary script/path | ✅ | ✅ | ✅ | 🚧 stub — refusing arbitrary scripts by default |

⏳ = doc-locked, code lands next pass.
🚧 = stub or unimplemented; safe to invoke (logs only).

---

# 💡 Principle

> **Specify the full surface in v2.0. Land the foundation. Bind side
> effects later, version by version, with a security and QA story for
> each.**
