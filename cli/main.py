"""
CalFlow Runtime (v2.0 — Smart Mode + Plus Mode).

Pipeline:
    fetch → parse → route → execute → persist

Routing:
    if parsed.mode == "smart":
        executor.execute_entries(...)
    elif parsed.mode == "plus":
        command_executor.execute_commands(...)

This file is the daemon entry point. Heavy lifting (auth, parsing,
execution) lives in dedicated modules; this file is orchestration only.

Salvaged from v1.0:
- multi-calendar polling (data/config.json or data/calendars.json)
- file-based lock (prevents launchd overlap)
- (id, start) deduplication across calendars

Design:
- deterministic
- non-blocking
- thin controller
- backward-compatible: Smart Mode still routes through `execute_entries`
  with the same arguments it received in v1.0
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# CLI / lifecycle
from cli.onboarding import (
    restart_launchd,
    run_onboarding,
    start_launchd,
    status_launchd,
    stop_launchd,
    uninstall_launchd,
)

# Infra
from infra.calendar.calendar_client import (
    build_service,
    get_upcoming_events,
    next_event_across_calendars,
)

# Core (unified parser + back-compat re-exports)
from core.parser.parser import (
    extract_alert_offset,
    extract_tags,
    parse,
)

# Runtime
from runtime.command_executor import execute_commands
from runtime.executor import execute_entries

# State
from state import is_done, load_state, mark_done, save_state

# Utils
from core.utils import log

# Config
from config.config import DATA_DIR
from config.settings import EARLY_TOLERANCE, GRACE_SECONDS, STATUS_LOOKAHEAD_HOURS


# =========================================================
# 🔧 FLAGS / PATHS
# =========================================================

DEBUG = "--debug" in sys.argv

CONFIG_PATH = Path(DATA_DIR) / "config.json"
LEGACY_CALENDARS_PATH = Path(DATA_DIR) / "calendars.json"

LOCK_FILE = "/tmp/calflow.lock"
MAX_RUNTIME = 180  # seconds — stale-lock threshold


# =========================================================
# 🔒 LOCK FILE (salvaged from v1.0)
# =========================================================

def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_stale_lock(pid: int, ts: int) -> bool:
    if not _is_process_running(pid):
        return True
    if time.time() - ts > MAX_RUNTIME:
        return True
    return False


def acquire_lock() -> bool:
    """Acquire a single-instance lock. Returns False if another run is active."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                pid_str, ts_str = f.read().strip().split("|")
                pid = int(pid_str)
                ts = int(ts_str)
            if not _is_stale_lock(pid, ts):
                log(f"[WARN] Already running (PID {pid}). Skipping.")
                return False
            log("[WARN] Stale lock detected. Removing.")
            os.remove(LOCK_FILE)
        except Exception:
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass

    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}|{int(time.time())}")
    except OSError as exc:
        log(f"[WARN] Could not write lock file: {exc}")
        return False
    return True


def release_lock() -> None:
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


# =========================================================
# 🗂 CALENDAR SELECTION
# =========================================================

def get_selected_calendars() -> List[str]:
    """
    Read calendar IDs the daemon should poll.

    Lookup order:
        1. data/config.json   (canonical, written by onboarding)
        2. data/calendars.json (legacy fallback)
        3. ["primary"]        (default)
    """
    for path in (CONFIG_PATH, LEGACY_CALENDARS_PATH):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            log(f"[WARN] Could not read {path}: {exc}")
            continue
        cals = data.get("calendars") if isinstance(data, dict) else None
        if cals:
            return list(cals)

    return ["primary"]


# =========================================================
# 🧠 HELPERS
# =========================================================

