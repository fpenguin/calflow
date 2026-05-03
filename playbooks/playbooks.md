# 📚 CalFlow Playbooks

## What this is (in plain English)

Playbooks are **ready-to-run automations**.

Copy → paste → done.

They turn your calendar events into actions like:

- opening apps  
- arranging windows  
- clicking buttons  
- capturing reports  

---

## Why this matters

Instead of:

❌ opening the same apps every day  
❌ setting up dashboards manually  
❌ taking repetitive screenshots  

You get:

✅ one event → full setup  
✅ consistent workflow  
✅ zero manual repetition  

---

# 🧠 What is a Playbook?

A Playbook = a **script that runs automatically from your calendar**.

- runs top → bottom  
- same input → same result  
- safe to edit  
- failures don’t stop the rest  

---

# 🚀 How to use (3 steps)

## 1. Create a calendar event

Use Google / Apple Calendar.

Pick when you want it to run.

---

## 2. Paste this

```text
+CalFlow+

open @work #display(ext)
focus @chrome title("Inbox")
click text("Export")
```

---

## 3. Done

At runtime:

- CalFlow reads the event  
- runs each line  
- your setup happens automatically  

---

## ⚠️ Critical rule

You MUST include:

```text
+CalFlow+
```

Without it:

- runs in Smart Mode  
- commands like `click`, `type`, `press` will NOT run  

---

# ⏱ When does it run?

- typically ~5 minutes before event start  
- configurable in `config/settings.py`  

---

# 🔥 What you can automate (real examples)

---

## 🧰 Daily setup

```text
+CalFlow+

open @work
open slack.com #right(30%)
open notion.so #left(70%)
```

→ full workspace ready instantly  

---

## 🎯 Focus mode

```text
+CalFlow+

hide except(@work)
focus @chrome #full
```

→ distraction-free environment  

---

## ⚡ Quick dashboards

```text
+CalFlow+

open analytics.com #left(50%)
open logs.com #right(50%)
open status.com #display(ext)
```

→ everything visible at once  

---

## 📸 Screenshot capture

```text
+CalFlow+

focus @chrome title("Slack")
screenshot
save source(clipboard) to("~/Desktop/slack_{now}.png")
```

→ capture + save automatically  

---

## 📊 Weekly report

```text
+CalFlow+

open "report.com?start={now-7d}&end={now}"
screenshot
save source(clipboard) to("~/Reports/weekly_{now > YYYY-MM-DD}.png")
```

→ automated reporting  

---

# ⚙️ Aliases (important but simple)

You’ll see things like:

```text
@work
@chrome
@safari
```

These are shortcuts.

---

## Where they live

```python
# config/settings.py
TARGETS = {
    "@work": ["Google Chrome", "Notion", "Figma"],
    "@chrome": "Google Chrome",
}
```

---

## What they do

```text
open @work
```

→ becomes:

```text
open "Google Chrome"
open "Notion"
open "Figma"
```

---

## Rule

- must start with `@`  
- must exist in settings  
- if missing → skipped  

---

# 🧩 Customize anything

You can safely change:

---

## Apps

```text
@chrome → @safari
```

---

## Layout

```text
#left(70%)  
#right(30%)
#full
```

---

## Timing

```text
wait 3s
```

---

## File paths

```text
"~/Desktop/"
"~/Reports/"
```

---

## Dynamic data

```text
{now}
{now-7d}
{now > YYYY-MM-DD}
```

---

# ⚠️ Common mistakes

---

## Missing +CalFlow+

```text
open @work
```

→ ❌ commands won’t run  

---

## Wrong target

```text
open chrome
```

→ ❌ invalid  

✔ use:

```text
open @chrome
open "Google Chrome"
```

---

## Wrong syntax

```text
click text="Submit"
```

→ ❌ invalid  

✔ use:

```text
click text("Submit")
```

---

## UI too slow

```text
wait 3s
```

→ fixes timing issues  

---

# 💡 Tips that actually matter

---

## Start small

Don’t automate everything at once.

---

## Be explicit

```text
focus @chrome
```

is better than guessing  

---

## Use wait when needed

Prevents flaky behavior  

---

## Prefer text()

```text
click text("Submit")
```

Use selector only if needed  

---

## Use dynamic dates

```text
{now}
{now-7d}
```

→ removes manual work  

---

# 🧠 Mental model

Playbooks are:

- small scripts  
- triggered by time  
- predictable  
- repeatable  

---

# 🧭 Philosophy

You don’t need to learn the DSL.

Just:

- copy  
- tweak  
- run  
- improve  

---

# 💡 Aha

**"If it’s on your calendar, it should just happen."**