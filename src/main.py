import os
import sys
import time

from datetime import datetime, timezone, timedelta

from calendar_client import get_upcoming_events
from parser import extract_url_entries, extract_global_tags, extract_alert_offset
from browser import (
    open_urls,
    trigger_autofill,
    adjust_window,
    parse_browser,
    get_frontmost_app,
    has_layout,
)
from state import load_state, save_state, is_done, mark_done
from utils import log
from onboarding import run_onboarding, uninstall_launchd, load_json

from settings import (
    GRACE_SECONDS,
    EARLY_TOLERANCE,
    DEFAULT_DELAY,
    SLOW_DELAY,
    MAX_DELAY,
    POST_AUTOFILL_DELAY,
    AUTOFILL_MODE,
    NO_AUTOFILL_TAG,
    FORCE_FILL_TAG,
    FORCE_SUBMIT_TAG,
    AUTOFILL_BUFFER,
    BROWSER_MAP,
)

DEBUG = "--debug" in sys.argv


# =========================
# 🔒 Lock
# =========================

LOCK_FILE = "/tmp/calflow.lock"
MAX_RUNTIME = 180


def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_stale_lock(pid, timestamp):
    if not is_process_running(pid):
        return True
    if time.time() - timestamp > MAX_RUNTIME:
        return True
    return False


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                pid_str, ts_str = f.read().strip().split("|")
                pid = int(pid_str)
                ts = int(ts_str)

            if not is_stale_lock(pid, ts):
                log(f"⚠️ Already running (PID {pid}). Skipping.")
                return False

            log("⚠️ Stale lock detected. Removing.")
            os.remove(LOCK_FILE)

        except Exception:
            os.remove(LOCK_FILE)

    with open(LOCK_FILE, "w") as f:
        f.write(f"{os.getpid()}|{int(time.time())}")

    return True


def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


# =========================
# ⏱ Delay
# =========================

def detect_delay(tags):
    delay = SLOW_DELAY if "#slow" in tags else DEFAULT_DELAY
    return max(1, min(delay, MAX_DELAY))


# =========================
# 🔐 Autofill
# =========================

def resolve_autofill(tags):
    if NO_AUTOFILL_TAG in tags:
        return False, False

    if FORCE_SUBMIT_TAG in tags:
        return True, True

    if FORCE_FILL_TAG in tags:
        return True, False

    if AUTOFILL_MODE == "auto":
        return True, True

    if AUTOFILL_MODE == "semi-auto":
        return True, False

    return False, False


# =========================
# 🧠 Tag Resolution
# =========================

def resolve_tags(global_tags, entry_tags):
    def is_layout(tag):
        return tag.startswith(("#left", "#right", "#top", "#bottom", "#full"))

    entry_layout = {t for t in entry_tags if is_layout(t)}
    global_layout = {t for t in global_tags if is_layout(t)}
    layout_tags = entry_layout if entry_layout else global_layout

    entry_browser = [t for t in entry_tags if t in BROWSER_MAP]
    global_browser = [t for t in global_tags if t in BROWSER_MAP]
    browser_tag = entry_browser[0] if entry_browser else (global_browser[0] if global_browser else None)

    tags = global_tags | entry_tags

    tags = {
        t for t in tags
        if t not in BROWSER_MAP and not is_layout(t)
    }

    tags |= layout_tags
    if browser_tag:
        tags.add(browser_tag)

    return tags


# =========================
# 🚀 Main
# =========================

def main():
    log("Calflow started")

    os.makedirs("data", exist_ok=True)

    state = load_state()

    config = load_json("data/config.json")
    selected_calendars = (
        config.get("calendars") if config and "calendars" in config else ["primary"]
    )

    if DEBUG:
        log(f"DEBUG: Calendars → {selected_calendars}")

    events = []

    for calendar_id in selected_calendars:
        cal_events = get_upcoming_events(calendar_id)

        if DEBUG:
            log(f"DEBUG: {calendar_id} → {len(cal_events)} events")

        events.extend(cal_events)

    # Deduplicate
    seen = set()
    unique_events = []

    for e in events:
        key = (e["id"], e["start"])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    events = unique_events

    # Sort
    events.sort(key=lambda e: e["start"])

    log(f"EVENT COUNT: {len(events)}")

    for event in events:
        text = event.get("text") or ""
        event_time = event.get("start")
        calendar_id = event.get("calendar_id", "unknown")

        if DEBUG:
            log(f"DEBUG: Event → [{calendar_id}] {event.get('title')}")

        if not event_time:
            continue

        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc).astimezone(event_time.tzinfo)
        key = f"{event['id']}_{event_time.isoformat()}"

        if is_done(state, key):
            if DEBUG:
                log("DEBUG: Skipped (already done)")
            continue

        global_tags = extract_global_tags(text)
        alert_offset = extract_alert_offset(global_tags)
        trigger_time = event_time - timedelta(seconds=alert_offset)

        if now < trigger_time - timedelta(seconds=EARLY_TOLERANCE):
            if DEBUG:
                log("DEBUG: Skipped (too early)")
            continue

        if now > trigger_time + timedelta(seconds=GRACE_SECONDS):
            if DEBUG:
                log("DEBUG: Skipped (too late)")
            continue

        entries = extract_url_entries(text, title=event.get("title"))

        if not entries:
            continue

        log(f"Processing: {event.get('title')}")

        for entry in entries:
            url = entry["url"]
            entry_tags = entry["tags"]

            tags = resolve_tags(global_tags, entry_tags)

            if DEBUG:
                log(f"DEBUG: Tags → {tags}")

            delay = detect_delay(tags)
            should_autofill, should_submit = resolve_autofill(tags)

            open_urls([url], tags)
            time.sleep(AUTOFILL_BUFFER)

            browser_name, _ = parse_browser(tags)
            browser_name = browser_name or get_frontmost_app()

            if has_layout(tags) and browser_name:
                adjust_window(browser_name, tags)

            time.sleep(delay)

            if should_autofill:
                trigger_autofill(tags, submit=should_submit, browser_name=browser_name)
                time.sleep(POST_AUTOFILL_DELAY)

        mark_done(state, key)
        log("✅ Event completed")

    save_state(state)
    log("Calflow finished")


# =========================
# ▶ Entry
# =========================

if __name__ == "__main__":
    full = "--full" in sys.argv

    if "--uninstall" in sys.argv:
        uninstall_launchd(full=full)
        sys.exit(0)

    if "--setup" in sys.argv:
        run_onboarding()
        sys.exit(0)

    if not acquire_lock():
        sys.exit(0)

    try:
        main()
    finally:
        release_lock()