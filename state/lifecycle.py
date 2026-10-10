"""Persistent login and pause preferences, independent of current launchd state."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

from config.config import DATA_DIR

__all__ = ["load", "update"]

PREFERENCES_PATH = Path(DATA_DIR) / "lifecycle.json"
DEFAULTS = {"paused": False, "daemon_login": True, "menubar_login": True}


def load() -> dict[str, bool]:
    try:
        raw = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULTS)
    if not isinstance(raw, dict):
        raise ValueError("Invalid lifecycle preferences")
    return {key: raw[key] if isinstance(raw.get(key), bool) else default
            for key, default in DEFAULTS.items()}


def update(**changes: bool) -> None:
    if any(key not in DEFAULTS or type(value) is not bool for key, value in changes.items()):
        raise ValueError("Invalid lifecycle preference")
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(PREFERENCES_PATH) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = {**load(), **changes}
        fd, name = tempfile.mkstemp(dir=PREFERENCES_PATH.parent, prefix=".lifecycle-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(values, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, PREFERENCES_PATH)
        finally:
            Path(name).unlink(missing_ok=True)
