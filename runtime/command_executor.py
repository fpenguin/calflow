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
from core.resolver import (
    resolve_autofill,
    resolve_chrome_profile,
    resolve_command,
    resolve_display,
)
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

    tags = set(params.get("tags") or frozenset())
    display_spec = resolve_display(tags)
    chrome_profile = resolve_chrome_profile(tags)

    # Bundle expansion: if the primary itself is `@bundle`, the resolver
    # populated `apps` with multiple items. Each bundle item becomes its
    # own open dispatch — and the item's own classification (URL / app /
    # file) decides what gets opened.
    apps: List[str] = params.get("apps") or []
    primary_is_bundle = url and url.startswith("@") and len(apps) > 1

    if primary_is_bundle:
        # `open @work` → expand to N opens, one per item.
        for item in apps:
            # Each `item` is a string from settings.TARGETS — could be
            # an app name ("Slack"), URL ("https://x.com"), or file path.
            open_target(
                url=item,           # let _classify_primary inside open_target dispatch
                app=None,           # no routing — item's type decides
                layout=params.get("layout"),
                display_spec=display_spec,
                chrome_profile=chrome_profile,
            )
        return

    # Normal case: one open. `apps` contains the routing browser (or None).
    if not apps:
        apps = [params.get("app") or None]  # type: ignore[list-item]

    for app in apps:
        open_target(
            url=url,
            app=app,
            layout=params.get("layout"),
            display_spec=display_spec,
            chrome_profile=chrome_profile,
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
    """
    v1.1.2 forms:
        focus @app                  → activate app
        focus @app title("X")       → activate + raise matching window
        focus @app display(N|"name") → activate + move all windows to display
        focus active                → no-op (frontmost is already focused)
    """
    from runtime.actions.app_control import focus_app, focus_window_by_title
    from runtime.actions.window import move_app_to_display

    # Runtime target — `focus active` is a no-op.
    if params.get("target_keyword") == "active":
        log("[INFO] FOCUS active (no-op — frontmost is already focused)")
        return

    title = params.get("title")
    display_target = params.get("display_target")
    apps = params.get("apps") or ([params.get("target")] if params.get("target") else [])
    apps = [a for a in apps if a]

    if not apps:
        log("[WARN] FOCUS missing target")
        return

    for app in apps:
        # Strip @ prefix if it leaked through
        app_name = app.lstrip("@") if isinstance(app, str) else app
        if title:
            focus_window_by_title(app_name, title)
        else:
            focus_app(app_name)
        if display_target is not None:
            move_app_to_display(app_name, display_target)


def _do_close(params: Dict[str, Any]) -> None:
    """
    v1.1.2 shapes:
        close active                              → quit frontmost app
        close all                                 → quit every visible app
        close [list] / close @app / close "App"   → items populated
        close except(<arg>)                       → keep populated
    """
    from runtime.actions.app_control import (
        close_app, close_all, get_frontmost_app_name,
    )

    target_keyword = params.get("target_keyword")
    if target_keyword == "active":
        name = get_frontmost_app_name()
        if name:
            close_app(name)
        else:
            log("[WARN] CLOSE active: could not determine frontmost app")
        return
    if target_keyword == "all":
        # Note: `close_all` keeps frontmost for safety, even with `all`.
        close_all(except_apps=())
        return

    items = params.get("items") or ()
    keep = params.get("keep") or ()

    if items:
        for item in items:
            name = item.lstrip("@") if isinstance(item, str) else item
            close_app(name)
        return

    if keep is not None:  # except(<arg>) form — even empty keep is valid here
        # close everything visible except the keep set + frontmost
        close_all(except_apps=keep)
        return

    log("[WARN] CLOSE missing arguments (validator should have caught)")


def _do_hide(params: Dict[str, Any]) -> None:
    """
    v1.1.2 shapes:
        hide active                               → hide frontmost app
        hide all                                  → hide every visible app
        hide [list] / hide @app / hide "App"      → items populated
        hide except(<arg>)                        → keep populated
        hide display(N|"name")                    → display_filter set
        hide except(<arg>) display(N|"name")      → both

    `display_filter` per-window scoping is still a stub (full impl in
    a follow-up); we log the filter and proceed across all displays.
    """
    from runtime.actions.app_control import (
        hide_app, hide_all, get_frontmost_app_name,
    )

    target_keyword = params.get("target_keyword")
    if target_keyword == "active":
        name = get_frontmost_app_name()
        if name:
            hide_app(name)
        else:
            log("[WARN] HIDE active: could not determine frontmost app")
        return
    if target_keyword == "all":
        # `hide all` per spec hides EVERY visible non-bg app, including
        # the frontmost. `hide_all(except_apps=())` keeps frontmost for
        # safety; for `all` we explicitly bypass that by hiding frontmost
        # individually first.
        hide_all(except_apps=())
        # hide_all keeps the frontmost; finish the job.
        front = get_frontmost_app_name()
        if front:
            hide_app(front)
        return

    items = params.get("items") or ()
    keep = params.get("keep") or ()
    display_filter = params.get("display_filter")

    if items:
        for item in items:
            name = item.lstrip("@") if isinstance(item, str) else item
            hide_app(name)
        return

    # v1.1.7+ — real per-window display filter via JXA + System Events.
    # On failure (typically Accessibility not granted to osascript),
    # the wrapper has already logged an actionable message — we do
    # NOT fall back to hide_all here, because hiding EVERY visible
    # app would surprise the user who asked for a specific display.
    if display_filter is not None:
        from runtime.actions.window import hide_apps_on_display
        hide_apps_on_display(display_filter, except_apps=tuple(keep))
        return

    hide_all(except_apps=keep)


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
    """
    v1.1.2 forms:
        screenshot                          → default sink
        screenshot to("~/x.png")            → explicit path
        screenshot active                   → frontmost-window capture (stub)
        screenshot display(N) | window(...) | area(...)   (stub variants)
    """
    if params.get("target_keyword") == "active":
        log(
            "[INFO] SCREENSHOT active: frontmost-window capture is a "
            "stub — falling back to full screen"
        )
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
