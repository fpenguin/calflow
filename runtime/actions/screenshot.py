"""
CalFlow Screenshot Action (v1.1.2).

Best-effort screen capture used by Plus Mode `SCREENSHOT` commands.

Design:
- macOS first (uses `/usr/sbin/screencapture` when available)
- never raises — failures are logged
- caller passes a fully-resolved absolute path OR None for the default
- v1.1.2 — default sink is configurable via:
      PLUS_SCREENSHOT_DIR              (folder)
      PLUS_SCREENSHOT_FILENAME_FORMAT  (filename pattern)
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import (
    PLUS_SCREENSHOT_DIR,
    PLUS_SCREENSHOT_FILENAME_FORMAT,
)
from core.utils import log


# =========================================================
# 📁 PATH HELPERS
# =========================================================

def _format_filename(pattern: str, now: datetime.datetime) -> str:
    """
    Expand the user's filename pattern. Recognised tokens:

        {YYYY}                4-digit year
        {MM}                  2-digit month
        {DD}                  2-digit day
        {HH}                  2-digit hour (24h)
        {mm}                  2-digit minute
        {ss}                  2-digit second
        {YYYY-MM-DD}          shorthand date
        {YYYY-MM-DD_HHMMSS}   shorthand date+time

    Anything else is left literal.
    """
    table = {
        "{YYYY}":              now.strftime("%Y"),
        "{MM}":                now.strftime("%m"),
        "{DD}":                now.strftime("%d"),
        "{HH}":                now.strftime("%H"),
        "{mm}":                now.strftime("%M"),
        "{ss}":                now.strftime("%S"),
        "{YYYY-MM-DD}":        now.strftime("%Y-%m-%d"),
        "{YYYY-MM-DD_HHMMSS}": now.strftime("%Y-%m-%d_%H%M%S"),
    }
    out = pattern or "CalFlow_{YYYY-MM-DD_HHMMSS}.png"
    for token, value in table.items():
        out = out.replace(token, value)
    return out


def default_screenshot_path() -> str:
    """
    Build a path under PLUS_SCREENSHOT_DIR (default `~/Downloads/CalFlow`)
    using PLUS_SCREENSHOT_FILENAME_FORMAT (default
    `CalFlow_{YYYY-MM-DD_HHMMSS}.png`).

    Creates the directory if it doesn't exist; falls back to
    `~/Library/Application Support/CalFlow/screenshots` if the
    primary directory is read-only (e.g. iCloud Drive edge cases).
    """
    primary = Path(os.path.expanduser(PLUS_SCREENSHOT_DIR))
    fallback = Path(
        os.path.expanduser(
            "~/Library/Application Support/CalFlow/screenshots"
        )
    )
    target_dir = primary
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log(
            f"[WARN] Could not create screenshot dir {primary}: {exc}; "
            f"falling back to {fallback}"
        )
        target_dir = fallback
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc2:
            log(f"[WARN] Fallback dir also failed: {exc2}")
    filename = _format_filename(
        PLUS_SCREENSHOT_FILENAME_FORMAT, datetime.datetime.now()
    )
    return str(target_dir / filename)


# =========================================================
# 📸 PUBLIC API
# =========================================================

def take_screenshot(path: Optional[str] = None) -> Optional[str]:
    """
    Capture a screenshot to `path` (or a default path if None).

    Returns:
        The path written, or None on failure.
    """
    target = path or default_screenshot_path()

    try:
        # macOS: screencapture -x writes a silent PNG to the path.
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-x", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if result.returncode == 0 and os.path.exists(target):
            log(f"[INFO] Screenshot saved: {target}")
            return target
        log(f"[WARN] Screenshot command returned {result.returncode}")
        return None

    except FileNotFoundError:
        log("[WARN] /usr/sbin/screencapture not available on this platform")
        return None
    except Exception as exc:
        log(f"[ERROR] Screenshot failed: {exc}")
        return None


def take_screenshot_to_clipboard() -> bool:
    """
    Capture the screen straight to the clipboard (v1.5.2 — the default
    sink for bare `screenshot` and `screenshot to(clipboard)`).

    Returns:
        True on success, False on failure.
    """
    try:
        # macOS: screencapture -c -x captures silently to the clipboard.
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-c", "-x"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if result.returncode == 0:
            log("[INFO] Screenshot copied to clipboard")
            return True
        log(f"[WARN] Screenshot-to-clipboard returned {result.returncode}")
        return False

    except FileNotFoundError:
        log("[WARN] /usr/sbin/screencapture not available on this platform")
        return False
    except Exception as exc:
        log(f"[ERROR] Screenshot-to-clipboard failed: {exc}")
        return False
