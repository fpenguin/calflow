# 📸 Slack Screenshot Capture

## What it does

Capture → save → done.

- focuses your Slack window  
- takes a screenshot  
- saves it automatically with timestamp  

---

## Script

```text
+CalFlow+

focus @chrome title("Slack")
screenshot
save source(clipboard) to("~/Desktop/slack_{now > YYYY-MM-DD_hh-mm}.png")
```

---

## What actually happens

- Chrome switches to the tab with title "Slack"  
- screenshot is captured to clipboard  
- image is saved to Desktop with timestamp  

→ no manual capture or renaming  

---

## Why this matters

Instead of:

❌ taking screenshots manually  
❌ renaming files  
❌ losing track of versions  

You get:

✅ one-command capture  
✅ auto-organized files  
✅ timestamped history  

---

## Real-life setups

### 🐞 Bug reporting

```text
+CalFlow+

focus @chrome title("Slack")
screenshot
save source(clipboard) to("~/Desktop/bug_{now > YYYY-MM-DD_hh-mm}.png")
```

→ quick bug evidence capture  

---

### 📊 Daily updates

```text
+CalFlow+

focus @chrome title("Slack")
screenshot
save source(clipboard) to("~/Desktop/daily_{now > YYYY-MM-DD}.png")
```

→ one snapshot per day  

---

### 🧾 Client communication log

```text
+CalFlow+

focus @chrome title("Slack")
screenshot
save source(clipboard) to("~/Desktop/client_{now > YYYY-MM-DD_hh-mm}.png")
```

→ track important messages  

---

## Customize

### Target different apps

```text
focus "Slack"
focus "Microsoft Teams"
focus "Discord"
```

→ works with browser or desktop apps  

---

### Change save location

```text
to("~/Documents/screenshots/slack_{now}.png")
```

---

### Change filename format

```text
{now}                      → full timestamp  
{now > YYYY-MM-DD}          → date only  
{now > hh-mm}               → time only  
```

---

## Mental model

- `focus` = bring correct window  
- `screenshot` = capture  
- `save` = persist with naming  

---

## Tip

If multiple Slack windows exist:

```text
focus @chrome title("Slack | general")
```

→ be more specific for accuracy  

---

# 💡 Aha

**"Capture and save in one command — no manual steps."**