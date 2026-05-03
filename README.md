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
python3 -m cli.main setup            # OAuth + calendar pick + daemon install
python3 -m cli.main status           # check daemon
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

open @work #display(2)
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
slack.com @chrome #display(2)
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

hide all except @work
focus @chrome #full
```

→ distraction-free setup  

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

- Smart Mode → safe, link-based  
- Plus Mode → fully controlled by you  

Planned:

- domain whitelist  
- permission controls  

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