# CalFlow

**Your calendar already knows what you are about to do. CalFlow prepares
your Mac for it.**

CalFlow turns calendar events into trusted local automations. Put a
small instruction block in an event, and CalFlow can open the right
links, route them to the right apps, trigger BetterTouchTool, run Apple
Shortcuts, fire Alfred External Triggers, or execute small inline
AppleScripts before the event starts.

It is built for the recurring setup work that quietly eats your day:
meeting prep, focus blocks, coding sessions, dashboards, reporting
rituals, and personal Mac workflows that should happen because they are
on the calendar.

```text
+CalFlow+

open https://zoom.us/j/123456789 @chrome #left(60%)
open https://docs.google.com/document/d/agenda @chrome #right(40%)
run -shortcut "Start Focus" "deep work"
run -btt BTT-ClaudeCoworkTryAgain
```

The calendar event becomes the playbook. CalFlow handles the setup.

---

## Why CalFlow

Most calendar events already contain the context for what comes next:
the meeting URL, the agenda, the project, the people, the dashboard, the
tooling. But your Mac still waits for you to do the repetitive part.

CalFlow gives that context an execution layer:

- A sales call can open the CRM, call notes, and meeting link.
- A coding block can start Focus mode and trigger your editor workflow.
- A standup can open Slack, Linear, GitHub, and the team dashboard.
- A recurring report can open the right date-filtered URL.
- A Claude cowork session can fire a BetterTouchTool trigger from the
  calendar.

The goal is not to turn your calendar into a programming language. The
goal is to make the obvious setup happen automatically.

---

## Two Modes

### Smart Mode

Smart Mode is for simple events. Paste links and add lightweight tags.

```text
zoom.us @chrome #left(40%)
notion.so @safari #right(60%)
```

CalFlow reads this as:

- open Zoom in Chrome
- open Notion in Safari
- apply the requested layout tags where supported

Use Smart Mode when the event is mostly links.

### Plus Mode

Plus Mode is for explicit multi-step automations. Add `+CalFlow+`, then
write one command per line.

```text
+CalFlow+

open @work #display(ext)
open https://github.com/fpenguin/calflow @chrome #left(60%)
open https://linear.app @chrome #right(40%)
wait 2
screenshot
```

Use Plus Mode when order matters, when you want run backends, or when
the event should become a repeatable workflow.

---

## V2.0 Examples

### Meeting Prep

```text
+CalFlow+

open https://zoom.us/j/123456789 @chrome #left(55%)
open https://docs.google.com/document/d/agenda @chrome #right(45%)
run -shortcut "Start Focus" "meeting"
```

### Claude Cowork Trigger

```text
+CalFlow+

run -btt BTT-ClaudeCoworkTryAgain
```

If your BetterTouchTool trigger is literally named with braces and
quotes, CalFlow preserves that too:

```text
+CalFlow+

run -btt {"BTT-ClaudeCoworkTryAgain"}
```

### Alfred External Trigger

Alfred requires the workflow bundle id and external trigger id. The
workflow display name alone is not enough.

```text
+CalFlow+

run -alfred "com.example.workflow" "try-again" "meeting prep"
```

Combined form is also supported:

```text
+CalFlow+

run -alfred "com.example.workflow/try-again" "meeting prep"
```

### Apple Shortcuts

```text
+CalFlow+

run -shortcut "Start Focus"
run -shortcut "Open Deep Work Stack" "calflow"
```

### Inline AppleScript

Small AppleScripts can live directly in the calendar event:

```text
+CalFlow+

run -applescript
display notification "Meeting setup complete"
end run
```

### Dynamic Dates

Dynamic expressions resolve at execution time, which makes recurring
events useful for reports and dashboards.

```text
+CalFlow+

open "https://reports.example.com/monthly?start={now-1mo > start_of_month}&end={now-1mo > end_of_month}"
```

---

## What Works Today

| Feature | V2.0 status |
| --- | --- |
| Smart Mode URL extraction | Real |
| Browser/app target tags like `@chrome`, `@safari` | Real |
| Bundles like `@work` | Real |
| Dynamic dates like `{now-7d}` | Real |
| `open` | Real |
| `wait` | Real |
| `screenshot` | Real for standard capture; some variants still fall back |
| `run -btt` | Real via BetterTouchTool URL scheme |
| `run -shortcut` | Real via macOS `shortcuts run` |
| `run -alfred` | Real via Alfred External Trigger URL scheme |
| `run -applescript` | Real via `osascript` |
| Calendar invite trust gate | Real |
| Run failure notifications | Real, best-effort macOS notifications |
| Arbitrary `run "~/script.sh"` / shell | Disabled by default |
| UI actions like `click`, `type`, `press`, `copy`, `paste`, `save` | Parsed and routed; backend work is staged for later releases |

