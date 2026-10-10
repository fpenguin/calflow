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


def migrate_targets_to_sidecar(
    *, settings_path: Path | None = None, defaults_path: Path | None = None,
) -> Dict[str, Any]:
    """Preserve legacy aliases; never silently replace conflicting sidecar data."""
    result: dict[str, Any] = {
        "ok": False, "migrated": False, "count": 0,
        "user_targets_path": str(USER_TARGETS_PATH), "backup_path": None,
    }
    try:
        live = _migration_targets(Path(settings_path or SETTINGS_PATH))
        defaults = _migration_targets(Path(defaults_path or DEFAULT_SETTINGS_PATH))
        if live != defaults:
            if USER_TARGETS_PATH.exists():
                data = json.loads(USER_TARGETS_PATH.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
                        or data.get("targets") != live):
                    raise ValueError("Existing aliases conflict with legacy settings; migration aborted")
            else:
                result["backup_path"] = save_user_targets(live)
            result.update(migrated=True, count=len(live))
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _migration_targets(path: Path) -> dict[str, TargetValue]:
    from core.targets_writer import validate_alias_name, validate_app_list

    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = [
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "TARGETS"
    ]
    if len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError("Cannot safely read legacy TARGETS")
    targets = values[0]
    for alias, apps in targets.items():
        if validate_alias_name(alias) or validate_app_list(apps):
            raise ValueError("Invalid legacy TARGETS; migration aborted")
    if _coerce_targets(targets) != targets:
        raise ValueError("Unsupported legacy TARGETS; migration aborted")
    return targets


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
