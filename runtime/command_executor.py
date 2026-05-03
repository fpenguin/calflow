"""
CalFlow Plus Mode Command Executor (v2.0).

Responsibilities:
- run a typed Plus Mode AST sequentially
- never block the pipeline on a single bad command
- delegate side effects to runtime/actions modules
- treat tags / aliases via the resolver layer (no shortcuts here)

Design:
- deterministic order (top-to-bottom)
- non-blocking (best-effort failure handling)
- stateless (no persistence here)
- DOES NOT modify or replace runtime/executor.py (Smart Mode)

Backend status:
- OPEN          → real (runtime.actions.browser.open_target)
- WAIT          → real (time.sleep)
- SCREENSHOT    → real (runtime.actions.screenshot.take_screenshot)
- FOCUS / CLOSE / HIDE / CLICK / TYPE / PRESS / COPY / PASTE / SAVE / RUN
                → stubs that log the resolved params (Quartz / AXUI / clipboard
                  backends land in v2.x); Plus Mode pipeline is fully wired
                  through resolution + dispatch already.
"""

from __future__ import annotations

import time
from typing import Any, Dict, FrozenSet, List, Optional, Set, Union

from config.config import MAX_WAIT_SECONDS
from config.settings import (
    AUTOFILL_BUFFER,
    PLUS_INTER_COMMAND_DELAY,
)
from core.dynamic import resolve_dynamic
from core.models import BaseCommand
from core.resolver import resolve_autofill, resolve_command
from core.utils import log
from runtime.actions.autofill import trigger_autofill
from runtime.actions.browser import open_target
from runtime.actions.screenshot import take_screenshot


# Fields that may carry user-facing strings with `{…}` dynamic blocks.
_DYNAMIC_FIELDS = ("url", "text", "path", "to", "title", "selector")


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def execute_commands(
    commands: List[BaseCommand],
    global_tags: Optional[Union[Set[str], FrozenSet[str]]] = None,
    debug: bool = False,
) -> None:
    """
    Run a list of typed Plus Mode commands sequentially.

    Behavior:
        - one failed command never aborts the rest
        - PLUS_INTER_COMMAND_DELAY is applied between commands
    """
    if not commands:
        log("[INFO] Plus Mode: nothing to execute")
        return

    block_tags: FrozenSet[str] = frozenset(global_tags or frozenset())

    for command in commands:
        try:
            params = resolve_command(command, block_tags)
            if "invalid" in params:
                log(
                    f"[WARN] skipped line {command.line_no}: {params['invalid']} "
                    f"({command.raw!r})"
                )
                continue

            # Substitute {…} dynamic expressions in any string fields
            # that may carry them (e.g. SAVE.to, SCREENSHOT.path,
            # OPEN.url, FOCUS.title). Per spec, dynamic resolution
            # happens AFTER parsing and BEFORE execution.
            for field in _DYNAMIC_FIELDS:
                if field in params and isinstance(params[field], str):
                    params[field] = resolve_dynamic(params[field])

            if debug:
                log(
                    f"[DEBUG] Plus[{command.line_no}] {params.get('verb')} "
                    f"params={_short(params)}"
                )
            _dispatch(params)

        except Exception as exc:
            log(
                f"[ERROR] Plus command failed at line {command.line_no} "
                f"({command.raw!r}): {exc}"
            )

        finally:
            time.sleep(max(0.0, PLUS_INTER_COMMAND_DELAY))


# =========================================================
# 🔁 DISPATCH
# =========================================================

def _dispatch(params: Dict[str, Any]) -> None:
    """Route a resolved param dict to the correct action."""
    verb = params.get("verb")

    handler = {
        "OPEN":       _do_open,
        "FOCUS":      _do_focus,
        "CLOSE":      _do_close,
        "HIDE":       _do_hide,
        "CLICK":      _do_click,
        "TYPE":       _do_type,
        "PRESS":      _do_press,
        "WAIT":       _do_wait,
        "SCREENSHOT": _do_screenshot,
        "COPY":       _do_copy,
        "PASTE":      _do_paste,
        "SAVE":       _do_save,
        "RUN":        _do_run,
    }.get(verb)

    if handler is None:
        log(f"[WARN] Plus executor: unknown verb {verb!r}")
        return

    handler(params)


# =========================================================
# 🌐 OPEN / FOCUS / CLOSE / HIDE
# =========================================================

