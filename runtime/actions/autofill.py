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
import os
import subprocess
from pathlib import Path
from typing import Optional

from config.config import DATA_DIR
from config.settings import AUTOFILL_PROVIDER, AUTOFILL_SHORTCUTS
from core.utils import log


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
        log(f"[WARN] Could not read {_USER_CONFIG_PATH.name}: {exc}")
    return None


def _is_provider_available(provider: str) -> bool:
    """Heuristic: provider is usable iff it has shortcuts defined."""
    return provider in AUTOFILL_SHORTCUTS


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
        f"[WARN] Autofill provider {AUTOFILL_PROVIDER!r} not available "
        f"→ falling back to 'default'"
    )
    return "default"


# =========================================================
# ⌨️ EXECUTION
# =========================================================

def trigger_autofill(mode: str = "fill") -> None:
    """
    Send the configured keystroke for `mode` ("fill" or "submit").
    """
    provider = resolve_autofill_provider()
    if provider == "none":
        log("[INFO] Autofill skipped (provider set to 'none')")
        return

    config = AUTOFILL_SHORTCUTS.get(provider)
    if not config:
        log(f"[WARN] No shortcut config for provider {provider!r}")
        return

    action = config.get(mode)
    if not action:
        log(f"[WARN] No {mode!r} action defined for provider {provider!r}")
        return

    _execute_shortcut(action, provider=provider, mode=mode)


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
        key = str(action["key"]).replace("\\", "\\\\").replace('"', '\\"')
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


def _execute_shortcut(action: dict, *, provider: str = "?", mode: str = "?") -> None:
    """
    Send the keystroke. Best-effort; any failure is logged.
    """
    script = _build_applescript(action)
    if script is None:
        log(f"[WARN] Unrecognized shortcut shape for {provider}/{mode}: {action!r}")
        return

    desc = _shortcut_description(action)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        log("[WARN] osascript not available — autofill skipped")
        return
    except Exception as exc:
        log(f"[ERROR] Autofill subprocess failed: {exc}")
        return

    if result.returncode == 0:
        log(f"[INFO] Autofill keystroke sent ({provider}/{mode}: {desc})")
        return

    stderr = (result.stderr or "").strip()
    log(f"[WARN] Autofill osascript failed ({provider}/{mode}): {stderr or '(no stderr)'}")
    if "not allowed" in stderr.lower() or "1002" in stderr:
        log(
            "[WARN] Grant Accessibility permission: "
            "System Settings → Privacy & Security → Accessibility"
        )


def _shortcut_description(action: dict) -> str:
    """Render an action as a short human-readable string for logs."""
    if "key_code" in action:
        return f"key code {action['key_code']}"
    if "key" in action:
        mods = "+".join(action.get("modifiers") or [])
        return f"{mods}+{action['key']}" if mods else action["key"]
    return repr(action)
