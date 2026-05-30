"""
BetterTouchTool integration helpers.

Keeps BTT's URL-scheme details out of the Plus Mode executor so users
can write a named trigger directly.
"""

from __future__ import annotations

__all__ = [
    "build_alfred_trigger_url",
    "build_named_trigger_url",
    "trigger_alfred",
    "trigger_named_btt",
]

import subprocess
from urllib.parse import quote

from config.settings import RUN_ALFRED_TIMEOUT
from core.utils import log
from runtime.actions.notifications import notify_run_error


def build_named_trigger_url(trigger_name: str) -> str:
    """Return the BTT URL-scheme invocation for a named trigger."""
    encoded = quote(trigger_name, safe="")
    return f"btt://trigger_named/?trigger_name={encoded}"


def build_alfred_trigger_url(bundle_id: str, trigger_id: str, argument: str = "") -> str:
    """Return Alfred's external-trigger URL."""
    bid = quote((bundle_id or "").strip(), safe="")
    tid = quote((trigger_id or "").strip(), safe="")
    url = f"alfred://runtrigger/{bid}/{tid}/"
    if argument:
        url += "?argument=" + quote(argument, safe="")
    return url


def trigger_named_btt(trigger_name: str) -> None:
    """Fire a BetterTouchTool named trigger via its URL scheme."""
    name = (trigger_name or "").strip()
    if not name:
        msg = "missing trigger name"
        log(f"[WARN] BTT {msg}")
        notify_run_error("CalFlow BTT failed", msg)
        return

    url = build_named_trigger_url(name)
    try:
        subprocess.run(["open", url], check=False, timeout=5)
        log(f"[INFO] BTT trigger: {name}")
    except Exception as exc:
        msg = f"trigger failed for {name!r}: {exc}"
        log(f"[ERROR] BTT {msg}")
        notify_run_error("CalFlow BTT failed", msg)


def trigger_alfred(bundle_id: str, trigger_id: str, argument: str = "") -> None:
    """Fire an Alfred workflow external trigger via URL scheme."""
    bid = (bundle_id or "").strip()
    tid = (trigger_id or "").strip()
    if not bid or not tid:
        msg = "missing workflow bundle id or trigger id"
        log(f"[WARN] Alfred {msg}")
        notify_run_error("CalFlow Alfred failed", msg)
        return

    url = build_alfred_trigger_url(bid, tid, argument)
    try:
        subprocess.run(["open", url], check=False, timeout=RUN_ALFRED_TIMEOUT)
        log(f"[INFO] Alfred trigger: {bid}/{tid}")
    except Exception as exc:
        msg = f"trigger failed for {bid}/{tid}: {exc}"
        log(f"[ERROR] Alfred {msg}")
        notify_run_error("CalFlow Alfred failed", msg)
