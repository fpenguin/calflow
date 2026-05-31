# 🧰 Daily Setup

## What it does

Open everything you need → exactly where you want it.

- launches your work apps
- splits windows automatically
- sets up multi-monitor layout in seconds

---

## Script

```text
+CalFlow+

open @work
open slack.com @chrome #right(30%) #display(ext)
open notion.so @chrome #left(70%) #display(ext)
run shortcut("Start Focus") input("daily setup")
```

---

## What actually happens

- `@work` → opens your core apps (Chrome, Figma, etc.) on the primary monitor
- Slack → right side (30%) on the **first external monitor**
- Notion → left side (70%) on the **first external monitor**
- Start Focus → runs your Apple Shortcut for focus mode
- everything launches in one run — no dragging windows

> The bare `#display` is **portable** — it works whether you're at your
> desk, a different desk, or laptop-only. For a stationary setup with
> a known arrangement you can also use `#display(2)` (numeric, 1-based)
> or `#display("Samsung S90D")` (substring match).
> Run `python3 -m cli.main display` to see your current monitors.

---

## Why this matters

Instead of:

❌ opening apps one by one
❌ dragging windows around
❌ fixing layout every morning

You get:

✅ consistent setup
✅ instant workspace
✅ zero friction start

---

## Real-life setups

### 💻 Single monitor (simple)

```text
open slack.com #right(30%)
open notion.so #left(70%)
```

→ Slack side panel + main workspace

---

### 🖥 Dual monitor (common)

```text
+CalFlow+

open @work
open slack.com #right(30%) #display(ext)
open notion.so #left(70%) #display(ext)
run shortcut("Start Focus") input("work")
```

→ work apps on main screen
→ communication + notes on the external monitor
→ portable: works at home or work without changes

---

### 📊 Deep work mode

```text
open notion.so #full
```

→ full-screen focus, no distractions

---

### 📈 Trading / dashboards

```text
open dashboard1.com #grid(1@2x2)
open dashboard2.com #grid(2@2x2)
open dashboard3.com #grid(3@2x2)
open dashboard4.com #grid(4@2x2)
```

→ instant multi-panel layout

---

## Customize it

### Change your apps

Edit `@work` in `config/settings.py`:

```python
TARGETS = {
    "@work": ["Google Chrome", "Notion", "Figma"],
    "@chrome": "Google Chrome",
}
```

→ this becomes your one-command launcher

---

### Adjust layout

```text
#left(70%)   → main workspace
#right(30%)  → side panel
#full        → fullscreen
```

→ tweak once, reuse forever

---

## Mental model

- `open` = launch
- `@work` = bundle
- `#left / #right` = layout
- `#display` = first external monitor (or `#display("Name")` / `#display(N)`)

---

## Tip

Start with 2 apps.

Once it clicks, scale it to:
- multiple monitors
- full workflows
- entire workdays

---

# 💡 Aha

**"One command replaces your entire morning setup."**
