import os
import json
import webbrowser
import subprocess
import sys

CREDENTIALS_PATH = "secrets/credentials.json"
CONFIG_PATH = "data/config.json"
DAEMON_CONFIG_PATH = "data/daemon.json"
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/com.calflow.plist")


# =========================
# 🧩 Helpers
# =========================

def step(title, i, total):
    print(f"\n[{i}/{total}] {title}")
    print("-" * 40)


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# =========================
# 🔐 Credentials
# =========================

def ensure_credentials():
    if os.path.exists(CREDENTIALS_PATH):
        print("🔐 Existing credentials detected.")
        choice = input("Keep existing credentials? [Y/n]: ").strip().lower()

        if choice in ["", "y", "yes"]:
            print("✅ Keeping existing credentials.\n")
            return

        print("🔄 Replacing credentials... Paste new JSON below.\n")

    print("""
⚠️ Google Calendar credentials required.
👉 Takes less than 5 minutes to set up.

1. Go to https://console.cloud.google.com/
2. Create a new project
3. Enable "Google Calendar API"
4. Configure OAuth consent screen
5. Add yourself as a Test User
6. Create OAuth Client ID (Desktop App)
7. Download credentials.json

If you see "This app isn't verified":
→ click "Advanced" → "Continue"

Then copy the entire JSON and paste it below.
""")

    print("\nOpening Google Cloud Console in your browser...\n")
    webbrowser.open("https://console.cloud.google.com/apis/credentials")

    print("Paste credentials.json content (press Enter twice to finish):\n")

    while True:
        lines = []

        while True:
            line = input()
            if line.strip() == "" and lines:
                break
            lines.append(line)

        raw = "\n".join(lines)

        try:
            parsed = json.loads(raw)

            if "installed" not in parsed and "web" not in parsed:
                raise ValueError

            save_json(CREDENTIALS_PATH, parsed)
            print("\n✅ credentials.json saved successfully!\n")
            break

        except Exception:
            print("\n❌ Invalid JSON or wrong format. Please try again.\n")


# =========================
# 📅 Calendar Selection
# =========================

def ensure_calendar_selection(service):
    config = load_json(CONFIG_PATH)

    if config and config.get("calendars"):
        existing = config["calendars"]

        print(f"\n📅 {len(existing)} calendar(s) connected.")
        choice = input("Change selection? [Y/n]: ").strip().lower()

        if choice in ["", "n", "no"]:
            print("✅ Keeping existing calendars.\n")
            return existing

        print("🔄 Re-selecting calendars...\n")

    try:
        calendars = service.calendarList().list().execute().get("items", [])
    except Exception as e:
        print(f"❌ Failed to load calendars: {e}")
        print("⚠️ Defaulting to primary calendar.\n")
        return ["primary"]

    calendars = [
        c for c in calendars
        if c.get("accessRole") in ["owner", "writer", "reader"]
    ]

    if not calendars:
        print("⚠️ No accessible calendars found. Using primary.\n")
        return ["primary"]

    print("\n→ Choose calendars to monitor:\n")

    for i, cal in enumerate(calendars, 1):
        print(f"[{i}] {cal['summary']} ({cal.get('id', '')})")

    print("\n👉 Press Enter for primary only")

    while True:
        choice = input("\nEnter numbers (comma separated): ").strip()

        if not choice:
            selected = ["primary"]
            break

        try:
            indexes = [int(x.strip()) - 1 for x in choice.split(",")]

            if any(i < 0 or i >= len(calendars) for i in indexes):
                raise ValueError

            selected = [calendars[i]["id"] for i in indexes]
            break

        except Exception:
            print("❌ Invalid input. Try again.")

    save_json(CONFIG_PATH, {"calendars": selected})
    print("\n✅ Calendar selection saved!\n")

    return selected


# =========================
# ⚙️ Launchd Management
# =========================

