"""
Editable Settings schema shared by the menubar settings reader/writer.

The schema intentionally lives outside `core.settings_writer` so
`config.settings` can load user overrides without importing the writer.
"""

from __future__ import annotations

from typing import Any, Dict


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


CONST_TO_SPEC: Dict[str, Dict[str, Any]] = {
    spec["const"]: spec for spec in EDITABLE_SETTINGS.values()
}
