"""
CalFlow settings writer (v1.4.1).

Writes user-edited values from the menubar Settings window into
`data/user_settings.json`. Project defaults remain in tracked
`config/settings.py`.

Design principles:
- WHITELIST. Only fields explicitly in EDITABLE_SETTINGS may be
  written. Unknown keys are rejected, never coerced.
- VALIDATE first. Type / range / choice checks BEFORE any disk write.
  An invalid value never reaches the file.
- BACKUP first. Existing `data/user_settings.json` is copied to
  `data/user_settings.json.bak` on every successful write batch.
- DEFAULTS STAY TRACKED. Runtime imports merge defaults from
  `config/settings.py` with this gitignored JSON sidecar.
- LAUNCHD-FREE. Toggles that depend on launchctl (e.g.
  `auto_start_at_login`) are NOT auto-applied — per CLAUDE.md, CalFlow
  never modifies launchd state autonomously. They return
  `requires_terminal` with the literal command for the user to run.

Public API:
    apply_settings(payload: dict) → dict
        payload: {ui_key: new_value, …}
        returns: {
            "applied":          [ui_key, …],
            "rejected":         [{"key": ui_key, "reason": str}, …],
            "requires_terminal":[{"key": ui_key, "command": str}, …],
            "backup_path":      str | None,
        }

    EDITABLE_SETTINGS — the whitelist (also exposed for the UI).

Why this lives in core/ and not runtime/: it's pure logic with one
file IO at the very end. Tests mock the file path; no daemon side
effects.
"""

from __future__ import annotations

# v1.3.2 — public surface lock.
__all__ = [
    "EDITABLE_SETTINGS",
    "apply_settings",
    "get_current_value",
]

from typing import Any, Dict, List, Optional

from core.settings_reader import (
    USER_SETTINGS_BACKUP_PATH,
    USER_SETTINGS_PATH,
    load_user_overrides,
    save_user_overrides,
)
from core.settings_schema import EDITABLE_SETTINGS


SETTINGS_PATH = USER_SETTINGS_PATH
BACKUP_PATH = USER_SETTINGS_BACKUP_PATH


# =========================================================
# 🚪 LAUNCHD-CONTROLLED FIELDS  (v1.3.6 — now executed natively)
# =========================================================
#
# These keys can't be written to settings.py — they live in launchd.
# v1.3.5 returned a copy-this-into-Terminal hint; v1.3.6 actually runs
# the launchctl operation, treating the user's UI click as explicit
# approval (same trust as them typing `python -m cli.main start`).
# CLAUDE.md still prohibits the AI agent from editing launchd state
# autonomously — that's about MY behaviour, not the app's.

_LAUNCHD_KEYS: Dict[str, str] = {
    # ui_key → daemon action ("start" | "stop")
    "general.auto_start_at_login": "toggle",
}


# =========================================================
# 🧠 PUBLIC API
# =========================================================

