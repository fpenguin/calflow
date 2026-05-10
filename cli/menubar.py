"""
CalFlow menubar companion app (v1.3.0).

Architecture:
    NSStatusItem (menu bar icon)
        │
        ├── click → toggle NSPopover
        │
        └── NSPopover hosts WKWebView
                  │
                  └── loads runtime/menubar/popover.html
                            │
                            └── window.webkit.messageHandlers.cf
                                    │
                                    ▼
                            CFBridge (this file)
                                    │
                                    ▼
                            subprocess: `python -m cli.main <verb>`
                                    │
                                    ▼
                            JSON to stdout → back to JS via
                            evaluateJavaScript("window.cf_resolve(...)")

Why subprocess instead of in-process imports:
    Each CLI subcommand spins up a fresh interpreter (~50 ms) and uses
    its own Google API client. The dominant cost is the API call
    (~500 ms-1 s), so subprocess overhead is negligible. This also
    keeps the menubar process from holding OAuth tokens in memory
    indefinitely. If we ever want a single-process design, refactor
    `print_*_json` to return dicts and skip subprocess.

Lifecycle:
    AppHelper.runEventLoop() blocks forever. Cmd+Q from the popover
    or NSApp.terminate_(None) cleanly exits.

Lazy import discipline:
    pyobjc-framework-WebKit and pyobjc-framework-Cocoa are optional
    runtime deps; importing this module without them raises ImportError,
    which `cli.main`'s dispatcher catches to print a friendly install hint.
"""

from __future__ import annotations

__all__ = ["main"]

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# =========================================================
# 🧷 LAZY IMPORTS (raise on missing deps so cli.main can intercept)
# =========================================================
#
# These three pyobjc frameworks plus rumps form the menubar runtime.
# We import at module top so class definitions can reference the
# names directly. cli.main wraps `from cli.menubar import main` in a
# try/except ImportError that prints an install hint.

