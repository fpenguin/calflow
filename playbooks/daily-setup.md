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

open @work #display(1)
open slack.com @chrome #right(30%) #display(2)
open notion.so @chrome #left(70%) #display(2)
```

---

## What actually happens

- `@work` → opens your core apps (Chrome, Figma, etc.)  
- Slack → right side (30%) on display 2  
- Notion → left side (70%) on display 2  
- everything launches in one run — no dragging windows  

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
open @work #display(1)
open slack.com #right(30%) #display(2)
open notion.so #left(70%) #display(2)
```

→ work apps on main screen  
→ communication + notes on second screen  

---

### 📊 Deep work mode

```text
open notion.so #full
```

→ full-screen focus, no distractions  

---

### 📈 Trading / dashboards

```text
open dashboard1.com #grid(2x2@1)
open dashboard2.com #grid(2x2@2)
open dashboard3.com #grid(2x2@3)
open dashboard4.com #grid(2x2@4)
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
- `#display` = monitor  

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