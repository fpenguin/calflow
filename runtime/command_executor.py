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
- RUN btt(...)      → real (runtime.actions.btt.trigger_named_btt)
- RUN shortcut(...) → real (runtime.actions.shortcuts.run_shortcut)
- RUN alfred(...)   → real (runtime.actions.btt.trigger_alfred)
- RUN applescript   → real (runtime.actions.applescript.run_applescript)
- FOCUS / CLOSE / HIDE / CLICK / TYPE / PRESS / COPY / PASTE / SAVE
                → stubs that log the resolved params (Quartz / AXUI / clipboard
                  backends land in v2.x); Plus Mode pipeline is fully wired
                  through resolution + dispatch already.
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'execute_commands',
]

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

from config.config import MAX_WAIT_SECONDS
from config.settings import (
    AUTOFILL_BUFFER,
    PLUS_INTER_COMMAND_DELAY,
)
from core.event_trust import TRUST_SELF
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
from runtime.actions.applescript import run_applescript
from runtime.actions.browser import open_target
from runtime.actions.btt import trigger_alfred, trigger_named_btt
from runtime.actions.notifications import notify_run_error
from runtime.actions.run_result import RunResult, error_result, ok_result
from runtime.actions.screenshot import take_screenshot, take_screenshot_to_clipboard
from runtime.actions.shortcuts import run_shortcut
from runtime.run_policy import is_run_backend_allowed
from state.stats_store import record_action  # v1.3.0 — lifetime stats


