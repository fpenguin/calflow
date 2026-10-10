from __future__ import annotations

import os
import json
import plistlib
import webbrowser
import subprocess
import sys

from state import lifecycle

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CREDENTIALS_PATH = os.path.join(BASE_DIR, "secrets/credentials.json")
CONFIG_PATH = os.path.join(BASE_DIR, "data/config.json")
DAEMON_CONFIG_PATH = os.path.join(BASE_DIR, "data/daemon.json")
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/com.calflow.plist")

def uninstall_launchd(full=False):

    confirm = input("Are you sure you want to uninstall? [y/N]: ").strip().lower()
    if confirm not in ["y", "yes"]:
        print("Cancelled.\n")
        return

    if os.path.exists(PLIST_PATH):
        subprocess.run(
            ["launchctl", "unload", PLIST_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        os.remove(PLIST_PATH)
        print("🗑 Background automation removed.\n")
    else:
        print("⚠️ No background automation found.\n")

    if not full:
        print("✔ Basic uninstall complete (data preserved)\n")
        return

    print("⚠️ Full cleanup mode enabled.\n")

    paths = [
        os.path.join(BASE_DIR, CONFIG_PATH),
        os.path.join(BASE_DIR, DAEMON_CONFIG_PATH),
        os.path.join(BASE_DIR, "data/state.json"),
        os.path.join(BASE_DIR, "secrets/token.json"),
    ]

    for p in paths:
        if os.path.exists(p):
            os.remove(p)

    print("✅ Full cleanup complete.\n")


# =========================
# Helpers
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
    except:
        return None


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _loaded() -> bool:
    result = subprocess.run(["launchctl", "list"], capture_output=True,
                            text=True, timeout=10, check=True)
    return any(line.split() and line.split()[-1] == "com.calflow"
               for line in result.stdout.splitlines())


def set_login_preference(service: str, enabled: bool) -> None:
    if service not in {"daemon", "menubar"} or type(enabled) is not bool:
        raise ValueError("Invalid login preference")
    if service == "menubar":
        from cli.menubar_launchd import MENUBAR_PLIST_PATH, install_menubar
        if not MENUBAR_PLIST_PATH.exists() and enabled:
            install_menubar(load=False)
        label = "com.calflow.menubar"
    else:
        if not os.path.exists(PLIST_PATH):
            raise FileNotFoundError("Run calflow setup before enabling background login")
        label = "com.calflow"
    key = service + "_login"
    previous = lifecycle.load()[key]
    target = f"gui/{os.getuid()}/{label}"
    subprocess.run(["launchctl", "enable" if enabled else "disable", target],
                   capture_output=True, timeout=10, check=True)
    try:
        lifecycle.update(**{key: enabled})
    except Exception:
        subprocess.run(["launchctl", "enable" if previous else "disable", target],
                       capture_output=True, timeout=10, check=True)
        raise


def start_launchd(*, persist: bool = True) -> None:
    if not os.path.exists(PLIST_PATH):
        raise FileNotFoundError(PLIST_PATH)
    if _loaded():
        if persist:
            lifecycle.update(paused=False)
        print("⚠️ Already running\n")
        return
    target = f"gui/{os.getuid()}/com.calflow"
    subprocess.run(["launchctl", "enable", target], timeout=10, check=True)
    try:
        subprocess.run(["launchctl", "load", PLIST_PATH], timeout=10, check=True)
    finally:
        if not lifecycle.load()["daemon_login"]:
            subprocess.run(["launchctl", "disable", target], timeout=10, check=True)
    if persist:
        lifecycle.update(paused=False)
    print("▶️ CalFlow started\n")


def stop_launchd(*, persist: bool = True) -> None:
    if not os.path.exists(PLIST_PATH):
        if persist:
            lifecycle.update(paused=True)
        print("⚠️ Nothing to stop (not installed)\n")
        return

    result = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True, timeout=10, check=True,
    )
    if not any(line.split() and line.split()[-1] == "com.calflow" for line in result.stdout.splitlines()):
        if persist:
            lifecycle.update(paused=True)
        print("CalFlow is already stopped\n")
        return

    subprocess.run(
        ["launchctl", "unload", PLIST_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=True,
    )
    if persist:
        lifecycle.update(paused=True)
    print("⏹ CalFlow stopped\n")


def restart_launchd():
    if lifecycle.load()["paused"] or not _loaded():
        print("CalFlow remains paused/stopped; use Start to resume\n")
        return
    stop_launchd(persist=False)
    start_launchd(persist=False)
    print("🔄 CalFlow restarted\n")


def status_launchd():
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    matches = [line for line in result.stdout.splitlines() if line.split() and line.split()[-1] == "com.calflow"]
    if matches:
        print("✅ CalFlow is loaded")

        for line in matches:
            print("→", line.strip())
    else:
        print("❌ CalFlow is not running")

# =========================
# Sample Event
# =========================

from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone

def open_sample_event_in_browser():
    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=5)
    end = start + timedelta(minutes=10)

    def fmt(dt):
        return dt.strftime("%Y%m%dT%H%M%SZ")

    # v2.0 syntax:
    #   - `@chrome` / `@safari` are TARGETS (route to a specific browser)
    #   - `#left(70%)` / `#right(30%)` use parens (validation §3.3)
    #   - `## …` lines are comments (DSL_GRAMMAR §1.3)
    #   - the README link is a `##` line so the parser doesn't try to open it
    #
    description = """## CalFlow test event — runs ~5 min after Save

https://buymeacoffee.com/therapydoge @safari #right(30%)
https://login.yahoo.com/ @chrome #left(70%) #fill

## What you should see:
##  - Safari opens buymeacoffee.com (right side, 30%)
##  - Chrome opens login.yahoo.com (left side, 70%)
##  - Autofill (#fill) is triggered on the Yahoo login page
##
## Install the named browsers first. A failed launch skips autofill.
##
## Learn more: https://github.com/fpenguin/calflow/blob/main/README.md
"""

    params = {
        "action": "TEMPLATE",
        "text": "CalFlow Test Event",
        "dates": f"{fmt(start)}/{fmt(end)}",
        "details": description,
    }

    url = "https://calendar.google.com/calendar/render?" + urlencode(params)

    webbrowser.open(url)




# =========================
# Credentials
# =========================

def ensure_credentials():
    if os.path.exists(CREDENTIALS_PATH):
        print("🔐 Existing credentials detected.")
        choice = input("Keep existing credentials? [Y/n]: ").strip().lower()
        if choice in ["", "y", "yes"]:
            print("✅ Keeping existing credentials.\n")
            return

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

Then paste the JSON below.
""")

    webbrowser.open("https://console.cloud.google.com/apis/credentials")

    print("\nPaste credentials.json (press Enter twice to finish):\n")

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
            print("\n✅ credentials.json saved!\n")
            break

        except:
            print("\n❌ Invalid JSON. Try again.\n")


# =========================
# Calendar Selection
# =========================

def ensure_calendar_selection(service):
    config = load_json(CONFIG_PATH)

    if config and config.get("calendars"):
        print(f"\n📅 {len(config['calendars'])} calendar(s) already selected.")
        choice = input("Change selection? [y/N]: ").strip().lower()
        if choice not in ["y", "yes"]:
            return config["calendars"]

    try:
        calendars = service.calendarList().list().execute().get("items", [])
    except Exception as e:
        print(f"❌ Failed to load calendars: {e}")
        return ["primary"]

    if not calendars:
        print("⚠️ No calendars found. Using primary.")
        return ["primary"]

    print("\nSelect calendars:\n")

    for i, cal in enumerate(calendars, 1):
        print(f"[{i}] {cal['summary']}")

    print("""
👉 Choose one or more calendars to monitor:

- Enter numbers separated by commas (e.g. 1,3,4) and press Enter
- Press Enter without typing anything → use primary calendar only
""")

    while True:
        choice = input("> ").strip()

        if not choice:
            selected = ["primary"]
            break

        try:
            idx = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [calendars[i]["id"] for i in idx]
            break
        except:
            print("❌ Invalid input")

    save_json(CONFIG_PATH, {"calendars": selected})
    print("✅ Saved\n")

    return selected


# =========================
# Launchd
# =========================

def generate_plist(interval):
    """
    Build a launchd plist that runs `python -m cli.main` from the project
    root, so package imports (cli/, core/, runtime/, ...) resolve correctly.

    v2.0 layout differs from v1.0 (`src/main.py`) — we now invoke the
    package entrypoint via -m, with WorkingDirectory pinned to BASE_DIR.
    """
    python_path = sys.executable
    log_dir = os.path.join(BASE_DIR, "data")
    stdout_log = os.path.join(log_dir, "launchd.out.log")
    stderr_log = os.path.join(log_dir, "launchd.err.log")

    return plistlib.dumps({
        "Label": "com.calflow",
        "ProgramArguments": [python_path, "-m", "cli.main"],
        "WorkingDirectory": BASE_DIR,
        "EnvironmentVariables": {"PYTHONPATH": BASE_DIR},
        "StartInterval": int(interval),
        "RunAtLoad": True,
        "StandardOutPath": stdout_log,
        "StandardErrorPath": stderr_log,
    }).decode("utf-8")


def install_launchd(interval):
    plist = generate_plist(interval)

    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)

    with open(PLIST_PATH, "w") as f:
        f.write(plist)

    set_login_preference("daemon", True)
    subprocess.run(["launchctl", "unload", PLIST_PATH], stderr=subprocess.DEVNULL, timeout=10)
    subprocess.run(["launchctl", "load", PLIST_PATH], timeout=10, check=True)
    lifecycle.update(paused=False)

    print("✅ Background automation enabled\n")


# =========================
# Interval
# =========================

def ensure_daemon_setup():
    DEFAULT = 60
    MIN = 20
    MAX = 3600

    print(f"""
⏱ How often should CalFlow check your calendar?

→ Press Enter to use {DEFAULT} seconds (recommended)
→ Or enter a custom value ({MIN}–{MAX} seconds):
""")

    while True:
        choice = input("> ").strip()

        if not choice:
            interval = DEFAULT
            break

        try:
            interval = int(choice)

            if interval < MIN:
                print(f"⚠️ Minimum is {MIN} seconds")
                continue

            if interval > MAX:
                print(f"⚠️ That's too infrequent. Try ≤ {MAX} seconds")
                continue

            break

        except ValueError:
            print("❌ Invalid number")

    if interval >= 60:
        print(f"→ Checking every {interval // 60} minute(s)")
    else:
        print(f"→ Checking every {interval} seconds")

    save_json(DAEMON_CONFIG_PATH, {"interval": interval})
    install_launchd(interval)

    return interval


# =========================
# Password Manager
# =========================

# Each entry: (key, display label).  `key` must exist in
# config.settings.AUTOFILL_SHORTCUTS (or be 'none' to disable).
AUTOFILL_OPTIONS = [
    ("apple",     "Apple Passwords          (⌘\\)"),
    ("1password", "1Password                (⌘\\)"),
    ("bitwarden", "Bitwarden                (⌘⇧L)"),
    ("none",      "None / skip autofill"),
]


def _autofill_label(key: str) -> str:
    for k, lbl in AUTOFILL_OPTIONS:
        if k == key:
            return lbl
    return key


def ensure_accessibility_permission():
    """
    Step 5 of onboarding: walk the user through granting Accessibility
    permission to /usr/bin/osascript so window-aware verbs work.

    Two macOS permission buckets matter:
      - Apple Events / Automation  → enough for `set visible to false`
                                     (powers `hide @app`, `hide all`,
                                     `close @app`, `close all`)
      - Accessibility              → needed for AX attribute reads
                                     (powers `hide display(N)`,
                                     `focus … display(N)` window
                                     positioning, future click/type)

    Granting Automation does NOT grant Accessibility — they're separate
    TCC buckets. This step opens System Settings directly to the
    Accessibility pane so the user doesn't have to hunt for it.
    """
    print("""
🔐 Accessibility permission

Some CalFlow verbs read window geometry (which display a window is on,
where it's positioned). macOS gates this behind the Accessibility
permission, granted PER BINARY.

Without it, these verbs degrade or fail:
   hide display(N)            ← needs window position reads
   focus @app display(N)      ← needs window relocation
   future click/type backends ← needs UI element reads

Verbs that DON'T need this (work without Accessibility):
   open / focus / close / hide @app / hide all / wait / screenshot

Want to open System Settings → Privacy & Security → Accessibility now?
""")
    choice = input("Open Accessibility settings? [Y/n]: ").strip().lower()
    if choice not in ("", "y", "yes"):
        print("\nSkipped. You can grant it later — CalFlow will print")
        print("a clear error the first time a window-aware verb runs.\n")
        return False

    # Open the Accessibility pane directly. macOS supports
    # `x-apple.systempreferences:` URLs for deep-linking into Settings.
    url = (
        "x-apple.systempreferences:"
        "com.apple.preference.security?Privacy_Accessibility"
    )
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"⚠  Could not open Settings automatically: {exc}")
        print("   Open it manually: System Settings → Privacy & Security → Accessibility")
        return False

    print("""
👉 In the Accessibility pane that just opened:

   1. Click the [+] button (lock unlock first if needed)
   2. Press ⌘⇧G (Cmd+Shift+G) to type a path
   3. Paste:  /usr/bin/osascript
   4. Click Open
   5. Toggle the new "osascript" entry ON

When done, hit Enter here and CalFlow will continue.
""")
    input("Press Enter once you've granted permission (or to skip): ")
    print("✅ Accessibility step complete (verification happens at first use).\n")
    return True


def ensure_autofill_provider():
    """
    Step 4 of onboarding: pick which password manager to drive when
    a `#fill` tag is in an event description. Choice is saved to
    data/config.json (alongside the calendars list); the runtime
    reads it from there at execute time.
    """
    config = load_json(CONFIG_PATH) or {}

    if config.get("autofill_provider"):
        current = config["autofill_provider"]
        print(f"\n🔑 Autofill provider already set: {_autofill_label(current)}")
        choice = input("Change? [y/N]: ").strip().lower()
        if choice not in ("y", "yes"):
            return current

    print("""
🔑 Which password manager do you use?

CalFlow sends an autofill keystroke when a `#fill` tag is on a URL
line in your event description.
""")
    for i, (_, label) in enumerate(AUTOFILL_OPTIONS, 1):
        print(f"  [{i}] {label}")

    print("\n→ Press Enter to use Apple Passwords (default)")

    while True:
        raw = input("> ").strip()
        if not raw:
            provider = "apple"
            break
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(AUTOFILL_OPTIONS):
                provider = AUTOFILL_OPTIONS[idx][0]
                break
        except ValueError:
            pass
        print(f"❌ Pick a number 1–{len(AUTOFILL_OPTIONS)}")

    config["autofill_provider"] = provider
    save_json(CONFIG_PATH, config)
    print(f"\n✅ {_autofill_label(provider)}\n")

    if provider != "none":
        print("""
🔐 First time CalFlow triggers autofill, macOS will ask you to grant
   Accessibility permission to whichever process is sending the
   keystroke (osascript / Python / launchd).

   Click "Allow" in the system prompt. After that, autofill is silent.

   You can also pre-grant it any time:
       System Settings → Privacy & Security → Accessibility
""")

    return provider


# =========================
# Main
# =========================

def run_onboarding():

    print(r"""
  ____      _ _____ _               
 / ___|__ _| |  ___| | _____      __
| |   / _` | | |_  | |/ _ \ \ /\ / /
| |__| (_| | |  _| | | (_) \ V  V / 
 \____\__,_|_|_|   |_|\___/ \_/\_/  

Turn your calendar into an automation engine
— trigger apps, layouts, and workflows from simple text.

🚀 Welcome to CalFlow Setup
""")

    total = 5

    step("Google Credentials", 1, total)
    ensure_credentials()

    from infra.calendar.calendar_client import build_service
    service = build_service()

    step("Calendar Selection", 2, total)
    calendars = ensure_calendar_selection(service)

    step("Background Automation", 3, total)
    interval = ensure_daemon_setup()

    step("Password Manager", 4, total)
    provider = ensure_autofill_provider()

    step("Accessibility Permission", 5, total)
    ensure_accessibility_permission()

    print("\n🎉 Setup complete!\n")
    print(f"✔ Calendars: {len(calendars)}")
    print(f"✔ Interval:  {interval}s")
    print(f"✔ Autofill:  {_autofill_label(provider)}\n")

    print("""
---------------------------------------------------
ℹ️  Create a test event to verify everything works?
---------------------------------------------------
→ Opens a pre-filled event in your browser
→ Review and click “Save”
→ It will trigger in ~5 minutes
""")

    choice = input("Create test event? [Y/n]: ").strip().lower()

    if choice in ["", "y", "yes"]:
        open_sample_event_in_browser()

        print("""
👉 A new event page has opened in your browser
👉 Click "Save" to activate the test

What will happen afterwards?
""")

        # timing message
        if interval >= 60:
            timing = f"~{interval // 60} minute(s)"
        else:
            timing = f"~{interval} seconds"

        print(f"→ Two links will open shortly (within {timing})\n")

        print("""
→ The first opens in Safari (30% of your screen)
→ The second opens in Chrome (70% of your screen)

Install the named browsers first. A failed launch skips autofill.

Learn more:
https://github.com/fpenguin/calflow/blob/main/README.md
""")

    else:
        print("Skipped sample event.\n")

# =========================
# Entry
# =========================

if __name__ == "__main__":
    run_onboarding()