def _normalize_event_time(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _within_execution_window(now: datetime, trigger: datetime) -> bool:
    if now < trigger - timedelta(seconds=EARLY_TOLERANCE):
        return False
    if now > trigger + timedelta(seconds=GRACE_SECONDS):
        return False
    return True


def _first_non_flag_arg(args: List[str]) -> Optional[str]:
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None


# =========================================================
# 🟢 STATUS DASHBOARD
# =========================================================

def _format_duration(delta: timedelta) -> str:
    """Render a timedelta as 'in 1h 28m' / 'in 4m 12s' / 'now'."""
    total = int(delta.total_seconds())
    if total < 0:
        return "in the past"
    if total < 60:
        return f"in {total}s"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h >= 1:
        return f"in {h}h {m}m"
    if m >= 5:
        return f"in {m}m"
    return f"in {m}m {s}s"


def _daemon_state() -> dict:
    """Return {loaded: bool, raw_line: str|None}. Reads launchctl."""
    import subprocess
    try:
        out = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return {"loaded": False, "raw_line": None}
    for line in (out.stdout or "").splitlines():
        if "com.calflow" in line:
            return {"loaded": True, "raw_line": line.strip()}
    return {"loaded": False, "raw_line": None}


_AVAILABLE_COMMANDS = """
🛠  Try:
    python3 -m cli.main             # run one cycle now
    python3 -m cli.main start       # start the background daemon
    python3 -m cli.main stop        # stop the background daemon
    python3 -m cli.main restart     # restart it
    python3 -m cli.main setup       # re-onboarding (4 steps)
    python3 -m cli.main display     # list connected monitors + #display syntax
    python3 -m cli.main test        # generate a test event + run it on demand
    python3 -m cli.main uninstall   # remove daemon (data preserved; --full to wipe)
    python3 -m cli.repl             # interactive REPL (no daemon needed)
""".rstrip()


def print_status_summary() -> None:
    """
    Friendly multi-line status output:

        🟢 CalFlow is active with 3 connected calendars
        📅 Next event starts in 1h 28m  (Daily standup)
        🛠  Try: …

    Degrades gracefully on missing creds, expired token, network error,
    no events, or daemon not loaded.
    """
    daemon = _daemon_state()
    calendars = get_selected_calendars()
    cal_count = len(calendars)

    # ------------------ daemon line ------------------
    if daemon["loaded"]:
        head = f"🟢 CalFlow is active with {cal_count} connected calendar{'s' if cal_count != 1 else ''}."
    else:
        head = "🟡 CalFlow is installed but the daemon is not loaded."
    print(head)

    # ------------------ next event line --------------
    next_line: Optional[str] = None
    try:
        service = build_service()
        ev = next_event_across_calendars(
            service, calendars, hours=STATUS_LOOKAHEAD_HOURS,
        )
        if ev is None:
            next_line = (
                f"📅 No upcoming events in the next {STATUS_LOOKAHEAD_HOURS}h."
            )
        else:
            now = datetime.now(timezone.utc).astimezone(ev["start"].tzinfo)
            delta = ev["start"] - now
            title = (ev.get("title") or "(untitled)").strip() or "(untitled)"
            next_line = (
                f"📅 Next event starts {_format_duration(delta)}  "
                f"(Event title: {title})"
            )
    except RuntimeError as exc:
        # build_service raises this when credentials.json is missing
        next_line = (
            "🔐 Not connected to Google Calendar yet.\n"
            f"    {exc}"
        )
    except Exception as exc:
        # Token expired without refresh, network failure, API down, …
        next_line = (
            "⚠  Could not fetch upcoming events:\n"
            f"    {type(exc).__name__}: {exc}"
        )

    if next_line:
        print(next_line)

    # ------------------ launchctl detail (if loaded) -
    if daemon["loaded"] and daemon["raw_line"]:
        print(f"   ↳ launchctl: {daemon['raw_line']}")

    # ------------------ available commands -----------
    print(_AVAILABLE_COMMANDS)


def _lookup_window_hours() -> int:
    """Daemon's per-cycle window. Status uses STATUS_LOOKAHEAD_HOURS."""
    from config.settings import FETCH_WINDOW_HOURS
    return FETCH_WINDOW_HOURS


# =========================================================
# 🧪 ON-DEMAND TEST  (`python3 -m cli.main test`)
# =========================================================

def run_test() -> None:
    """
    Generate a pre-filled "CalFlow Test Event" in the browser, prompt
    the user to click Save, then immediately execute the event —
    bypassing the trigger window — so the user gets instant feedback
    instead of waiting ~5 minutes for the daemon's next cycle.

    After execution, the event is marked done in `data/state.json` so
    the launchd daemon won't re-fire it on its next pass.
    """
    from cli.onboarding import open_sample_event_in_browser

    print("=" * 50)
    print(" 🧪  CalFlow test event")
    print("=" * 50)
    print()
    print("→ Opening a pre-filled event in your browser…")
    open_sample_event_in_browser()
    print()
    print("👉 Click 'Save' in Google Calendar to commit the event.")
    print("   (Your default browser should have just opened the editor.)")
    print()

    answer = input("Test calendar event saved? Run it now? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes"):
        print("Cancelled. The event will run automatically ~5 minutes from now")
        print("if you saved it (the daemon picks it up on its next cycle).")
        return

    print()
    print("[INFO] Fetching upcoming events from Google Calendar…")

    try:
        service = build_service()
    except RuntimeError as exc:
        print(f"\n🔐 Not connected to Google Calendar yet.\n   {exc}")
        return
    except Exception as exc:
        print(f"\n⚠  Could not connect to Google Calendar:\n   {type(exc).__name__}: {exc}")
        return

    calendars = get_selected_calendars()

    # The onboarding sample event is scheduled 5 min out; look up to
    # 1 hour ahead in case the user took a while to save it.
    test_event = None
    for cal_id in calendars:
        for ev in get_upcoming_events(service, cal_id, hours=1):
            title = (ev.get("title") or "").strip()
            if "calflow test event" in title.lower():
                test_event = ev
                break
        if test_event:
            break

    if test_event is None:
        print()
        print("⚠  No 'CalFlow Test Event' found in the next hour across")
        print(f"   {len(calendars)} selected calendar(s).")
        print("   • Did you click 'Save' in the Google Calendar tab?")
        print("   • Is the event in one of your selected calendars?")
        print("     (Run `python3 -m cli.main display` … wait, that's monitors.")
        print("      The selected calendars are in `data/config.json`.)")
        return

    event_time = test_event["start"]
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    print()
    print(f"[INFO] Found:    {test_event['title']!r}")
    print(f"[INFO] Calendar: {test_event.get('calendar_id', '(unknown)')}")
    print(f"[INFO] Scheduled at: {event_time.isoformat()}")
    print(f"[INFO] Running now (bypassing trigger window)…")
    print()

    text = test_event.get("text") or ""
    parsed = parse(text, title=test_event.get("title"))

    if parsed.is_empty:
        print("[WARN] No executable content in the event description.")
        return

    print(f"[INFO] Mode: {parsed.mode}")

    try:
        if parsed.is_smart:
            execute_entries(
                entries=parsed.entries,
                global_tags=set(),         # parser already merged
                debug=DEBUG,
            )
        elif parsed.is_plus:
            if parsed.has_errors:
                for err in parsed.errors:
                    print(f"[WARN] Plus validation: {err}")
            execute_commands(
                commands=parsed.commands,
                global_tags=set(),
                debug=DEBUG,
            )
        else:
            print(f"[WARN] Unrecognized mode: {parsed.mode}")
            return

        # Mark this run as done so the launchd daemon's next cycle
        # doesn't re-fire the same event a few minutes from now.
        state = load_state()
        run_key = f"{test_event['id']}_{event_time.isoformat()}"
        mark_done(state, run_key)
        save_state(state)

        print()
        print("✅ Test event executed.")
        print("   (Marked done — the background daemon won't re-fire it.)")
    except Exception as exc:
        print(f"\n[ERROR] Test execution failed: {exc}")


# =========================================================
# 🖥 DISPLAY INVENTORY
# =========================================================

def print_display_inventory() -> None:
    """
    Print connected displays + a `#display` syntax cheat sheet.

    Pure macOS query (osascript JXA + NSScreen) — no Google
    credentials needed.
    """
    from runtime.actions.window import enumerate_displays

    try:
        displays = enumerate_displays(force_refresh=True)
    except Exception as exc:
        print(f"⚠ Could not enumerate displays: {exc}")
        return

    if not displays:
        print("No displays detected (osascript may not be available).")
        return

    print(f"\nConnected displays ({len(displays)}):\n")
    print(f"  {'#':>3}    {'name':<32}  {'size':<11}  "
          f"{'top-left (x,y)':<16}  type")
    print(f"  {'-'*3}    {'-'*32}  {'-'*11}  {'-'*16}  {'-'*8}")
    for d in displays:
        marker = "★" if d.get("primary") else " "
        if d.get("primary"):
            kind = "primary"
        elif d.get("builtin"):
            kind = "builtin"
        else:
            kind = "external"
        name = d.get("name") or f"Display {d['index']}"
        size = f"{d['w']}×{d['h']}"
        origin = f"({d['x']:>5}, {d['y']:>5})"
        print(
            f"  [{d['index']}] {marker} {name:<32}  {size:<11}  "
            f"{origin:<16}  {kind}"
        )

    externals = [d for d in displays if d.get("external")]
    primary = next((d for d in displays if d.get("primary")), displays[0])

    print()
    print("Use #display in your CalFlow scripts:")
    print(f"   no tag                      → primary  ({primary['name']})")

    if not externals:
        print("   #display                    → no external monitor connected")
    elif len(externals) == 1:
        print(f"   #display                    → {externals[0]['name']}")
        print(f"   #display(ext)               → same — recommended for readability")
    else:
        first = externals[0]
        print(f"   #display                    → first external (currently: {first['name']})")
        print(f"   #display(ext)               → same — recommended for readability")
        print('   #display("Samsung")         → matches by name (case-insensitive substring)')
        for d in externals:
            short = (d['name'].split() or ['?'])[0]
            print(f'   #display("{short}")'.ljust(35) + f"  → matches \"{d['name']}\"")

    print(f"   #display({len(displays)})                 → display by index (1 = primary)")
    print()


# =========================================================
# 🚀 MAIN PIPELINE
# =========================================================

def main() -> None:
    log("[INFO] CalFlow started")

    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    state = load_state()
    calendars = get_selected_calendars()

    if DEBUG:
        log(f"[DEBUG] calendars: {calendars}")

    service = build_service()

    # --- Fetch from every selected calendar ---------------
    events: List[Dict] = []
    for cal_id in calendars:
        cal_events = get_upcoming_events(service, cal_id)
        if DEBUG:
            log(f"[DEBUG] {cal_id} → {len(cal_events)} event(s)")
        events.extend(cal_events)

    # --- Deduplicate by (id, start) -----------------------
    seen = set()
    unique: List[Dict] = []
    for ev in events:
        key = (ev.get("id"), ev.get("start"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ev)
    events = sorted(unique, key=lambda e: e.get("start") or datetime.min.replace(tzinfo=timezone.utc))

    log(f"[INFO] Events fetched: {len(events)}")

    # =====================================================
    # 🔁 EVENT LOOP
    # =====================================================

    for event in events:
        event_time = event.get("start")
        if not event_time:
            continue

        event_time = _normalize_event_time(event_time)
        now = datetime.now(timezone.utc).astimezone(event_time.tzinfo)

        run_key = f"{event['id']}_{event_time.isoformat()}"

        if is_done(state, run_key):
            if DEBUG:
                log(f"[DEBUG] Skipped (already executed): {run_key}")
            continue

        text = event.get("text") or ""
        if not text.strip():
            continue

        global_tags = extract_tags(text)
        alert_offset = extract_alert_offset(global_tags)
        trigger_time = event_time - timedelta(seconds=alert_offset)

        if DEBUG:
            log(f"[DEBUG] Event: {event.get('title')}")
            log(f"[DEBUG] Now: {now.isoformat()}")
            log(f"[DEBUG] Trigger: {trigger_time.isoformat()}")

        if not _within_execution_window(now, trigger_time):
            continue

        # --- Parse (unified entrypoint, v2.0) ---
        parsed = parse(text, title=event.get("title"))

        if parsed.is_empty:
            if DEBUG:
                log("[DEBUG] No executable content")
            continue

        log(
            f"[INFO] Processing ({parsed.mode}): "
            f"{event.get('title', '(untitled)')}"
        )

        # =================================================
        # 🚀 ROUTE → EXECUTION
        # =================================================
        try:
            if parsed.is_smart:
                # v1.0 contract preserved:
                execute_entries(
                    entries=parsed.entries,
                    global_tags=global_tags,
                    debug=DEBUG,
                )
            elif parsed.is_plus:
                if parsed.has_errors and DEBUG:
                    for err in parsed.errors:
                        log(f"[DEBUG] Plus validation: {err}")
                execute_commands(
                    commands=parsed.commands,
                    global_tags=global_tags,
                    debug=DEBUG,
                )
            else:
                log(f"[WARN] Unrecognized parse mode: {parsed.mode!r}")
        except Exception as exc:
            log(f"[ERROR] Event execution failed: {exc}")

        mark_done(state, run_key)
        log("[INFO] Event completed")

    save_state(state)
    log("[INFO] CalFlow finished")


# =========================================================
# CLI ENTRY
# =========================================================

if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = _first_non_flag_arg(args)
    full = "--full" in args

    if cmd in ("setup", "--setup"):
        run_onboarding()
        sys.exit(0)
    if cmd in ("uninstall", "--uninstall"):
        uninstall_launchd(full=full)
        sys.exit(0)
    if cmd == "start":
        start_launchd()
        sys.exit(0)
    if cmd == "stop":
        stop_launchd()
        sys.exit(0)
    if cmd == "restart":
        restart_launchd()
        sys.exit(0)
    if cmd == "status":
        print_status_summary()
        sys.exit(0)
    if cmd == "display":
        print_display_inventory()
        sys.exit(0)
    if cmd == "test":
        run_test()
        sys.exit(0)

    if not acquire_lock():
        sys.exit(0)
    try:
        main()
    finally:
        release_lock()
