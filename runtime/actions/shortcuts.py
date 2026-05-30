"""macOS Shortcuts backend for CalFlow `run -shortcut`."""

from __future__ import annotations

__all__ = ["run_shortcut"]

import os
import subprocess
import tempfile

from config.settings import RUN_SHORTCUT_TIMEOUT
from core.utils import log
from runtime.actions.notifications import notify_run_error


def run_shortcut(name: str, input_text: str = "") -> None:
    shortcut = (name or "").strip()
    if not shortcut:
        msg = "missing name"
        log(f"[WARN] Shortcut {msg}")
        notify_run_error("CalFlow Shortcut failed", msg)
        return

    input_path = None
    try:
        args = ["shortcuts", "run", shortcut]
        if input_text:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                prefix="calflow-shortcut-",
                suffix=".txt",
            ) as tmp:
                tmp.write(input_text)
                input_path = tmp.name
            args.extend(["--input-path", input_path])

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=RUN_SHORTCUT_TIMEOUT,
        )
    except Exception as exc:
        msg = f"failed to launch for {shortcut!r}: {exc}"
        log(f"[ERROR] Shortcut {msg}")
        notify_run_error("CalFlow Shortcut failed", msg)
        return
    finally:
        if input_path:
            try:
                os.unlink(input_path)
            except OSError:
                pass

    if result.returncode == 0:
        log(f"[INFO] Shortcut completed: {shortcut}")
    else:
        stderr = (result.stderr or "").strip()
        if len(stderr) > 300:
            stderr = stderr[:300] + "..."
        msg = f"exited {result.returncode}: {stderr}"
        log(f"[WARN] Shortcut {msg}")
        notify_run_error("CalFlow Shortcut failed", msg)