import objc                                              # noqa: E402
from AppKit import (                                     # noqa: E402
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSImage,
    NSMaxYEdge,
    NSModalResponseOK,
    NSOpenPanel,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSScreen,
    NSSquareStatusItemLength,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSViewController,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import (                                 # noqa: E402
    NSMakeRect,
    NSObject,
    NSOperationQueue,
    NSURL,
)
from WebKit import (                                     # noqa: E402
    WKUserContentController,
    WKWebView,
    WKWebViewConfiguration,
)
from PyObjCTools import AppHelper                        # noqa: E402

from runtime.menubar import POPOVER_HTML, RECIPES_HTML, SETTINGS_HTML  # noqa: E402

# Path to the same Python interpreter the user invoked us with —
# subprocess calls reuse it so deps line up.
_PY = sys.executable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Popover dimensions (px). Tall enough that a typical "Up next + 2
# missed events + stats" fits without scrolling the popover itself
# (the missed list scrolls inside its own pane).
_POPOVER_W = 360
_POPOVER_H = 540

# Window dimensions for the Recipes / Settings standalone pages.
_RECIPES_W,  _RECIPES_H,  _RECIPES_MIN  = 760, 540, (640, 480)
_SETTINGS_W, _SETTINGS_H, _SETTINGS_MIN = 680, 540, (560, 420)


# =========================================================
# 🌐 EXTERNAL LINKS
# =========================================================
#
# `open-coffee` and `open-about` open URLs in the user's default
# browser via `open(1)`. Replace these with your real URLs once
# the GitHub repo and Buy-Me-a-Coffee page exist.

_OPEN_URLS: Dict[str, str] = {
    "open-coffee": "https://www.buymeacoffee.com/calflow",
    "open-about":  "https://github.com/calflow/calflow/releases/latest",
}

# v1.3.1 — these now route to native windows (see _CFApp.show_window_).
# Kept as a fallback path: if the window can't be created for any reason,
# the bridge falls through to opening the folder in Finder.
_OPEN_PATHS: Dict[str, Path] = {
    "open-recipes-folder":  _PROJECT_ROOT / "playbooks",
    "open-settings-folder": _PROJECT_ROOT / "config",
}


# =========================================================
# 🌉 SCRIPT MESSAGE HANDLER (JS → Python)
# =========================================================
#
# WKWebView fires
#     userContentController:didReceiveScriptMessage:
# whenever the page calls
#     window.webkit.messageHandlers.cf.postMessage({...})
# We forward to _CFApp.handle_message which dispatches to subprocess
# or local action and resolves the JS Promise via evaluateJavaScript.

class _CFBridge(NSObject):
    def initWithApp_(self, app):           # noqa: N802 (Cocoa naming)
        self = objc.super(_CFBridge, self).init()
        if self is None:
            return None
        self._app = app
        return self

    def userContentController_didReceiveScriptMessage_(  # noqa: N802
        self, controller, message,
    ):
        body = message.body()
        try:
            data = dict(body) if body else {}
        except Exception:
            data = {}
        msg_id = str(data.get("id") or "")
        op = str(data.get("op") or "")
        raw_args = data.get("args") or {}
        try:
            args = dict(raw_args)
        except Exception:
            args = {}
        # v1.3.5 — capture the source webview so the response goes back
        # to the SAME page that sent the message. Before this fix every
        # response was routed to the popover, leaving Settings / Recipes
        # promises unresolved (UI hung in "Saving…").
        try:
            src_wv = message.webView()
        except Exception:
            src_wv = None
        self._app.handle_message(msg_id, op, args, src_wv)


# =========================================================
# 🚀 APP CONTROLLER
# =========================================================

class _CFApp(NSObject):
    """
    Owns the status item, popover, and web view.

    NSObject subclass so its methods can be exposed as Cocoa
    selectors (the status item's action target needs an
    Objective-C-compatible callable).
    """

    def init(self):
        self = objc.super(_CFApp, self).init()
        if self is None:
            return None

        # --- Popover web view + bridge ---------------------------
        bridge = _CFBridge.alloc().initWithApp_(self)
        webview = self._make_webview(POPOVER_HTML, (_POPOVER_W, _POPOVER_H), bridge)

        # --- Popover ---------------------------------------------
        popover = NSPopover.alloc().init()
        popover.setBehavior_(NSPopoverBehaviorTransient)  # auto-dismiss
        popover.setAnimates_(True)

        vc = NSViewController.alloc().init()
        vc.setView_(webview)
        popover.setContentViewController_(vc)
        popover.setContentSize_((_POPOVER_W, _POPOVER_H))

        # --- Status bar item -------------------------------------
        status_item = (
            NSStatusBar.systemStatusBar()
            .statusItemWithLength_(NSVariableStatusItemLength)
        )
        button = status_item.button()
        # Compact monogram. Replace with NSImage(named:"…") later.
        button.setTitle_("⏱ CF")
        button.setAction_("togglePopover:")
        button.setTarget_(self)

        # --- Retain references -----------------------------------
        self._bridge = bridge
        self._webview = webview
        self._popover = popover
        self._status_item = status_item

        # Lazy-created secondary windows (Recipes, Settings).
        self._windows: Dict[str, Any] = {}
        self._window_webviews: Dict[str, Any] = {}

        return self

    # =====================================================
    # 🛠 WebView factory (popover + windows share this)
    # =====================================================

    @objc.python_method
    def _make_webview(self, html_path: Path, size, bridge) -> Any:
        """Create a WKWebView pre-wired to our bridge, loading `html_path`."""
        ucc = WKUserContentController.alloc().init()
        ucc.addScriptMessageHandler_name_(bridge, "cf")

        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(ucc)
        try:
            config.preferences().setJavaScriptEnabled_(True)
        except Exception:
            pass

        wv = WKWebView.alloc().initWithFrame_configuration_(
            ((0, 0), size), config,
        )
        try:
            wv.setNavigationDelegate_(self)
        except Exception:
            pass

        html_url = NSURL.fileURLWithPath_(str(html_path))
        wv.loadFileURL_allowingReadAccessToURL_(
            html_url, html_url.URLByDeletingLastPathComponent(),
        )
        return wv

    # =====================================================
    # 🖱  Status item click
    # =====================================================

    def togglePopover_(self, sender):       # noqa: N802 (Cocoa selector)
        if self._popover.isShown():
            self._popover.close()
            return
        # Activate so the popover gets keyboard focus.
        NSApp.activateIgnoringOtherApps_(True)
        self._popover.showRelativeToRect_ofView_preferredEdge_(
            sender.bounds(), sender, NSMaxYEdge,
        )
        # Tell the page it's been shown so it can refresh.
        self._eval_js("if (window.cf_onShow) cf_onShow();")

    # =====================================================
    # 📨 Message dispatch (JS → Python)
    # =====================================================
    #
    # PyObjC note: every method on an NSObject subclass is, by default,
    # treated as a candidate Cocoa selector — its arity must match the
    # selector's underscore-separated arg slots. The methods below are
    # Python-only helpers (called from worker threads / other Python
    # code, never via Cocoa runtime), so they get @objc.python_method
    # to opt out of selector machinery.

    @objc.python_method
    def handle_message(self, msg_id: str, op: str, args: Dict[str, Any],
                       src_wv: Any = None) -> None:
        """Route a postMessage from JS to either a subprocess or a local action.

        `src_wv` is the WKWebView that originated the message — responses
        must be evaluateJavaScript'd back into the SAME view, otherwise
        the calling page's pending promise never resolves and its UI hangs.
        """
        # --- Local: open URL --------------------------------
        if op in _OPEN_URLS:
            self._open_url(_OPEN_URLS[op])
            self._resolve(msg_id, {"opened": _OPEN_URLS[op]}, src_wv)
            return

        # --- Local: open a folder/file in Finder ------------
        if op in _OPEN_PATHS:
            path = _OPEN_PATHS[op]
            if path.exists():
                self._open_path(path)
                self._resolve(msg_id, {"opened": str(path)}, src_wv)
            else:
                self._reject(msg_id, f"path not found: {path}", src_wv)
            return

        # --- Local: show a secondary window (Recipes / Settings)
        if op == "show-recipes-window":
            try:
                self._popover.close()
            except Exception:
                pass
            self._show_window("recipes", "CalFlow — Recipes",
                              RECIPES_HTML, _RECIPES_W, _RECIPES_H, _RECIPES_MIN)
            self._resolve(msg_id, {"shown": "recipes"}, src_wv)
            return
        if op == "show-settings-window":
            try:
                self._popover.close()
            except Exception:
                pass
            self._show_window("settings", "CalFlow — Settings",
                              SETTINGS_HTML, _SETTINGS_W, _SETTINGS_H, _SETTINGS_MIN)
            self._resolve(msg_id, {"shown": "settings"}, src_wv)
            return

        # --- Local: clipboard (recipes window Copy fallback) -
        if op == "copy-to-clipboard":
            text = str(args.get("text") or "")
            try:
                # v1.3.14 — use subprocess.run with timeout (CLAUDE.md §3:
                # every subprocess call must have a timeout). The previous
                # Popen.communicate() variant could hang the worker thread
                # indefinitely if the system pasteboard was locked.
                subprocess.run(
                    ["pbcopy"],
                    input=text.encode("utf-8"),
                    timeout=5,
                    check=False,
                )
                self._resolve(msg_id, {"ok": True}, src_wv)
            except subprocess.TimeoutExpired:
                self._reject(msg_id, "pbcopy timeout (5s)", src_wv)
            except Exception as exc:
                self._reject(msg_id, f"pbcopy failed: {exc}", src_wv)
            return

        # --- Local: native folder picker (NSOpenPanel) ------
        if op == "pick-folder":
            self._show_folder_picker(msg_id, args, src_wv)
            return

        # --- Local: quit ------------------------------------
        if op == "quit":
            self._resolve(msg_id, {"quitting": True}, src_wv)
            NSApp.terminate_(None)
            return

        # --- Subprocess: build cmd --------------------------
        cmd = self._build_cmd(op, args)
        if cmd is None:
            self._reject(msg_id, f"unknown op: {op!r}", src_wv)
            return

        # save-recipe / run-script / apply-settings need stdin payload — handle separately.
        stdin_payload: Optional[bytes] = None
        if op == "save-recipe":
            try:
                stdin_payload = json.dumps(args or {}).encode("utf-8")
            except Exception as exc:
                self._reject(msg_id, f"bad save-recipe payload: {exc}", src_wv); return
        elif op == "run-script":
            body = args.get("body") if isinstance(args, dict) else None
            if not body:
                self._reject(msg_id, "missing body", src_wv); return
            stdin_payload = str(body).encode("utf-8")
        elif op == "apply-settings":
            try:
                stdin_payload = json.dumps(args or {}).encode("utf-8")
            except Exception as exc:
                self._reject(msg_id, f"bad apply-settings payload: {exc}", src_wv); return
        elif op == "apply-targets":
            try:
                stdin_payload = json.dumps(args or {}).encode("utf-8")
            except Exception as exc:
                self._reject(msg_id, f"bad apply-targets payload: {exc}", src_wv); return

        # Run on a worker thread; reply via main-thread evaluateJavaScript.
        threading.Thread(
            target=self._run_subprocess,
            args=(msg_id, cmd, stdin_payload, src_wv),
            daemon=True,
        ).start()

    # =====================================================
    # 🛠 Build CLI command
    # =====================================================

    @objc.python_method
    def _build_cmd(self, op: str, args: Dict[str, Any]):
        base = [_PY, "-m", "cli.main"]
        if op == "status":
            return base + ["status", "--json"]
        if op == "stats":
            return base + ["stats"]
        if op in ("upcoming", "missed"):
            cmd = base + [op]
            hours = args.get("hours")
            if hours:
                try:
                    cmd += ["--hours", str(int(hours))]
                except (TypeError, ValueError):
                    pass
            return cmd
        if op == "run-event":
            ev_id = args.get("id")
            if not ev_id:
                return None
            return base + ["run-event", str(ev_id)]
        if op == "pause":
            return base + ["pause"]
        if op == "resume":
            return base + ["resume"]
        # v1.3.1 — recipes + settings + run-script ops.
        if op == "recipes":
            return base + ["recipes"]
        if op == "save-recipe":
            return base + ["save-recipe"]
        if op == "delete-recipe":
            rid = args.get("id")
            if not rid:
                return None
            return base + ["delete-recipe", str(rid)]
        if op == "run-script":
            return base + ["run-script"]
        if op == "settings":
            return base + ["settings"]
        if op == "edit-settings-file":
            return base + ["edit-settings-file"]
        if op == "apply-settings":
            return base + ["apply-settings"]
        if op == "targets":
            return base + ["targets"]
        if op == "apply-targets":
            return base + ["apply-targets"]
        if op in ("daemon-start", "daemon-stop", "daemon-restart"):
            return base + [op]
        if op == "open-system-prefs":
            pane = args.get("pane") if isinstance(args, dict) else None
            return base + ["open-system-prefs", str(pane or "accessibility")]
        return None

    # =====================================================
    # ⚙️ Subprocess runner (worker thread)
    # =====================================================

    @objc.python_method
    def _run_subprocess(self, msg_id: str, cmd, stdin_payload: Optional[bytes] = None,
                        src_wv: Any = None) -> None:
        # run-script may legitimately take many seconds (it executes a
        # full Smart/Plus pipeline). Give it a longer budget; everything
        # else stays on the original 20 s clock.
        timeout = 60 if cmd and cmd[-1] == "run-script" else 20
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(_PROJECT_ROOT),
                input=stdin_payload,
                capture_output=True,
                timeout=timeout,
            )
            stdout = (proc.stdout or b"").decode("utf-8", "replace").strip()
            try:
                payload = _parse_json_from_log(stdout)
            except Exception as exc:
                payload = {
                    "error": f"invalid JSON from cli ({exc})",
                    "stdout": stdout[:500],
                    "stderr": (proc.stderr or b"").decode("utf-8", "replace").strip()[:500],
                }
            if proc.returncode != 0 and isinstance(payload, dict):
                payload.setdefault("exit_code", proc.returncode)
            self._resolve(msg_id, payload, src_wv)
        except subprocess.TimeoutExpired:
            self._reject(msg_id, f"subprocess timeout ({timeout}s)", src_wv)
        except Exception as exc:
            self._reject(msg_id, f"{type(exc).__name__}: {exc}", src_wv)

    # =====================================================
    # 🪟 External-open helpers
    # =====================================================

    @objc.python_method
    def _open_url(self, url: str) -> None:
        try:
            ns_url = NSURL.URLWithString_(url)
            NSWorkspace.sharedWorkspace().openURL_(ns_url)
        except Exception:
            try:
                subprocess.Popen(["open", url])
            except Exception:
                pass

    @objc.python_method
    def _open_path(self, path: Path) -> None:
        try:
            subprocess.Popen(["open", str(path)])
        except Exception:
            pass

    # =====================================================
    # 🪟 Secondary windows (Recipes, Settings)
    # =====================================================

    @objc.python_method
    def _show_window(self, key: str, title: str, html_path: Path,
                     w: int, h: int, min_size) -> None:
        """
        Lazy-create or focus an NSWindow + WKWebView for the given key.

        Re-clicks reuse the same window (and webview) — keeps editor
        state across opens. Closing the window hides it; the next call
        re-shows + tells the page to refresh via cf_onShow.
        """
        existing = self._windows.get(key)
        if existing is not None:
            existing.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            wv = self._window_webviews.get(key)
            if wv is not None:
                self._eval_js_on(wv, "if (window.cf_onShow) cf_onShow();")
            return

        # Centre on the active screen.
        screen = NSScreen.mainScreen() or NSScreen.screens().objectAtIndex_(0)
        sf = screen.visibleFrame()
        x = sf.origin.x + (sf.size.width  - w) / 2
        y = sf.origin.y + (sf.size.height - h) / 2
        rect = NSMakeRect(x, y, w, h)

        style = (NSWindowStyleMaskTitled
                 | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskResizable
                 | NSWindowStyleMaskMiniaturizable)

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False,
        )
        win.setTitle_(title)
        win.setReleasedWhenClosed_(False)   # we keep the python ref alive
        win.setMinSize_((min_size[0], min_size[1]))

        wv = self._make_webview(html_path, (w, h), self._bridge)
        win.setContentView_(wv)

        # Retain.
        self._windows[key] = win
        self._window_webviews[key] = wv

        win.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _eval_js_on(self, webview, js: str) -> None:
        """Back-compat alias for _eval_js(js, webview)."""
        self._eval_js(js, webview)

    # =====================================================
    # 📁 Folder picker (NSOpenPanel — main thread, modal)
    # =====================================================

    @objc.python_method
    def _show_folder_picker(self, msg_id: str, args: Dict[str, Any], src_wv: Any) -> None:
        """
        Show a native NSOpenPanel for picking a single directory.

        Runs synchronously on the main thread (NSOpenPanel.runModal blocks).
        That's fine — the WebView is non-interactive while a sheet is up,
        which matches user expectations for a file picker.
        """
        try:
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(False)
            panel.setCanChooseDirectories_(True)
            panel.setAllowsMultipleSelection_(False)
            panel.setTitle_(str(args.get("title") or "Pick a folder"))
            panel.setPrompt_(str(args.get("prompt") or "Select"))
            current = args.get("current")
            if current:
                try:
                    expanded = os.path.expanduser(str(current))
                    panel.setDirectoryURL_(NSURL.fileURLWithPath_(expanded))
                except Exception:
                    pass
            response = panel.runModal()
            if response == NSModalResponseOK:
                urls = panel.URLs()
                if urls and urls.count() > 0:
                    path = str(urls.objectAtIndex_(0).path())
                    self._resolve(msg_id, {"ok": True, "path": path}, src_wv)
                    return
            # User cancelled.
            self._resolve(msg_id, {"ok": False, "path": None}, src_wv)
        except Exception as exc:
            self._reject(msg_id, f"folder picker failed: {exc}", src_wv)

    # =====================================================
    # 🔁 JS bridge replies (main thread)
    # =====================================================

    @objc.python_method
    def _resolve(self, msg_id: str, payload: Any, src_wv: Any = None) -> None:
        if not msg_id:
            return
        try:
            js = "window.cf_resolve({}, {});".format(
                json.dumps(msg_id),
                json.dumps(payload, default=str),
            )
        except Exception as exc:
            js = "window.cf_reject({}, {});".format(
                json.dumps(msg_id),
                json.dumps(f"json encode failed: {exc}"),
            )
        self._eval_js(js, src_wv)

    @objc.python_method
    def _reject(self, msg_id: str, error: str, src_wv: Any = None) -> None:
        if not msg_id:
            return
        js = "window.cf_reject({}, {});".format(
            json.dumps(msg_id),
            json.dumps(str(error)),
        )
        self._eval_js(js, src_wv)

    @objc.python_method
    def _eval_js(self, js: str, target_wv: Any = None) -> None:
        """
        Hop to the main thread to call evaluateJavaScript:.
        evaluateJavaScript: must be invoked on the main thread; the
        worker thread that ran the subprocess is NOT main.

        v1.3.5 — accepts an explicit `target_wv`. Without this, every
        bridge response went to the popover regardless of which window
        sent the message → Settings / Recipes promises never resolved.
        """
        webview = target_wv if target_wv is not None else self._webview

        def _do():
            try:
                webview.evaluateJavaScript_completionHandler_(js, None)
            except Exception:
                # Never raise out of a UI callback.
                pass

        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)


