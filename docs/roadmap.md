# CalFlow Roadmap

Release line: v1.5.x. Historical v2.x headings below identify architecture
milestones, not a claim that those future backends have shipped.

## Release Gate: Reliability Before More Features

The [2026-10-10 audit](codebase-audit-2026-10-10.md) reviewed v1.5.6-dev
(`f1d876c`). Passing automated tests do not cover all of the reproduced
failures below. Concurrent reliability work is in progress; these remain
open until its fixes and regression tests are verified.

1. **Execution safety:** reject ambiguous CLOSE scopes, apply the same path
   permissions to all equivalent spellings, preserve calendar trust in the
   interactive test runner, and make help/unknown CLI input non-executing.
2. **Honest results and job ownership:** propagate action failures and
   unsupported operations, mark events done only according to an explicit
   success policy, serialize duplicate jobs across entry points, and support
   long workflows with observable cancellation of child processes.
3. **Data preservation:** replace destructive reinstall with a staged,
   recoverable upgrade; make settings/alias transactions safe under concurrent
   writers and remove the import-order dependency when loading preferences.
4. **Desktop recovery:** keep live status separate from cached events, inspect
   bridge error results, prove managed launchd ownership, and finish the
   confirmation, draft-preservation and folder-picker fixes.
5. **Parser contracts:** preserve source order and layout arguments, contain
   numeric/date overflows, reject incomplete scripts, and redact event payloads
   from normal logs. Test parsing through actual mocked action arguments.
6. **Acceptance:** isolate all test storage, run Python and Node suites in a
   clean source copy, then perform separately approved macOS permission,
   reboot, multi-display and upgrade/rollback checks. Record evidence against
   the exact release commit.

## Implemented Foundation

The [2026-10-10 implementation follow-up](reliability-followup-2026-10-10.md)
supersedes the corresponding baseline findings above: shared job ownership,
honest outcomes, long menu runs, persistent login/pause controls, staged upgrades,
CLI/trust guards and the documented parser regressions now have tests. Remaining
data-store concurrency, cached controls and native recovery UX work stays open.

- **Smart Mode** — the core implementation includes:
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
- **Plus Mode parser, validator, resolver, dispatcher** — all 14
  verbs parse and route. `#grid(D@NxM)` and `#area(x,y,w,h)` parse
  to typed dicts.
- **Calendar layer** — multi-calendar polling, OAuth flow, event
  completion records and launchd install. Shared occurrence claims, a desktop
  execution lock and per-step results are implemented; native acceptance remains.
- **Onboarding** — `python3 -m cli.main setup` (5 steps: Google credentials, calendar selection, daemon install, password manager, Accessibility).
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

Many deferred verbs already parse and route, but their side-effect backends
are stubs. Scoped screenshots are refused without capture. Arbitrary script
files remain unsupported; parsing alone is not evidence an action runs.

The base Smart Mode and dynamic-expression features exist, but layout conflict
ordering, argument preservation and overflow handling have known defects.
Feature presence is not a claim that every documented edge case works.

---

