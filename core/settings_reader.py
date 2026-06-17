"""
User settings sidecar reader/writer.

Runtime defaults live in `config/settings.py`. User edits from the
menubar Settings UI live in `data/user_settings.json`, which is
gitignored and safe to mutate at runtime.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from config.config import BASE_DIR, DATA_DIR
from core.settings_schema import CONST_TO_SPEC
from core.utils import log


USER_SETTINGS_PATH = Path(DATA_DIR) / "user_settings.json"
USER_SETTINGS_BACKUP_PATH = Path(DATA_DIR) / "user_settings.json.bak"
SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.py"
DEFAULT_SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.defaults.py"

SCHEMA_VERSION = 1


def load_user_overrides(path: Path | None = None) -> Dict[str, Any]:
    """Return valid constant-name overrides from the JSON sidecar."""
    p = Path(path or USER_SETTINGS_PATH)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log(f"[WARN] user_settings.json ignored: {exc}")
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        log("[WARN] user_settings.json ignored: unsupported schema")
        return {}
    raw = data.get("overrides")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for const_name, value in raw.items():
        coerced, err = _coerce_const_override(str(const_name), value)
        if err:
            log(f"[WARN] user_settings.json dropped {const_name!r}: {err}")
            continue
        out[str(const_name)] = coerced
    return out


def save_user_overrides(
    overrides: Mapping[str, Any],
    *,
    path: Path | None = None,
    backup_path: Path | None = None,
) -> str | None:
    """
    Persist overrides atomically. Returns the backup path if one was made.
    Raises on write failures so callers can surface the Apply error.
    """
    p = Path(path or USER_SETTINGS_PATH)
    b = Path(backup_path or USER_SETTINGS_BACKUP_PATH)
    cleaned: Dict[str, Any] = {}
    for const_name, value in dict(overrides).items():
        coerced, err = _coerce_const_override(str(const_name), value)
        if err:
            raise ValueError(f"{const_name}: {err}")
        cleaned[str(const_name)] = coerced

    p.parent.mkdir(parents=True, exist_ok=True)
    backup: str | None = None
    if p.exists():
        try:
            shutil.copyfile(str(p), str(b))
            backup = str(b)
        except Exception as exc:
            log(f"[WARN] user_settings.json backup failed: {exc}")

    payload = {"schema_version": SCHEMA_VERSION, "overrides": cleaned}
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return backup


def migrate_settings_to_sidecars() -> Dict[str, Any]:
    """
    One-shot migration for older installs that had local edits in
    `config/settings.py`. Editable constant drift is copied into
    `data/user_settings.json`; TARGETS drift is handled by
    `core.targets_reader.migrate_targets_to_sidecar`.
    """
    live = _literal_assignments(SETTINGS_PATH)
    defaults = _literal_assignments(DEFAULT_SETTINGS_PATH if DEFAULT_SETTINGS_PATH.exists() else SETTINGS_PATH)
    found: Dict[str, Any] = {}
    for const_name in CONST_TO_SPEC:
        if const_name not in live or const_name not in defaults:
            continue
        if live[const_name] != defaults[const_name]:
            found[const_name] = live[const_name]

    existing = load_user_overrides()
    merged = {**existing, **found}
    backup = None
    if found:
        backup = save_user_overrides(merged)

    # If a defaults snapshot exists, restore settings.py to the tracked
    # snapshot after overrides were safely written.
    restored = False
    restore_backup = None
    if found and DEFAULT_SETTINGS_PATH.exists():
        restore_backup = Path(DATA_DIR) / "settings.py.bak"
        try:
            restore_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(SETTINGS_PATH), str(restore_backup))
            tmp = str(SETTINGS_PATH) + ".tmp"
            Path(tmp).write_text(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            os.replace(tmp, SETTINGS_PATH)
            restored = True
        except Exception as exc:
            log(f"[WARN] settings.py restore after migration failed: {exc}")

    return {
        "ok": True,
        "migrated": sorted(found.keys()),
        "count": len(found),
        "user_settings_path": str(USER_SETTINGS_PATH),
        "backup_path": backup,
        "settings_restored": restored,
        "settings_backup_path": str(restore_backup) if restored else None,
    }


def _coerce_const_override(const_name: str, value: Any) -> Tuple[Any, str | None]:
    spec = CONST_TO_SPEC.get(const_name)
    if spec is None:
        return None, "not editable from UI"
    py_type = spec.get("py_type", str)
    try:
        if py_type is bool:
            coerced: Any = bool(value)
        elif py_type is int:
            coerced = int(value)
        elif py_type is float:
            coerced = float(value)
        elif py_type is str:
            coerced = str(value)
        else:
            coerced = value
    except (TypeError, ValueError):
        return None, f"could not coerce to {py_type.__name__}"

    if "choices" in spec and coerced not in spec["choices"]:
        return None, f"must be one of {spec['choices']}"
    if isinstance(coerced, str) and any(ch in coerced for ch in ('"', "'", "\n", "\r")):
        return None, "string must not contain quotes or newlines"

    # Stored values use storage units. Convert minute-based bounds.
    min_v = spec.get("min")
    max_v = spec.get("max")
    if spec.get("unit_in") == "minutes" and spec.get("unit_out") == "seconds":
        if min_v is not None:
            min_v = int(min_v) * 60
        if max_v is not None:
            max_v = int(max_v) * 60
    if min_v is not None and coerced < min_v:
        return None, f"must be >= {min_v}"
    if max_v is not None and coerced > max_v:
        return None, f"must be <= {max_v}"
    return coerced, None


def _literal_assignments(path: Path) -> Dict[str, Any]:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: Dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except Exception:
            continue
    return out
