# CalFlow

**CalFlow gets your Mac ready before each calendar event.**

CalFlow watches your Google Calendar and runs small local automations
before an event starts. It can open meeting links, choose a browser,
arrange windows, start Apple Shortcuts, trigger BetterTouchTool, or fire
an Alfred External Trigger.

Think of it as a bridge:

```text
calendar event -> CalFlow -> your Mac is ready
```

Example: five minutes before a meeting, CalFlow can open Zoom on the
left side of your screen and the agenda on the right side.

CalFlow is currently a **macOS beta** for people who are comfortable
using a terminal during setup.

---

## What CalFlow Is For

CalFlow is useful when your calendar already describes what you are
about to do, but your Mac still waits for you to set everything up by
hand.

Common examples:

- Open Zoom, Google Meet, or Teams before a meeting.
- Open the agenda, notes, CRM, dashboard, or GitHub repo next to it.
- Start a Focus mode or Apple Shortcut for deep work.
- Trigger a BetterTouchTool or Alfred workflow from a calendar event.
- Prepare the same workspace every week for recurring routines.

CalFlow is **not** a calendar replacement. It does not edit your Google
Calendar. It reads upcoming events and uses them as local automation
instructions.

---

## The Simplest Example

Add this to a calendar event description:

```text
zoom.us @chrome #left(50%)
docs.google.com @chrome #right(50%)
```

When the event is about to start, CalFlow reads those two lines as:

1. Open Zoom in Chrome.
2. Put it on the left half of the screen.
3. Open Google Docs in Chrome.
4. Put it on the right half of the screen.

That is called **Smart Mode**. It is the best place to start.

---

## A More Explicit Example

For a repeatable workflow, add a `+CalFlow+` block:

```text
+CalFlow+

open https://zoom.us/j/123456789 @chrome #left(60%)
open https://docs.google.com/document/d/agenda @chrome #right(40%)
run shortcut("Start Focus") input("meeting")
```

That is called **Plus Mode**. Use it when the order matters or when you
want to run a Shortcut, BetterTouchTool trigger, Alfred workflow, or
AppleScript.

---

## Install

CalFlow requires macOS and Python. It also requires Google Calendar API
credentials because Google asks each local calendar app to authenticate
with OAuth.

Install from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/fpenguin/calflow/main/scripts/install.sh | bash
```

Or install manually:

```bash
git clone https://github.com/fpenguin/calflow.git ~/calflow
cd ~/calflow
./scripts/setup.sh
```

Then connect Google Calendar:

1. In Google Cloud Console, create an OAuth Client ID for a Desktop App.
2. Download the file as `credentials.json`.
3. Put it here:

```text
secrets/credentials.json
```

4. Run setup:

```bash
source .venv/bin/activate
python3 -m cli.main setup
python3 -m cli.main status
```

If setup works, CalFlow can see your upcoming calendar events.

---

## First Run Checklist

After installation, try these commands:

```bash
source .venv/bin/activate
python3 -m cli.main --version
python3 -m cli.main status
python3 -m cli.main display
python3 -m cli.repl
```

Use the REPL to test a CalFlow block without waiting for a real calendar
event:

```text
+CalFlow+

open https://github.com/fpenguin/calflow @chrome #left(60%)
```

If that opens and positions a browser window, your local automation path
is working.

---

## Menu Bar Companion

CalFlow includes a small menu bar companion for status, upcoming events,
manual run buttons, playbooks, and settings.

Install it with:

```bash
python3 -m cli.main menubar-install
python3 -m cli.main menubar-status
```

Look for the month/day icon in the macOS menu bar, for example `JUN`
over `3`.

The menu bar app is separate from the background automation loop:

- the daemon watches calendar events and runs automations
- the menu bar app shows status and gives you manual controls

---

## Two Ways To Write Automations

### 1. Smart Mode

Smart Mode is just links plus lightweight tags.

```text
zoom.us @chrome #left(40%)
notion.so @safari #right(60%)
docs.google.com #display(ext)
appstoreconnect.apple.com @chrome display(2) grid(1@2x2) profile(3)
```

Use Smart Mode when the calendar event is mostly links.

Common tags:

| Tag | Meaning |
| --- | --- |
| `@chrome` | Open in Chrome |
| `@safari` | Open in Safari |
| `#left(50%)` | Put the window on the left half |
| `#right(50%)` | Put the window on the right half |
| `#full` | Fill the display |
| `#display(ext)` | Prefer an external display |
| `grid(1@2x2)` | Put the window in cell 1 of a 2-by-2 grid |
| `profile(3)` | Open Chrome profile 3 |

