# Calflow

Automate opening URLs from calendar events — with browser control, window layout, and optional password autofill.

---

## ✨ What It Does

Calflow reads upcoming calendar events and:

- Opens URLs automatically  
- Selects browser (Chrome, Safari, etc.) and profile (Chrome-only)  
- Positions windows (left/right/full)  
- Triggers password autofill (Bitwarden / 1Password)  
- Optionally signs in automatically  

---

## 🧠 Example

### Calendar Event Description

```text
#chrome
https://login.yahoo.com/ #left30 #fill 
https://www.notion.so/login #right70 #submit
```

### What happens:

- Opens both URLs in Chrome (even if OS default browser is Safari)  
- First window → left 30%  
- Second window → right 70%  
- Autofills ID/PW on both websites (via password manager)  
- Submits login on the second website (`#submit`)  

---

## 🏷 Supported Tags

### 🌐 Browser

| Tag | Browser |
|-----|--------|
| `#chrome` | Google Chrome |
| `#chrome-1` | Chrome Profile 1 |
| `#chrome-2` | Chrome Profile 2 |
| `#safari` | Safari |
| `#edge` | Microsoft Edge |
| `#brave` | Brave |
| `#firefox` | Firefox |
| `#opera` | Opera |
| `#vivaldi` | Vivaldi |
| `#arc` | Arc |
| `#tor` | Tor Browser |
| `#comet` | Comet |

---

### 🪟 Window Layout

| Tag | Behavior |
|-----|--------|
| `#left` | Left 50% |
| `#right` | Right 50% |
| `#top` | Top 50% |
| `#bottom` | Bottom 50% |
| `#left30` | Left 30% |
| `#right70` | Right 70% |
| `#top10` | Top 10% |
| `#bottom90` | Bottom 90% |
| `#full` | Full screen |

👉 Layout automatically forces **new window mode**

---

### 🔐 Autofill

| Tag | Behavior |
|-----|--------|
| `#submit` | Autofill + press Enter (Manual / Semi-auto mode) |
| `#fill` | Autofill only (Manual mode) |
| `#noautofill` | Disable autofill (Auto mode) |

---

### ⚡ Timing

| Tag | Behavior |
|-----|--------|
| `#slow` | Use longer delay (SSO / heavy pages) |

---

## ⚙️ How It Works

```text
Calendar → Parse → Open URL → Detect Browser → Resize → Autofill
```

### Key principles:

- Always targets **frontmost window**  
- Layout happens **before autofill** (prevents popup interference)  
- Tags are resolved with **entry > global priority**  

---

## 🧱 Project Structure

```text
calflow/
├── src/
│   ├── main.py
│   ├── browser.py
│   ├── parser.py
│   ├── calendar_client.py
│   ├── state.py
│   └── utils.py
├── settings.py
└── README.md
```

---

## 🔧 Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 2. Configure settings

Edit `settings.py`:

- Autofill provider (Bitwarden / 1Password)  
- Delays  
- Browser mappings  

---

### 3. Run

```bash
python src/main.py
```

---

## 🔐 Autofill Setup

Calflow triggers your password manager via keyboard shortcuts.

Example (Bitwarden):

```text
Cmd + Shift + L
```

Configure in `settings.py`:

```python
AUTOFILL_SHORTCUTS
```

---

## ⚠️ Known Limitations

- macOS only (uses AppleScript)  
- Window control depends on browser support  
- Chrome profile switching requires CLI launch  
- Dynamic login pages may need `#slow`  

---

## 🚀 Roadmap

- Smart page-load detection (replace fixed delays)  
- Multi-monitor support  
- Per-domain automation rules  

---

## 💡 Tips

- Keep extensions minimal for performance  
- Use explicit browser tags to avoid ambiguity  
- Avoid opening large directories in your editor  

---

## 📄 License

MIT
