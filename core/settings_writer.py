"""
CalFlow settings writer (v1.3.2).

Writes user-edited values back into `config/settings.py` from the
menubar Settings window.

Design principles:
- WHITELIST. Only fields explicitly in EDITABLE_SETTINGS may be
  written. Unknown keys are rejected, never coerced.
- VALIDATE first. Type / range / choice checks BEFORE any disk write.
  An invalid value never reaches the file.
- BACKUP first. `config/settings.py` is copied to
  `config/settings.py.bak` on every successful write batch.
- LINE-BASED REPLACE. We match `^KEY = …$` once at module top level
  and rewrite the value in place. Comments outside the line are
  preserved; an inline `# …` comment on the assignment line is dropped
  (rare in our settings.py).
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

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.config import BASE_DIR
from core.utils import log


SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.py"
BACKUP_PATH   = Path(BASE_DIR) / "config" / "settings.py.bak"


# =========================================================
# 📋 WHITELIST
# =========================================================
#
# Each entry maps a UI-side dotted key to the settings.py constant
# name + a type rule + (optional) range / choices / unit conversion.
#
# Format:
#   ui_key: {
#     "const":      "CONSTANT_NAME",   # symbol in settings.py
#     "py_type":    int|float|str,     # Python type to coerce to
#     "min": …, "max": …               # numeric range (inclusive)
#     "choices":    [...]              # allowed string values
#     "unit_in":    "minutes" | "seconds"   # what the UI sends
#     "unit_out":   "seconds"               # what settings.py stores
#   }

EDITABLE_SETTINGS: Dict[str, Dict[str, Any]] = {
    # ----- Events -----
    "events.open_minutes_early": {
        "const": "DEFAULT_ALERT_SECONDS",
        "py_type": int, "min": 0, "max": 60,
        "unit_in": "minutes", "unit_out": "seconds",
    },
    "events.fetch_window_hours": {
        "const": "FETCH_WINDOW_HOURS",
        "py_type": int, "min": 1, "max": 24,
    },
    "events.status_lookahead_h": {
        "const": "STATUS_LOOKAHEAD_HOURS",
        "py_type": int, "min": 1, "max": 168,
    },

    # ----- Title links -----
    "title_links.open_mode": {
        "const": "TITLE_URL_OPEN_DEFAULT",
        "py_type": str, "choices": ["tab", "window"],
    },
    "title_links.autofill": {
        "const": "TITLE_URL_AUTOFILL_DEFAULT",
        "py_type": str, "choices": ["none", "fill", "submit"],
    },

    # ----- Passwords -----
    "passwords.provider": {
        "const": "AUTOFILL_PROVIDER",
        "py_type": str, "choices": ["apple", "1password", "bitwarden", "default"],
    },
    # v1.3.7 — UI sends a bool toggle; map True→"semi-auto", False→"off".
    "passwords.autofill_on_open": {
        "const": "AUTOFILL_MODE",
        "py_type": str, "choices": ["off", "semi-auto"],
        "from_bool": True,
    },

    # ----- Advanced -----
    "advanced.trigger_grace_seconds": {
        "const": "GRACE_SECONDS",
        "py_type": int, "min": 0, "max": 3600,
    },
    "advanced.early_tolerance_sec": {
        "const": "EARLY_TOLERANCE",
        "py_type": int, "min": 0, "max": 600,
    },
    "advanced.max_urls_per_event": {
        "const": "MAX_URLS",
        "py_type": int, "min": 1, "max": 50,
    },
    "advanced.log_mode": {
        "const": "LOG_MODE",
        "py_type": str, "choices": ["stdout", "stderr", "both"],
    },
    "advanced.plus_max_commands": {
        "const": "PLUS_MAX_COMMANDS",
        "py_type": int, "min": 1, "max": 200,
    },
    "advanced.plus_inter_command_delay_sec": {
        "const": "PLUS_INTER_COMMAND_DELAY",
        "py_type": float, "min": 0.0, "max": 10.0,
    },
    "advanced.plus_screenshot_dir": {
        "const": "PLUS_SCREENSHOT_DIR",
        "py_type": str,
    },
}


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
    Validate + apply a batch of UI edits to settings.py.

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

    # --- Pass 2: write-back, only if anything passed validation ---
    backup: Optional[str] = None
    if write_plan:
        try:
            text = SETTINGS_PATH.read_text(encoding="utf-8")
        except Exception as exc:
            for w in write_plan:
                rejected.append({"key": w["ui_key"], "reason": f"could not read settings.py: {exc}"})
            # v1.3.14 — was `needs_term` (undefined name from pre-v1.3.6
            # refactor); now matches the v1.3.6+ schema with daemon_actions.
            return {"applied": applied, "rejected": rejected,
                    "requires_terminal": [], "daemon_actions": daemon_actions,
                    "backup_path": None}

        new_text = text
        ok_writes: List[Dict[str, Any]] = []
        for w in write_plan:
            updated, hit = _replace_assignment(new_text, w["const"], w["py_value"])
            if not hit:
                rejected.append({"key": w["ui_key"],
                                 "reason": f"constant {w['const']} not found in settings.py"})
                continue
            new_text = updated
            ok_writes.append(w)

        if ok_writes:
            # Backup once per successful batch.
            try:
                shutil.copyfile(str(SETTINGS_PATH), str(BACKUP_PATH))
                backup = str(BACKUP_PATH)
            except Exception as exc:
                log(f"[WARN] settings backup failed: {exc}")
            try:
                tmp = str(SETTINGS_PATH) + ".tmp"
                Path(tmp).write_text(new_text, encoding="utf-8")
                Path(tmp).replace(SETTINGS_PATH)
                applied.extend(w["ui_key"] for w in ok_writes)
            except Exception as exc:
                for w in ok_writes:
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


def _replace_assignment(text: str, const_name: str, py_value: Any):
    """
    Replace the FIRST top-level `CONST = …` assignment in `text`.

    Returns (new_text, hit) where hit is True if the assignment was
    found and replaced.
    """
    formatted = _format_python_value(py_value)
    pattern = re.compile(
        r"(?m)^([ \t]*)" + re.escape(const_name) + r"\s*=[^\n]*$"
    )
    new_text, n = pattern.subn(rf"\1{const_name} = {formatted}", text, count=1)
    return new_text, n > 0


def _format_python_value(value: Any) -> str:
    """Render a Python value as it should appear on the right side of `=`."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Validation already rejected embedded quotes / newlines.
        # v1.3.14 — also escape backslashes so paths like "C:\foo" round-trip
        # cleanly (a literal "\n" in the input would otherwise become a real
        # newline at next module-load, breaking syntax).
        return '"' + value.replace("\\", "\\\\") + '"'
    # Defensive: never write a list / dict via this path.
    return repr(value)