CalFlow is intentionally conservative about local execution. The useful
automation backends are available, but arbitrary shell/script execution
is not enabled by default.

---

## Safety Model

Calendar automation is powerful, so CalFlow treats event origin as a
permission boundary.

Default policy:

- self-authored events can execute
- third-party calendar invites are blocked
- trusted domains and emails are empty by default
- run backends are allowed by trust level
- dangerous arbitrary script/shell execution is disabled by default

Configure trust and backend allowlists in `config/settings.py`:

```python
TRUSTED_INVITE_DOMAINS = set()
TRUSTED_INVITE_EMAILS = set()

ALLOW_RUN_BACKENDS_SELF = {"btt", "alfred", "shortcut", "applescript"}
ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN = {"shortcut"}
ALLOW_RUN_BACKENDS_TRUSTED_EMAIL = {"shortcut"}
RUN_ERROR_NOTIFICATIONS = True
```

Example:

```python
TRUSTED_INVITE_DOMAINS = {"company.com"}
ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN = {"shortcut"}
```

The trust gate applies to daemon auto-runs and manual `run-event`
execution from the menubar or CLI. Local REPL and recipe sandbox runs
are treated as user-initiated local actions.

Run backend errors are logged and, by default, shown as macOS
notifications. This includes blocked backends, missing trigger names,
AppleScript failures, Shortcut failures, and local URL-launch failures
for BTT and Alfred. Alfred's URL scheme does not report
workflow-internal failures back to CalFlow, so those still need to be
checked in Alfred.

---

## Install

One-line install:

```bash
curl -fsSL https://raw.githubusercontent.com/fpenguin/calflow/main/scripts/install.sh | bash
```

Manual install:

```bash
git clone https://github.com/fpenguin/calflow.git ~/calflow
cd ~/calflow
./scripts/setup.sh
```

Connect Google Calendar:

1. In Google Cloud Console, create an OAuth Client ID for a Desktop App.
2. Download `credentials.json`.
3. Place it at `secrets/credentials.json`.
4. Run setup:

```bash
source .venv/bin/activate
python3 -m cli.main setup
python3 -m cli.main status
```

Useful first checks:

```bash
python3 -m cli.main display
python3 -m cli.repl
```

---

## Grammar Cheatsheet

### Smart Mode

```text
https://example.com @chrome #left(50%)
zoom.us @chrome
docs.google.com #display(ext)
```

### Plus Mode

```text
+CalFlow+

open <url|app|bundle> [@target] [#tag ...]
wait <seconds>
screenshot
run -btt <trigger-name>
run -shortcut "<shortcut name>" ["input text"]
run -alfred "<workflow.bundle.id>" "<external-trigger-id>" ["argument"]
run -applescript
<script>
end run
```

Common symbols:

| Symbol | Meaning |
| --- | --- |
| `@chrome`, `@safari` | Target app |
| `@work`, `@comm` | Bundle alias |
| `#left(50%)`, `#right(50%)`, `#display(ext)` | Layout/display tags |
| `{now-7d}` | Dynamic value |
| `text("Submit")` | Function-style argument |

More details:

- [DSL grammar](docs/DSL_GRAMMAR.md)
- [DSL spec](docs/DSL_SPEC.md)
- [Roadmap](docs/roadmap.md)
- [QA guide](docs/QA.md)

---

## How It Runs

CalFlow polls your selected calendars and evaluates upcoming events.
When an event enters the configured trigger window, CalFlow parses the
event text and executes it once.

Default timing is roughly five minutes before the event starts. Timing,
calendar choices, backend allowlists, trusted invite policy, and run
notifications are configured in `config/settings.py`.

For local experimentation:

```bash
python3 -m cli.repl
```

For daemon status:

```bash
python3 -m cli.main status
```

---

## Design Philosophy

CalFlow is built around three ideas:

- Calendar context should be executable when you authored it.
- Automation should be explicit enough to debug at a glance.
- Local execution should be gated, observable, and boringly safe.

If it is on your calendar, your Mac should already be getting ready.
