# CalFlow Codebase Audit

Date: 2026-10-10. Reviewed baseline: **v1.5.6-dev, `f1d876c`**.

Subsequent repairs and their verification are tracked in the
[implementation follow-up](reliability-followup-2026-10-10.md). This document
remains a record of the audited baseline, not a claim that every finding below
is still present or that all remaining findings have been resolved.

## Verdict

**Hold the next public launch for the P1 fixes below.** The automated suite
passes, but additional isolated reproductions found unsafe command scope,
inconsistent authorization, false completion, and data-preservation risks.
No P0 issue was demonstrated. This is not a claim that no other defects exist.

This audit started on the uncommitted changes after v1.5.5. Another session
committed those changes as `f1d876c` during the review. Subsequent execution
result, job-management and action changes are concurrent work, not verified
fixes in this report. Re-test them before closing any finding.

The audit itself changes documentation only. It does not repair runtime code,
bump a version, commit, tag or push. Existing and concurrent work was preserved.

## Scope And Evidence

Reviewed the CLI/setup/REPL entry points, native menu bridge and HTML,
configuration readers/writers, parser/validator/resolver, action dispatch and
macOS backends, Calendar integration, persistence, installation, CI/tests,
public documentation and playbook examples. Parser/runtime and desktop
specialists supplemented the main review using inherited-model sessions with
ultra reasoning. Their scoped test counts overlap the full suite below.

Verification used synthetic events, temporary files and mocked actions. No
real Calendar event was executed, no user credentials were read, and no
LaunchAgent was installed or restarted.

| Check | Result |
| --- | --- |
| Full Python suite, disposable source copy | **827 passed; 186 subtests passed** |
| Menu JavaScript behavior tests | **3 passed** |
| Playbook/spec tests after documentation edits | **111 passed** (subset, not additional suite coverage) |
| Local Markdown link targets in edited docs | **70 checked; none missing** |
| Python dependency consistency (`pip check`) | Passed |
| Shell syntax: install, setup, typecheck scripts | Passed |
| Guarded targeted probes | Confirmed the behavioral findings described below |
| Ruff | 656 findings, predominantly existing cleanup; not counted as product bugs |
| Strict mypy | 218 errors in 25 files; 60 files checked; not all are runtime defects |

The full Python run used Python 3.11.17 with guards against network, desktop
processes and personal data access. Three inspected, harmless Python child
probes were permitted. An earlier guard run blocked two such probes and caught
the real migration-fixture isolation bug listed below. Those guard failures
are not three failing product tests.

No coverage percentage was measured. There was no live reboot, Accessibility,
OAuth, multi-display or end-to-end desktop acceptance run, no clean Python
3.10/3.12 run, and no dependency vulnerability scan. Passing unit tests do not
establish those properties.

Locations below use module/function names because line numbers change during
the concurrent fixes. All findings refer to the reviewed baseline.

## P1: Fix Before Launch

### P1-01: CLOSE can widen a named target to all applications

**Location:** [Plus parser](../core/parser/plus_parser.py),
[validator](../core/validator/validator.py),
[`_do_close`](../runtime/command_executor.py).

**Evidence:** `close @chrome except("Notes")` validates, loses the Chrome
target and calls mocked `close_all(except_apps=('Notes',))`.
`close except()` also calls close-all. A user intending a narrow operation
can unexpectedly quit unrelated applications and interrupt unsaved work.

**Fix/test:** reject target-plus-exception ambiguity and empty exceptions,
retain selection provenance through resolution, and assert that invalid or
unresolved scopes never call a broad action. Cover CLOSE as well as HIDE.

### P1-02: Relative paths bypass invitation permissions

**Location:** [`is_open_target_allowed`](../runtime/run_policy.py).

**Evidence:** under `trusted_domain`, `open "folder/Example.app"` is allowed
and reaches a mocked application launch; `./folder/Example.app` is denied.
Equivalent filesystem targets receive different permissions, defeating the
guard against invited events launching local executable paths.

**Fix/test:** classify and normalize filesystem paths before authorization,
including alias-expanded values. Test absolute, home-relative, dot-relative,
bare relative, file-URL and alias spellings through parsing and execution.
Do not accidentally forbid intentionally allowed ordinary application names.

### P1-03: Help and unknown CLI input can run automation

