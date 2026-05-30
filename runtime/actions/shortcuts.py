"""macOS Shortcuts backend for CalFlow `run -shortcut`."""

from __future__ import annotations

__all__ = ["run_shortcut"]

import os
import subprocess
import tempfile

from config.settings import RUN_SHORTCUT_TIMEOUT
from core.utils import log
from runtime.actions.notifications import notify_run_error
from runtime.actions.run_result import RunResult, error_result, ok_result


def run_shortcut(name: str, input_text: str = "") -> RunResult:
    shortcut = (name or "").strip()
    if not shortcut:
        msg = "missing name"
        log(f"[WARN] Shortcut {msg}")
        notify_run_error("CalFlow Shortcut failed", msg)
        return error_result("shortcut", msg)

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
        return error_result("shortcut", msg)
    finally:
        if input_path:
            try:
                os.unlink(input_path)
            except OSError:
                pass

    if result.returncode == 0:
        log(f"[INFO] Shortcut completed: {shortcut}")
        return ok_result(
            "shortcut",
            f"Shortcut completed: {shortcut}",
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
    else:
        stderr = (result.stderr or "").strip()
        if len(stderr) > 300:
            stderr = stderr[:300] + "..."
        msg = f"exited {result.returncode}: {stderr}"
        log(f"[WARN] Shortcut {msg}")
        notify_run_error("CalFlow Shortcut failed", msg)
        return error_result(
            "shortcut",
            msg,
            stderr=stderr,
            returncode=int(result.returncode),
        )
