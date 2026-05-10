"""
CalFlow lifetime stats persistence (v1.3.0).

Schema (`data/stats.json`):

    {
        "first_run_date": "2024-07-28T14:32:01+00:00",
        "actions_run":    12546,
        "actions_failed": 87,
        "by_type": {
            "open_url":     6500,
            "open_profile": 1500,
            "arrange":      2000,
            "hide":         1000,
            "focus":        300,
            "autofill":     1200,
            "screenshot":   46,
        },
        "schema_version": 1,
    }

Why this is separate from `state.json`:
- state.json is time-pruned (STATE_RETENTION_HOURS) and size-capped
  (MAX_STATE_ENTRIES); stats are permanent and monotonic.
- state.json keys are run-keys (event-id_iso); intermixing schemas
  would force every reader to special-case stats keys.
- Different failure modes — a corrupt state.json should NOT cost the
  user their lifetime stats, and vice versa.

Public API:
    load_stats()                          → dict
    save_stats(stats)                     → None
    get_or_init_first_run()               → str (ISO-8601 UTC)
    record_action(verb_key, success=True) → None  (load + mutate + save)
    record_actions(counts: dict)          → None  (batch variant)
    snapshot()                            → dict  (UI-ready, includes computed time_saved)

Concurrency:
- Atomic write via tmp + os.replace (same pattern as state_manager).
- The daemon and the menubar are separate processes; they may interleave.
  Each call is read-modify-write, last-write-wins. For a stats counter
  this is acceptable — at worst we lose one increment per collision.
- A future v2.x can switch to a fcntl.flock-based critical section if
  collisions ever matter. They won't for an event-driven workload.
"""

from __future__ import annotations

# v1.3.0 — public surface lock.
__all__ = [
    "DEFAULT_STATS",
    "get_or_init_first_run",
    "load_stats",
    "record_action",
    "record_actions",
    "save_stats",
    "snapshot",
]

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from config.config import DATA_DIR
from core.stats import compute_time_saved, format_time_saved
from core.utils import log


# =========================================================
# 📁 STATS FILE LOCATION
# =========================================================
#
# Sibling of state.json under data/. Created on first write; never
# deleted by CalFlow itself (uninstall --full clears the whole data/
# tree, but that's the user's explicit choice).

STATS_PATH = Path(DATA_DIR) / "stats.json"


# =========================================================
# 🌱 DEFAULTS
# =========================================================

DEFAULT_STATS: Dict[str, Any] = {
    "first_run_date": None,    # ISO-8601 UTC; set on first save
    "actions_run":    0,
    "actions_failed": 0,
    "by_type":        {},
    "schema_version": 1,
}


# =========================================================
# 💾 LOAD / SAVE
# =========================================================

def load_stats() -> Dict[str, Any]:
    """
    Load stats from disk. Returns DEFAULT_STATS (a fresh copy) on any
    failure — corrupted, missing, or malformed.

    Never raises; always returns a writable dict.
    """
    if not STATS_PATH.exists():
        return _fresh()
    try:
        if STATS_PATH.stat().st_size == 0:
            return _fresh()
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _fresh()
        # Normalise — a partial / hand-edited file shouldn't crash readers.
        out = _fresh()
        out.update({k: data.get(k, v) for k, v in DEFAULT_STATS.items()})
        if not isinstance(out["by_type"], dict):
            out["by_type"] = {}
        return out
    except Exception as exc:
        log(f"[WARN] stats.json corrupted, resetting in-memory copy: {exc}")
        return _fresh()


def save_stats(stats: Mapping[str, Any]) -> None:
    """
    Persist stats atomically. Failures are logged but never raised —
    a stats write that fails should never abort the executor.
    """
    try:
        STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(STATS_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(stats), f, indent=2, sort_keys=True)
        os.replace(tmp, STATS_PATH)
    except Exception as exc:
        log(f"[WARN] Failed to save stats.json: {exc}")


# =========================================================
# 🌱 FIRST-RUN INIT
# =========================================================

def get_or_init_first_run() -> str:
    """
    Return the stored first_run_date, initialising it on first call.

    Idempotent — subsequent calls return the originally-stored value
    even if the daemon has been restarted hundreds of times.
    """
    stats = load_stats()
    if stats.get("first_run_date"):
        return str(stats["first_run_date"])
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stats["first_run_date"] = now
    save_stats(stats)
    return now


# =========================================================
# ➕ INCREMENT API
# =========================================================

def record_action(verb_key: str, success: bool = True) -> None:
    """
    Record a single executed action.

    Args:
        verb_key: e.g. "open_url", "autofill", "hide"
        success: False → bumps actions_failed instead of actions_run
                 (failed actions never count toward time saved)

    No-op on empty / non-string keys.
    """
    if not verb_key or not isinstance(verb_key, str):
        return
    stats = load_stats()
    if stats.get("first_run_date") is None:
        stats["first_run_date"] = datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat()
    if success:
        stats["actions_run"] = int(stats.get("actions_run", 0)) + 1
        bt = stats.setdefault("by_type", {})
        bt[verb_key] = int(bt.get(verb_key, 0)) + 1
    else:
        stats["actions_failed"] = int(stats.get("actions_failed", 0)) + 1
    save_stats(stats)


def record_actions(counts: Mapping[str, int]) -> None:
    """
    Batch variant of record_action. Single read-modify-write for the
    whole map — preferred when the caller has multiple successful
    actions to record from one event (executor end-of-event flush).

    Failed actions are not addressed here — failures are individual
    and should call record_action(..., success=False).
    """
    if not counts:
        return
    stats = load_stats()
    if stats.get("first_run_date") is None:
        stats["first_run_date"] = datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat()
    bt = stats.setdefault("by_type", {})
    delta = 0
    for key, count in counts.items():
        if not isinstance(key, str) or not key:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        bt[key] = int(bt.get(key, 0)) + n
        delta += n
    stats["actions_run"] = int(stats.get("actions_run", 0)) + delta
    save_stats(stats)


# =========================================================
# 📊 UI SNAPSHOT
# =========================================================

def snapshot() -> Dict[str, Any]:
    """
    Return a UI-ready stats snapshot, including computed fields the
    raw JSON doesn't store.

    Used by `cli.main stats --json` and (eventually) the menubar.

    Schema:
        {
            "first_run_date":    str | None,
            "actions_run":       int,
            "actions_failed":    int,
            "by_type":           dict[str, int],
            "time_saved_seconds": int,
            "time_saved_human":   str,
            "schema_version":    int,
        }
    """
    stats = load_stats()
    secs = compute_time_saved(stats.get("by_type", {}) or {})
    return {
        "first_run_date":     stats.get("first_run_date"),
        "actions_run":        int(stats.get("actions_run", 0)),
        "actions_failed":     int(stats.get("actions_failed", 0)),
        "by_type":            dict(stats.get("by_type", {}) or {}),
        "time_saved_seconds": int(secs),
        "time_saved_human":   format_time_saved(secs),
        "schema_version":     int(stats.get("schema_version", 1)),
    }


# =========================================================
# 🛠 INTERNAL
# =========================================================

def _fresh() -> Dict[str, Any]:
    """Return a fresh, mutable copy of the default stats schema."""
    return {
        "first_run_date": None,
        "actions_run":    0,
        "actions_failed": 0,
        "by_type":        {},
        "schema_version": 1,
    }
