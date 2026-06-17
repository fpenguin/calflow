"""
User TARGETS sidecar reader/writer.

`config/settings.py` keeps the default @aliases. Runtime/user edits from
the Settings window live in `data/user_targets.json`.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

from config.config import BASE_DIR, DATA_DIR
from core.utils import log


TargetValue = Union[str, List[str]]

USER_TARGETS_PATH = Path(DATA_DIR) / "user_targets.json"
USER_TARGETS_BACKUP_PATH = Path(DATA_DIR) / "user_targets.json.bak"
SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.py"
DEFAULT_SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.defaults.py"
SCHEMA_VERSION = 1


def load_user_targets(path: Path | None = None) -> Dict[str, TargetValue] | None:
    """Return user TARGETS if the sidecar exists; None means no override."""
    p = Path(path or USER_TARGETS_PATH)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log(f"[WARN] user_targets.json ignored: {exc}")
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        log("[WARN] user_targets.json ignored: unsupported schema")
        return None
    raw = data.get("targets")
    return _coerce_targets(raw)


def save_user_targets(
    targets: Mapping[str, TargetValue],
    *,
    path: Path | None = None,
    backup_path: Path | None = None,
) -> str | None:
    p = Path(path or USER_TARGETS_PATH)
    b = Path(backup_path or USER_TARGETS_BACKUP_PATH)
    cleaned = _coerce_targets(dict(targets))
    p.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if p.exists():
        try:
            shutil.copyfile(str(p), str(b))
            backup = str(b)
        except Exception as exc:
            log(f"[WARN] user_targets.json backup failed: {exc}")
    payload = {"schema_version": SCHEMA_VERSION, "targets": cleaned}
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return backup


def migrate_targets_to_sidecar() -> Dict[str, Any]:
    live = _read_targets_from_path(SETTINGS_PATH)
    defaults = _read_targets_from_path(DEFAULT_SETTINGS_PATH if DEFAULT_SETTINGS_PATH.exists() else SETTINGS_PATH)
    changed = live != defaults
    backup = None
    if changed:
        backup = save_user_targets(live)
    return {
        "ok": True,
        "migrated": changed,
        "count": len(live) if changed else 0,
        "user_targets_path": str(USER_TARGETS_PATH),
        "backup_path": backup,
    }


def _read_targets_from_path(path: Path) -> Dict[str, TargetValue]:
    try:
        text = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "TARGETS":
                    return _coerce_targets(ast.literal_eval(node.value))
    except Exception:
        return {}
    return {}


def _coerce_targets(raw: Any) -> Dict[str, TargetValue]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, TargetValue] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, str):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            apps = [a for a in v if isinstance(a, str)]
            if apps:
                out[k] = apps
    return out
