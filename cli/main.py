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
    """
    Top-level dispatcher for `python3 -m cli.main test`.

    Pipeline:
        1. fetch all upcoming events (next 2 hours)
        2. rank: Plus > Smart-with-content > empty
        3. let user pick (or fall to custom script / new event)
    """
    print("=" * 50)
    print(" 🧪  CalFlow test runner")
    print("=" * 50)
    print()

    candidates = _list_test_candidates()
    test_event = _pick_test_candidate(candidates)
    if test_event is None:
        return

    _step1_choose_mode(test_event)


def _step1_choose_mode(test_event: Dict) -> None:
    """Display the event header + preview + run-mode menu."""
    text = test_event.get("text") or ""
    parsed = parse(text, title=test_event.get("title"))
    plus_marker = "+CalFlow+" if parsed.is_plus else "Smart"

    print(f"Selected: {test_event['title']!r}")
    print(f"Mode    : {plus_marker}")
    print()
    _print_description_preview(text)
    if parsed.is_empty:
        print()
        print("⚠  This event has no executable content.")
        print("   Pick a different event (option 4) or paste a custom script.")
        print()
    else:
        print()
    print("Run mode:")
    print()
    print("  1) Calendar Event — Dry run (no execution)")
    print("  2) Calendar Event — Execute")
    print("  3) Custom Script")
    print("  4) Pick a different event")
    print("  q) Quit")
    print()

    choice = input("Choose: ").strip().lower()
    print()
    if choice == "1":
        _step2a_dry_run(test_event, parsed)
    elif choice == "2":
        if parsed.is_empty:
            print("[WARN] Refusing to execute — nothing to do.")
            return
        _step2b_execute_loop(test_event, parsed)
    elif choice == "3":
        _run_custom_script_loop()
    elif choice == "4":
        candidates = _list_test_candidates()
        next_event = _pick_test_candidate(candidates)
        if next_event is not None:
            _step1_choose_mode(next_event)
    elif choice in ("q", "quit", "exit"):
        return
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
    """Execute, then loop on [Enter]=rerun / [n]=new event / [p]=pick / [q]=quit."""
    while True:
        if parsed.is_empty:
            print("[WARN] Refusing to execute — nothing to do.")
            print("       Pick a different event or paste a custom script.")
        else:
            try:
                _execute_parsed(parsed)
                _mark_test_event_done(test_event)
            except Exception as exc:
                print(f"\n[ERROR] Test execution failed: {exc}")

        print()
        print("Press:")
        print("  [Enter] → run again")
        print("  [n]     → create a new Google Calendar event")
        print("  [p]     → pick a different event")
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
            continue
        if choice == "p":
            candidates = _list_test_candidates()
            picked = _pick_test_candidate(candidates)
            if picked is None:
                return
            test_event = picked
            text = test_event.get("text") or ""
            parsed = parse(text, title=test_event.get("title"))
            continue
        # empty input → re-run with same parsed AST


def _run_custom_script_loop() -> None:
    """Paste DSL → parse → run; offer [Enter]/[c]/[q]."""
    script = _prompt_for_script()
    while script is not None:
        parsed = parse(script, title="Custom script")

        # v1.1.16 — custom-script convenience: if the paste smells like
        # Plus Mode (any line starts with a Plus verb), auto-prepend
        # `+CalFlow+\n` and re-parse — REGARDLESS of whether Smart Mode
        # produced an entry from the same text.
        #
        # Why dropped the v1.1.6 `is_empty` precondition: Smart Mode
        # mis-parses lines like `open "site.com?date={now}"` into a
        # truncated entry (URL stops at `{`) instead of empty. The user
        # clearly meant Plus Mode (Smart has no `open` verb), so the
        # presence of a Plus verb word at line start is a stronger
        # signal than 'Smart found nothing'. Calendar events still
        # REQUIRE the marker — auto-promote is custom-script-only.
        if parsed.mode == "smart" and _looks_like_plus(script):
            print()
            print("[WARN] Plus mode command detected (line starts with a Plus verb).")
            print("[WARN] Auto-switching to Plus mode for this run.")
            print("[WARN] Add `+CalFlow+` header at the top to suppress this warning,")
            print("       or to use Plus mode in calendar events.")
            parsed = parse("+CalFlow+\n" + script, title="Custom script")

        print()
        print("Parsed:")
        _print_parsed_summary(parsed)
        if parsed.is_empty:
            _diagnose_empty_script(script)
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
    Open Google Calendar with a pre-filled sample event, then poll for
    it to appear. Returns the freshly created event dict, or None if
    the user backs out / it never shows up.

    After saving, we re-fetch and pick the highest-scored candidate
    starting in the next 10 minutes — that's almost always the just-
    saved sample.
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

    print()
    candidates = _list_test_candidates(hours=1)
    if not candidates:
        print("⚠  No upcoming events found — did you click Save?")
        return None

    # The freshly saved sample is the highest-scoring item starting in
    # the next ~10 minutes. If multiple match, hand off to the picker.
    now = datetime.now(timezone.utc)
    near = [
        ev for ev in candidates
        if (ev["start"] - now).total_seconds() < 600
    ]
    if len(near) == 1:
        chosen = near[0]
        print(f"[INFO] Found:        {chosen['title']!r}")
        print(f"[INFO] Calendar:     {chosen.get('calendar_id', '(unknown)')}")
        print(f"[INFO] Scheduled at: {chosen['start'].isoformat()}")
        print()
        return chosen
    return _pick_test_candidate(candidates)


