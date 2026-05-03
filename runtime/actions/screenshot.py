"""
CalFlow Screenshot Action (v2.0).

Best-effort screen capture used by Plus Mode `SCREENSHOT` commands.

Design:
- macOS first (uses `/usr/sbin/screencapture` when available)
- never raises — failures are logged
- caller passes a fully-resolved absolute path; this module does NOT
  invent or decide on paths beyond the small fallback below
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import PLUS_SCREENSHOT_DIR
from core.utils import log


# =========================================================
# 📁 PATH HELPERS
# =========================================================

def default_screenshot_path() -> str:
    """
    Build a timestamped path under PLUS_SCREENSHOT_DIR (default
    `~/Downloads/CalFlow`). Creates the directory if it doesn't exist.
    """
    target_dir = Path(os.path.expanduser(PLUS_SCREENSHOT_DIR))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log(f"[WARN] Could not create screenshot dir: {exc}")
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return str(target_dir / f"calflow_{stamp}.png")


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