# Multi-account Google Calendar (designed · tabled)

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
  + a `data/accounts.json` registry. Reuses the
  [user-settings sidecar pattern](menubar.md#settings-and-files).
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
| `click … button(…) count(…)` | CGEvent button constant + click-state (syntax shipped v1.5.4) | easy | low |
| `drag from(x,y) to(x,y)` | CGEvent mouseDown → interpolated drags over `duration` → mouseUp (syntax shipped v1.5.4) | medium | medium — drag-threshold timing per app |
| `type("…")` | CGEventKeyboardSetUnicodeString | easy | medium — focus-dependent |
| `press {…}` | Keycode mapping + CGEventCreateKeyboardEvent | medium | medium |
| `press [{…},({…})x5,{…}]` | Sequence orchestration with key-down/key-up state | medium | high |

App focus, matching-window focus, hide and close already have real backends;
they are not part of the deferred mouse/keyboard implementation.

## Why deferred
- `pyobjc` is a 100+ MB dependency tree; we want it **optional**.
- Accessibility permissions require a one-time macOS prompt — onboarding
  needs to walk the user through granting access in System Settings.
- Reliable QA requires either a real macOS runner with a logged-in
  session or VM screenshots — neither exists in v2.0's CI.

## Deliverables
- `runtime/actions/quartz.py` — thin wrapper over Quartz mouse/key events
- `runtime/actions/axui.py` — wrapper over AXUIElement (FOCUS, CLICK by text)
- Improve the existing "Accessibility permissions" onboarding step
- Integration tests that run on a real macOS workstation (opt-in via env var)

---

# v2.2 — Layout Application Backend

**Implemented.** Basic layout, grids, absolute areas and display selection
already use osascript/JXA. Remaining work is application-specific reliability
and real multi-display integration coverage.

## Goal
Make `#left(50%)`, `#right(50%)`, `#grid(1@3x2)`, `#area(...)`, `#display(N)`
move and resize windows using the existing action backend.

## Scope
- `#left/#right/#middle/#top/#bottom` — single-axis split
- `#full` — maximize on the active display
- `#grid(D@NxM)` — divide screen into N×M cells, place window in cell D
- `#area(x,y,w,h)` — absolute pixel/% positioning
- `#display(N)` — move to display N before applying layout

## Remaining Verification
- The current backend uses osascript/JXA; it is not waiting on a new Quartz
  implementation. Test the existing path with real supported applications.
- Multi-monitor coordinate space is fiddly (origin at primary, negative
  coordinates for displays to the left, fractional scaling on Retina).
- Accessibility permissions required.
- Fix the parser's lost layout arguments and last-wins ordering before
  treating every syntax variant as equivalent.

## Deliverables
- `runtime/actions/window.py` — `move_window(app, layout, display)`
- Test fixtures for grid math (no real display needed)
- Integration tests opt-in (real display required)

---

# v2.3 — Clipboard + Save

**Partially implemented.** Literal `copy("text")`, screenshot-to-file and
run-result copy/save/append work. Bare selection-copy, paste and standalone
clipboard-save are still stubs.

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

# v2.6 — Dynamic Expression Polish (base feature already implemented)

> **The dynamic-expression base feature is already implemented.**
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

# Status Table (reviewed v1.5.6-dev baseline)

These rows describe implementation presence, not release acceptance. See the
audit for edge cases and missing integration coverage.

| Component | Parses | Validates | Resolves | Executes |
|-----------|:------:|:---------:|:--------:|:--------:|
| **Smart Mode — full pipeline** | ✅ | ✅ | ✅ | ✅ (real) |
| Smart Mode global tag state | ✅ | n/a | ✅ | ✅ (real) |
| Smart Mode tag conflict (last wins) | ✅ | ✅ | ⚠ source order can be lost | ⚠ regression fix needed |
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
| SCREENSHOT — `screenshot active` (frontmost window) | ✅ | ✅ | ✅ | 🚧 rejected without capture |
| CLICK | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| DRAG | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| TYPE | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| PRESS (single / combo / sequence) | ✅ | ✅ | ✅ | 🚧 stub (v2.1) |
| SCREENSHOT (display/window/area variants) | ✅ | ✅ | ✅ | 🚧 rejected without capture (v2.5) |
| COPY literal text | ✅ | ✅ | ✅ | ✅ real, pbcopy |
| Bare COPY / PASTE | ✅ | ✅ | ✅ | 🚧 stub (v2.3) |
| SAVE | ✅ | ✅ | ✅ | 🚧 stub (v2.3) |
| RUN trusted backends (`btt(...)`, `shortcut(...)`, `alfred(...)`, `applescript`) | ✅ | ✅ | ✅ | ✅ real, gated by event trust + backend allowlists |
| RUN arbitrary script/path | unsupported | unsupported | unsupported | refused |

⏳ = doc-locked, code lands next pass.
🚧 = stub or unimplemented; the requested action is not performed. The
reliability follow-up reports these steps as unsupported instead of successful.

---

# 💡 Principle

> **Specify the full surface in v2.0. Land the foundation. Bind side
> effects later, version by version, with a security and QA story for
> each.**
