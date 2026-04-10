# Calflow

Turn your calendar into an automation engine — open apps, log in, and arrange your workspace automatically.

---

## ⚡ Quick Start

```bash
git clone https://github.com/fpenguin/calflow.git
cd calflow
pip install -r requirements.txt
python src/main.py
```

---

## ✨ What It Does

Calflow reads upcoming calendar events and:

- Opens URLs automatically  
- Selects browser (Chrome, Safari, etc.) and profile (Chrome-only)  
- Positions windows (left/right/full)  
- Triggers password autofill (Bitwarden / 1Password)  
- Optionally signs in automatically  

---

## 🎯 Use Cases

- Daily login workflows (Notion, Gmail, Slack, etc.)
- SSO-heavy enterprise environments
- Multi-window setups for operators / traders
- Automating repetitive browser routines

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
- Autofills credentials  
- Submits login on the second site  

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

👉 Layout forces **new window mode**

---

### 🔐 Autofill

| Tag | Behavior |
|-----|--------|
| `#submit` | Autofill + Enter |
| `#fill` | Autofill only |
| `#noautofill` | Disable autofill |

---

### ⚡ Timing

| Tag | Behavior |
|-----|--------|
| `#slow` | Longer delay |

---

## ⚙️ How It Works

```text
Calendar → Parse → Open → Detect → Resize → Autofill
```

---

## 🧱 Project Structure

```text
calflow/
├── src/
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

### 2. Google Calendar API

1. Go to https://console.cloud.google.com/
2. Create project
3. Enable Google Calendar API
4. Configure OAuth consent screen
5. Add yourself as **Test User**
6. Create OAuth Client ID (Desktop App)
7. Download credentials.json

Place it here:

```text
secrets/credentials.json
```

---

### 3. First Run

```bash
python src/main.py
```

---

## ⏱ Run Automatically (macOS)

```bash
mkdir -p ~/Library/LaunchAgents
nano ~/Library/LaunchAgents/com.calflow.plist
```

Use launchd for scheduling.

---

## 🔐 Autofill Setup

Example (Bitwarden):

```text
Cmd + Shift + L
```

---

## ⚠️ Known Limitations

- macOS only  
- AppleScript dependency  
- Chrome profile requires CLI  
- Dynamic pages may need `#slow`  

---

## 🚀 Roadmap

- Smart page detection  
- Multi-monitor  
- Rules engine  
- Headless mode  

---

## 📄 License

MIT