**Location:** [`_first_non_flag_arg` and module dispatch](../cli/main.py).

**Evidence:** `--help`, `--setup` and `statuz` reach the default daemon-cycle
path. A guarded module run intercepted each immediately before lock
acquisition; no real cycle ran. Flag stripping also makes some advertised
flag aliases unreachable.

**Fix/test:** use explicit command/argument validation. Help must exit without
Calendar, filesystem-state or desktop effects; unknown input must exit with a
useful error. Preserve a no-argument daemon cycle only as an intentional,
documented case. Add subprocess entry-point tests, not only handler tests.

### P1-04: The interactive test runner promotes calendar event trust

**Location:** [`_step2b_execute_loop` and `_execute_parsed`](../cli/main.py).

**Evidence:** selecting a synthetic event created by an untrusted address and
choosing execution reaches the mocked AppleScript backend because the runner
uses the executor's default self-trust. Daemon and `run-event` paths use the
event trust decision. This requires the user to choose Execute; it is not
automatic execution on merely viewing an invitation.

**Fix/test:** retain event provenance and trust in calendar-selected tests.
Keep deliberately pasted local scripts a separate local-action path. Any
override must be explicit and explain the permission change. Test identical
events across daemon, menu, CLI and test-runner entry points.

### P1-05: Failed execution is recorded or presented as success

**Location:** [`main` and `run_event_by_id`](../cli/main.py),
[Smart executor](../runtime/executor.py),
[Plus executor](../runtime/command_executor.py).

**Evidence:** a mocked executor exception is caught, but the daemon still
marks the event's run key done. Backend failures and unimplemented actions
often return no structured outcome, so manual entry points can also announce
success. A failed event may then be suppressed on future polls.

**Fix/test:** propagate explicit success, partial, failure, unsupported and
cancelled outcomes. Define when completion is persisted and how retries avoid
repeating already successful side effects. Test failed OPEN, unavailable
backends, stubs, mixed results and interrupted workflows. Concurrent
execution-result work needs these end-to-end assertions before sign-off.

### P1-06: Different entry points do not share reliable job ownership

**Location:** [`acquire_lock` and manual run paths](../cli/main.py),
[menubar subprocess execution](../cli/menubar.py).

**Evidence:** a live PID's cycle lock expires after 180 seconds; acquisition
is a check followed by a write, not an atomic claim. Manual event execution
does not use the same ownership mechanism. Long workflows can overlap another
poll/manual run. The menu worker's 60-second deadline also cannot complete the
bundled 25-minute Pomodoro; timeout is not proof every descendant has stopped.

**Fix/test:** use shared per-job ownership across launch sources and observable
job states; keep long jobs independent of UI request deadlines. Verify process
group cancellation, stale-owner recovery, two-process contention, and a job
longer than both existing deadlines. A lock around state-file writes alone
does not serialize execution.

### P1-07: Reinstall removes user data before the replacement is ready

**Location:** [installer](../scripts/install.sh), existing-directory branch.

**Evidence:** accepting the reinstall prompt runs `rm -rf "$INSTALL_DIR"`
before clone/dependency setup. Preferences, playbooks, state and credentials
inside that installation are lost; a failed replacement leaves no working
installation. The user does confirm reinstall, but this is not a safe updater.

**Fix/test:** stage the replacement, preserve private/user data, verify it,
then switch with rollback. Explain any destructive choice separately. Test
clone failure, dependency failure, interruption and upgrade with populated
synthetic data. Do not use real credentials for the upgrade fixture.

## P2: Correctness And Recovery

### P2-01: Import order changes saved settings and aliases

**Location:** [settings defaults](../config/settings.py),
[settings reader](../core/settings_reader.py), [logging utilities](../core/utils.py).

Fresh-process probes using temporary preferences show that importing
`core.utils` or `core.settings_reader` first can leave defaults and omit aliases.
Importing settings first loads the preference but can leave the logger using
its old mode. The cycle is settings -> reader -> utils -> settings.

**Fix:** load/validate user configuration without importing the logging
consumer, then initialize runtime consumers explicitly. Test all entry-point
import orders in separate interpreters, not just module reloads.

### P2-02: Atomic replacement is not a concurrent settings transaction

**Location:** [`save_user_overrides`](../core/settings_reader.py); review the
same fixed-temporary-name pattern in alias, cache, recipe and statistics stores.

