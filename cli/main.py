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
#
# Three-mode interactive runner (v1.1.3):
#
#   Step 1: Fetch the next CalFlow Test Event + show its mode.
#           Offer:
#               1) Calendar Event — Dry run
#               2) Calendar Event — Execute
#               3) Custom Script
#
#   Step 2a: Dry run  → parse + summarise; ask Proceed?
#   Step 2b: Execute  → run; offer [Enter] re-run / [n] new event / [q] quit
#   Step 2c: Custom   → paste DSL; parse; run; [Enter] re-run / [c] change / [q] quit
#
# Why a re-run loop matters: most QA iterations are "tweak the event,
# test, tweak, test", and re-running shouldn't require re-creating an
# event from scratch.
# =========================================================

def run_test() -> None:
    """Top-level dispatcher for `python3 -m cli.main test`."""
    print("=" * 50)
    print(" 🧪  CalFlow test runner")
    print("=" * 50)
    print()

    # Try to fetch a pre-existing CalFlow Test Event. If none, fall
    # straight into the offer-to-create + custom-script flow.
    test_event = _find_existing_test_event(silent=True)
    if test_event is None:
        test_event = _offer_create_test_event()
        if test_event is None:
            # The user declined creating one but might still want to try
            # a custom script — let them in.
            _run_custom_script_loop()
            return

    _step1_choose_mode(test_event)


def _step1_choose_mode(test_event: Dict) -> None:
    """Display the event header + run-mode menu. Dispatches to step 2a/b/c."""
    text = test_event.get("text") or ""
    parsed = parse(text, title=test_event.get("title"))
    plus_marker = "+CalFlow+" if parsed.is_plus else "Smart"

    print(f"Selected: {test_event['title']!r}")
    print(f"Mode    : {plus_marker}")
    print()
    print("Run mode:")
    print()
    print("  1) Calendar Event — Dry run (no execution)")
    print("  2) Calendar Event — Execute")
    print("  3) Custom Script")
    print()

    choice = input("Choose: ").strip()
    print()
    if choice == "1":
        _step2a_dry_run(test_event, parsed)
    elif choice == "2":
        _step2b_execute_loop(test_event, parsed)
    elif choice == "3":
        _run_custom_script_loop()
    else:
        print("Cancelled.")


