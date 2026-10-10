# Audit and login recovery - 2026-10-10

Authorized scope: full codebase audit, documentation updates, and repair of the
missing menubar icon after reboot. No release or GitHub push is requested.

## Planned changes

- `cli/menubar_launchd.py`: generate an escaped plist, restrict the agent to
  GUI login, restart unsuccessful exits, use explicit GUI-domain launchctl
  operations, update old registrations, and verify readiness.
- `cli/onboarding.py`: match the daemon label exactly and report launchctl
  failures; remove outdated setup help for implemented window layouts.
- `cli/menubar.py`: keep the singleton valid for long-running instances and
  make the menu process start independently of calendar dependencies.
- `cli/main.py`: route the menubar entrypoint before calendar imports.
- Menubar UI/bridge: address verified status/timeout inconsistencies only.
- Relevant tests: regressions first, then focused checks and the full suite.
- README, menubar/QA/roadmap documentation: describe actual startup, recovery,
  action support and known limitations. Record remaining findings in audit
  reports rather than expanding this repair into architectural refactors.

This is the dry-run scope for the multi-file audit repair. No DSL syntax or
state-file schema change, dependency upgrade, or bulk formatting is planned.

## Confirmed audit expansion

The independent audits reproduced trust bypasses and unsafe scope widening.
The repair now also includes bounded fixes to existing behavior:

- Actions: escape AppleScript data, prevent hide from closing windows, honor
  subprocess failures/timeouts, and refuse unsupported screenshot scopes.
- Parser: preserve autofill opt-outs; ignore URL fragments as command tags;
  reject display-filter combinations that would widen a hide operation.
- Executor/policy: enforce backend policy for deep links, stop handlers after
  authorization denial, restrict invited-event file handlers, honor command
  caps, and resolve one-item aliases correctly.
- Trust/persistence/calendar: avoid treating shared calendar ownership as
  self identity, preserve migration inputs, merge concurrent completion state,
  propagate API failure and follow pagination.
- Tests: replace incomplete desktop-action mocks before another full suite.

These changes retain the existing DSL and state schema. Deferred design work
and residual issues remain explicit in the audit report.

## Verification

Baseline: 690 tests pass; Ruff reports 665 existing findings. Audit workers
use GPT-6 Astra with ultra reasoning. Inspect launchd configuration and validate
restart/recovery on this Mac without rebooting or executing calendar events.
An actual reboot/login remains a user verification step.

Final: 827 Python tests and 3 Node UI tests pass. Guarded full-suite execution
reported no unexpected external IO. Ruff has 656 remaining findings; strict
mypy has 218 errors. LaunchAgent installed, forced-failure recovery verified,
and companion restarted successfully. No release, push or version change.
Remaining findings are recorded in `_workspace/reviews/audit-2026-10-10.md`.