A controlled two-writer probe shows one writer replacing the shared `.tmp`
file, then the other raising `FileNotFoundError`. Only one update survives.

**Fix:** serialize read/merge/write, use unique temporary files, and define
conflict handling. Test threads and processes with disjoint and overlapping
updates. Atomic rename alone does not prevent lost updates.

### P2-03: Non-finite numeric preferences are accepted

**Location:** [settings writer validation](../core/settings_writer.py),
[reader coercion](../core/settings_reader.py).

Saving `advanced.plus_inter_command_delay_sec = "nan"` succeeds and emits JSON
`NaN`. Range comparisons do not reject it, and runtime delay operations can
fail. Persisted values also need type validation, not just UI validation.

**Fix:** require finite numbers, validate types/bounds at both boundaries and
write standards-compliant JSON. Test NaN, infinities, booleans and corrupt files.

### P2-04: Corrupt statistics can take down the calendar feed

**Location:** [`snapshot`](../state/stats_store.py),
[`collect_popover_feed`](../cli/main.py).

A saved `"actions_run": "bad"` raises during integer conversion. Statistics
are collected inside the same broad failure block as the calendar feed, so
an unrelated local counter can force stale-data fallback.

**Fix:** validate counters and isolate optional statistics failures from event
retrieval. Preserve/recover corrupt files without wiping unrelated state.

### P2-05: Cached events also restore stale controls and timestamps

**Location:** [`collect_popover_feed`](../cli/main.py),
[popover refresh/render](../runtime/menubar/popover.html).

A cached `daemon.loaded=true` wins over fresh `loaded=false` during a simulated
API outage. The UI can stamp Last sync as now and retain old relative urgency.
The cache banner does not make those controls or timestamps accurate.

**Fix:** cache event data separately; always obtain live/unknown control status,
retain the last successful synchronization time, and recompute urgency from
absolute event times. Test cold startup, paused daemon and prolonged outage.

### P2-06: Lifecycle bridge errors are shown as success

**Location:** [popover pause](../runtime/menubar/popover.html),
[Settings restart](../runtime/menubar/settings.html), [bridge results](../cli/main.py).

Resolving a request with `{ok:false,error:...}` leaves the optimistic Paused UI
in place or produces a "daemon restarted" message. Application errors resolve
the transport promise rather than rejecting it.

**Fix:** inspect result status, restore controls on failure and refresh actual
service state. Test both rejected promises and resolved error payloads.

### P2-07: LaunchAgent readiness does not prove managed ownership

**Location:** [menubar launch lifecycle](../cli/menubar_launchd.py),
[singleton acquisition](../cli/menubar.py).

A registered job without a managed PID plus a live manually launched companion
can pass readiness. The launched child exits on the singleton lock, so the
remaining manual process is not protected by that job's recovery policy.

**Fix:** match managed PID and lock owner, wait for post-initialization readiness,
and explicitly handle a pre-existing unmanaged instance.

### P2-08: Native webview Delete confirmations have no handler

**Location:** [webview setup](../cli/menubar.py),
[playbook Delete](../runtime/menubar/recipes.html),
[alias Delete](../runtime/menubar/settings.html).

Both controls use JavaScript `confirm`, but only a navigation delegate is
installed. WebKit documents that an unimplemented confirmation delegate treats
the action as Cancel. This is a native API contract/static finding supported
by a mocked default-cancel probe, not a live desktop acceptance test.
[WebKit contract](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/API/Cocoa/WKUIDelegate.h).

**Fix:** retain a WKUIDelegate implementation or use an in-page confirmation.
Test Cancel and Confirm in the actual native host.

### P2-09: Keyboard reentry duplicates playbook execution

**Location:** [Playbooks keyboard listener and `onRun`](../runtime/menubar/recipes.html).

Two Cmd+Enter presses send two run-script requests despite the disabled Run
button. **Fix:** share an in-flight guard across every activation path and add
a keyboard reentry test; backend ownership remains necessary too.

### P2-10: Refresh can erase an unsaved blank playbook

**Location:** [Playbooks `newBlank`, `renderList`, refresh](../runtime/menubar/recipes.html).

