"""
CalFlow Browser & App Launcher (v2.0)

Responsibilities:
- Open URLs in specific browsers (or default)
- Launch native macOS applications
- Apply window layout (best-effort)

Design Principles:
- deterministic execution
- best-effort (never crash)
- no parsing logic (inputs must be pre-resolved)
- layout applied AFTER open
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'open_target',
    'parse_layout_tag',
    'wants_new_window',
]

import subprocess
import sys
import webbrowser
import time
from typing import Optional, Dict

from core.utils import log
from runtime.actions._applescript import escape_applescript_string


_LAUNCH_TIMEOUT_SECONDS = 10


# =========================================================
# 🔧 PLATFORM DETECTION
# =========================================================

try:
    from AppKit import NSWorkspace
    from Foundation import NSBundle, NSURL
    MAC_AVAILABLE = True
except ImportError:
    MAC_AVAILABLE = False


# =========================================================
# 🪟 NEW-WINDOW DECISION (v1.1.20)
# =========================================================

# Tag prefixes that imply window-level control. Their presence flips
# the `new(window)` default ON because layout / display tags are
# meaningless for a tab — you can't position a tab independently of
# the window it lives in. `#profile` is NOT in this list: profile is a
# session selector, not a placement modifier, and the existing -na
# path keeps its current behaviour for back-compat.
_WINDOW_TRIGGER_PREFIXES = (
    "#left", "#right", "#middle", "#top", "#bottom", "#full",
    "#grid(", "#area(", "#display",
)


def wants_new_window(tags=None, functions=None) -> bool:
    """
    Compute whether an open should force a NEW WINDOW vs land in a tab.

    Rule (v1.1.22):
      1. Explicit Plus-mode `new(window)` / `new(tab)` function call wins.
      2. Explicit tag `#window` / `#new-window` / `#tab` / `#new-tab`
         wins (for Smart Mode + the # drop sugar in Plus Mode).
      3. Otherwise: any layout / display tag implies window mode
         (because layout cannot be applied to a tab independently).
      4. Default: tab.

    `tags`     — iterable of `#tag` strings (mixed case OK)
    `functions`— iterable of (name, value) tuples from the parser
    """
    tag_set = {str(t).lower() for t in (tags or ())}

    # 1. Explicit Plus-mode function call
    if functions:
        for name, value in functions:
            if name == "new":
                s = str(value).strip().lower().strip("\"'")
                if s == "window":
                    return True
                if s == "tab":
                    return False
                log(
                    "[WARN] Invalid new mode; expected new(window) or "
                    "new(tab); ignoring and using default"
                )

    # 2. Explicit tag override (v1.1.22 — works in Smart + Plus)
    if tag_set & {"#window", "#new-window"}:
        return True
    if tag_set & {"#tab", "#new-tab"}:
        return False

    # 3. Layout / display tag → window
    for tl in tag_set:
        for prefix in _WINDOW_TRIGGER_PREFIXES:
            if tl == prefix.rstrip("(") or tl.startswith(prefix):
                return True
    return False


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def open_target(
    url: Optional[str] = None,
    app: Optional[str] = None,
    layout: Optional[Dict] = None,
    display_spec=None,
    *,
    chrome_profile: Optional[str] = None,
    new_window: bool = False,
) -> bool:
    """
    Open one target (URL, app, or file) and optionally apply layout.

    Returns True only when launch and any requested layout succeed.
    Unresolvable window-control requests fail before launching.

    The `url` parameter holds the **primary** of an OPEN command, which
    can be any of:
        - a real URL (`https://…`)
        - an app name (`Google Chrome`)
        - a file path (`~/file.pdf`, `/Users/foo/x.txt`, `./script.sh`)

    Dispatch is by primary type, not by hardcoded "URL or app" split.

    Args:
        url:            primary string (URL / app name / file path)
        app:            optional macOS browser to route a URL through
        layout:         normalized layout dict from parse_layout_tag()
        display_spec:   target display from core.resolver.resolve_display()
        chrome_profile: optional Chrome --profile-directory value
                        ("Default", "Profile 1", "Profile 2", …)
        new_window:     v1.1.20 — when True, force the URL into a fresh
                        browser window (--new-window for Chromium,
                        AppleScript for Safari, --new-window for Firefox).
                        When False, macOS default behaviour applies
                        (typically a new tab in an existing window).
    """
    if not url and not app:
        log("[WARN] open_target: no primary or app provided")
        return False

    try:
        # Decide what `url` actually is.
        kind = _classify_primary(url) if url else None
        needs_layout = layout is not None or display_spec is not None
        if kind == "url" and not app and (needs_layout or new_window or chrome_profile):
            app = _resolve_default_browser(url)
            if app is None:
                return False
        target_app = app if kind == "url" else (
            _strip_quotes(url) if kind == "app" else (app if kind is None else None)
        )
        if needs_layout and not target_app:
            log("[WARN] OPEN layout target unavailable; specify a supported app or browser")
            return False

        if kind == "url":
            opened = _open_url(url, app, chrome_profile=chrome_profile,
                               new_window=new_window)
        elif kind == "file":
            opened = _open_file(url)
        elif kind == "app":
            opened = _open_app(_strip_quotes(url))
        elif app:
            # No primary → just launch the app
            opened = _open_app(app)
        else:
            log("[WARN] open_target: could not classify primary")
            return False

        if not opened:
            return False

        # Allow OS time to spawn window
        time.sleep(0.8)

        if needs_layout:
            return _apply_layout(target_app, layout, display_spec)
        return True

    except Exception as e:
        log(f"[ERROR] open_target failed: {type(e).__name__}")
        return False


# =========================================================
# 🔍 PRIMARY CLASSIFICATION
# =========================================================

# A primary is a "URL" if it has a scheme (`x://`) or looks like a
# bare domain (`example.com`, `localhost:8080`). A primary is a "file"
# if it starts with `~`, `/`, or `./`. Anything else (typically a
# bare quoted string like "Google Chrome") is an app name.
_URL_HAS_SCHEME = _re_compile = __import__("re").compile(r"^\s*[a-z][a-z0-9+\-.]*://", __import__("re").IGNORECASE)
_URL_BARE_DOMAIN = __import__("re").compile(r"^\s*[a-z0-9.\-]+\.[a-z]{2,}", __import__("re").IGNORECASE)
_FILE_PATH = __import__("re").compile(r'^\s*"?(?:~|/|\./)')


def _classify_primary(text: str) -> str:
    """Return one of 'url' | 'file' | 'app' for an OPEN primary."""
    if not text:
        return "app"
    bare = _strip_quotes(text)
    if _URL_HAS_SCHEME.match(bare) or _URL_BARE_DOMAIN.match(bare):
        return "url"
    if _FILE_PATH.match(text):  # check ORIGINAL — quotes preserved
        return "file"
    if _FILE_PATH.match(bare):
        return "file"
    return "app"


def _strip_quotes(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if (t.startswith('"') and t.endswith('"')) or (
        t.startswith("'") and t.endswith("'")
    ):
        return t[1:-1]
    return t


# =========================================================
# 🌐 URL HANDLING
# =========================================================

_CHROMIUM_BROWSERS = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Arc")


def _resolve_default_browser(url: str) -> Optional[str]:
    """Resolve a supported URL handler without opening any app or window."""
    if not MAC_AVAILABLE:
        log("[WARN] Default browser cannot be resolved; specify a supported browser")
        return None
    try:
        lookup_url = _strip_quotes(url)
        if not _URL_HAS_SCHEME.match(lookup_url):
            lookup_url = "https://" + lookup_url
        app_url = NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(
            NSURL.URLWithString_(lookup_url)
        )
        bundle = NSBundle.bundleWithURL_(app_url) if app_url is not None else None
        identifier = bundle.bundleIdentifier() if bundle is not None else None
        app = {
            "com.apple.Safari": "Safari",
            "com.google.Chrome": "Google Chrome",
            "com.brave.Browser": "Brave Browser",
            "com.microsoft.edgemac": "Microsoft Edge",
            "company.thebrowser.Browser": "Arc",
            "org.mozilla.firefox": "Firefox",
        }.get(identifier)
        if app:
            return app
    except Exception as exc:
        log(f"[WARN] Default browser lookup failed ({type(exc).__name__}); specify a browser")
        return None
    log("[WARN] Default browser does not support window control; specify a supported browser")
    return None


def _run_launch(args: list[str]) -> bool:
    result = subprocess.run(
        args, check=False, capture_output=True, text=True,
        timeout=_LAUNCH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        log(f"[WARN] Launch command failed (exit {result.returncode})")
        return False
    return True


def _open_url(
    url: str,
    app: Optional[str],
    *,
    chrome_profile: Optional[str] = None,
    new_window: bool = False,
) -> bool:
    """
    Open URL in the specified browser, or the OS default when no app is given.
    Explicit browser/profile failures are not retried in a different context.

    v1.1.20 semantics for `new_window`:
        True  → guarantee the URL lands in a fresh BROWSER WINDOW
        False → default macOS behaviour (tab in existing window if any)

    Per-browser mechanics for `new_window=True`:
        Chromium (Chrome, Brave, Edge, Arc) — `-na <app> --args --new-window <url>`
                  (with `--profile-directory=…` appended for Chrome+profile)
        Safari   — AppleScript: `tell app "Safari" to make new document with properties {URL:…}`
        Firefox  — `-a Firefox --args --new-window <url>`
        anything else / unknown -> fail before launching; no window guarantee.
    """
    if not app and (new_window or chrome_profile):
        app = _resolve_default_browser(url)
        if app is None:
            return False
    if chrome_profile and app != "Google Chrome":
        log("[WARN] Requested profile requires Google Chrome; specify that browser")
        return False

    # ── new_window=True path ─────────────────────────────────────────
    if new_window and app:
        try:
            if app in _CHROMIUM_BROWSERS:
                args = ["open", "-na", app, "--args", "--new-window"]
                if app == "Google Chrome" and chrome_profile:
                    args.append(f"--profile-directory={chrome_profile}")
                args.append(url)
                if not _run_launch(args):
                    return False
                log("[INFO] Opened URL in requested browser (new window)")
                return True
            if app == "Safari":
                escaped = escape_applescript_string(url)
                script = (
                    'tell application "Safari"\n'
                    '    activate\n'
                    f'    make new document with properties {{URL:"{escaped}"}}\n'
                    'end tell\n'
                )
                if not _run_launch(["osascript", "-e", script]):
                    return False
                log("[INFO] Opened URL in Safari (new window)")
                return True
            if app == "Firefox":
                if not _run_launch(["open", "-a", "Firefox", "--args", "--new-window", url]):
                    return False
                log("[INFO] Opened URL in Firefox (new window)")
                return True
            log("[WARN] New-window guarantee unsupported; specify a supported browser")
            return False
        except Exception as e:
            log(f"[WARN] New-window launch failed ({type(e).__name__}); check browser installation")
            return False

    # ── new_window=False (or no app) path ────────────────────────────
    if app == "Google Chrome" and chrome_profile:
        try:
            if not _run_launch(
                ["open", "-na", "Google Chrome", "--args",
                 f"--profile-directory={chrome_profile}", url],
            ):
                return False
            log("[INFO] Opened URL in requested Chrome profile")
            return True
        except Exception as e:
            log(f"[WARN] Chrome profile launch failed: {type(e).__name__}")
            return False

    if app:
        try:
            if not _run_launch(["open", "-a", app, url]):
                return False
            log("[INFO] Opened URL in requested browser")
            return True
        except Exception as e:
            log(f"[WARN] Browser launch failed ({type(e).__name__}); check browser installation")
            return False

    if sys.platform == "darwin":
        if not _run_launch(["open", url]):
            return False
    elif not webbrowser.open(url):
        log("[WARN] Default browser failed to open URL")
        return False
    log("[INFO] Opened URL (default)")
    return True


# =========================================================
# 📄 FILE HANDLING
# =========================================================

def _open_file(path: str) -> bool:
    """Open a file with its OS-default app via `open <path>`."""
    import os
    expanded = os.path.expanduser(_strip_quotes(path))
    try:
        if not _run_launch(["open", expanded]):
            return False
        log("[INFO] Opened file")
        return True
    except Exception as e:
        log(f"[ERROR] Failed to open file: {type(e).__name__}")
        return False


# =========================================================
# 🖥️ APP HANDLING
# =========================================================

def _open_app(app: str) -> bool:
    """Launch macOS application by name (e.g. 'Google Chrome')."""
    try:
        if not _run_launch(["open", "-a", app]):
            return False
        log("[INFO] Opened app")
        return True
    except Exception as e:
        log(f"[ERROR] App launch failed ({type(e).__name__}); check app installation")
        return False


# =========================================================
# 🪟 LAYOUT ENGINE (BEST-EFFORT)
# =========================================================

def _apply_layout(
    app_name: Optional[str],
    layout: Optional[Dict],
    display_spec=None,
) -> bool:
    """
    Apply window layout for `app_name` via runtime.actions.window.

    Real macOS implementation lives in window.py — this wrapper exists
    so the executor doesn't need to import the window module directly
    and so unit tests can monkey-patch this symbol.
    """
    try:
        # Local import keeps the dependency edge inside this function:
        # importing window.py at module load would mean it's imported
        # by every Smart Mode dispatch even when no layout is requested.
        from runtime.actions.window import apply_layout as _impl
        return _impl(app_name, layout, display_spec)
    except Exception as e:
        log(f"[WARN] Layout failed ({type(e).__name__}); check target window and display")
        return False


# =========================================================
# 🧩 TAG → LAYOUT PARSER
# =========================================================

_LAYOUT_NAMES = ("left", "right", "middle", "top", "bottom", "full")

# v1.1.19 — grid grammar:
#   CANONICAL : #grid(D @ NxM)   D = 1-indexed cell (row-major), NxM = cols × rows
#   FALLBACK  : #grid(NxM @ D)   old form (pre-v1.1.19), accepted with [WARN]
import re as _re
_GRID_RE_CANON = _re.compile(
    r"^#grid\(\s*(\d+)\s*@\s*(\d+)\s*x\s*(\d+)\s*\)$", _re.IGNORECASE
)
_GRID_RE_LEGACY = _re.compile(
    r"^#grid\(\s*(\d+)\s*x\s*(\d+)\s*@\s*(\d+)\s*\)$", _re.IGNORECASE
)

# #area(x,y,w,h)  — pixel default; '%'-suffixed values are relative; mixed allowed.
_AREA_RE = _re.compile(r"^#area\(([^)]*)\)$", _re.IGNORECASE)


def parse_layout_tag(tag: str) -> Optional[Dict]:
    """
    Convert layout tag → normalized layout dict.

    Strict grammar (validation §3.3): a layout tag is either
        #<name>            (bare; defaults to 50% — except #full → 100%)
        #<name>(<arg>)     (parenthesized argument)

    Supported variants (DSL_GRAMMAR §9):
        #left(50%)            → {"type": "left",  "value": 0.5}
        #right(30)            → {"type": "right", "value": 0.3}
        #full                 → {"type": "full",  "value": 1.0}
        #middle / #top / #bottom — same shape as #left
        #grid(1@3x2)          → {"type": "grid",  "cell": 1, "cols": 3, "rows": 2}
        #grid(3x2@1)          → fallback (legacy order); same dict, [WARN] logged
        #area(0,0,1920,1080)  → {"type": "area",  "x": ..., "y": ..., "w": ..., "h": ...}
        #area(0,0,50%,50%)    → percentage components (mixed units allowed)

    Anything else (`#left30`, `#leftish`, …) → None + [WARN].
    """
    if not tag:
        return None

    try:
        tag_lower = tag.lower().strip()

        # ---- #grid(D@NxM) ─ canonical (v1.1.19+) --------------------
        m = _GRID_RE_CANON.match(tag_lower)
        if m:
            return {
                "type": "grid",
                "cell": int(m.group(1)),
                "cols": int(m.group(2)),
                "rows": int(m.group(3)),
            }

        # ---- #grid(NxM@D) ─ legacy fallback (pre-v1.1.19) -----------
        m = _GRID_RE_LEGACY.match(tag_lower)
        if m:
            log(
                "[WARN] Legacy grid order; prefer #grid(<cell>@<cols>x<rows>)"
            )
            return {
                "type": "grid",
                "cols": int(m.group(1)),
                "rows": int(m.group(2)),
                "cell": int(m.group(3)),
            }

        # ---- #area(x,y,w,h) -----------------------------------------
        m = _AREA_RE.match(tag_lower)
        if m:
            inner = m.group(1).strip()
            if not inner:
                return None
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) != 4:
                log(f"[WARN] #area expects 4 args (x,y,w,h); got {len(parts)}")
                return None
            coords = [_parse_area_value(p) for p in parts]
            if any(c is None for c in coords):
                log("[WARN] #area: invalid coordinates; use numeric pixel or percent values")
                return None
            return {
                "type": "area",
                "x": coords[0],
                "y": coords[1],
                "w": coords[2],
                "h": coords[3],
            }

        # ---- relative layouts ---------------------------------------
        for name in _LAYOUT_NAMES:
            if tag_lower == f"#{name}":
                return {
                    "type": name,
                    "value": 1.0 if name == "full" else _parse_percent(tag_lower),
                }
            if tag_lower.startswith(f"#{name}("):
                if name == "full":
                    return {"type": "full", "value": 1.0}
                return {"type": name, "value": _parse_percent(tag_lower)}

        # ---- v1.1.19 — surface unrecognised layout-shaped tags ------
        # If the tag looks like one of our layout names (so the user
        # clearly INTENDED a layout) but didn't match any of the regexes
        # above, log a WARN with a hint instead of silently dropping it.
        layout_prefixes = ("#grid(", "#area(") + tuple(f"#{n}(" for n in _LAYOUT_NAMES)
        if any(tag_lower.startswith(p) for p in layout_prefixes):
            hint = ""
            if tag_lower.startswith("#grid("):
                hint = " — expected `#grid(<cell>@<cols>x<rows>)`, e.g. #grid(1@3x2)"
            elif tag_lower.startswith("#area("):
                hint = " — expected `#area(x,y,w,h)` (4 comma-separated values)"
            log(f"[WARN] Unrecognised layout tag{hint}")

    except Exception as e:
        log(f"[WARN] Layout parsing failed ({type(e).__name__}); check layout syntax")

    return None


def _parse_area_value(token: str) -> Optional[Dict]:
    """
    Parse one #area component into {value: float, unit: 'pixel'|'percent'}.

    Negative values are normalized to 0 (validation §6.6).
    """
    if not token:
        return None
    is_pct = token.endswith("%")
    raw = token.rstrip("%").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0:
        value = 0.0
    return {"value": value, "unit": "percent" if is_pct else "pixel"}


# =========================================================
# 🔢 VALUE PARSING
# =========================================================

def _parse_percent(tag: str) -> float:
    """
    Extract percentage from layout tag.

    Examples:
        #left(50%) → 0.5
        #right(30) → 0.3
        #left      → 0.5

    Rules:
        - default = 50%
        - unitless = %
        - clamped to [0.0, 1.0]
    """

    if "(" not in tag:
        return 0.5

    raw = tag.split("(", 1)[1].replace(")", "").strip()

    if raw.endswith("%"):
        raw = raw[:-1]

    try:
        value = float(raw)
    except ValueError:
        return 0.5

    return max(0.0, min(1.0, value / 100.0))
