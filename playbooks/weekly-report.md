# 📊 Weekly Report

## What it does

Open → load → capture.

- opens your analytics dashboard  
- loads last 7 days automatically  
- captures and saves the report  

---

## Script

```text
+CalFlow+

open "tip-developer-today.com/report?start={now-7d}&end={now}"
focus @chrome title("Report")
screenshot
save source(clipboard) to("~/Reports/weekly_{now > YYYY-MM-DD}.png")
```

---

## What actually happens

- URL loads with dynamic date range (last 7 days)  
- Chrome focuses on the report page  
- screenshot is captured  
- file saved with today’s date  

→ fully automated weekly reporting  

---

## Why this matters

Instead of:

❌ manually setting date filters  
❌ taking screenshots  
❌ naming files  

You get:

✅ auto-generated reports  
✅ consistent naming  
✅ zero manual steps  

---

## Real-life setups

### 📈 Growth tracking

```text
+CalFlow+

open "analytics.com?start={now-7d}&end={now}"
screenshot
save source(clipboard) to("~/Reports/growth_{now > YYYY-MM-DD}.png")
```

→ weekly performance snapshot  

---

### 💰 Revenue report

```text
+CalFlow+

open "dashboard.com/revenue?from={now-7d}&to={now}"
screenshot
save source(clipboard) to("~/Reports/revenue_{now > YYYY-MM-DD}.png")
```

→ finance reporting  

---

### 📊 Marketing report

```text
+CalFlow+

open "ads.com/report?start={now-7d}&end={now}"
screenshot
save source(clipboard) to("~/Reports/ads_{now > YYYY-MM-DD}.png")
```

→ campaign tracking  

---

## Customize

### Change time range

```text
{now-7d}   → last 7 days  
{now-30d}  → last 30 days  
{now-1mo}  → last month  
```

---

### Change filename

```text
weekly_{now}.png
weekly_{now > YYYY-MM-DD}.png
```

---

### Change save location

```text
"~/Desktop/"
"~/Documents/reports/"
"~/Dropbox/reports/"
```

---

## Mental model

- `open` = load report with dynamic dates  
- `{}` = generate time range automatically  
- `screenshot` = capture  
- `save` = archive  

---

## Tip

If the page loads slowly:

```text
wait 3s
```

Add before `screenshot` to ensure full rendering.

---

# 💡 Aha

**"Your weekly report — generated in one command."**