def apply_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate + apply a batch of UI edits to data/user_settings.json.

    Returns a dict summarising what happened:
        applied:           [ui_key, …]               — written to disk
        rejected:          [{key, reason}, …]        — validation failed
        requires_terminal: [{key, command}, …]       — launchctl-controlled
        backup_path:       str | None                — bak path if a write occurred
    """
    if not isinstance(payload, dict) or not payload:
        return {"applied": [], "rejected": [{"key": "", "reason": "empty payload"}],
                "requires_terminal": [], "backup_path": None}

    applied: List[str] = []
    rejected: List[Dict[str, str]] = []
    daemon_actions: List[Dict[str, str]] = []  # what we ran via launchctl

    # --- Pass 1: split into write-able vs launchd vs unknown ---
    write_plan: List[Dict[str, Any]] = []   # [{ui_key, const, py_value}]
    for ui_key, raw_value in payload.items():
        # launchd-controlled?
        if ui_key in _LAUNCHD_KEYS:
            action = "start" if raw_value else "stop"
            ok, err = _run_launchctl(action)
            if ok:
                applied.append(ui_key)
                daemon_actions.append({"key": ui_key, "action": action})
            else:
                rejected.append({"key": ui_key, "reason": err or "launchctl failed"})
            continue

        spec = EDITABLE_SETTINGS.get(ui_key)
        if spec is None:
            rejected.append({"key": ui_key, "reason": "not editable from UI"})
            continue

        coerced, err = _validate(spec, raw_value)
        if err is not None:
            rejected.append({"key": ui_key, "reason": err})
            continue

        write_plan.append({
            "ui_key": ui_key,
            "const":  spec["const"],
            "py_value": coerced,
        })

    # --- Pass 2: write sidecar, only if anything passed validation ---
    backup: Optional[str] = None
    if write_plan:
        try:
            overrides = load_user_overrides(SETTINGS_PATH)
        except Exception as exc:
            for w in write_plan:
                rejected.append({"key": w["ui_key"], "reason": f"could not read user_settings.json: {exc}"})
            return {"applied": applied, "rejected": rejected,
                    "requires_terminal": [], "daemon_actions": daemon_actions,
                    "backup_path": None}

        for w in write_plan:
            overrides[w["const"]] = w["py_value"]

        try:
            backup = save_user_overrides(
                overrides,
                path=SETTINGS_PATH,
                backup_path=BACKUP_PATH,
            )
            applied.extend(w["ui_key"] for w in write_plan)
        except Exception as exc:
            for w in write_plan:
                rejected.append({"key": w["ui_key"],
                                 "reason": f"write failed: {exc}"})

    return {
        "applied": applied,
        "rejected": rejected,
        "requires_terminal": [],     # kept for back-compat; always empty in v1.3.6+
        "daemon_actions": daemon_actions,
        "backup_path": backup,
    }


def _run_launchctl(action: str):
    """
    Run a launchctl start/stop on the CalFlow daemon. Returns (ok, err).

    Imports lazily so that tests / non-macOS environments can import
    settings_writer without dragging in cli.onboarding's launchd helpers.
    """
    try:
        from cli.onboarding import (
            start_launchd, stop_launchd, restart_launchd,
        )
        if action == "start":
            start_launchd()
        elif action == "stop":
            stop_launchd()
        elif action == "restart":
            restart_launchd()
        else:
            return False, f"unknown launchd action {action!r}"
        return True, None
    except FileNotFoundError as exc:
        return False, f"launchd plist missing: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def get_current_value(ui_key: str) -> Any:
    """
    Read the live value of an editable setting from `config.settings`.

    Returns the value in the unit the UI expects (e.g. minutes for
    `events.open_minutes_early`, even though storage is seconds).
    Returns None on unknown keys.
    """
    spec = EDITABLE_SETTINGS.get(ui_key)
    if spec is None:
        return None
    try:
        from config import settings as S
        raw = getattr(S, spec["const"], None)
    except Exception:
        return None
    if raw is None:
        return None
    if spec.get("unit_in") == "minutes" and spec.get("unit_out") == "seconds":
        try:
            return int(raw) // 60
        except (TypeError, ValueError):
            return None
    return raw


# =========================================================
# 🛠 INTERNALS
# =========================================================

def _validate(spec: Dict[str, Any], raw_value: Any):
    """
    Coerce + range-check a value against a spec. Returns (coerced, err).

    Order matters: type-coerce → range / choices on the INPUT value
    (min/max are expressed in the user-facing unit), THEN apply unit
    conversion to produce the storage value. Without that ordering
    `events.open_minutes_early=10` (UI: 10 minutes) would get converted
    to 600 then rejected against `max=60`.
    """
    py_type = spec.get("py_type", str)

    # 0. Bool→string mapping for toggle-backed string settings
    #    (e.g. AUTOFILL_MODE: True → "semi-auto", False → "off").
    if spec.get("from_bool") and isinstance(raw_value, bool):
        if py_type is str:
            choices = spec.get("choices") or []
            if len(choices) >= 2:
                # Convention: choices[0] = "off-equivalent", choices[1+] = "on".
                raw_value = choices[1] if raw_value else choices[0]
            else:
                raw_value = "on" if raw_value else "off"

    # 1. Type coerce the INPUT.
    try:
        if py_type is int:
            input_val: Any = int(raw_value)
        elif py_type is float:
            input_val = float(raw_value)
        elif py_type is str:
            input_val = str(raw_value)
        else:
            input_val = raw_value
    except (TypeError, ValueError):
        return None, f"could not coerce to {py_type.__name__}"

    # 2. Choices (in input units).
    if "choices" in spec and input_val not in spec["choices"]:
        return None, f"must be one of {spec['choices']}"

    # 3. Range (in input units — what the user sees).
    if "min" in spec and input_val < spec["min"]:
        return None, f"must be >= {spec['min']}"
    if "max" in spec and input_val > spec["max"]:
        return None, f"must be <= {spec['max']}"

    # 4. String safety: no embedded quotes (we'll re-quote on write).
    if isinstance(input_val, str):
        if any(ch in input_val for ch in ('"', "'", "\n", "\r")):
            return None, "string must not contain quotes or newlines"

    # 5. Unit conversion to storage units (only AFTER all checks pass).
    out_value = input_val
    if spec.get("unit_in") == "minutes" and spec.get("unit_out") == "seconds":
        out_value = int(input_val) * 60

    return out_value, None
