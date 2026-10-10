# CalFlow Handoff

## Current Release State

- **Active branch: `main`** (dev moved off `v2.0` at the v1.5 prerelease,
  2026-07-04; branch `v2.0` still exists at that point but is no longer
  the trunk).
- **Current release: v1.5.5** — first public tagged release of the v1.5
  line. **Development version: v1.5.6-dev**, with `__is_release__ = False`.
  Audit checkpoint: `f1d876c`; reliability implementation follows that commit.
- **Pushes**: only on user-requested releases. Local commits otherwise.
  The old blanket push freeze is lifted (superseded by CLAUDE.md §7).
- `v2.0.0` remains reserved for the public launch milestone. Do not
  recreate any `v2.0.x` tag until the user says the launch is ready.

## What shipped in v1.5.x

- **v1.5 / v1.5.1** — README overhaul (beginner-friendly), action-verb
  documentation, prerelease prep.
- **v1.5.2** — DSL batch: `hide active display(N)` (per-window scope),
  `hide [active,"App"]` runtime expansion, `copy("text")` via pbcopy,
  screenshot → clipboard default (`to(clipboard)` / `to("path")`),
  bare parenless layout words (`full`, `left`, …) as Plus drop-sugar,
  `new(tab)`/`new(window)` documented.
- **v1.5.3** — Smart Mode hash-drop for function tags
  (`zoom.us display(2)` ≡ `#display(2)`), with value-shaped arg
  guardrails (no `#top(ic)` from prose) and quoted-arg fixes on
  standalone modifier lines.
- **v1.5.4** — mouse gestures: `click button(left|right|middle)`,
  `click count(1|2|3)` (click-state ≠ repeat), `drag from(x,y) to(x,y)
  [button()] [duration(t)]` — verb #14. Parse/validate/resolve real;
  execution stubs until the v2.1 Quartz backend.
- **v1.5.5** — menubar Tip Dev → buymeacoffee.com/therapydoge, markdown
  sync for the new verb surface, `docs/examples.md` generated from the
  examples sheet ('260707' tab).

## Reference

- Examples spec-of-record: the "CalFlow Examples" Google Sheet, tab
  `260707` (mirrored in `docs/examples.md`).
- Multi-account calendar: designed + tabled —
  `_workspace/specs/v1.5.0-multi-account-calendar.md` (NOTE: spec label
  predates the v1.5 prerelease line; renumber to v1.6 when picked up).
- `.app` bundle (py2app): deferred until near public launch. When it
  ships, remove the `permissions.python_binary` Settings row.
- `run script(PATH)`: approved syntax, ships with the v2.4 whitelist
  security model. Bare `run "path"` stays rejected.
- Queued verb-vocabulary questions: `minimize` / `#minimized`, `show` /
  `unhide`, `restore`, native fullscreen vs `#full`. Spec before code.

## Working Notes

- **Implementation follow-up:** see `docs/reliability-followup-2026-10-10.md`.
  Structured results, durable attempts, detached menu workers, persistent login/
  pause state, parser repairs and staged installer rollback are implemented.
  CLI dispatch and interactive invitation trust are also repaired. Preserve the
  audit below as baseline evidence; its remaining P2 items are not all closed.
  No release tag was requested for this development push.
  Final local checks: 1,010 Python tests, 6 Node UI tests, targeted Ruff,
  installer shell syntax and dependency checks passed. Pytest now isolates
  migration backups and rejects unmocked native-action processes.

- **Historical audit handoff (before implementation):** reviewed the changes subsequently committed
  by another session as v1.5.6-dev (`f1d876c`), with inherited-model specialist
  audits at ultra reasoning. See
  `docs/codebase-audit-2026-10-10.md` for verified open bugs, reproductions and
  the repair order. Concurrent execution-result, job and action changes are
  outside the verified baseline and must be re-tested before closing findings.
  Other sessions' working changes were preserved.
- That audit handoff changed documentation only; no runtime repair, version bump,
  commit, tag or push. Passing tests are not launch clearance. Prioritize CLI
  dispatch/trust, execution ownership/results, and data-preserving installation.
- At audit time, the full Python suite passed in a disposable source copy with external IO
  guarded; the existing migration test otherwise writes `data/settings.py.bak`
  in the real checkout. The implementation's pytest fixture now redirects it.
  Native reboot/permissions and live Calendar behavior were not run.

- `config/settings.py` is tracked defaults only; user overrides live in
  `data/user_settings.json` / `data/user_targets.json` (gitignored).
  Never reintroduce runtime writes to tracked files.
- Historical references to the v2.0 architecture in parser/runtime/
  roadmap docs are labels, not release tags — don't bulk-rewrite.
- `_workspace/` specs are tracked; scratchpads are gitignored handoff
  notes between Cowork/Codex/Code sessions.
