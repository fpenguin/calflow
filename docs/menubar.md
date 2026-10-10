# CalFlow Menu Bar Companion

The native macOS companion shows a 30-hour timeline, runnable missed events
from the last 12 hours, manual Run Now buttons, Playbooks, Settings, activity
logs and lifetime stats. The month/day icon has a Calendar Plus fallback.

## Install And Open

From the CalFlow folder:

```bash
.venv/bin/python -m cli.main menubar-install
.venv/bin/python -m cli.main menubar-status
```

Installation enables the companion now and at future logins. It upgrades an
older registration to the current recovery policy.

The companion and calendar automation are separate:

| Command | Controls |
| --- | --- |
| start / stop / restart | Calendar automation, label `com.calflow` |
| menubar-install | Install/upgrade the companion's login registration and start it |
| menubar-start | Open the companion; repair an old registration if needed |
| menubar-restart | Stop and start the companion |
| menubar-stop | Stop the companion for this login session |
| menubar-uninstall | Remove its login registration |
| menubar-status | Report registration, process/lock state and log paths |
| menubar | Run directly in the foreground; by itself does not install a login item |

Prefix commands with `.venv/bin/python -m cli.main`.
The **Quit** button closes only the companion. Calendar automation continues.
Use `menubar-start` to reopen it immediately.

## Login And Recovery

The per-user registration lives at:

```text
~/Library/LaunchAgents/com.calflow.menubar.plist
```

It runs in the logged-in graphical session (`Aqua`), starts at login
(`RunAtLoad`), and restarts after an unsuccessful exit
(`KeepAlive.SuccessfulExit=false`). Deliberate Quit exits cleanly and stays
closed until the next login or explicit start. Restart attempts are throttled
to avoid a rapid failure loop.

Installation uses `launchctl enable` and `bootstrap gui/<uid>`; stopping uses
`bootout`. These settings follow macOS's
[LaunchAgent lifecycle](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

If the icon is missing:

1. Run `.venv/bin/python -m cli.main menubar-install` from the project folder.
2. Inspect `menubar-status`: `loaded` means the job is registered, while
   `lock.alive` means its process is running. Registration alone is insufficient.
3. Inspect `data/menubar.err.log` for a missing dependency or startup exception.
4. Keep the installed project and its `.venv` at the registered path. After
   moving the folder or replacing Python, reinstall dependencies and rerun
   `menubar-install`.
5. If macOS has disabled the background item, re-enable it in System Settings
   and retry installation.

An actual reboot/login check is still required for final machine-level
acceptance; a process restart alone does not test reboot timing.

Only one instance is intended to run. The PID lock is
`/tmp/calflow_menubar.lock`. A live instance does not lose ownership merely
because it has been running longer than seven days.

## Menu Behavior

- **Timeline:** up to five nearby events, with priority for the next runnable
  event and tomorrow's events inside the lookahead.
- **View Event:** opens the source event URL in the default browser. With no
  URL, opens Google Calendar. CalFlow never edits the calendar event.
- **Run Now:** executes that occurrence and records completion, preventing
  automatic replay. Explicit manual reruns are still possible. Individual
  action failures are not yet aggregated: a handled backend failure can still
  mark the event complete. Inspect the activity log when an action did not occur.
- **Missed Automations:** recent runnable events not recorded as completed.
  View more currently opens the activity log; it is not a full missed-event browser.
- **Pause/Resume:** controls background automation, not the companion.
- **Playbooks:** opens the editor; Try it executes locally.
- **Settings:** opens the preferences window at roughly 75% of the current
  screen's usable height.
- **Tip Dev:** opens the support page.

The page refreshes on show and every 30 seconds, including while the companion
is running with its popover closed. A usable cached feed can be shown when
calendar refresh fails, with a visible stale-data banner.

Run Now remains disabled for an in-flight event across menu rerenders. Native
workers allow 60 seconds for manual runs and 20 seconds for other subprocess
operations; JavaScript waits slightly longer so it can receive their errors.
Longer workflows still need a persistent execution/job design.

## Settings And Files

Settings edits are validated and saved in `data/user_settings.json`; aliases
use `data/user_targets.json`. Tracked `config/settings.py` contains defaults
and advanced settings that are not all exposed in the GUI.

Apply & restart may restart automation after a change. The current
**Auto-start at login** setting controls daemon loading; its persistent
login semantics still need separation from the Pause control. It does not
install or control the menu bar companion.

Diagnostics and Copy to Clipboard are at the bottom of Advanced.
Accessibility and Apple Events probes are separate from Screen Recording
permission. Permissions attach to the Python/osascript binaries used by this
checkout until CalFlow has a signed app bundle.

| File | Purpose |
| --- | --- |
| cli/menubar.py | Native status item, popover/windows and message bridge |
| cli/menubar_launchd.py | Companion installation/start/stop/recovery |
| runtime/menubar/popover.html | Main menu |
| runtime/menubar/recipes.html | Playbooks editor (internal filename retained) |
| runtime/menubar/settings.html | Preferences |
| data/my_recipes.json | Saved playbooks |
| data/run.log | Activity log |
| data/stats.json | Counts and weighted time-saved estimate |

Time saved is an estimate from action counts, not measured elapsed time.
Default weights are in `core/stats.py`; advanced overrides use
`STATS_ACTION_WEIGHTS`.

## JSON And Native Bridge

CLI endpoints include `status`, `stats`, `upcoming`, `missed`,
`popover-feed`, `run-event <id>`, `recipes`, `save-recipe`, `delete-recipe`,
`run-script`, `settings`, `apply-settings`, `targets`, `apply-targets` and
`daemon-start|stop|restart`.

Write operations use stdin JSON, except `run-script`, whose stdin is DSL text.
The native bridge launches the same Python interpreter as the companion and
returns each response to the webview that sent it. Local bridge operations
handle external links, clipboard copy, the folder picker, resizing and Quit.

A resolved bridge promise can contain an error payload. Callers must inspect
`ok`, `success` or `error` rather than treating every response as success.
Playbook execution is a real local action, not a security-isolated sandbox.

## Verification

```bash
.venv/bin/python -m pytest tests/test_v3_menubar_launchd.py tests/test_launchd_lifecycle.py tests/test_v3_menubar_bridge.py
node --test tests/menubar_ui.test.cjs
```

See [QA](QA.md) for the live login/recovery checklist and action support.
