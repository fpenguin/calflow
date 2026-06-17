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
from typing import Any, Dict, List, Optional

# Keep dependency-free commands usable before the project environment is
# installed. Heavy imports below may require dateutil/google/pyobjc.
if __name__ == "__main__":
    _early_args = sys.argv[1:]
    _early_cmd = next((a for a in _early_args if not a.startswith("-")), None)
    if any(flag in _early_args for flag in ("--version", "-V")) or _early_cmd == "version":
        from core.version import version_string
        print(f"CalFlow {version_string()}")
        sys.exit(0)
    if _early_cmd in (
        "menubar-install",
        "menubar-start",
        "menubar-stop",
        "menubar-restart",
        "menubar-status",
        "menubar-uninstall",
    ):
        from cli.menubar_launchd import print_menubar_action_json
        print_menubar_action_json(_early_cmd.split("-", 1)[1])
        sys.exit(0)

# CLI / lifecycle
from cli.onboarding import (
    restart_launchd,
    run_onboarding,
    start_launchd,
    stop_launchd,
    uninstall_launchd,
)
from cli.menubar_launchd import print_menubar_action_json

# Infra
from infra.calendar.calendar_client import (
    build_service,
    get_recent_events,
    get_upcoming_events,
    next_event_across_calendars,
)

# Core (unified parser + back-compat re-exports)
from core.parser.parser import (
    extract_alert_offset,
    extract_tags,
    parse,
)
from core.event_trust import classify_event_trust

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
    python3 -m cli.main menubar-install  # show ⏱ CF now and at login
    python3 -m cli.main menubar-status   # check menu bar companion
    python3 -m cli.main uninstall   # remove daemon (data preserved; --full to wipe)
    python3 -m cli.repl             # interactive REPL (no daemon needed)