# Fields that may carry user-facing strings with `{…}` dynamic blocks.
_DYNAMIC_FIELDS = ("url", "text", "path", "to", "title", "selector")


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def execute_commands(
    commands: List[BaseCommand],
    global_tags: Optional[Union[Set[str], FrozenSet[str]]] = None,
    debug: bool = False,
    trust_level: str = TRUST_SELF,
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
            _dispatch(params, trust_level=trust_level)

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

def _dispatch(params: Dict[str, Any], *, trust_level: str = TRUST_SELF) -> None:
    """Route a resolved param dict to the correct action."""
    verb = params.get("verb")

    handler = {
        "OPEN":       _do_open,
        "FOCUS":      _do_focus,
        "CLOSE":      _do_close,
        "HIDE":       _do_hide,
        "CLICK":      _do_click,
        "DRAG":       _do_drag,
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

    if verb == "RUN":
        handler(params, trust_level=trust_level)
    else:
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
    functions = params.get("functions") or {}
    display_spec = resolve_display(tags)
    chrome_profile = resolve_chrome_profile(tags)
    # v1.1.20 — layout/display tag implies new window; new(window)/new(tab)
    # explicitly overrides. See runtime.actions.browser.wants_new_window.
    from runtime.actions.browser import wants_new_window
    new_win = wants_new_window(
        tags=tags,
        functions=list(functions.items()) if isinstance(functions, dict) else functions,
    )

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
                new_window=new_win,
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
            new_window=new_win,
        )
        # v1.3.0 — count once per app routed (bundle expansion → N counts).
        record_action("open_profile" if chrome_profile else "open_url")
        if params.get("layout") is not None:
            record_action("arrange")

    time.sleep(max(0.0, AUTOFILL_BUFFER))

    tags = set(params.get("tags") or frozenset())
    if tags:
        should_fill, should_submit = resolve_autofill(tags)
        if should_fill:
            trigger_autofill(mode="fill")
            if should_submit:
                trigger_autofill(mode="submit")
            record_action("autofill")


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
        # v1.3.0 — focus is a 1-second-saved manual action.
        record_action("focus")
        if display_target is not None:
            record_action("arrange")


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
            record_action("hide")  # v1.3.0 — close == hide for time-saving purposes
        else:
            log("[WARN] CLOSE active: could not determine frontmost app")
        return
    if target_keyword == "all":
        # Note: `close_all` keeps frontmost for safety, even with `all`.
        close_all(except_apps=())
        record_action("hide")
        return

    items = params.get("items") or ()
    keep = params.get("keep") or ()
    had_items = params.get("had_items", False)

    if items:
        for item in items:
            name = item.lstrip("@") if isinstance(item, str) else item
            close_app(name)
            record_action("hide")
        return

    # v1.1.14 — refuse to fall through to close_all when the user
    # explicitly listed items (even if they all failed to resolve).
    # Otherwise an unknown @alias collapses to "close everything".
    if had_items:
        log(
            "[WARN] CLOSE: items list resolved to empty (all unknown). "
            "Refusing to fall through to `close all`-style behaviour."
        )
        return

    if keep is not None:  # except(<arg>) form — even empty keep is valid here
        # close everything visible except the keep set + frontmost
        close_all(except_apps=keep)
        record_action("hide")
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

    v1.5.2 shapes:
        hide active display(N|"name")   → miniaturize the frontmost
                                          app's windows on that display
                                          only (per-window JXA path)
        hide [active,"App"]             → `active` expands to the
                                          frontmost app name at
                                          execution time, deduped
    """
    from runtime.actions.app_control import (
        hide_app, hide_all, get_frontmost_app_name,
    )

    target_keyword = params.get("target_keyword")
    if target_keyword == "active":
        name = get_frontmost_app_name()
        if not name:
            log("[WARN] HIDE active: could not determine frontmost app")
            return
        # v1.5.2 — `hide active display(N)`: per-window scope. App-level
        # hide would remove the app's windows on EVERY display, which is
        # not what the user asked for.
        active_display = params.get("display_filter")
        if active_display is not None:
            from runtime.actions.window import hide_apps_on_display
            hide_apps_on_display(active_display, only_app=name)
            record_action("hide")
            return
        hide_app(name)
        record_action("hide")
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
        record_action("hide")
        return

    items = params.get("items") or ()
    keep = params.get("keep") or ()
    display_filter = params.get("display_filter")
    had_items = params.get("had_items", False)

    if items:
        # v1.5.2 — `active` inside a list expands to the frontmost app
        # name at execution time; duplicates collapse (e.g. the
        # frontmost IS one of the listed apps).
        expanded: List[str] = []
        for item in items:
            name = item.lstrip("@") if isinstance(item, str) else item
            if isinstance(name, str) and name.lower() == "active":
                front = get_frontmost_app_name()
                if not front:
                    log("[WARN] HIDE list: `active` skipped — could not "
                        "determine frontmost app")
                    continue
                name = front
            if name not in expanded:
                expanded.append(name)
        for name in expanded:
            hide_app(name)
            record_action("hide")
        return

    # v1.1.14 — refuse to fall through to hide_all when the user
    # explicitly listed items (even if they all failed to resolve).
    # Otherwise an unknown @alias collapses to "hide everything".
    if had_items:
        log(
            "[WARN] HIDE: items list resolved to empty (all unknown). "
            "Refusing to fall through to `hide all`-style behaviour."
        )
        return

    # v1.1.7+ — real per-window display filter via JXA + System Events.
    # On failure (typically Accessibility not granted to osascript),
    # the wrapper has already logged an actionable message — we do
    # NOT fall back to hide_all here, because hiding EVERY visible
    # app would surprise the user who asked for a specific display.
    #
    # v1.1.12 — `keep_frontmost` is opt-in. Bare `hide display(N)`
    # targets the frontmost app too (the user explicitly asked).
    # `hide except(active) display(N)` is how the user asks to keep
    # the frontmost as a safety. We detect the runtime keyword
    # `active` in the keep set; the JXA-side keep list still also
    # contains it as a literal name (harmless — no real app is
    # called "active" since v1.1.2 reserves it).
    if display_filter is not None:
        from runtime.actions.window import hide_apps_on_display
        keep_active = "active" in (keep or ())
        hide_apps_on_display(
            display_filter,
            except_apps=tuple(keep),
            keep_frontmost=keep_active,
        )
        record_action("hide")
        return

    hide_all(except_apps=keep)
    record_action("hide")


# =========================================================
# 🖱️ CLICK / TYPE / PRESS
# =========================================================

def _do_click(params: Dict[str, Any]) -> None:
    text = params.get("text")
    selector = params.get("selector")
    x, y = params.get("x"), params.get("y")
    # v1.5.4 — gesture modifiers surface in the stub log so a dry run
    # shows what the v2.1 backend will receive.
    gesture = ""
    if params.get("button", "left") != "left":
        gesture += f" button={params['button']}"
    if params.get("count", 1) != 1:
        gesture += f" count={params['count']}"
    if text:
        log(f"[INFO] CLICK text={text!r} selector={selector!r}{gesture} (stub)")
    elif selector:
        log(f"[INFO] CLICK selector={selector!r}{gesture} (stub)")
    elif x is not None and y is not None:
        log(f"[INFO] CLICK at ({x},{y}){gesture} (stub)")
    else:
        log("[WARN] CLICK missing target")


def _do_drag(params: Dict[str, Any]) -> None:
    """
    v1.5.4 — parses/validates/resolves today; the Quartz backend
    (CGEvent mouseDown → interpolated drags over `duration` → mouseUp)
    lands with the v2.1 UI-action batch.
    """
    x1, y1 = params.get("x1"), params.get("y1")
    x2, y2 = params.get("x2"), params.get("y2")
    if None in (x1, y1, x2, y2):
        log("[WARN] DRAG missing endpoints (validator should have caught)")
        return
    log(
        f"[INFO] DRAG ({x1},{y1}) → ({x2},{y2}) "
        f"button={params.get('button', 'left')} "
        f"duration={params.get('duration', 0.3)}s (stub)"
    )


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
    # v1.5.2 — the default sink is the CLIPBOARD. A file is written only
    # when the user asked for one via `to("path")`. `to(clipboard)` is
    # the explicit spelling of the default.
    path = params.get("path")
    if path is None or path == "clipboard":
        ok = take_screenshot_to_clipboard()
        record_action("screenshot", success=ok)
        if not ok:
            log("[WARN] Screenshot-to-clipboard failed (best-effort)")
        return
    saved = take_screenshot(path)
    if saved is None:
        log("[WARN] Screenshot failed (best-effort)")
        record_action("screenshot", success=False)
    else:
        record_action("screenshot")


# =========================================================
# 📋 CLIPBOARD / SAVE
# =========================================================

def _do_copy(params: Dict[str, Any]) -> None:
    """
    copy("text")  → v1.5.2: place the literal on the clipboard (real).
    copy          → selection copy via synthesized ⌘C (still stub, v2.3).
    """
    text = params.get("text")
    if text is None:
        log("[INFO] COPY (stub)")
        return
    try:
        result = subprocess.run(
            ["pbcopy"], input=text, text=True, timeout=5, check=False,
        )
        if result.returncode == 0:
            log(f"[INFO] COPY: {len(text)} chars → clipboard")
            record_action("copy")
        else:
            log(f"[WARN] COPY: pbcopy returned {result.returncode}")
            record_action("copy", success=False)
    except FileNotFoundError:
        log("[WARN] COPY: pbcopy not available on this platform")
        record_action("copy", success=False)
    except Exception as exc:
        log(f"[ERROR] COPY failed: {exc}")
        record_action("copy", success=False)


def _do_paste(params: Dict[str, Any]) -> None:
    log("[INFO] PASTE (stub)")


def _do_save(params: Dict[str, Any]) -> None:
    src = params.get("source")
    to = params.get("to")
    log(f"[INFO] SAVE source={src!r} to={to!r} (stub)")


# =========================================================
# 🛠️ RUN
# =========================================================

def _do_run(params: Dict[str, Any], *, trust_level: str = TRUST_SELF) -> None:
    backend = params.get("backend") or "script"
    handlers = tuple(params.get("run_handlers") or ())
    if not is_run_backend_allowed(backend, trust_level):
        msg = f"RUN {backend} disabled for trust level {trust_level!r}"
        log(f"[WARN] {msg}")
        notify_run_error("CalFlow run blocked", msg)
        _apply_run_handlers(
            handlers,
            error_result(str(backend), msg),
        )
        return

    result: Optional[RunResult] = None
    if backend == "btt":
        trigger_name = params.get("trigger_name")
        if not trigger_name:
            msg = "RUN btt(...) missing trigger name"
            log(f"[WARN] {msg}")
            notify_run_error("CalFlow BTT failed", msg)
            _apply_run_handlers(handlers, error_result("btt", msg))
            return
        result = trigger_named_btt(str(trigger_name))
        _apply_run_handlers(handlers, result or ok_result("btt"))
        return

    if backend == "applescript":
        if params.get("timeout") is None:
            result = run_applescript(str(params.get("script") or ""))
        else:
            result = run_applescript(
                str(params.get("script") or ""),
                timeout=params.get("timeout"),
            )
        _apply_run_handlers(handlers, result or ok_result("applescript"))
        return

    if backend == "shortcut":
        result = run_shortcut(
            str(params.get("shortcut_name") or ""),
            str(params.get("shortcut_input") or ""),
        )
        _apply_run_handlers(handlers, result or ok_result("shortcut"))
        return

    if backend == "alfred":
        result = trigger_alfred(
            str(params.get("alfred_bundle_id") or ""),
            str(params.get("alfred_trigger") or ""),
            str(params.get("alfred_argument") or ""),
        )
        _apply_run_handlers(handlers, result or ok_result("alfred"))
        return

    path = params.get("path")
    log(f"[INFO] RUN {path!r} (stub — refusing to exec arbitrary scripts)")
    _apply_run_handlers(
        handlers,
        error_result("script", "arbitrary scripts are disabled in this build"),
    )


# =========================================================
# 🛠️ HELPERS
# =========================================================

def _short(params: Dict[str, Any]) -> Dict[str, Any]:
    """Shorten params for debug log output."""
    out = {k: v for k, v in params.items() if k not in ("raw",)}
    if isinstance(out.get("tags"), (set, frozenset)):
        out["tags"] = sorted(out["tags"])
    return out


def _apply_run_handlers(
    handlers: Tuple[Tuple[str, str, str], ...],
    result: RunResult,
) -> None:
    if not handlers:
        return
    for condition, action, value in handlers:
        if not _run_condition_matches(condition, result):
            continue
        try:
            if action == "notify":
                text = _run_handler_text(value, result)
                notify_run_error(result.title, text)
            elif action == "copy":
                text = _run_handler_text(value, result)
                _copy_text_to_clipboard(text)
            elif action == "save":
                text = result.result_text
                _write_text(value, text, append=False)
            elif action == "append":
                text = result.result_text
                _write_text(value, text, append=True)
        except Exception as exc:
            log(f"[WARN] RUN handler {action!r} failed: {exc}")


def _run_condition_matches(condition: str, result: RunResult) -> bool:
    name = (condition or "").strip().lower()
    if name == "error":
        return not result.ok
    if name == "success":
        return result.ok
    if name == "output":
        return bool((result.stdout or result.stderr or result.message).strip())
    return False


def _run_handler_text(value: str, result: RunResult) -> str:
    payload = (value or "").strip()
    if not payload or payload == "result":
        return result.result_text
    return payload


def _copy_text_to_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=False, timeout=5)


def _write_text(path: str, text: str, *, append: bool) -> None:
    if not path:
        raise ValueError("missing output path")
    target = Path(resolve_dynamic(path)).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as fh:
        fh.write(text)
        if append and text and not text.endswith("\n"):
            fh.write("\n")