A new draft has a null selection; a refresh auto-selects stock content and
replaces the dirty editor. **Fix:** model drafts independently of selection,
preserve them on show/refresh, and confirm before destructive replacement.

### P2-11: Password-manager preference has two sources of truth

**Location:** [autofill provider selection](../runtime/actions/autofill.py),
[settings schema](../core/settings_schema.py).

The GUI saves `AUTOFILL_PROVIDER`, but execution prefers the older onboarding
value in `data/config.json`. Selecting 1Password after Apple/None can keep using
the old provider. **Fix:** migrate to one source and let explicit saved edits
win; test setup-to-GUI-to-runtime transitions.

### P2-12: Daemon installation still has a separate unsafe error path

**Location:** [onboarding plist generation/install](../cli/onboarding.py).

An installation path containing `&` creates invalid interpolated XML. A mocked
launchctl failure still prints enabled, and those setup calls lack timeouts.
The repaired menubar installer does not repair this separate daemon path.

**Fix:** use `plistlib`, checked bounded calls and shared recovery reporting.
Test special characters, already-loaded jobs and failed bootstrap/load.

### P2-13: Folder selection expires while the dialog remains open

**Location:** [Settings bridge timeout](../runtime/menubar/settings.html),
[native folder picker](../cli/menubar.py).

After 25 seconds the pending promise is discarded, so a later valid selection
is ignored. **Fix:** distinguish user-driven modal lifetimes from worker
deadlines; settle on selection/cancellation and test delayed completion.

### P2-14: Numeric overflow silently discards a whole Plus block

**Location:** [Plus numeric coercion and parse fallback](../core/parser/plus_parser.py).

A 311-digit coordinate in `drag from(N,0) to(1,1)` between two valid WAIT lines
causes zero commands and zero diagnostics. **Fix:** reject out-of-range numbers,
contain failures per line, and retain the valid surrounding commands.

### P2-15: Canonical layout arguments disappear

**Location:** [Plus tag tokenization](../core/parser/plus_parser.py).

`#display("DELL")` and `#area(0, 0, 100, 100)` validate but dispatch with their
layout/display missing. **Fix:** parse balanced arguments and test hash/drop-
sugar forms through resolved action parameters, including spaces and quotes.

### P2-16: Last-wins modifiers lose source order

**Location:** [Plus parser](../core/parser/plus_parser.py),
[Smart parser](../core/parser/smart_parser.py), [resolver](../core/resolver/resolver.py).

Reversing `#left(30) #right(70)` can produce the same result, contrary to the
documented last-wins contract. **Fix:** retain order until category conflicts
are resolved; test reversed permutations and inherited versus local modifiers.

### P2-17: Malformed AppleScript forms are accepted

**Location:** [Plus script parser](../core/parser/plus_parser.py),
[validator](../core/validator/validator.py).

`run applescript("return 1")` validates but dispatches an empty script; a fenced
script without closing `+++` dispatches its payload. **Fix:** reject unsupported
inline forms and incomplete fences, or explicitly support/preserve the inline
payload. Never silently execute an unterminated block.

### P2-18: Date-expression overflow drops an otherwise valid action

**Location:** [dynamic date arithmetic](../core/dynamic.py).

`{now+999999999d}` raises `OverflowError`; inside a URL this prevents its OPEN
instead of retaining the expression as documented. **Fix:** contain arithmetic
and transformation errors per expression, preserve the placeholder, and emit
a redacted diagnostic while continuing the remaining workflow.

### P2-19: Uppercase URL schemes are corrupted

**Location:** [Smart URL normalization](../core/parser/smart_parser.py).

`HTTPS://example.com/path` becomes `https://HTTPS://example.com/path`.
**Fix:** recognize schemes case-insensitively before adding HTTPS and test
mixed-case values through execution.

### P2-20: Normal logs reveal calendar payloads

**Location:** [Smart title logging](../core/parser/smart_parser.py),
[Plus validation logging](../core/parser/plus_parser.py),
[TYPE stub logging](../runtime/command_executor.py).

Captured non-debug logs contain a URL query token, the full invalid command
and literal typed text. **Fix:** log verb, location and error category rather
than payload; use synthetic secret sentinels in leakage tests. Debug mode must
not silently waive the repository's privacy policy.

### P2-21: HTML cleanup modifies plain script content

**Location:** [Calendar description normalization](../infra/calendar/normalize.py).

