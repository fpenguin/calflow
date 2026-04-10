import subprocess
import re
import time

from utils import log
from settings import (
    AUTOFILL_PROVIDER,
    AUTOFILL_SHORTCUTS,
    BROWSER_MAP,
    AUTOFILL_BUFFER,
)

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# =========================
# 🧠 Helpers
# =========================

def run_applescript(script):
    subprocess.run(["osascript", "-e", script], timeout=5, check=False)


def build_modifier_string(mods):
    if not mods:
        return ""
    return " using {" + ", ".join(f"{m} down" for m in mods) + "}"


def get_frontmost_app():
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process whose frontmost is true'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() or None
    except:
        return None


def has_layout(tags):
    return any(tag.startswith(("#left", "#right", "#top", "#bottom", "#full")) for tag in tags)


# =========================
# 🌐 Browser Detection
# =========================

CHROME_PROFILE_PATTERN = re.compile(r"#chrome-(\d+)", re.IGNORECASE)
POSITION_PATTERN = re.compile(r"#(left|right|top|bottom)(\d+)?", re.IGNORECASE)


def parse_browser(tags):
    for tag in tags:
        match = CHROME_PROFILE_PATTERN.match(tag)
        if match:
            num = match.group(1)
            profile = "Default" if num == "0" else f"Profile {num}"
            return "Google Chrome", profile

    for tag in tags:
        lowered = tag.lower()
        if lowered in BROWSER_MAP:
            return BROWSER_MAP[lowered], None

    return None, None


# =========================
# 🪟 Layout Parsing
# =========================

def parse_window_layout(tags):
    for tag in tags:
        lowered = tag.lower()

        if lowered == "#full":
            return {"position": "full", "ratio": 1.0}

        match = POSITION_PATTERN.match(lowered)
        if match:
            position = match.group(1)
            percent = match.group(2)
            ratio = int(percent) / 100.0 if percent else 0.5
            return {"position": position, "ratio": ratio}

    return None


# =========================
# 🔐 Autofill
# =========================

def trigger_autofill(tags, submit=False, browser_name=None):
    provider = AUTOFILL_PROVIDER

    if provider not in AUTOFILL_SHORTCUTS:
        log(f"⚠️ Unknown autofill provider: {provider}")
        return

    shortcut = AUTOFILL_SHORTCUTS[provider]

    time.sleep(AUTOFILL_BUFFER)

    fill = shortcut["fill"]
    key = fill["key"]
    modifier_str = build_modifier_string(fill.get("modifiers", []))

    log(f"🔐 Autofill ({provider})")

    run_applescript(
        f'tell application "System Events" to keystroke "{key}"{modifier_str}'
    )

    if submit:
        time.sleep(AUTOFILL_BUFFER)

        log("↩️ Submitting login")

        submit_cmd = shortcut["submit"]

        if "key_code" in submit_cmd:
            run_applescript(
                f'tell application "System Events" to key code {submit_cmd["key_code"]}'
            )
        else:
            submit_key = submit_cmd["key"]
            submit_modifiers = build_modifier_string(submit_cmd.get("modifiers", []))
            run_applescript(
                f'tell application "System Events" to keystroke "{submit_key}"{submit_modifiers}'
            )


# =========================
# 🌐 Chrome launcher (FIXED)
# =========================

def launch_chrome(url, profile=None, new_window=False, incognito=False):
    args = [CHROME_BIN]

    if profile:
        args.append(f"--profile-directory={profile}")

    if incognito:
        args.append("--incognito")

    if new_window:
        args.append("--new-window")

    args.append("--no-first-run")
    args.append("--no-default-browser-check")

    args.append(url)

    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # 🔥 critical
    )


# =========================
# 🌐 Open URLs
# =========================

def open_urls(urls, tags):
    browser, profile = parse_browser(tags)
    layout_requested = has_layout(tags)
    incognito = "#incognito" in tags

    for url in urls:
        try:
            # =========================
            # 🪟 NEW WINDOW MODE
            # =========================
            if layout_requested:

                if browser == "Safari":
                    run_applescript(f'''
                        tell application "Safari"
                            activate
                            make new document with properties {{URL:"{url}"}}
                        end tell
                    ''')

                elif browser == "Google Chrome":
                    # 🔥 ALWAYS CLI for Chrome profiles
                    launch_chrome(
                        url=url,
                        profile=profile,
                        new_window=True,
                        incognito=incognito,
                    )

                elif browser in ["Arc", "Brave Browser", "Microsoft Edge"]:
                    run_applescript(f'''
                        tell application "{browser}"
                            activate
                            make new window
                            set URL of active tab of front window to "{url}"
                        end tell
                    ''')

                else:
                    subprocess.run(["open", url], timeout=5, check=False)

                time.sleep(0.5)
                log(f"Opened {url} in NEW WINDOW ({browser or 'default'})")

            # =========================
            # 🌐 TAB MODE
            # =========================
            else:
                if browser == "Safari":
                    run_applescript(f'''
                        tell application "Safari"
                            activate
                            open location "{url}"
                        end tell
                    ''')

                elif browser == "Google Chrome":
                    launch_chrome(
                        url=url,
                        profile=profile,
                        new_window=False,
                        incognito=incognito,
                    )

                elif browser in ["Arc", "Brave Browser", "Microsoft Edge"]:
                    run_applescript(f'''
                        tell application "{browser}"
                            activate
                            open location "{url}"
                        end tell
                    ''')

                else:
                    subprocess.run(["open", url], timeout=5, check=False)

                log(f"Opened {url} in tab ({browser or 'default'})")

        except Exception as e:
            log(f"❌ Failed to open {url}: {e}")


# =========================
# 🪟 Adjust Window (stable)
# =========================

def adjust_window(browser_name, tags):
    if not browser_name:
        return

    layout = parse_window_layout(tags)
    if not layout:
        return

    position = layout["position"]
    ratio = max(0.1, min(layout["ratio"], 1.0))

    script = f'''
    tell application "{browser_name}" to activate

    delay 0.3

    tell application "System Events"
        tell process "{browser_name}"
            set frontmost to true

            if (count of windows) > 0 then
                set w to front window

                tell application "Finder"
                    set screenBounds to bounds of window of desktop
                end tell

                set screenWidth to item 3 of screenBounds
                set screenHeight to item 4 of screenBounds

                set targetWidth to (screenWidth * {ratio}) as integer
                set xPos to 0

                if "{position}" is "right" then
                    set xPos to screenWidth - targetWidth
                else if "{position}" is "full" then
                    set targetWidth to screenWidth
                end if

                set position of w to {{xPos, 0}}
                set size of w to {{targetWidth, screenHeight}}
            end if
        end tell
    end tell
    '''

    run_applescript(script)