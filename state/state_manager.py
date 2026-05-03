"""
CalFlow State Management (v2.0).

Salvaged from v1.0 (the v1.0 state.py was correct and minimal — the
v2.0 attempt at richer JSON state had broken imports). Reverted to the
simple key→ISO-timestamp dict, which is enough for idempotency.

Public API:
    load_state()                   → dict
    save_state(state: dict)        → None  (atomic, with retention + cap)
    is_done(state, run_key)        → bool
    mark_done(state, run_key)      → None  (sets state[run_key] = now)

Design:
- atomic write via temp file + os.replace
- time-based pruning via STATE_RETENTION_HOURS
- size cap via MAX_STATE_ENTRIES
- never raises; failures logged
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from config.config import STATE_PATH
from config.settings import MAX_STATE_ENTRIES, STATE_RETENTION_HOURS
from core.utils import log


# =========================================================
# 🔄 LOAD / SAVE
# =========================================================

def load_state() -> Dict[str, str]:
    """
    Load state from disk. Returns {} if absent, empty, or corrupted.

    Empty file (0 bytes) is treated as 'fresh state' — silent.
    Truly malformed JSON gets a `[WARN]` and resets to {}.
    """
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        # Treat empty / whitespace-only file as fresh — no warning.
        if os.path.getsize(STATE_PATH) == 0:
            return {}
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log(f"[WARN] State corrupted, resetting: {exc}")
        return {}


def save_state(state: Dict[str, str]) -> None:
    """
    Persist state with retention + size cap.

    - drops entries older than `STATE_RETENTION_HOURS`
    - caps at `MAX_STATE_ENTRIES` (keeps newest by timestamp)
    - atomic write
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STATE_RETENTION_HOURS)
    pruned: Dict[str, str] = {}

    # Time-based pruning
    for key, ts_str in state.items():
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts > cutoff:
                pruned[key] = ts_str
        except Exception:
            continue

    # Size cap (keep newest)
    if len(pruned) > MAX_STATE_ENTRIES:
        pruned = dict(
            sorted(pruned.items(), key=lambda kv: kv[1], reverse=True)
            [:MAX_STATE_ENTRIES]
        )

    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = str(STATE_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pruned, f)
        os.replace(tmp, STATE_PATH)
    except Exception as exc:
        log(f"[WARN] Failed to save state: {exc}")


# =========================================================
# ✅ IDEMPOTENCY
# =========================================================

def is_done(state: Dict[str, str], run_key: str) -> bool:
    """True iff `run_key` has already been recorded."""
    return run_key in state


def mark_done(state: Dict[str, str], run_key: str) -> None:
    """Record `run_key` with the current UTC timestamp."""
    state[run_key] = datetime.now(timezone.utc).isoformat()


# =========================================================
# 🧹 DEV / DEBUG
# =========================================================

def clear_state() -> None:
    """Wipe the on-disk state file."""
    try:
        if os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
        log("[INFO] State cleared")
    except Exception as exc:
        log(f"[WARN] clear_state failed: {exc}")