""".rstrip()


def collect_status() -> Dict:
    """
    Gather status data WITHOUT printing.

    v1.1.27 — single source of truth for both the human dashboard
    (`print_status_summary`) and the machine-readable `--json` output.
    Future menubar consumers can call this directly.

    Returns a dict with these keys (all guaranteed present):

        version       str            — CalFlow version (e.g. "1.1.27")
        daemon        dict           — {loaded: bool, pid?: int, raw_line?: str}
        calendars     list[str]      — selected calendar IDs
        next_event    dict | None    — {title, start, seconds_until, calendar_id}
                                       (None if no event in the lookahead window)
        google_error  str | None     — human-readable error if calendar fetch failed
        lookahead_hours int          — STATUS_LOOKAHEAD_HOURS (e.g. 24)
    """
    from core.version import version_string

    daemon = _daemon_state()
    calendars = get_selected_calendars()

    out: Dict = {
        "version": version_string(),
        "daemon": daemon,
        "calendars": calendars,
        "next_event": None,
        "google_error": None,
        "lookahead_hours": STATUS_LOOKAHEAD_HOURS,
    }

    try:
        service = build_service()
        ev = next_event_across_calendars(
            service, calendars, hours=STATUS_LOOKAHEAD_HOURS,
        )
        if ev is not None:
            now = datetime.now(timezone.utc).astimezone(ev["start"].tzinfo)
            delta = ev["start"] - now
            out["next_event"] = {
                "title": (ev.get("title") or "(untitled)").strip() or "(untitled)",
                "start": ev["start"].isoformat(),
                "seconds_until": int(delta.total_seconds()),
                "calendar_id": ev.get("calendar_id"),
            }
    except RuntimeError as exc:
        out["google_error"] = f"not connected: {exc}"
    except Exception as exc:
        out["google_error"] = f"{type(exc).__name__}: {exc}"

    return out


def print_status_summary() -> None:
    """
    Friendly multi-line status output:

        🟢 CalFlow is active with 3 connected calendars
        📅 Next event starts in 1h 28m  (Daily standup)
        🛠  Try: …

    Degrades gracefully on missing creds, expired token, network error,
    no events, or daemon not loaded.

    v1.1.27 — backed by `collect_status()` for parity with the JSON
    output. Pass `as_json=True` to print machine-readable output instead.
    """
    s = collect_status()
    daemon = s["daemon"]
    cal_count = len(s["calendars"])

    # ------------------ daemon line ------------------
    if daemon["loaded"]:
        head = (
            f"🟢 CalFlow is active with {cal_count} connected calendar"
            f"{'s' if cal_count != 1 else ''}."
        )
    else:
        head = "🟡 CalFlow is installed but the daemon is not loaded."
    print(head)

    # ------------------ next event line --------------
    if s["google_error"]:
        if "not connected" in s["google_error"]:
            print(f"🔐 Not connected to Google Calendar yet.\n    {s['google_error']}")
        else:
            print(f"⚠  Could not fetch upcoming events:\n    {s['google_error']}")
    elif s["next_event"] is None:
        print(f"📅 No upcoming events in the next {s['lookahead_hours']}h.")
    else:
        ev = s["next_event"]
        from datetime import timedelta
        delta = timedelta(seconds=ev["seconds_until"])
        print(
            f"📅 Next event starts {_format_duration(delta)}  "
            f"(Event title: {ev['title']})"
        )

    # ------------------ launchctl detail (if loaded) -
    if daemon["loaded"] and daemon.get("raw_line"):
        print(f"   ↳ launchctl: {daemon['raw_line']}")

    # ------------------ available commands -----------
    print(_AVAILABLE_COMMANDS)


def print_status_json() -> None:
    """v1.1.27 — `cli.main status --json`. Stable contract for menubar consumers."""
    print(json.dumps(collect_status(), indent=2, default=str))


# =========================================================
# 📊 STATS / EVENTS / RUN-EVENT JSON ENDPOINTS  (v1.3.0)
# =========================================================
#
# These power the menubar popover. Each prints a single JSON object
# to stdout, exits 0 on success, non-zero with `{"error": "..."}` on
# failure. Stable contract documented in docs/menubar.md.


def _summarise_event(ev: Dict, *, now: datetime) -> Dict:
    """
    Project a calendar-client event dict into the JSON shape the
    menubar consumes. Pure function (no IO).

    Mode detection mirrors the test runner's _list_test_candidates
    scoring so what the menubar shows == what the daemon would do.
    """
    title = (ev.get("title") or "").strip()
    text = (ev.get("text") or "").strip()
    start = ev.get("start")
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    # Mode detection mirrors run-event. A normal calendar description
    # is not automation just because it has text; only parser output
    # that can execute should get a play button in the menubar.
    import re as _re
    parsed = parse(text, title=title)
    if parsed.is_empty:
        mode = "empty"
    else:
        mode = parsed.mode

    delta = (start - now).total_seconds() if start is not None else None

    # Preview line — best-effort one-liner for the popover row. We
    # never want to leak the full body (PII), so we cap at 1 line +
    # 60 chars and never emit URLs verbatim — host-only.
    preview: Optional[str] = None
    if mode == "smart":
        entry = parsed.entries[0] if parsed.entries else {}
        url = entry.get("url") or ""
        host = _re.sub(r"^https?://", "", url, flags=_re.IGNORECASE).split("/", 1)[0]
        if host:
            preview = f"Opens {host}"
    elif mode == "plus":
        # First non-blank line after the +CalFlow+ header.
        for raw in text.splitlines():
            ln = raw.strip()
            if not ln or ln.lower().startswith("+calflow+") or ln.startswith("##"):
                continue
            preview = ln if len(ln) <= 60 else ln[:57] + "…"
            break

    return {
        "id":             ev.get("id") or "",
        "calendar_id":    ev.get("calendar_id") or "",
        "title":          title or "(untitled)",
        "start":          start.isoformat() if start is not None else None,
        "seconds_until":  int(delta) if delta is not None else None,
        "mode":           mode,
        "preview":        preview,
        "event_url":      ev.get("event_url") or "",
    }


def _hours_arg(args: List[str], default: int) -> int:
    """Parse `--hours N` from args, falling back to `default`."""
    for i, arg in enumerate(args):
        if arg == "--hours" and i + 1 < len(args):
            try:
                return max(1, int(args[i + 1]))
            except ValueError:
                pass
        if arg.startswith("--hours="):
            try:
                return max(1, int(arg.split("=", 1)[1]))
            except ValueError:
                pass
    return default


def print_stats_json() -> None:
    """`cli.main stats --json` — lifetime stats for the menubar header card."""
    from state.stats_store import snapshot
    print(json.dumps(snapshot(), indent=2, default=str))


def collect_upcoming_json(hours: int = 24) -> Dict:
    """Collect data for `cli.main upcoming --json [--hours N]`."""
    out: Dict = {"events": [], "google_error": None, "hours": hours}
    try:
        service = build_service()
    except RuntimeError as exc:
        out["google_error"] = f"not connected: {exc}"
        return out
    except Exception as exc:
        out["google_error"] = f"{type(exc).__name__}: {exc}"
        return out

    now = datetime.now(timezone.utc)
    rows: List[Dict] = []
    try:
        for cal_id in get_selected_calendars():
            for ev in get_upcoming_events(service, cal_id, hours=hours):
                rows.append(_summarise_event(ev, now=now))
    except Exception as exc:
        out["google_error"] = f"{type(exc).__name__}: {exc}"
        return out
    rows.sort(key=lambda r: r.get("start") or "")
    out["events"] = rows
    return out


def print_upcoming_json(hours: int = 24) -> None:
    """`cli.main upcoming --json [--hours N]` — populates the menubar 'Today' list."""
    out = collect_upcoming_json(hours=hours)
    print(json.dumps(out, indent=2, default=str))


def collect_missed_json(hours: int = 12) -> Dict:
    """
    Collect data for `cli.main missed --json [--hours N]` — events whose start was in the
    past `hours` window AND whose run_key is NOT in state. The menubar
    renders these in its "Missed · last 12 h" pane.
    """
    out: Dict = {"events": [], "google_error": None, "hours": hours}
    try:
        service = build_service()
    except RuntimeError as exc:
        out["google_error"] = f"not connected: {exc}"
        return out
    except Exception as exc:
        out["google_error"] = f"{type(exc).__name__}: {exc}"
        return out

    state = load_state()
    now = datetime.now(timezone.utc)
    rows: List[Dict] = []
    try:
        for cal_id in get_selected_calendars():
            for ev in get_recent_events(service, cal_id, hours=hours):
                start = ev.get("start")
                if start is not None and start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                    ev["start"] = start
                run_key = f"{ev.get('id')}_{start.isoformat() if start else ''}"
                if is_done(state, run_key):
                    continue  # already executed — not "missed"
                row = _summarise_event(ev, now=now)
                if row["mode"] == "empty":
                    continue  # no automation → nothing to "miss"
                rows.append(row)
    except Exception as exc:
        out["google_error"] = f"{type(exc).__name__}: {exc}"
        return out
    # Most recent first — the user cares most about what just happened.
    rows.sort(key=lambda r: r.get("start") or "", reverse=True)
    out["events"] = rows
    return out


def print_missed_json(hours: int = 12) -> None:
    """
    `cli.main missed --json [--hours N]` — events whose start was in the
    past `hours` window AND whose run_key is NOT in state. The menubar
    renders these in its "Missed · last 12 h" pane.
    """
    out = collect_missed_json(hours=hours)
    print(json.dumps(out, indent=2, default=str))


def collect_popover_feed(upcoming_hours: int = 30, missed_hours: int = 12) -> Dict:
    """Combined menubar popover feed with cached-data fallback."""
    from state.popover_cache import load_cache, save_cache
    from state.stats_store import snapshot

    try:
        payload = {
            "status": collect_status(),
            "stats": snapshot(),
            "upcoming": collect_upcoming_json(hours=upcoming_hours),
            "missed": collect_missed_json(hours=missed_hours),
            "stale": False,
            "cached_at": None,
            "google_error": None,
        }
        errors = []
        for key in ("status", "upcoming", "missed"):
            err = (payload.get(key) or {}).get("google_error") or (payload.get(key) or {}).get("error")
            if err:
                errors.append(f"{key}: {err}")
        if errors:
            raise RuntimeError("; ".join(errors))
        save_cache(payload)
        return payload
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        cached = load_cache()
        if cached:
            cached = dict(cached)
            cached["stale"] = True
            cached["google_error"] = err
            cached.pop("error", None)
            return cached
        return {
            "status": {"error": err},
            "stats": {},
            "upcoming": {"events": [], "google_error": err, "hours": upcoming_hours},
            "missed": {"events": [], "google_error": err, "hours": missed_hours},
            "stale": False,
            "cached_at": None,
            "google_error": err,
            "error": err,
        }


def print_popover_feed_json(upcoming_hours: int = 30, missed_hours: int = 12) -> None:
    print(json.dumps(
        collect_popover_feed(upcoming_hours=upcoming_hours, missed_hours=missed_hours),
        indent=2,
        default=str,
    ))


def run_event_by_id(event_id: str) -> None:
    """
    `cli.main run-event <id> --json` — locate a calendar event by id
    in the upcoming OR missed window, parse it, execute it, mark done,
    print result JSON.

    Used by the menubar play-icon buttons. Does NOT consult the daemon
    lock — manual run-now is intentional and overrides idempotency
    checks (the user just clicked Run).
    """
    out: Dict = {"id": event_id, "success": False, "mode": None, "error": None}
    if not event_id:
        out["error"] = "missing event id"
        print(json.dumps(out)); return

    try:
        service = build_service()
    except Exception as exc:
        out["error"] = f"calendar: {type(exc).__name__}: {exc}"
        print(json.dumps(out)); return

    target: Optional[Dict] = None
    for cal_id in get_selected_calendars():
        for ev in get_upcoming_events(service, cal_id, hours=24):
            if ev.get("id") == event_id:
                target = ev; break
        if target: break
        for ev in get_recent_events(service, cal_id, hours=12):
            if ev.get("id") == event_id:
                target = ev; break
        if target: break

    if target is None:
        out["error"] = "event not found in upcoming/missed window"
        print(json.dumps(out)); return

    trust_level = _event_trust_or_log(target)
    if trust_level is None:
        out["error"] = "untrusted event source"
        print(json.dumps(out)); return

    text = target.get("text") or ""
    title = target.get("title") or ""
    parsed = parse(text, title=title)
    out["mode"] = parsed.mode

    if parsed.is_empty:
        out["error"] = "no executable content"
        print(json.dumps(out)); return

    try:
        if parsed.is_smart:
            execute_entries(
                entries=parsed.entries,
                global_tags=extract_tags(text),
                debug=DEBUG,
            )
        elif parsed.is_plus:
            execute_commands(
                commands=parsed.commands,
                global_tags=extract_tags(text),
                debug=DEBUG,
                trust_level=trust_level,
            )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out)); return

    # Mark done so the daemon won't re-fire it.
    start = target.get("start")
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start is not None:
        state = load_state()
        run_key = f"{event_id}_{start.isoformat()}"
        mark_done(state, run_key)
        save_state(state)

    out["success"] = True
    print(json.dumps(out))


def _daemon_loaded() -> bool:
    return _daemon_state().get("loaded", False)


def print_daemon_action_json(action: str) -> None:
    """
    `cli.main daemon-{start|stop|restart}` (v1.3.6) — actually run the
    launchctl operation and return the resulting state as JSON.

    Per CLAUDE.md the prohibition on auto-modifying launchd applies to
    the AI agent editing code; a UI button is explicit user approval —
    same trust as the user typing `python -m cli.main start` themselves.
    """
    out: Dict[str, Any] = {"action": action, "ok": False}
    try:
        if action == "start":
            start_launchd()
        elif action == "stop":
            stop_launchd()
        elif action == "restart":
            restart_launchd()
        else:
            out["error"] = f"unknown action {action!r}"
            print(json.dumps(out)); return
        out["ok"] = True
        out["loaded_after"] = _daemon_loaded()
    except FileNotFoundError as exc:
        out["error"] = f"launchd plist missing: {exc}"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(out))


def print_pause_hint() -> None:
    """`cli.main pause` — back-compat alias for `daemon-stop`."""
    print_daemon_action_json("stop")


def print_resume_hint() -> None:
    """`cli.main resume` — back-compat alias for `daemon-start`."""
    print_daemon_action_json("start")


# =========================================================
# 📚 RECIPES JSON ENDPOINTS  (v1.3.1 — menubar Recipes window)
# =========================================================

def print_recipes_json() -> None:
    """`cli.main recipes --json` — stock catalog + user recipes for the Recipes window."""
    from core.recipes import all_recipes
    print(json.dumps(all_recipes(), indent=2, default=str))


def save_recipe_from_stdin() -> None:
    """
    `cli.main save-recipe --json` — read a JSON payload from stdin,
    upsert into data/my_recipes.json, print the canonical saved dict.

    Stdin shape: `{"id"?: "...", "name": "...", "category": "...", "body": "..."}`
    """
    from core.recipes import save_my_recipe
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("stdin must be a JSON object")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"bad payload: {exc}"}))
        sys.exit(1)
    print(json.dumps(save_my_recipe(payload), default=str))


def delete_recipe_by_id(rid: str) -> None:
    """`cli.main delete-recipe <id> --json`."""
    from core.recipes import delete_my_recipe
    print(json.dumps(delete_my_recipe(rid), default=str))


def run_script_from_stdin() -> None:
    """
    `cli.main run-script --json` — execute a literal script string from
    stdin via the existing parser → executor pipeline.

    Used by the menubar Recipes window's "Try it" button. Same execution
    surface as a calendar event; no new permissions. The script body
    is NEVER logged (PII discipline) — only an entry marker is emitted.
    """
    out: Dict = {"success": False, "mode": None, "error": None}
    try:
        body = sys.stdin.read()
    except Exception as exc:
        out["error"] = f"could not read stdin: {exc}"
        print(json.dumps(out)); sys.exit(1)
    if not body or not body.strip():
        out["error"] = "empty script body"
        print(json.dumps(out)); return

    log("[INFO] Sandbox run from menubar Recipes window")
    parsed = parse(body, title="Recipes sandbox")
    out["mode"] = parsed.mode

    if parsed.is_empty:
        out["error"] = "no executable content"
        print(json.dumps(out)); return

    try:
        if parsed.is_smart:
            execute_entries(
                entries=parsed.entries,
                global_tags=extract_tags(body),
                debug=DEBUG,
            )
        elif parsed.is_plus:
            execute_commands(
                commands=parsed.commands,
                global_tags=extract_tags(body),
                debug=DEBUG,
            )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out)); return

    out["success"] = True
    print(json.dumps(out))


# =========================================================
# ⚙️  SETTINGS JSON ENDPOINT  (v1.3.1 — menubar Settings window)
# =========================================================
#
# v1.4.1 — native editing writes gitignored sidecars
# (`data/user_settings.json` / `data/user_targets.json`). Defaults remain
# in `config/settings.py`.
#
# Hidden fields (security / size):
#   - AUTOFILL_SHORTCUTS    (binding table; large, key-centric)
#   - BLACKLIST_REGEX       (security; surface count only)
#   - MAP_DOMAINS           (large list; surface count only)

def print_settings_json() -> None:
    """`cli.main settings --json` — beginner-friendly view of effective settings.

    v1.3.7 — removed Show-menu-bar / Theme / Notifications surfaces;
    real probes for accessibility, apple events, google account.
    """
    from config import settings as S

    def _count_or_none(seq):
        try:
            return len(seq)
        except Exception:
            return None

    payload = {
        "schema_version": 2,
        "general": {
            "auto_start_at_login": _launchd_loaded(),
        },
        "calendar": {
            "google_account":     _google_account_label(),
            "google_status":      "ok" if _has_oauth_token() else "missing",
            "calendars_watched":  _calendar_count_label(),
        },
        "events": {
            "open_minutes_early":   getattr(S, "DEFAULT_ALERT_SECONDS", 300) // 60,
            "default_browser":      _default_browser_label(),
            "default_profile":      _default_profile_label(),
            "fetch_window_hours":   getattr(S, "FETCH_WINDOW_HOURS", 2),
            "status_lookahead_h":   getattr(S, "STATUS_LOOKAHEAD_HOURS", 24),
        },
        "title_links": {
            "use_title_url_when_present": True,    # always-on in current parser
            "open_mode": getattr(S, "TITLE_URL_OPEN_DEFAULT", "tab"),
            "autofill":  getattr(S, "TITLE_URL_AUTOFILL_DEFAULT", "submit"),
        },
        "passwords": {
            "provider":         getattr(S, "AUTOFILL_PROVIDER", "apple"),
            "autofill_on_open": getattr(S, "AUTOFILL_MODE", "semi-auto") != "off",
        },
        # Notifications section removed in v1.3.7 — feature not yet built.
        "permissions": _probe_permissions(),
        "advanced": {
            "trigger_grace_seconds":  getattr(S, "GRACE_SECONDS", 600),
            "early_tolerance_sec":    getattr(S, "EARLY_TOLERANCE", 30),
            "max_urls_per_event":     getattr(S, "MAX_URLS", 5),
            "blocked_url_patterns":   _count_or_none(getattr(S, "BLACKLIST_REGEX", [])),
            "ignored_protocols":      list(getattr(S, "IGNORED_PROTOCOLS", [])),
            "log_mode":               getattr(S, "LOG_MODE", "both"),
            "plus_max_commands":      getattr(S, "PLUS_MAX_COMMANDS", 50),
            "plus_inter_command_delay_sec": getattr(S, "PLUS_INTER_COMMAND_DELAY", 0.3),
            "plus_screenshot_dir":    getattr(S, "PLUS_SCREENSHOT_DIR", "~/Downloads/CalFlow"),
            "settings_file_path":     str(Path(__file__).resolve().parent.parent / "config" / "settings.py"),
        },
    }
    print(json.dumps(payload, indent=2, default=str))


# --- helpers for settings dump --------------------------------

def _launchd_loaded() -> bool:
    return _daemon_state().get("loaded", False)


def _google_account_label() -> str:
    """
    Best-effort: parse the email out of `data/oauth_token.json`, falling
    back to 'Connected' / 'Not connected' if we can't extract it.

    google-auth-oauthlib stores the granted email in the credentials
    JSON when the userinfo scope is included; we ALSO check `data/config.json`
    in case onboarding stashed it there. Never raises.
    """
    # 1) Onboarding-written hint.
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        addr = cfg.get("google_account") or cfg.get("account") or ""
        if addr and "@" in addr:
            return addr
    except Exception:
        pass
    # 2) Token file.
    try:
        from config.config import TOKEN_PATH
        if Path(TOKEN_PATH).exists():
            with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                token = json.load(f)
            for k in ("account", "email", "user_email", "client_id"):
                v = token.get(k)
                if v and isinstance(v, str) and "@" in v:
                    return v
            return "Connected"
    except Exception:
        pass
    return "Not connected"


def _owner_email_hint() -> Optional[str]:
    label = _google_account_label()
    return label if "@" in label else None


def _event_trust_or_log(event: Dict) -> Optional[str]:
    trust = classify_event_trust(event, owner_email=_owner_email_hint())
    if trust.trusted:
        return trust.level
    log(
        "[WARN] Skipped untrusted CalFlow event: "
        f"title={event.get('title', '(untitled)')!r} "
        f"actor={trust.actor or '(unknown)'} reason={trust.reason}"
    )
    return None


def _default_profile_label() -> str:
    """Profile is per-event (#profile(N)). Surface a friendly note."""
    return "per-event tag"


def _probe_permissions() -> Dict[str, Any]:
    """
    Run osascript probes for Apple Events + Accessibility, plus check
    OAuth token. Each probe returns 'granted' | 'denied' | 'unknown'.

    `python_binary` is included so the UI can show the exact path the
    user must add manually in System Settings → Privacy & Security
    → Accessibility (since the OS doesn't auto-list Python until we
    can trigger an AX prompt — see v1.3.9 roadmap).
    """
    return {
        "calendar_oauth":  "granted" if _has_oauth_token() else "denied",
        "apple_events":    _probe_apple_events(),
        "accessibility":   _probe_accessibility(),
        "python_binary":   sys.executable,
    }


def _probe_apple_events() -> str:
    """Try a benign osascript that sends an Apple Event to System Events."""
    import subprocess as _sp
    try:
        result = _sp.run(
            ["osascript", "-e",
             'tell application "System Events" to count of every process'],
            capture_output=True, text=True, timeout=4,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return "granted"
        msg = (result.stderr or "").lower()
        if "-1743" in msg or "not authorized" in msg or "not allowed" in msg:
            return "denied"
        return "unknown"
    except FileNotFoundError:
        return "unknown"
    except Exception:
        return "unknown"


def _probe_accessibility() -> str:
    """
    Probe Accessibility (separate from Apple Events) by reading an AX
    attribute. Apple Events must be granted first; if it's denied this
    returns 'unknown' rather than 'denied' (we can't tell yet).
    """
    import subprocess as _sp
    try:
        result = _sp.run(
            ["osascript", "-e",
             'tell application "System Events" to '
             'get value of attribute "AXEnabled" of UI element 1 '
             'of process "Finder"'],
            capture_output=True, text=True, timeout=4,
        )
        if result.returncode == 0:
            return "granted"
        msg = (result.stderr or "").lower()
        if "assistive" in msg or "accessibility" in msg or "1719" in msg:
            return "denied"
        if "-1743" in msg or "not authorized" in msg:
            return "unknown"   # Apple Events denied — can't probe AX
        return "unknown"
    except FileNotFoundError:
        return "unknown"
    except Exception:
        return "unknown"


def _calendar_count_label() -> str:
    cals = get_selected_calendars()
    return f"{len(cals)} selected"


def _default_browser_label() -> str:
    """Best-effort pull from settings.TARGETS — surface the @chrome target."""
    from config.settings import TARGETS
    chrome = TARGETS.get("@chrome")
    if isinstance(chrome, str):
        return chrome
    return "Default"


def _has_oauth_token() -> bool:
    from config.config import TOKEN_PATH
    return Path(TOKEN_PATH).exists()


# Local "open settings.py in user's editor" — advanced defaults editor.

def open_settings_file() -> None:
    """`cli.main edit-settings-file` — open config/settings.py in default editor."""
    path = Path(__file__).resolve().parent.parent / "config" / "settings.py"
    try:
        import subprocess as _sp
        _sp.Popen(["open", "-t", str(path)])
        print(json.dumps({"ok": True, "opened": str(path)}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


_SYSTEM_PREFS_PANES = {
    "accessibility":
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "automation":
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "appleevents":
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "calendar":
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars",
}


def open_system_prefs(pane: str) -> None:
    """`cli.main open-system-prefs <pane>` — open System Settings to a pane.

    Used by the Settings page Permissions section "Open System Settings"
    buttons. macOS uses the deep-link URL scheme to jump to the right pane.
    """
    url = _SYSTEM_PREFS_PANES.get(pane.lower())
    if not url:
        print(json.dumps({"ok": False, "error": f"unknown pane: {pane!r}",
                          "valid": list(_SYSTEM_PREFS_PANES.keys())}))
        return
    try:
        import subprocess as _sp
        _sp.Popen(["open", url])
        print(json.dumps({"ok": True, "opened": url}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


def apply_settings_from_stdin() -> None:
    """
    `cli.main apply-settings --json` (v1.3.2) — read a JSON object of
    {ui_key: new_value} from stdin and write to data/user_settings.json.

    Returns a result dict (see core.settings_writer.apply_settings).
    """
    from core.settings_writer import apply_settings
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("stdin must be a JSON object")
    except Exception as exc:
        print(json.dumps({
            "applied": [], "rejected": [{"key": "", "reason": f"bad payload: {exc}"}],
            "requires_terminal": [], "backup_path": None,
        }))
        sys.exit(1)
    result = apply_settings(payload)
    print(json.dumps(result, default=str))


def print_targets_json() -> None:
    """`cli.main targets --json` (v1.3.9) — return current TARGETS dict."""
    from core.targets_writer import read_targets
    out = {"targets": read_targets(), "schema_version": 1}
    print(json.dumps(out, indent=2, default=str))


def apply_targets_from_stdin() -> None:
    """
    `cli.main apply-targets --json` (v1.3.9) — read a JSON object
    `{"targets": {alias: "App"|["App",…], …}}` from stdin and replace
    data/user_targets.json atomically.
    """
    from core.targets_writer import apply_targets
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("stdin must be a JSON object")
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "errors": [{"alias": "", "reason": f"bad payload: {exc}"}],
        }))
        sys.exit(1)
    print(json.dumps(apply_targets(payload), default=str))


def migrate_settings_command() -> None:
    """Move legacy settings.py/TARGETS edits into gitignored JSON sidecars."""
    from core.settings_reader import migrate_settings_to_sidecars
    from core.targets_reader import migrate_targets_to_sidecar

    settings_result = migrate_settings_to_sidecars()
    targets_result = migrate_targets_to_sidecar()
    print(json.dumps({
        "ok": bool(settings_result.get("ok")) and bool(targets_result.get("ok")),
        "settings": settings_result,
        "targets": targets_result,
    }, indent=2, default=str))


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
    from core.version import version_string
    log(f"[INFO] CalFlow {version_string()} started")

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

        trust_level = _event_trust_or_log(event)
        if trust_level is None:
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
                    trust_level=trust_level,
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

    # v1.2.0 — flag-only invocations (no subcommand). `cmd` strips flags
    # via `_first_non_flag_arg`, so `python -m cli.main --version` would
    # otherwise fall through to the daemon path. Check sys.argv directly.
    if any(flag in args for flag in ("--version", "-V")):
        from core.version import version_string
        print(f"CalFlow {version_string()}")
        sys.exit(0)

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
        # v1.1.27 — `--json` flag gives machine-readable output for the
        # future menubar app. The contract is `cli.main.collect_status()`.
        if "--json" in sys.argv:
            print_status_json()
        else:
            print_status_summary()
        sys.exit(0)
    if cmd == "display":
        print_display_inventory()
        sys.exit(0)
    if cmd == "test":
        run_test()
        sys.exit(0)
    if cmd == "stats":
        print_stats_json()
        sys.exit(0)
    if cmd == "recipes":
        print_recipes_json()
        sys.exit(0)
    if cmd == "save-recipe":
        save_recipe_from_stdin()
        sys.exit(0)
    if cmd == "delete-recipe":
        # Find first non-flag arg AFTER `delete-recipe`.
        rid = None
        seen = False
        for a in args:
            if a == "delete-recipe":
                seen = True; continue
            if seen and not a.startswith("-"):
                rid = a; break
        delete_recipe_by_id(rid or "")
        sys.exit(0)
    if cmd == "run-script":
        run_script_from_stdin()
        sys.exit(0)
    if cmd == "settings":
        print_settings_json()
        sys.exit(0)
    if cmd == "edit-settings-file":
        open_settings_file()
        sys.exit(0)
    if cmd == "apply-settings":
        apply_settings_from_stdin()
        sys.exit(0)
    if cmd == "targets":
        print_targets_json()
        sys.exit(0)
    if cmd == "apply-targets":
        apply_targets_from_stdin()
        sys.exit(0)
    if cmd == "migrate-settings":
        migrate_settings_command()
        sys.exit(0)
    if cmd in ("daemon-start", "daemon-stop", "daemon-restart"):
        print_daemon_action_json(cmd.split("-", 1)[1])
        sys.exit(0)
    if cmd in (
        "menubar-install",
        "menubar-start",
        "menubar-stop",
        "menubar-restart",
        "menubar-status",
        "menubar-uninstall",
    ):
        print_menubar_action_json(cmd.split("-", 1)[1])
        sys.exit(0)
    if cmd == "open-system-prefs":
        # Find the pane arg AFTER the verb.
        pane = None; seen = False
        for a in args:
            if a == "open-system-prefs":
                seen = True; continue
            if seen and not a.startswith("-"):
                pane = a; break
        open_system_prefs(pane or "accessibility")
        sys.exit(0)
    if cmd == "popover-feed":
        print_popover_feed_json(upcoming_hours=_hours_arg(args, default=30), missed_hours=12)
        sys.exit(0)
    if cmd == "upcoming":
        print_upcoming_json(hours=_hours_arg(args, default=24))
        sys.exit(0)
    if cmd == "missed":
        print_missed_json(hours=_hours_arg(args, default=12))
        sys.exit(0)
    if cmd == "run-event":
        # Find the event id — first non-flag arg AFTER the verb.
        ev_id: Optional[str] = None
        seen_verb = False
        for a in args:
            if a == "run-event":
                seen_verb = True; continue
            if seen_verb and not a.startswith("-"):
                ev_id = a; break
        run_event_by_id(ev_id or "")
        sys.exit(0)
    if cmd == "pause":
        print_pause_hint()
        sys.exit(0)
    if cmd == "resume":
        print_resume_hint()
        sys.exit(0)
    if cmd == "menubar":
        # Lazy import — rumps + pyobjc are optional runtime deps.
        try:
            from cli.menubar import main as menubar_main
        except ImportError as exc:
            print(json.dumps({
                "error": f"menubar deps missing: {exc}",
                "install": "pip install rumps pyobjc-framework-WebKit pyobjc-framework-Cocoa",
            }, indent=2))
            sys.exit(2)
        menubar_main()
        sys.exit(0)
    if cmd in ("--version", "-V", "version"):
        from core.version import version_string
        print(f"CalFlow {version_string()}")
        sys.exit(0)

    if not acquire_lock():
        sys.exit(0)
    try:
        main()
    finally:
        release_lock()
