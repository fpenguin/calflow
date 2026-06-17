"""
Menubar popover cache.

Successful `cli.main popover-feed --json` responses are snapshotted here
so a temporary Google/API refresh failure can still render the last good
timeline instead of an empty popover.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from config.config import DATA_DIR
from core.utils import log


POPOVER_CACHE_PATH = Path(DATA_DIR) / "popover_cache.json"
SCHEMA_VERSION = 1
MAX_AGE_SECONDS = 24 * 60 * 60


def load_cache(path: Path | None = None) -> Dict[str, Any]:
    p = Path(path or POPOVER_CACHE_PATH)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log(f"[WARN] popover_cache.json ignored: {exc}")
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return {}
    if _age_seconds(data.get("cached_at")) is None:
        return {}
    if int(_age_seconds(data.get("cached_at")) or 0) > MAX_AGE_SECONDS:
        return {}
    return data


def save_cache(payload: Mapping[str, Any], path: Path | None = None) -> None:
    p = Path(path or POPOVER_CACHE_PATH)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["schema_version"] = SCHEMA_VERSION
        data["cached_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        data["stale"] = False
        data.pop("error", None)
        data.pop("google_error", None)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, p)
    except Exception as exc:
        log(f"[WARN] Failed to save popover_cache.json: {exc}")


def cache_age_seconds(path: Path | None = None) -> int | None:
    data = load_cache(path)
    if not data:
        return None
    return _age_seconds(data.get("cached_at"))


def _age_seconds(cached_at: Any) -> int | None:
    if not isinstance(cached_at, str) or not cached_at:
        return None
    try:
        dt = datetime.fromisoformat(cached_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None
