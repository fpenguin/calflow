Calflow

Automate opening URLs from calendar events — with browser control, window layout, and optional password autofill.

⸻

✨ What It Does

Calflow reads upcoming calendar events and:
	•	Opens URLs automatically
	•	Selects browser (Chrome, Safari, etc.) and profile (Chrome-only)
	•	Positions windows (left/right/full)
	•	Triggers password autofill (Bitwarden / 1Password)
	•	Optionally sign-in automatically

⸻

🧠 Example

Calendar Event Description

#chrome
https://login.yahoo.com/ #left30 #fill 
https://www.notion.so/login #right70 #submit

What happens:
	•	Opens both URLs in Chrome (while OS default browser set to Safari)
	•	First window → left 30%
	•	Second window → right 70%
	•	Autofills ID/PW on both websites (via pre-defined Password Manager)
	•	Submits login on the Second website (#submit) 

⸻

🏷 Supported Tags

🌐 Browser

Tag	Browser
#chrome	Google Chrome
#chrome-1	Chrome Profile 1
#chrome-2	Chrome Profile 2
#safari	Safari
#edge	Microsoft Edge
#brave	Brave
#firefox	Firefox
#opera	Opera
#vivaldi	Vivaldi
#arc	Arc
#tor	Tor Browser
#comet	Comet


⸻

🪟 Window Layout

Tag	Behavior
#left   Left 50%
#right  Right 50%
#top	Top 50%
#bottom	Bottom 50%

#left30	Left 30%
#right70	Right 70%
#top10  Top 10%
#bottom90   Bottom 90%
#full	Full screen

👉 Layout automatically forces new window mode

⸻

🔐 Autofill

Tag	Behavior
#submit	Autofill + press Enter (When on Manual or SemiAuto mode)
#fill	Autofill only (when on Manual mode)
#noautofill	Disable autofill (when on Auto-mode)


⸻

⚡ Timing

Tag	Behavior
#slow	Use longer delay (SSO / heavy pages)


⸻

⚙️ How It Works

Calendar → Parse → Open URL → Detect Browser → Resize → Autofill

Key principles:
	•	Always targets frontmost window
	•	Layout happens before autofill (prevents popup interference)
	•	Tags are resolved with entry > global priority

⸻

🧱 Project Structure

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


⸻

🔧 Setup

1. Install dependencies

pip install -r requirements.txt


⸻

2. Configure settings

Edit settings.py:
	•	Autofill provider (Bitwarden / 1Password)
	•	Delays
	•	Browser mappings

⸻

3. Run

python src/main.py


⸻

🔐 Autofill Setup

Calflow triggers your password manager via keyboard shortcuts.

Example (Bitwarden):

Cmd + Shift + L

Configure in settings.py:

AUTOFILL_SHORTCUTS


⸻

⚠️ Known Limitations
	•	macOS only (uses AppleScript)
	•	Window control depends on browser support
	•	Chrome profile switching requires CLI launch
	•	Dynamic login pages may need #slow

⸻

🚀 Roadmap
	•	Smart page-load detection (replace fixed delays)
	•	Multi-monitor support
	•	Per-domain automation rules
	•	Headless / background mode
	•	Native macOS app

⸻

💡 Tips
	•	Keep extensions minimal for performance
	•	Use explicit browser tags to avoid ambiguity
	•	Avoid opening large directories in your editor


⸻

📄 License

MIT