def generate_plist(interval):
    python_path = sys.executable
    script_path = os.path.abspath("src/main.py")

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <key>Label</key>
    <string>com.calflow</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>

    <key>StartInterval</key>
    <integer>{interval}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/calflow.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/calflow.err</string>

</dict>
</plist>
'''


def install_launchd(interval):
    print("\n→ Installing background automation...")

    plist_content = generate_plist(interval)
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)

    with open(PLIST_PATH, "w") as f:
        f.write(plist_content)

    subprocess.run(
        ["launchctl", "unload", PLIST_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    result = subprocess.run(["launchctl", "load", PLIST_PATH])

    if result.returncode != 0:
        print("⚠️ Failed to load launchd job. You may need to run manually.")

    print("✅ Background automation installed\n")


def uninstall_launchd(full=False):
    if os.path.exists(PLIST_PATH):
        subprocess.run(
            ["launchctl", "unload", PLIST_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.remove(PLIST_PATH)
        print("🗑 Background automation removed.\n")
    else:
        print("⚠️ No background automation found.\n")

    paths = [
        "data/config.json",
        "data/daemon.json",
        "data/state.json",
        "secrets/token.json",
    ]

    if full:
        print("⚠️ Full cleanup mode enabled.\n")

        for p in paths:
            if os.path.exists(p):
                os.remove(p)

        print("✅ Full cleanup complete.\n")
        return

    print("Do you also want to remove local Calflow data?")
    print("(This will NOT remove credentials.json)\n")

    choice = input("Remove local data? [Y/n]: ").strip().lower()

    if choice not in ["", "y", "yes"]:
        print("Keeping local data.\n")
        return

    for p in paths:
        if os.path.exists(p):
            os.remove(p)

    print("\n✅ Cleanup complete.\n")


# =========================
# ⏱ Interval Setup
# =========================

def ensure_daemon_setup():
    DEFAULT_INTERVAL = 60
    config = load_json(DAEMON_CONFIG_PATH)

    existing = config.get("interval") if config else None

    print("\n[3/3] Background automation")
    print("→ How often should Calflow check your calendar?\n")

    if existing:
        print(f"Current: {existing} seconds")
        print("Recommended: 60 seconds\n")
        print("Press Enter to keep, or enter a new value:\n")
        prompt = "> "
    else:
        print("Recommended: 60 seconds\n")
        prompt = "Enter interval [default: 60]:\n> "

    while True:
        choice = input(prompt).strip()

        if not choice:
            interval = existing if existing else DEFAULT_INTERVAL
            break

        try:
            interval = int(choice)
            if interval < 5:
                print("⚠️ Minimum is 5 seconds.")
                continue
            break
        except Exception:
            print("❌ Enter a valid number.")

    save_json(DAEMON_CONFIG_PATH, {"interval": interval})
    install_launchd(interval)

    return interval


# =========================
# 🚀 Main Onboarding
# =========================

def run_onboarding():
    print("""
  ____      _ _____ _               
 / ___|__ _| |  ___| | _____      __
| |   / _` | | |_  | |/ _ \ \ /\ / /
| |__| (_| | |  _| | | (_) \ V  V / 
 \____\__,_|_|_|   |_|\___/ \_/\_/  

Turn your calendar into an automation engine
— open apps, log in, and arrange your workspace automatically.

Welcome to Calflow Setup
""")

    total = 3

    step("Google Calendar credentials", 1, total)
    ensure_credentials()

    if not os.path.exists(CREDENTIALS_PATH) or os.path.getsize(CREDENTIALS_PATH) == 0:
        print("❌ credentials.json missing or invalid. Please run setup again.")
        sys.exit(1)

    from calendar_client import build_service
    service = build_service()

    step("Calendars", 2, total)
    calendars = ensure_calendar_selection(service)

    interval = ensure_daemon_setup()

    print("🎉 Setup complete!\n")
    print("Summary:")
    print(f"✔ Calendars: {len(calendars)} selected")
    print(f"✔ Interval: {interval} seconds")
    print("✔ Background automation: enabled\n")

    return calendars, interval