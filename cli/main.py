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
from infra.calendar.calendar_client import build_service, get_upcoming_events

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
from config.settings import EARLY_TOLERANCE, GRACE_SECONDS


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
        status_launchd()
        sys.exit(0)

    if not acquire_lock():
        sys.exit(0)
    try:
        main()
    finally:
        release_lock()
