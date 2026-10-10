"""Serialize desktop workflows across processes, without age-based expiry."""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path

from config.config import DATA_DIR

__all__ = ["desktop_session"]

LOCK_PATH = Path(DATA_DIR) / ".desktop.lock"
_thread_lock = threading.RLock()
_local = threading.local()


@contextmanager
def desktop_session():
    # Nested entrypoints in the same thread share the outer process lock.
    with _thread_lock:
        if getattr(_local, "active", False):
            yield
            return
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            _local.active = True
            try:
                yield
            finally:
                _local.active = False
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
