# ⚡ Quick Open

## What it does

Launch everything → instantly organized.

- opens multiple dashboards at once  
- splits layout automatically  
- uses multiple browsers + displays  
- removes distractions  

---

## Script

```text
+CalFlow+

open tip-developer-today.com/dashboard @chrome #left(50%) #submit
open tip-developer-today.com/analytics @chrome #right(50%)
open tip-developer-today.com/ @safari #display(ext)
close "Spotify"
```

---

## What actually happens

- Chrome opens two dashboards (left/right split 50/50)  
- first page triggers autofill + submit (if configured)  
- Safari opens a separate page on display 2  
- Spotify is closed  

→ everything is ready in one run  

---

## Why this matters

Instead of:

❌ opening tabs manually  
❌ arranging windows every time  
❌ switching browsers by hand  

You get:

✅ instant multi-dashboard setup  
✅ consistent layout  
✅ zero setup time  

---

## Real-life setups

### 📊 Analytics + monitoring

```text
+CalFlow+

open analytics.com @chrome #left(60%)
open logs.com @chrome #right(40%)
open status.com @safari #display(ext)
```

→ main dashboard + logs + status screen  

---

### 💰 Finance / trading

```text
+CalFlow+

open tradingview.com #left(50%)
open broker.com #right(50%)
open news.com #display(ext)
```

→ charts + execution + news  

---

### 🚀 Startup ops

```text
+CalFlow+

open notion.so #left(50%)
open slack.com #right(50%)
open admin.dashboard.com #display(ext)
```

→ docs + communication + backend  

---

### 🧪 Growth / marketing

```text
+CalFlow+

open ads.google.com #left(50%)
open analytics.google.com #right(50%)
open ahrefs.com #display(ext)
```

→ ads + analytics + SEO tools  

---

## Customize

### Replace URLs

```text
open your-dashboard.com
```

→ plug in your own tools  

---

### Change layout

```text
#left(70%)   → main focus  
#right(30%)  → side panel  
```

---

### Change browsers

```text
@chrome
@safari
```

→ route tools where they work best  

---

### Close distractions

```text
close "Spotify"
close "Discord"
```

---

## Mental model

- `open` = launch tool  
- `@chrome / @safari` = choose browser  
- `#left / #right` = layout  
- `#display` = first external monitor (or `#display("Name")` / `#display(N)`)  
- `close` = remove noise  

---

## Tip

Start with 2 tabs.

Then scale to:
- full dashboards  
- multi-screen setups  
- daily workflows  

---

# 💡 Aha

**"Open your entire workspace in one command."**