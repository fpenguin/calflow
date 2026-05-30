"""macOS notification helpers for user-visible runtime failures."""

from __future__ import annotations

__all__ = ["notify_run_error"]

import subprocess

from config.settings import RUN_ERROR_NOTIFICATIONS
from core.utils import log


def notify_run_error(title: str, message: str) -> None:
    """Show a best-effort macOS notification for `run` backend errors."""
    if not RUN_ERROR_NOTIFICATIONS:
        return

    safe_title = _clip(title or "CalFlow run failed", 80)
    safe_message = _clip(message or "Check CalFlow logs for details.", 220)
    script = (
        f'display notification {_applescript_string(safe_message)} '
        f'with title {_applescript_string(safe_title)}'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception as exc:
        log(f"[WARN] notification failed: {exc}")


def _clip(text: str, limit: int) -> str:
    value = str(text).strip().replace("\n", " ")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