# =========================================================
# 🛠 JSON-FROM-LOG HELPER
# =========================================================
#
# Several CLI helpers emit [INFO]/[WARN]/[ERROR] log lines before the
# JSON object (because executors call core.utils.log unconditionally).
# Find the JSON by scanning for the first '{' on a line and trying to
# decode from there. Falls back to splitting on lines and trying each
# leading '{'.

def _parse_json_from_log(stdout: str) -> Any:
    if not stdout:
        return {}
    # Fast path: pure JSON.
    s = stdout.lstrip()
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    # Slow path: try each line that starts with '{' or '['.
    for i, line in enumerate(stdout.splitlines()):
        stripped = line.lstrip()
        if stripped and stripped[0] in "{[":
            tail = "\n".join(stdout.splitlines()[i:])
            try:
                return json.loads(tail)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("no JSON object found in stdout", stdout, 0)


# =========================================================
# 🔒 SINGLETON LOCK  (v1.3.2)
# =========================================================
#
# Without this, every `python -m cli.main menubar` happily creates
# another NSStatusItem; the user ends up with N ⏱ icons and N webviews
# all polling Google Calendar. The lock keeps it to one.
#
# Pattern mirrors cli/main.py's daemon LOCK_FILE:
#   - file at /tmp/calflow_menubar.lock
#   - contents: "<pid>|<unix_ts>"
#   - stale detection: process is dead OR ts > MAX_AGE
#   - stale lock is replaced; live lock makes us exit cleanly