Fenced AppleScript containing `return "a < b > c"` becomes `return "a  c"`
because a broad tag regex strips the comparison-like text. **Fix:** preserve
plain code and separate markup processing from script payloads; test plain,
HTML-wrapped and entity-escaped scripts through repeated normalization.

### P2-22: Calendar selection accepts invalid indices and omits pages

**Location:** [`ensure_calendar_selection`](../cli/onboarding.py).

A mocked input of `0` selects the last calendar; negative numbers can select
from the end too. Static inspection also shows only one calendar-list page is
read. **Fix:** validate `1 <= index <= count`, deduplicate selections, and
follow page tokens. Never silently monitor a different calendar than selected.

### P2-23: Smart test preview hides the URL that would execute

**Location:** [`_print_parsed_summary`](../cli/main.py).

`parse('https://example.com @chrome')` produces dictionary entries, but the
preview reads attributes and prints `URL: (no url)`. **Fix:** use the actual
entry schema and test the preview against resolved targets without executing
them. A review step must reveal the target before asking for permission.

### P2-24: A migration test writes into the developer's real data directory

**Location:** [migration test](../tests/test_v4_user_settings.py),
[settings backup path](../core/settings_reader.py).

The fixture patches several paths but leaves `DATA_DIR` unchanged. A guarded
run intercepted a write to the checkout's `data/settings.py.bak`; it passes in
the disposable copy precisely because that directory is disposable.

**Fix:** redirect every consumed path, including backups, and enforce an IO
boundary in tests so missing mocks fail safely. Assert that original data,
tokens and LaunchAgents remain untouched.

## What The Existing Repairs Already Address

The reviewed baseline contains prior fixes for event trust on daemon/manual
run-event paths, deep-link and result-handler restrictions, screenshot scope
rejection, HIDE fallback, JavaScript bridge deadlines, popover Run Now reentry,
AppleScript escaping, and menubar lock/recovery handling. Those are not
re-reported as wholly absent. The findings above identify residual paths or
incomplete integration, such as the separate test runner and daemon installer.

## Repair And Regression Plan

1. **Contain unsafe dispatch first:** P1-01 through P1-04. Add forbidden-action
   assertions before touching code; use complete parse/resolve/execute tests.
2. **Make execution observable and exclusive:** P1-05/P1-06 plus P2-06/P2-09.
   Verify the concurrent result/job work against mixed failures, restart,
   duplicate launches and cancellation of descendants. Agree retry semantics
   before enabling automatic retries of partially completed side effects.
3. **Preserve user data:** P1-07 and P2-01 through P2-04/P2-11/P2-24. Test
   upgrades and preference writes with synthetic populated installations,
   separate interpreters and actual competing processes.
4. **Finish recovery UX:** P2-05 through P2-13 and P2-22/P2-23. Unit-test bridge
   results and draft state, then perform native-host confirmation, delayed
   picker, managed launch/reboot and permissions acceptance with approval.
5. **Close parser/privacy contracts:** P2-14 through P2-21. Use paired syntax
   variants, malformed inputs and synthetic privacy sentinels. Assert both the
   requested action arguments and that unrelated actions still run.
6. **Release gate:** run clean Python-version CI and Node checks, verify
   documentation/examples against the final commit, and record manual macOS
   evidence separately. Do not equate a green unit suite with launch clearance.

The most important coverage gap is entry-point integration: trust, settings,
failure results and native behavior are often tested at individual handlers
but not through the whole user action that supplies their inputs.

## Documentation Updated In This Audit

- README: Python minimum, correct install paths, destructive-reinstall warning,
  actual REPL input, trust caveat and removal of an exactly-once implication.
- Testing guide: correct state mock target, migration isolation caveat, actual
  CI/pre-commit behavior and native acceptance boundaries.
- Menubar guide/readiness memo: current cached-status and long-job limitations;
  mark historical readiness guidance as historical.
- Playbooks: user settings/aliases belong in sidecar files, not tracked defaults;
  explain unimplemented actions and current trigger-window defaults.
- Roadmap and agent handoff: prioritize verified reliability work and distinguish
  implementation presence, planned backends and release acceptance.

As the concurrent fixes land, replace temporary README/guide caveats only after
their regression evidence exists. Retain this report as a dated audit record.
