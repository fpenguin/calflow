# CalFlow Handoff

## Current Release Discipline

The project is building toward a future public **v2.0 launch**, but active
pre-launch development must stay on **v1.4.x** until the user says otherwise.

Current local version source:

- `core/version.py` renders `1.4.1-dev`

## Current v1.4 Local Work

The current local work is the v1.4 settings/cache/recovery cleanup:

- Settings UI writes user preferences to `data/user_settings.json`.
- Alias/TARGETS edits write to `data/user_targets.json`.
- `config/settings.py` keeps tracked defaults and imports those sidecars at
  module load.
- `config/settings.defaults.py` is the restore/diff snapshot for
  `python -m cli.main migrate-settings`.
- The menubar popover now uses `cli.main popover-feed`; successful payloads
  are cached in `data/popover_cache.json` for up to 24 hours.
- If the popover refresh fails but cache is usable, UI shows stale cached data
  with an amber retry banner rather than going empty.
- Menu bar LaunchAgent lifecycle failures now include `error` and `recovery`
  steps with reset commands/log paths.

Do not reintroduce writes to tracked `config/settings.py` from Settings UI
or TARGETS editor. Runtime writes belong under `data/`.

## Recently Completed (v1.4.1-dev)

- **Q3 Settings vocabulary pass** (`d4c4594`) — rewrote ~50 user-facing strings
  in `runtime/menubar/settings.html` to remove jargon (daemon, launchd, OAuth,
  regex, URI scheme, TARGETS, etc.). No behaviour changes.
- **Settings UX fixes** (`78db945`) — Aliases save/remove crash (INSDictionaryM
  serialization), Events section cleanup (removed Default browser / Chrome profile
  rows), Permissions section reordering and Accessibility status clarification.
- **Dynamic popover sizing** — `resize-popover` bridge op + `resizePopover()` JS,
  clamped to `[200, 720]px`. Tests in `tests/test_v3_menubar_resize.py`.

## Pending (next sessions)

- **Q1 — Multi-account calendar** (user confirmed: wants this): allow
  connecting/disconnecting Google accounts and per-account calendar pickers.
  Feature needs design/spec before implementation. Multi-session.
- **Q2 — .app bundle** (user confirmed: wants this): proper macOS app bundle with
  `Info.plist` so System Settings shows "CalFlow" instead of `python3.11`.
  When shipped, the `permissions.python_binary` row in Settings can be removed.
  Multi-session packaging work.

## GitHub Push Freeze

**Until further notice, do not push anything to GitHub.**

This includes:

- commits
- branches
- tags
- force-pushes
- release/tag cleanup

Local commits are allowed only when the user asks for them. If a task appears
to require GitHub, stop and ask the user first.

## v2.0 Tag Cleanup

The accidental public GitHub tags were removed:

- `v2.0.0`
- `v2.0.1`

The matching local tags were also deleted so they are not accidentally pushed
again.

Do not recreate any `v2.0.x` tag until the user explicitly says the public
v2.0 launch is ready.

## Menubar Version Relabel

Recent menubar work was relabeled from `v2.0.x-dev` to `v1.4.0-dev`:

- LaunchAgent lifecycle commands
- dynamic month/day menu bar icon
- dynamic popover sizing

The dynamic popover sizing implementation itself remains in place:

- `resize-popover` bridge op in `cli/menubar.py`
- dynamic `resizePopover()` call in `runtime/menubar/popover.html`
- resize tests in `tests/test_v3_menubar_resize.py`

The popover width intentionally remains `_POPOVER_W = 560`.

## Working Notes

- The current branch name is still `v2.0`; do not rename or push it without
  explicit user instruction.
- `docs/menubar.md`, `cli/menubar.py`, and `runtime/menubar/__init__.py`
  use `v1.4.x` for current menubar docs/header labels.
- Historical references to the v2.0 architecture may still exist in parser,
  runtime, and roadmap docs. Do not bulk-rewrite them unless the user asks;
  many are historical/architectural labels rather than release tags.
- `_workspace/specs/v1.4.0-user-settings-json.md` is an untracked local spec
  file. Do not add, delete, or modify it unless asked.