_LOCK_PATH = "/tmp/calflow_menubar.lock"
_LOCK_MAX_AGE = 7 * 24 * 3600   # 7 days — menubar can stay up that long

def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock():
    try:
        with open(_LOCK_PATH, "r", encoding="utf-8") as f:
            pid_s, ts_s = f.read().strip().split("|")
        return int(pid_s), int(ts_s)
    except Exception:
        return None


def _write_lock() -> None:
    try:
        import time as _t
        with open(_LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}|{int(_t.time())}")
    except Exception:
        pass


def _release_lock() -> None:
    try:
        if os.path.exists(_LOCK_PATH):
            # Only remove if the lock is OURS — defensive.
            data = _read_lock()
            if data and data[0] == os.getpid():
                os.unlink(_LOCK_PATH)
    except Exception:
        pass


def _acquire_singleton_or_exit() -> None:
    """
    Refuse to start if another menubar instance is already running.

    Prints a friendly message + the kill command and exits 0 (not 1)
    so the user's shell doesn't think it's an error.
    """
    import os as _os
    import time as _t

    existing = _read_lock()
    if existing is not None:
        pid, ts = existing
        age = _t.time() - ts
        if age <= _LOCK_MAX_AGE and _is_pid_alive(pid) and pid != _os.getpid():
            print(
                "CalFlow menubar is already running (PID {}).\n"
                "  • To stop it:    pkill -f 'cli.main menubar'\n"
                "  • To replace it: pkill -f 'cli.main menubar' && "
                "python -m cli.main menubar &"
                .format(pid),
                file=sys.stderr,
            )
            sys.exit(0)
        # Lock exists but is stale (pid dead or too old) — overwrite it.

    _write_lock()
    # Best-effort cleanup on normal exit. SIGKILL leaves it; the next
    # start sees stale lock and recovers.
    import atexit
    atexit.register(_release_lock)


# =========================================================
# 🧩 ENTRYPOINT
# =========================================================

def main() -> None:
    """Run the menubar app forever."""
    _acquire_singleton_or_exit()

    app = NSApplication.sharedApplication()
    # Accessory: no Dock icon, no app menu — pure menu bar.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    cf = _CFApp.alloc().init()
    if cf is None:
        print("[ERROR] Failed to construct menubar app.", file=sys.stderr)
        sys.exit(1)

    # Hold a reference so it isn't garbage-collected.
    globals()["_cf_app_singleton"] = cf

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
