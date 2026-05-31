# 🎯 Focus Mode

## What it does

Remove noise → keep only what matters.

- closes distractions
- hides non-essential apps
- brings one app into full focus

---

## Script (simple)

```text
+CalFlow+

close "Spotify"
hide ["Discord","WhatsApp"]
focus "Google Chrome" #full
```

---

## Script (clean slate)

```text
+CalFlow+

hide except(@work)
focus @chrome #full
```

---

## What actually happens

- Spotify is closed completely
- Discord + WhatsApp are hidden
- Chrome becomes full screen
- only your work context remains

---

## Why this matters

Instead of:

❌ notifications pulling your attention
❌ switching between apps
❌ cluttered screens

You get:

✅ single-task focus
✅ distraction-free environment
✅ faster deep work

---

## Real-life setups

### 🧠 Deep work (writing / coding)

```text
+CalFlow+

hide except(active)
open notion.so #full
run btt("Hard Focus")
```

→ full-screen thinking space
→ optional BetterTouchTool focus preset

---

### 💼 Work-only mode

```text
+CalFlow+

hide except(@work)
focus @chrome #left(70%)
focus @slack #right(30%)
```

→ work apps only, clean split layout

---

### 📞 Meeting mode

```text
+CalFlow+

hide except(active)
open zoom.us #full
```

→ no distractions during calls

---

### 🔕 Hard focus (max isolation)

```text
+CalFlow+

close "Spotify"
close "Slack"
close "Discord"
hide except(active)
open notion.so #full
```

→ nothing left except your task

---

## Customize

### Close different apps

```text
close "Slack"
close "Telegram"
close "Spotify"
```

→ remove your personal distractions

---

### Control what stays visible

```text
hide except(@work)
```

→ only keep your defined work apps

---

### Focus layout

```text
#full        → full screen
#left(70%)   → main area
#right(30%)  → side panel
```

---

## Mental model

- `close` = kill the distraction
- `hide` = temporarily remove
- `focus` = bring forward
- `#full` = eliminate everything else

---

## Tip

Start with:

```text
hide except(@work)
focus @chrome #full
```

Then tighten from there.

---

# 💡 Aha

**"Focus Mode turns your entire computer into a single-purpose machine."**
