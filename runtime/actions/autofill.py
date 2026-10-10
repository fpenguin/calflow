"""
CalFlow Autofill Engine (v2.0).

Sends password-manager autofill keystrokes via osascript +
`System Events`. No `pyobjc` required.

Provider resolution order:
    1. data/config.json  (set by `python3 -m cli.main setup` step 4)
    2. config.settings.AUTOFILL_PROVIDER (Python default)
    3. "default" entry in AUTOFILL_SHORTCUTS (last-resort)

Pass `none` (from onboarding) to disable autofill entirely.

Design:
- runtime-only logic — settings define WHAT, this module sends keys
- best-effort: any subprocess failure is logged and swallowed
- first run will trigger macOS Accessibility prompt for whichever
  process is calling osascript (usually `python3` / `osascript`)
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'resolve_autofill_provider',
    'trigger_autofill',
]

import json
import subprocess
from pathlib import Path
from typing import Optional

from config.config import DATA_DIR
from config.settings import AUTOFILL_PROVIDER, AUTOFILL_SHORTCUTS
from core.utils import log
from runtime.actions._applescript import escape_applescript_string


_USER_CONFIG_PATH = Path(DATA_DIR) / "config.json"


# =========================================================
# 🔍 PROVIDER RESOLUTION
# =========================================================

def _read_user_provider() -> Optional[str]:
    """Read autofill_provider from data/config.json (set by onboarding)."""
    if not _USER_CONFIG_PATH.exists():
        return None
    try:
        with open(_USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get("autofill_provider")
    except Exception as exc:
        log(f"[WARN] Could not read autofill configuration ({type(exc).__name__}); check config")
    return None


def _is_provider_available(provider: str) -> bool:
    """Heuristic: provider is usable iff it has shortcuts defined."""
    return isinstance(provider, str) and provider in AUTOFILL_SHORTCUTS


def resolve_autofill_provider() -> str:
    """
    Resolve effective autofill provider, layering:
        1. data/config.json (user choice from onboarding)
        2. config.settings.AUTOFILL_PROVIDER (Python default)
        3. "default" in AUTOFILL_SHORTCUTS

    Returns "none" to indicate autofill is disabled by user choice.
    """
    user = _read_user_provider()
    if user == "none":
        return "none"
    if user and _is_provider_available(user):
        return user
    if _is_provider_available(AUTOFILL_PROVIDER):
        return AUTOFILL_PROVIDER
    log(
        "[WARN] Configured autofill provider unavailable; falling back to 'default'"
    )
    return "default"


# =========================================================
# ⌨️ EXECUTION
# =========================================================

def trigger_autofill(mode: str = "fill") -> bool:
    """
    Send the configured keystroke; True only when a keystroke was sent.
    """
    provider = resolve_autofill_provider()
    if provider == "none":
        log("[INFO] Autofill skipped (provider set to 'none')")
        return False

    config = AUTOFILL_SHORTCUTS.get(provider)
    if not isinstance(config, dict) or not config:
        log("[WARN] Autofill shortcut configuration missing; check provider settings")
        return False

    action = config.get(mode)
    if not action:
        log("[WARN] Autofill action not configured; check provider settings")
        return False

    return _execute_shortcut(action, provider=provider, mode=mode)


# =========================================================
# 🔧 KEYSTROKE INJECTION (osascript + System Events)
# =========================================================

# Map our internal modifier names to AppleScript modifier tokens.
_MODIFIER_MAP = {
    "command": "command down",
    "cmd":     "command down",
    "shift":   "shift down",
    "option":  "option down",
    "alt":     "option down",
    "control": "control down",
    "ctrl":    "control down",
}


def _build_applescript(action: dict) -> Optional[str]:
    """
    Translate an action dict into an AppleScript that sends one keystroke.

    Two action shapes:
        {"key_code": 36}                          → key code 36 (Return)
        {"key": "\\", "modifiers": ["command"]}   → keystroke with modifiers
    """
    if "key_code" in action:
        try:
            kc = int(action["key_code"])
        except (TypeError, ValueError):
            return None
        return (
            'tell application "System Events"\n'
            f'    key code {kc}\n'
            'end tell'
        )

    if "key" in action:
        # AppleScript-escape backslash and double-quote inside the key.
        key = escape_applescript_string(str(action["key"]))
        modifiers = action.get("modifiers") or []
        using = ", ".join(
            _MODIFIER_MAP[m.lower()] for m in modifiers
            if m and m.lower() in _MODIFIER_MAP
        )
        if using:
            return (
                'tell application "System Events"\n'
                f'    keystroke "{key}" using {{{using}}}\n'
                'end tell'
            )
        return (
            'tell application "System Events"\n'
            f'    keystroke "{key}"\n'
            'end tell'
        )

    return None


def _execute_shortcut(action: dict, *, provider: str = "?", mode: str = "?") -> bool:
    """
    Send the keystroke. Invalid configuration or subprocess failure returns False.
    """
    # Do not silently remove a modifier and send a different keystroke.
    script = None
    try:
        if isinstance(action, dict):
            modifiers = action.get("modifiers") or []
            valid_modifiers = isinstance(modifiers, (list, tuple)) and all(
                isinstance(m, str) and m.lower() in _MODIFIER_MAP for m in modifiers
            )
            if "key_code" in action and modifiers:
                valid_modifiers = False
            if valid_modifiers and ("key_code" in action or action.get("key")):
                script = _build_applescript(action)
    except (TypeError, ValueError, OverflowError):
        pass
    if script is None:
        log("[WARN] Invalid autofill shortcut; check key and modifier settings")
        return False

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        log("[WARN] osascript not available — autofill skipped")
        return False
    except Exception as exc:
        log(f"[ERROR] Autofill subprocess failed ({type(exc).__name__}); check permissions")
        return False

    if result.returncode == 0:
        log("[INFO] Autofill keystroke sent")
        return True

    stderr = (result.stderr or "").strip()
    log(f"[WARN] Autofill failed (exit {result.returncode}); check shortcut and permissions")
    if "not allowed" in stderr.lower() or "1002" in stderr:
        log(
            "[WARN] Grant Accessibility permission: "
            "System Settings → Privacy & Security → Accessibility"
        )
    return False


def _shortcut_description(action: dict) -> str:
    """Render a shortcut for direct user-facing detail, never ordinary logs."""
    if "key_code" in action:
        return f"key code {action['key_code']}"
    if "key" in action:
        mods = "+".join(action.get("modifiers") or [])
        return f"{mods}+{action['key']}" if mods else action["key"]
    return repr(action)
