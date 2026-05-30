# 🚀 CalFlow

**Turn your calendar into an automation engine.**

Stop opening the same apps.  
Stop arranging the same windows.  
Stop repeating the same workflows.

Put instructions in your calendar → CalFlow executes them.

---

## ⚡ What it does (in 10 seconds)

CalFlow reads your calendar event and automatically:

- opens links and apps  
- arranges your workspace  
- clicks, types, and navigates  
- captures screenshots and saves files  

👉 If it’s scheduled, it happens.

---

## 🚀 Install (first-time setup)

**One-line install (recommended):**

```bash
curl -fsSL https://raw.githubusercontent.com/<you>/calflow/main/scripts/install.sh | bash
```

**Manual install:**

```bash
git clone <repo> ~/calflow
cd ~/calflow
./scripts/setup.sh                   # venv + pip + dirs
```

**Connect your Google Calendar:**

1. Console → APIs & Services → Credentials → OAuth Client ID → **Desktop App**
2. Download `credentials.json` and place it at `secrets/credentials.json`
3. Run setup:

```bash
source .venv/bin/activate
python3 -m cli.main setup            # 4 steps: OAuth → calendars → daemon → password manager
python3 -m cli.main status           # check daemon
python3 -m cli.main display          # list connected monitors + #display(ext) syntax
```

Try it without waiting for an event:

```bash
python3 -m cli.repl
```

---

## 🎯 The problem

Your calendar already knows:

- when you meet  
- what tools you need  
- what context matters  

But execution is still manual:

❌ open → resize → switch → repeat  
❌ same setup, every time  

---

## ✅ The fix

CalFlow turns your calendar into:

> a **deterministic execution layer**

You define what should happen.  
CalFlow does it — exactly, every time.

---

## ✨ Two ways to use it

---

### 🟢 Smart Mode (zero setup)

Paste links. That’s it.

```text
zoom.us @chrome #left(30%)
notion.so @safari #right(70%)
```

**Result:**

- Zoom opens in Chrome (left 30%)  
- Notion opens in Safari (right 70%)  
- windows arranged automatically  

👉 No scripting. Just links + layout.

---

### 🔵 Plus Mode (full automation)

Add `+CalFlow+` → unlock everything.

```text
+CalFlow+

open @work #display(ext)
focus @chrome title("Inbox")
click text("Export")
screenshot
save source(clipboard) to("~/Desktop/export_{now > YYYY-MM-DD}.png")
```

**Result:**

- full workspace opens  
- correct tab is focused  
- export is triggered  
- screenshot is captured  
- file is saved automatically  

👉 No clicking. No switching. No friction.

---

## 🔥 Real use cases

---

### 🧑‍💻 Meeting setup (automatic)

```text
zoom.us @chrome #left(60%)
figma.com @chrome #right(40%)
slack.com @chrome #display(ext)
```

→ everything ready before the call  

---

### 📊 Daily workspace

```text
+CalFlow+

open @work
open slack.com #right(30%)
open notion.so #left(70%)
```

→ instant work environment  

---

### 📈 Automated reporting

```text
+CalFlow+

open "report.com?start={now-1mo > start_of_month}&end={now-1mo > end_of_month}"
screenshot
save source(clipboard) to("~/Reports/{now > YYYY-MM}.png")
```

→ reports generated automatically  

---

### 🎯 Focus mode

```text
+CalFlow+

hide except(@work)
focus @chrome #full
```

→ distraction-free setup  

---

### 🧰 Trusted run backends

`run` is backend-gated. Today CalFlow ships four working backends for
self-authored events:

```text
+CalFlow+

run -btt BTT-ClaudeCoworkTryAgain
run -btt {"BTT-ClaudeCoworkTryAgain"}
```

The braced form is literal. Use it when the BetterTouchTool trigger is
actually named `{"BTT-ClaudeCoworkTryAgain"}`.

Inline AppleScript is supported for small local automations:

```text
+CalFlow+

run -applescript
tell application "Finder"
  activate
end tell
end run
```

macOS Shortcuts can be run by name, with optional text input:

```text
+CalFlow+

run -shortcut "Start Focus"
run -shortcut "Start Focus" "deep work"
```

Alfred workflows can be run through Alfred External Triggers. Alfred
requires the workflow bundle id and external trigger id, not just the
workflow display name:

```text
+CalFlow+

run -alfred "com.example.workflow" "try-again"
run -alfred "com.example.workflow" "try-again" "optional argument"
run -alfred "com.example.workflow/try-again" "optional argument"
```

`run "~/script.sh"`, `run -script`, `run -shell`, and `run -terminal`
are reserved/disabled unless a future backend implements them and the
settings allow them.

Run backend errors are surfaced in the logs and, by default, as macOS
notifications. This includes blocked backends, missing trigger names,
AppleScript failures, Shortcut failures, and local URL-launch failures
for BTT/Alfred. Alfred's URL scheme does not report workflow-internal
failures back to CalFlow, so those still need to be checked in Alfred.

---

## 🧠 How it works

- each calendar event = one execution  
- each line = one action  
- runs automatically before the event  

Default:

```text
~5 minutes before start
```

Configurable in:

```text
config/settings.py
```

---

## 🧩 Simple syntax (you only need this)

| Symbol | Meaning |
|--------|--------|
| `@chrome`, `@safari` | **target** — which app handles a URL |
| `@work`, `@comm` | **bundle** — a list of things to open in one shot |
| `#` | layout / display |
| `()` | arguments |
| `{}` | dynamic values or keys |

> A bundle (`@work`) is its own argument and can't be combined with
> another one (`open zoom.us @work` is invalid). See `docs/DSL_SPEC.md §2.1`.

---

### Examples

```text
click text("Submit")
press {cmd+shift+tab}
#left(50%)
{now-7d}
open @work                      # expand bundle → multiple opens
open zoom.us @chrome            # URL + target routing
```

---

## 🔒 Safety model

Calendar text can execute local automation, so CalFlow treats invite
origin as a permission boundary.

Default policy:

- self-authored events can execute
- third-party calendar invites are blocked
- trusted domains/emails are empty by default
- `run` backends are allowed by trust level

Configure allowlists in `config/settings.py`:

```python
TRUSTED_INVITE_DOMAINS = set()
TRUSTED_INVITE_EMAILS = set()

ALLOW_RUN_BACKENDS_SELF = {"btt", "alfred", "shortcut", "applescript"}
ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN = {"shortcut"}
ALLOW_RUN_BACKENDS_TRUSTED_EMAIL = {"shortcut"}
RUN_ERROR_NOTIFICATIONS = True
```

Examples:

```python
TRUSTED_INVITE_DOMAINS = {"company.com"}
TRUSTED_INVITE_EMAILS = {"assistant@trusted-vendor.com"}
ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN = {"shortcut"}
```

The trust gate applies to daemon auto-runs and manual `run-event`
execution from the menubar/CLI. Local REPL and recipe sandbox runs are
treated as user-initiated local actions.

---

## 🚀 Why this matters

CalFlow removes:

❌ repetitive setup  
❌ context switching  
❌ manual workflows  

And replaces it with:

✅ predictable execution  
✅ reusable workflows  
✅ automation built into your calendar  

---

## 🧠 Mental shift

Your calendar stops being:

📅 a reminder tool  

and becomes:

⚙️ an execution system  

---

## 💡 Aha

**"If it’s on your calendar, it should just happen."**