For URL lines, layout/session tags can be written either way:
`#grid(1@2x2)` and `grid(1@2x2)` mean the same thing.

### 2. Plus Mode

Plus Mode starts with `+CalFlow+` and uses one command per line.

```text
+CalFlow+

open https://github.com/fpenguin/calflow @chrome #left(60%)
open https://linear.app @chrome #right(40%)
wait 2
screenshot
```

Use Plus Mode when you want a workflow, not just a list of links.

---

## Action Verbs

In Plus Mode, each line starts with an action verb. These are the main
verbs CalFlow understands today:

| Verb | What it does | Example |
| --- | --- | --- |
| `open` | Opens a URL, app, file, or bundle. | `open https://zoom.us @chrome #left(50%)` |
| `focus` | Brings an app or matching window to the front. | `focus @chrome title("Inbox")` |
| `hide` | Hides apps without quitting them. | `hide @slack` |
| `close` | Quits/closes apps; requires an explicit target. | `close @spotify` |
| `wait` | Pauses the workflow briefly. | `wait 5s` |
| `screenshot` | Captures to the clipboard by default, or to a file via `to("path")`. | `screenshot` · `screenshot to("~/Desktop/meeting.png")` |
| `click` | Clicks by visible text, selector, or position. Supports `button(right)` and `count(2)` for double-click. | `click text("row") button(right)` |
| `drag` | One mouse gesture from point to point. | `drag from(100,200) to(300,400)` |
| `type` | Types text into the focused app/window. | `type("hello")` |
| `press` | Sends a key or keyboard shortcut. | `press {cmd+k}` |
| `copy` | Copies the current selection, or places literal text on the clipboard. | `copy` · `copy("hello")` |
| `paste` | Pastes clipboard contents. | `paste` |
| `save` | Saves a source, such as clipboard or run result, to a file. | `save source(clipboard) to("~/Desktop/file.txt")` |
| `run` | Runs an external automation backend. | `run shortcut("Start Focus")` |

Smart Mode does not require verbs. A plain URL line is treated like
`open` automatically.

---

## Running Local Tools

CalFlow can trigger a few local automation systems.

### Apple Shortcuts

```text
+CalFlow+

run shortcut("Start Focus")
run shortcut("Open Deep Work Stack") input("calflow")
```

### BetterTouchTool

```text
+CalFlow+

run btt("BTT-ClaudeCoworkTryAgain")
```

The trigger name should match the BetterTouchTool trigger you created.

### Alfred External Trigger

Alfred needs the workflow bundle ID and the external trigger ID. The
workflow display name alone is not enough.

```text
+CalFlow+

run alfred("com.example.workflow", "try-again") input("meeting prep")
```

Combined form is also supported:

```text
+CalFlow+

run alfred("com.example.workflow/try-again") input("meeting prep")
```

### Inline AppleScript

Small AppleScripts can live directly in the calendar event:

```text
+CalFlow+

run applescript if(error) notify(result)
+++
display notification "Meeting setup complete"
+++
```

The `+++` delimiters keep AppleScript visually separate from CalFlow
commands.

---

## Error Handling

Run backends can report their result to a notification, the clipboard,
or a file.

```text
+CalFlow+

run applescript if(error) notify(result) if(error) copy(result) if(error) save to("~/Logs/calflow-last-error.txt")
+++
error "Demo failure"
+++
```