def _list_test_candidates(hours: int = 2) -> List[Dict]:
    """
    Fetch every upcoming event in the next `hours` hours across all
    selected calendars and rank them so the most likely test target
    floats to the top:

        score 3 — Plus block (`+CalFlow+` in description)
        score 2 — title contains 'calflow' or 'test'
        score 1 — non-empty description
        score 0 — empty / comments-only

    Within each score bucket, earliest start wins.

    Each event gets two computed fields:
        _score    : int (above)
        _mode     : 'plus' | 'smart' | 'empty'
    """
    print("[INFO] Fetching upcoming events from Google Calendar…")
    try:
        service = build_service()
    except RuntimeError as exc:
        print(f"\n🔐 Not connected to Google Calendar yet.\n   {exc}")
        return []
    except Exception as exc:
        print(
            f"\n⚠  Could not connect to Google Calendar:\n   "
            f"{type(exc).__name__}: {exc}"
        )
        return []

    out: List[Dict] = []
    for cal_id in get_selected_calendars():
        for ev in get_upcoming_events(service, cal_id, hours=hours):
            text = (ev.get("text") or "").strip()
            title_raw = (ev.get("title") or "").strip()
            title = title_raw.lower()

            # v1.1.21 — also probe the title for URLs. A title-URL-only
            # event (empty body, URL in title) used to score as
            # `[empty]` because the old logic looked at body text only.
            # Now any URL — body or title — counts as a Smart signal.
            import re as _re_local
            title_has_url = bool(
                _re_local.search(r"https?://", title_raw, _re_local.IGNORECASE)
            )

            # Score
            if "+calflow+" in text.lower():
                score = 3
                mode = "plus"
            elif "calflow" in title or "test" in title:
                score = 2
                mode = "smart" if (text or title_has_url) else "empty"
            elif text or title_has_url:
                score = 1
                mode = "smart"
            else:
                score = 0
                mode = "empty"

            ev["_score"] = score
            ev["_mode"] = mode

            event_time = ev["start"]
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
                ev["start"] = event_time

            out.append(ev)

    out.sort(key=lambda ev: (-ev["_score"], ev["start"]))
    print()
    return out


def _pick_test_candidate(candidates: List[Dict]) -> Optional[Dict]:
    """
    Show the user a numbered list of upcoming events, plus options to
    create a new test event, paste a custom script, or quit. Returns
    the chosen event dict, or None if the user picked custom/quit
    (those branches handle themselves).
    """
    if not candidates:
        print("⚠  No upcoming events in the next 2 hours.")
        print()
        return _offer_create_or_custom()

    print("Upcoming events (next 2 hours):")
    print()
    now = datetime.now(timezone.utc)
    for i, ev in enumerate(candidates[:9], start=1):
        delta = ev["start"] - now
        when = _format_relative_delta(delta)
        mode_tag = {
            "plus":  "[+CalFlow+]",
            "smart": "[Smart]    ",
            "empty": "[empty]    ",
        }.get(ev.get("_mode", "empty"), "[?]        ")
        title = ev.get("title") or "(untitled)"
        print(f"  [{i}] {mode_tag}  {title!r:40s}  {when}")
    print()
    print("  [n] Create a new test event (browser opens)")
    print("  [c] Custom script (paste DSL)")
    print("  [q] Quit")
    print()

    choice = input("Choose: ").strip().lower()
    print()
    if not choice or choice in ("q", "quit", "exit"):
        return None
    if choice == "n":
        return _offer_create_test_event()
    if choice == "c":
        _run_custom_script_loop()
        return None
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(candidates[:9]):
            return candidates[idx - 1]
    print(f"Unrecognised choice {choice!r}. Cancelled.")
    return None