def _step2a_dry_run(test_event: Dict, parsed) -> None:
    """Print the parsed AST without executing. Offer to proceed → execute."""
    print("--- DRY RUN ---")
    _print_parsed_summary(parsed)
    print()
    answer = input("Proceed? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        print()
        _step2b_execute_loop(test_event, parsed)


def _step2b_execute_loop(test_event: Dict, parsed) -> None:
    """Execute, then loop on [Enter]=rerun / [n]=new event / [q]=quit."""
    while True:
        try:
            _execute_parsed(parsed)
            _mark_test_event_done(test_event)
        except Exception as exc:
            print(f"\n[ERROR] Test execution failed: {exc}")

        print()
        print("Press:")
        print("  [Enter] → run again")
        print("  [n]     → create a new Google Calendar event (starting in 2 min)")
        print("  [q]     → quit")
        choice = input("> ").strip().lower()
        print()
        if choice in ("q", "quit", "exit"):
            return
        if choice == "n":
            new_event = _offer_create_test_event()
            if new_event is None:
                return
            test_event = new_event
            text = test_event.get("text") or ""
            parsed = parse(text, title=test_event.get("title"))
        # else: empty → re-run with same parsed AST


def _run_custom_script_loop() -> None:
    """Paste DSL → parse → run; offer [Enter]/[c]/[q]."""
    script = _prompt_for_script()
    while script is not None:
        parsed = parse(script, title="Custom script")
        print()
        print("Parsed:")
        _print_parsed_summary(parsed)
        if parsed.is_empty:
            print("[WARN] Script has no executable content; skipping.")
        else:
            print()
            answer = input("Run? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                try:
                    _execute_parsed(parsed)
                except Exception as exc:
                    print(f"\n[ERROR] Custom script failed: {exc}")

        print()
        print("Press:")
        print("  [Enter] → run again")
        print("  [c]     → change script")
        print("  [q]     → quit")
        choice = input("> ").strip().lower()
        print()
        if choice in ("q", "quit", "exit"):
            return
        if choice == "c":
            script = _prompt_for_script()
            continue
        # empty → re-run same script
        # (parsed re-built next loop iteration anyway)


# =========================================================
# 🛠️ TEST RUNNER HELPERS (v1.1.3)
# =========================================================

def _print_parsed_summary(parsed) -> None:
    """Compact, human-readable summary of a ParseResult."""
    print(f"Mode: {parsed.mode.upper()}")
    if parsed.is_smart:
        if not parsed.entries:
            print("(no entries)")
            return
        print("Parsed entries:")
        for entry in parsed.entries:
            url = getattr(entry, "url", None) or "(no url)"
            target = getattr(entry, "target", None)
            tags = sorted(getattr(entry, "tags", set()) or set())
            line = f"- URL: {url}"
            if target:
                line += f"   Target: {target}"
            if tags:
                line += f"   Tags: {', '.join(tags)}"
            print(line)
        if parsed.global_tags:
            print(f"Global tags: {', '.join(sorted(parsed.global_tags))}")
    elif parsed.is_plus:
        if parsed.has_errors:
            for err in parsed.errors:
                print(f"[WARN] Plus validation: {err}")
        if not parsed.commands:
            print("(no commands)")
            return
        print("Parsed commands:")
        for cmd in parsed.commands:
            tags = sorted(cmd.tags or [])
            tag_str = f"   Tags: {', '.join(tags)}" if tags else ""
            print(f"- {cmd.name}: {cmd.raw}{tag_str}")
    else:
        print("(empty / unrecognised)")


def _execute_parsed(parsed) -> None:
    """Dispatch a ParseResult to the right executor."""
    if parsed.is_empty:
        print("[WARN] No executable content.")
        return
    print(f"[INFO] Mode: {parsed.mode.upper()}")
    if parsed.is_smart:
        execute_entries(
            entries=parsed.entries,
            global_tags=set(),
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


def _prompt_for_script() -> Optional[str]:
    """
    Read a multi-line custom script. Two terminators:
        - blank line → done
        - EOF (Ctrl-D) → done
    Returns None if the user cancels (Ctrl-C).
    """
    print("Paste your script (blank line or Ctrl-D to finish):")
    lines: List[str] = []
    try:
        while True:
            try:
                line = input("> " if not lines else "  ")
            except EOFError:
                break
            if line == "" and lines:
                break
            if line == "" and not lines:
                # First-line blank → treat as cancel
                return None
            lines.append(line)
    except KeyboardInterrupt:
        print()
        return None
    return "\n".join(lines)


def _offer_create_test_event() -> Optional[Dict]:
    """
    Open Google Calendar with a pre-filled CalFlow Test Event, then
    poll for it to appear. Returns the event dict, or None if the user
    backs out / it never shows up.
    """
    from cli.onboarding import open_sample_event_in_browser

    print("→ Opening a pre-filled event in your browser…")
    open_sample_event_in_browser()
    print()
    print("👉 Click 'Save' in Google Calendar to commit the event.")
    print()

    answer = input("Test calendar event saved? Run it now? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes"):
        print("Cancelled. The event will run automatically ~5 minutes from now")
        print("if you saved it (the daemon picks it up on its next cycle).")
        return None

    return _find_existing_test_event(silent=False)


def _find_existing_test_event(*, silent: bool) -> Optional[Dict]:
    """
    Look up the most recent 'CalFlow Test Event' in the next hour
    across all selected calendars. Returns None if not found.
    """
    if not silent:
        print()
        print("[INFO] Fetching upcoming events from Google Calendar…")

    try:
        service = build_service()
    except RuntimeError as exc:
        if not silent:
            print(f"\n🔐 Not connected to Google Calendar yet.\n   {exc}")
        return None
    except Exception as exc:
        if not silent:
            print(
                f"\n⚠  Could not connect to Google Calendar:\n   "
                f"{type(exc).__name__}: {exc}"
            )
        return None

    calendars = get_selected_calendars()
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
        if not silent:
            print()
            print("⚠  No 'CalFlow Test Event' found in the next hour across")
            print(f"   {len(calendars)} selected calendar(s).")
        return None

    event_time = test_event["start"]
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
        test_event["start"] = event_time

    if not silent:
        print(f"[INFO] Found:        {test_event['title']!r}")
        print(f"[INFO] Calendar:     {test_event.get('calendar_id', '(unknown)')}")
        print(f"[INFO] Scheduled at: {event_time.isoformat()}")
        print()
    return test_event


def _mark_test_event_done(test_event: Dict) -> None:
    """Mark this run done so the launchd daemon won't re-fire it."""
    event_time = test_event["start"]
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    state = load_state()
    run_key = f"{test_event['id']}_{event_time.isoformat()}"
    mark_done(state, run_key)
    save_state(state)
    print("✅ Test event executed.")
    print("   (Marked done — the background daemon won't re-fire it.)")


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