def _do_open(params: Dict[str, Any]) -> None:
    url: Optional[str] = params.get("url")
    if not url:
        log("[WARN] OPEN missing url")
        return

    apps: List[str] = params.get("apps") or []
    if not apps:
        apps = [params.get("app") or None]  # type: ignore[list-item]

    for app in apps:
        open_target(
            url=url,
            app=app,
            layout=params.get("layout"),
        )

    time.sleep(max(0.0, AUTOFILL_BUFFER))

    tags = set(params.get("tags") or frozenset())
    if tags:
        should_fill, should_submit = resolve_autofill(tags)
        if should_fill:
            trigger_autofill(mode="fill")
            if should_submit:
                trigger_autofill(mode="submit")


def _do_focus(params: Dict[str, Any]) -> None:
    target = params.get("target")
    title = params.get("title")
    apps = params.get("apps") or ([target] if target else [])
    log(f"[INFO] FOCUS apps={apps} title={title!r} (stub)")


def _do_close(params: Dict[str, Any]) -> None:
    items = params.get("items") or ()
    log(f"[INFO] CLOSE items={list(items)} (stub)")


def _do_hide(params: Dict[str, Any]) -> None:
    if params.get("hide_all"):
        log(f"[INFO] HIDE all except={list(params.get('except') or ())} (stub)")
        return
    log(f"[INFO] HIDE items={list(params.get('items') or ())} (stub)")


# =========================================================
# 🖱️ CLICK / TYPE / PRESS
# =========================================================

def _do_click(params: Dict[str, Any]) -> None:
    text = params.get("text")
    selector = params.get("selector")
    x, y = params.get("x"), params.get("y")
    if text:
        log(f"[INFO] CLICK text={text!r} selector={selector!r} (stub)")
    elif selector:
        log(f"[INFO] CLICK selector={selector!r} (stub)")
    elif x is not None and y is not None:
        log(f"[INFO] CLICK at ({x},{y}) (stub)")
    else:
        log("[WARN] CLICK missing target")


def _do_type(params: Dict[str, Any]) -> None:
    text: str = params.get("text") or ""
    if not text:
        log("[WARN] TYPE missing text")
        return
    speed = params.get("speed") or 0.0
    repeat = params.get("repeat") or 1
    interval = params.get("interval") or 0.0
    log(
        f"[INFO] TYPE {text!r} repeat={repeat} interval={interval}s "
        f"speed={speed}s (stub)"
    )


def _do_press(params: Dict[str, Any]) -> None:
    keys = params.get("keys") or ()
    if not keys:
        log("[WARN] PRESS missing keys")
        return
    log(f"[INFO] PRESS keys={list(keys)} (stub)")


# =========================================================
# ⏳ WAIT
# =========================================================

def _do_wait(params: Dict[str, Any]) -> None:
    seconds = float(params.get("seconds") or 0.0)
    seconds = max(0.0, min(seconds, float(MAX_WAIT_SECONDS)))
    if seconds == 0.0:
        return
    log(f"[INFO] WAIT {seconds}s")
    time.sleep(seconds)


# =========================================================
# 📸 SCREENSHOT
# =========================================================

def _do_screenshot(params: Dict[str, Any]) -> None:
    if params.get("display") or params.get("window") or params.get("area"):
        log(
            "[INFO] SCREENSHOT variant: "
            f"display={params.get('display')} window={params.get('window')!r} "
            f"area={params.get('area')} (stub — falls back to full screen)"
        )
    saved = take_screenshot(params.get("path"))
    if saved is None:
        log("[WARN] Screenshot failed (best-effort)")


# =========================================================
# 📋 CLIPBOARD / SAVE
# =========================================================

def _do_copy(params: Dict[str, Any]) -> None:
    log("[INFO] COPY (stub)")


def _do_paste(params: Dict[str, Any]) -> None:
    log("[INFO] PASTE (stub)")


def _do_save(params: Dict[str, Any]) -> None:
    src = params.get("source")
    to = params.get("to")
    log(f"[INFO] SAVE source={src!r} to={to!r} (stub)")


# =========================================================
# 🛠️ RUN
# =========================================================

def _do_run(params: Dict[str, Any]) -> None:
    path = params.get("path")
    log(f"[INFO] RUN {path!r} (stub — refusing to exec arbitrary scripts)")


# =========================================================
# 🛠️ HELPERS
# =========================================================

def _short(params: Dict[str, Any]) -> Dict[str, Any]:
    """Shorten params for debug log output."""
    out = {k: v for k, v in params.items() if k not in ("raw",)}
    if isinstance(out.get("tags"), (set, frozenset)):
        out["tags"] = sorted(out["tags"])
    return out