You can also react to successful runs:

```text
+CalFlow+

run shortcut("Start Focus") if(success) notify("Focus mode started")
```

Run backend errors are logged and, by default, shown as macOS
notifications. This includes blocked backends, missing trigger names,
AppleScript failures, Shortcut failures, and local URL-launch failures
for BetterTouchTool and Alfred.

Alfred's URL scheme does not report workflow-internal failures back to
CalFlow, so those still need to be checked in Alfred.

---

## Dynamic Dates

Dynamic expressions are resolved when the event runs. They are useful
for recurring reports and dashboards.

```text
+CalFlow+

open "https://reports.example.com/monthly?start={now-1mo > start_of_month}&end={now-1mo > end_of_month}"
```

Examples:

| Expression | Meaning |
| --- | --- |
| `{now}` | Current date/time |
| `{now-7d}` | Seven days ago |
| `{now-1mo > start_of_month}` | Start of last month |
| `{now > YYYY-MM-DD}` | Format the current date |

---

## Safety Model

Calendar automation is powerful, so CalFlow is conservative by default.

Default policy:

- events you created can run automations
- third-party calendar invites are blocked
- trusted domains and trusted emails are empty by default
- run backends are allowed by trust level
- arbitrary shell/script execution is not part of the default grammar

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
execution from the menu bar or CLI. Local REPL and recipe sandbox runs
are treated as user-initiated local actions.

---

## What Works Today

| Feature | Status |
| --- | --- |
| Smart Mode URL extraction | Works |
| Browser/app target tags like `@chrome`, `@safari` | Works |
| Bundle aliases like `@work` | Works |
| Window layout tags like `#left(50%)` | Works |
| Dynamic dates like `{now-7d}` | Works |
| `open` | Works |
| `wait` | Works |
| `screenshot` | Works — clipboard by default, file via `to("path")`; window/display/area variants still fall back |
| `copy("text")` | Works — literal text straight to the clipboard |
| `run btt(...)` | Works via BetterTouchTool URL scheme |
| `run shortcut(...)` | Works via macOS `shortcuts run` |
| `run alfred(...)` | Works via Alfred External Trigger URL scheme |
| `run applescript` | Works via `osascript` |
| Calendar invite trust gate | Works |
| Run failure notifications | Works, best-effort macOS notifications |
| UI actions like `click`, `drag`, `type`, `press`, bare `copy`, `paste`, `save` | Parsed and routed; backend work continues |

---

## Grammar Cheatsheet

Smart Mode:

```text
https://example.com @chrome #left(50%)
zoom.us @chrome
docs.google.com #display(ext)
```

Plus Mode:

```text
+CalFlow+

open <url|app|bundle> [@target] [#tag ...]
wait <seconds>
screenshot
run btt("<trigger-name>")
run shortcut("<shortcut name>") input("optional input")
run alfred("<workflow.bundle.id>", "<external-trigger-id>") input("optional argument")
run applescript if(error) notify(result)
+++
<script>
+++
```

Common symbols:

| Symbol | Meaning |
| --- | --- |
| `@chrome`, `@safari` | Target app |
| `@work`, `@comm` | Bundle alias |
| `#left(50%)`, `#right(50%)`, `#display(ext)` | Layout/display tags |
| `{now-7d}` | Dynamic value |
| `text("Submit")` | Function-style argument |
| `if(error) notify(result)` | Run-result handler |
| `if(error) save to("~/x.txt")` | Save the latest run error/result |

More detail:

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

Useful commands:

```bash
python3 -m cli.main status
python3 -m cli.main display
python3 -m cli.main menubar-status
python3 -m cli.repl
```

---

## Design Philosophy

CalFlow is built around three ideas:

- Calendar context should be executable when you authored it.
- Automation should be explicit enough to debug at a glance.
- Local execution should be gated, observable, and boringly safe.

If it is on your calendar, your Mac should already be getting ready.