def _offer_create_or_custom() -> Optional[Dict]:
    """No candidates — offer to create one or paste a custom script."""
    print("Options:")
    print("  [n] Create a new test event (browser opens)")
    print("  [c] Custom script (paste DSL)")
    print("  [q] Quit")
    print()
    choice = input("Choose: ").strip().lower()
    print()
    if choice == "n":
        return _offer_create_test_event()
    if choice == "c":
        _run_custom_script_loop()
        return None
    return None


def _format_relative_delta(delta) -> str:
    """'in 2m', 'in 47s', 'now', '3m ago' — for candidate listing."""
    secs = int(delta.total_seconds())
    if -30 <= secs <= 30:
        return "now"
    sign = "in" if secs > 0 else "ago"
    secs = abs(secs)
    if secs < 60:
        magnitude = f"{secs}s"
    elif secs < 3600:
        magnitude = f"{secs // 60}m"
    else:
        magnitude = f"{secs // 3600}h{(secs % 3600) // 60}m"
    return f"{sign} {magnitude}" if sign == "in" else f"{magnitude} ago"


_PLUS_VERBS = (
    "open", "focus", "close", "hide", "click", "type", "press",
    "wait", "screenshot", "copy", "paste", "save", "run",
)


def _looks_like_plus(script: str) -> bool:
    """
    True if any non-blank line begins with a Plus Mode verb. Used to
    decide whether to auto-promote a custom-script paste into Plus
    Mode (v1.1.6). Substring `+CalFlow+` short-circuits to False (it
    would already parse as Plus directly).
    """
    if not script or "+calflow+" in script.lower():
        return False
    for raw in script.splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("##"):
            continue
        # First whitespace-delimited token IS the verb.
        head = line.split(None, 1)[0]
        # Detach trailing `(...)` if the user wrote `wait(5s)` or `type("x")`
        if "(" in head:
            head = head.split("(", 1)[0]
        if head in _PLUS_VERBS:
            return True
    return False


def _diagnose_empty_script(script: str) -> None:
    """
    When a custom script parses to nothing, surface the most likely
    explanation. Common cases:
        - copy-paste added a leading apostrophe / smart quote
        - the user forgot the `+CalFlow+` header but used Plus verbs
        - the description has no URL/Plus content (Smart-mode noise only)
    """
    if not script:
        print("[WARN] Empty script.")
        return

    lines = [ln for ln in script.splitlines() if ln.strip()]
    if not lines:
        print("[WARN] Script is whitespace only.")
        return

    # Detect a near-miss header (apostrophe / quote / case variation).
    plus_lower = "+calflow+"
    near_miss = None
    for ln in lines:
        s = ln.strip().lower()
        if s == plus_lower:
            near_miss = None  # actual header found, parser bug elsewhere
            break
        # Strip stray quote-like characters and re-test.
        stripped = s
        for ch in "'\"‘’“”`":
            stripped = stripped.strip(ch)
        if stripped.strip() == plus_lower and s != plus_lower:
            near_miss = ln
            break

    if near_miss is not None:
        print()
        print("[WARN] Script has no executable content.")
        print(f"       Found a near-miss header: {near_miss!r}")
        print("       Did your paste include surrounding quotes? Try:")
        print("         +CalFlow+   (no quotes, no leading whitespace)")
        return

    # No header detected at all — but script uses Plus verbs.
    plus_verbs = (
        "open", "focus", "close", "hide", "click", "type", "press",
        "wait", "screenshot", "copy", "paste", "save", "run",
    )
    has_verb = any(
        any(ln.strip().lower().startswith(v + " ") or ln.strip().lower() == v
            for v in plus_verbs)
        for ln in lines
    )
    if has_verb and not any("+calflow+" in ln.lower() for ln in lines):
        print()
        print("[WARN] Script has no executable content.")
        print("       Looks like a Plus Mode script but it's missing the")
        print("       `+CalFlow+` header on its own line at the top.")
        return

    print()
    print("[WARN] Script has no executable content; skipping.")


def _print_description_preview(text: str, max_lines: int = 8) -> None:
    """
    Show the post-normalize description so the user can verify what
    the parser actually saw. Trim to N lines for the menu view.
    """
    if not text:
        print("  (description is empty)")
        return
    lines = text.splitlines()
    print("Description:")
    for line in lines[:max_lines]:
        print(f"  │ {line}")
    if len(lines) > max_lines:
        print(f"  │ … ({len(lines) - max_lines} more line(s))")


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
        title = event.get("title") or ""

        # v1.1.23 — DO NOT skip when text.strip() is empty. v1.1.21
        # made the parser fall through to title-URL extraction, but
        # this early filter was bypassing it for the daemon. The
        # `parsed.is_empty` check below (after parse()) handles the
        # truly-empty case correctly.
        if not text.strip() and not title.strip():
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
