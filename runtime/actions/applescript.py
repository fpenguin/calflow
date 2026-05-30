"""AppleScript execution backend for trusted CalFlow `run` commands."""

from __future__ import annotations

__all__ = ["run_applescript"]

import subprocess

from config.settings import RUN_APPLESCRIPT_TIMEOUT
from core.utils import log
from runtime.actions.notifications import notify_run_error
from runtime.actions.run_result import RunResult, error_result, ok_result


def run_applescript(script: str, timeout: float | None = None) -> RunResult:
    body = (script or "").strip()
    if not body:
        msg = "empty script"
        log(f"[WARN] AppleScript: {msg}")
        notify_run_error("CalFlow AppleScript failed", msg)
        return error_result("applescript", msg)

    try:
        result = subprocess.run(
            ["osascript", "-"],
            input=body,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout or RUN_APPLESCRIPT_TIMEOUT,
        )
    except Exception as exc:
        msg = f"failed to launch: {exc}"
        log(f"[ERROR] AppleScript {msg}")
        notify_run_error("CalFlow AppleScript failed", msg)
        return error_result("applescript", msg)

    if result.returncode == 0:
        log("[INFO] AppleScript completed")
        return ok_result(
            "applescript",
            "AppleScript completed",
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
    else:
        stderr = (result.stderr or "").strip()
        if len(stderr) > 300:
            stderr = stderr[:300] + "..."
        msg = f"exited {result.returncode}: {stderr}"
        log(f"[WARN] AppleScript {msg}")
        notify_run_error("CalFlow AppleScript failed", msg)
        return error_result(
            "applescript",
            msg,
            stderr=stderr,
            returncode=int(result.returncode),
        )
