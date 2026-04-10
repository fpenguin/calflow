from settings import STATE_RETENTION_HOURS, MAX_STATE_ENTRIES
from datetime import datetime, timezone, timedelta
import json
import os

STATE_FILE = "data/opened_events.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STATE_RETENTION_HOURS)

    pruned = {}

    # --- time-based pruning ---
    for key, timestamp_str in state.items():
        try:
            ts = datetime.fromisoformat(timestamp_str)
            if ts > cutoff:
                pruned[key] = timestamp_str
        except Exception:
            continue

    # --- size cap (keep newest only) ---
    if len(pruned) > MAX_STATE_ENTRIES:
        pruned = dict(
            sorted(pruned.items(), key=lambda x: x[1], reverse=True)[:MAX_STATE_ENTRIES]
        )

    # --- ensure directory exists ---
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    # --- atomic save ---
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w") as f:
        json.dump(pruned, f)

    os.replace(temp_file, STATE_FILE)

def is_done(state, key):
    return key in state


def mark_done(state, key):
    state[key] = datetime.now(timezone.utc).isoformat()