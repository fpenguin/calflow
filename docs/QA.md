# CalFlow QA Guide

Use the project virtual environment. Automated tests use temporary data and
mocked desktop/calendar actions; manual examples below operate your Mac.

## Automated Checks

```bash
.venv/bin/python -m pytest tests -q
node --test tests/menubar_ui.test.cjs
.venv/bin/python -m ruff check .
.venv/bin/python -m pip check
bash -n scripts/install.sh scripts/setup.sh scripts/typecheck.sh
```

The Python suite covers parsing, validation, resolution, mocked execution,
calendar orchestration, persistence, settings and the native bridge. Node
22+ runs the menu's JavaScript behavior tests. Native AppKit tests skip when
PyObjC is unavailable, so Linux CI alone cannot verify the actual menu icon.

Ruff remains advisory in CI: the repository has pre-existing findings.
A successful test run does not mean lint is clean or all DSL verbs execute.
See [Testing](TESTING.md) for conventions.

## Interactive Checks

```bash
.venv/bin/python -m cli.repl
```

Smart Mode accepts a single URL line. For a multi-line Plus workflow, enter
`:plus`, then the commands, then `EOF` on its own line:

```text
:plus
open https://example.com @chrome left(50%)
wait 2
screenshot to("~/Desktop/calflow-test.png")
EOF
```

Expected: a Chrome window is opened and arranged, followed by a whole-screen
PNG on the Desktop. Screenshot requires macOS Screen Recording permission.
The REPL executes actions; `:ast` displays the last parsed input.

To verify a run error without a real calendar event:

```text
:plus
run applescript if(error) notify(result)
+++
error "Example failure"
+++
EOF
```

Expected: a logged backend failure and a best-effort macOS notification.
A denied backend executes no user-specified result handlers. Invited events
cannot write files through run-result handlers.

## Menu Bar Login And Recovery

```bash
.venv/bin/python -m cli.main menubar-install
.venv/bin/python -m cli.main menubar-status
```

Expected: `loaded: true` and `lock.alive: true`, with the month/day icon in
the menu bar. Installation writes an Aqua-session LaunchAgent with
`RunAtLoad` and `KeepAlive.SuccessfulExit=false`.

Manual acceptance checks:

1. Quit from the menu. The companion stays closed; background automation
   remains independent.
2. Run `menubar-start`. The icon returns without rerunning setup.
3. Log out/in or reboot when convenient. The icon should return after login.
4. Stop/resume background automation from the menu. Refresh must show its
   actual paused/active state.
5. Run a test event once. While it is running, refresh must not re-enable
   its Run Now button.

Crash recovery can be tested by terminating only the verified menubar PID,
then checking that a new PID appears. Do not use broad process-name kills.
The automated suite checks policy generation; an actual reboot is a separate
manual acceptance check.

See [Menubar](menubar.md#login-and-recovery) for missing-icon diagnostics.

## Calendar Integration

After `.venv/bin/python -m cli.main setup`, create your own short test event
in a watched calendar. The default lead time is three minutes unless your
saved settings or an alert modifier change it.

```text
+CalFlow+
open https://example.com @chrome left(50%)
```

Confirm that the event is trusted, in the trigger window, and has not already
been marked complete. Sleeping through the window does not automatically
replay it; check Missed Automations and choose Run Now deliberately.

For a requested display, check inventory first:

```bash
.venv/bin/python -m cli.main display
```

An unavailable explicit display number/name skips layout. External-display
preference (`display(ext)`) may fall back to the primary display.

## Actual Backend Support

| Action | Current behavior |
| --- | --- |
| open, focus, hide, close, wait | Implemented; verify macOS permissions and app-specific behavior |
| Window layouts and Chrome profiles | Implemented; require a valid display and scriptable windows |
| screenshot / screenshot to("path") | Whole-screen capture to clipboard / file |
| Scoped screenshot: active, display, window, area | Rejected without capture until implemented |
| copy("text") | Writes literal text to the clipboard |
| run btt / shortcut / alfred / applescript | Implemented with trust/backend checks |
| Run-result notify/copy/save/append handlers | Implemented; file handlers require self/local execution |
| click, drag, type, press, bare copy, paste, standalone save | Parsed/routed, but side-effect backends are still stubs |
| Arbitrary shell/script-file execution | Unsupported |

BTT and Alfred acknowledge local URL handoff only. CalFlow cannot observe
failures inside a workflow after that handoff. Notifications are best effort.
