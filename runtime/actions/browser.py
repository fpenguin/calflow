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

import subprocess
import webbrowser
import time
from typing import Optional, Dict

from core.utils import log


# =========================================================
# 🔧 PLATFORM DETECTION
# =========================================================

try:
    from AppKit import NSWorkspace  # noqa: F401
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

    Rule (v1.1.20):
      1. Explicit `new(window)` / `new(tab)` always wins.
      2. Otherwise: any layout / display tag implies window mode
         (because layout cannot be applied to a tab independently).
      3. Default: tab.

    `tags`     — iterable of `#tag` strings (mixed case OK)
    `functions`— iterable of (name, value) tuples from the parser
    """
    # 1. Explicit override
    if functions:
        for name, value in functions:
            if name == "new":
                s = str(value).strip().lower().strip("\"'")
                if s == "window":
                    return True
                if s == "tab":
                    return False
                log(
                    f"[WARN] new({value!r}) — expected new(window) or "
                    "new(tab); ignoring and using default"
                )

    # 2. Layout / display tag → window
    for t in tags or ():
        tl = str(t).lower()
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
) -> None:
    """
    Open one target (URL, app, or file) and optionally apply layout.

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
        return

    try:
        # Decide what `url` actually is.
        kind = _classify_primary(url) if url else None

        if kind == "url":
            _open_url(url, app, chrome_profile=chrome_profile,
                      new_window=new_window)
        elif kind == "file":
            _open_file(url)
        elif kind == "app":
            _open_app(_strip_quotes(url))
        elif app:
            # No primary → just launch the app
            _open_app(app)
        else:
            log(f"[WARN] open_target: could not classify primary {url!r}")
            return

        # Allow OS time to spawn window
        time.sleep(0.8)

        if layout or display_spec:
            # The window we'll be moving belongs to whichever app handled
            # the primary. For URLs that's the resolved browser; for app
            # primaries it's the app itself; for files it's the default
            # opener (best-effort — may not be scriptable).
            target_app = app if kind == "url" else (
                _strip_quotes(url) if kind == "app" else app
            )
            _apply_layout(target_app, layout, display_spec)

    except Exception as e:
        log(f"[ERROR] open_target failed: {e}")


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


def _open_url(
    url: str,
    app: Optional[str],
    *,
    chrome_profile: Optional[str] = None,
    new_window: bool = False,
) -> None:
    """
    Open URL in specified browser or fallback.

    v1.1.20 semantics for `new_window`:
        True  → guarantee the URL lands in a fresh BROWSER WINDOW
        False → default macOS behaviour (tab in existing window if any)

    Per-browser mechanics for `new_window=True`:
        Chromium (Chrome, Brave, Edge, Arc) — `-na <app> --args --new-window <url>`
                  (with `--profile-directory=…` appended for Chrome+profile)
        Safari   — AppleScript: `tell app "Safari" to make new document with properties {URL:…}`
        Firefox  — `-a Firefox --args --new-window <url>`
        anything else / unknown → fall back to `-na <app> <url>` (best-effort
                  new instance) and log [INFO] that we couldn't guarantee window mode.
    """
    # ── new_window=True path ─────────────────────────────────────────
    if new_window and app:
        try:
            if app in _CHROMIUM_BROWSERS:
                args = ["open", "-na", app, "--args", "--new-window"]
                if app == "Google Chrome" and chrome_profile:
                    args.append(f"--profile-directory={chrome_profile}")
                args.append(url)
                subprocess.run(args, check=False)
                log(
                    f"[INFO] Opened URL in {app} (new window"
                    f"{', ' + chrome_profile if app == 'Google Chrome' and chrome_profile else ''}"
                    f"): {url}"
                )
                return
            if app == "Safari":
                escaped = url.replace('"', '\\"')
                script = (
                    'tell application "Safari"\n'
                    '    activate\n'
                    f'    make new document with properties {{URL:"{escaped}"}}\n'
                    'end tell\n'
                )
                subprocess.run(["osascript", "-e", script], check=False)
                log(f"[INFO] Opened URL in Safari (new window): {url}")
                return
            if app == "Firefox":
                subprocess.run(
                    ["open", "-a", "Firefox", "--args", "--new-window", url],
                    check=False,
                )
                log(f"[INFO] Opened URL in Firefox (new window): {url}")
                return
            # Unknown browser — best-effort: -na (new instance)
            subprocess.run(["open", "-na", app, url], check=False)
            log(
                f"[INFO] Opened URL in {app} (-na fallback; "
                "new-window not guaranteed): {url}"
            )
            return
        except Exception as e:
            log(f"[WARN] new-window launch for {app} failed, falling back: {e}")

    # ── new_window=False (or no app) path ────────────────────────────
    if app == "Google Chrome" and chrome_profile:
        try:
            subprocess.run(
                ["open", "-na", "Google Chrome", "--args",
                 f"--profile-directory={chrome_profile}", url],
                check=False,
            )
            log(f"[INFO] Opened URL in Chrome ({chrome_profile}): {url}")
            return
        except Exception as e:
            log(f"[WARN] Chrome profile launch failed, fallback: {e}")

    if app:
        try:
            subprocess.run(["open", "-a", app, url], check=False)
            log(f"[INFO] Opened URL in {app}: {url}")
            return
        except Exception as e:
            log(f"[WARN] Failed to open in {app}, fallback: {e}")

    webbrowser.open(url)
    log(f"[INFO] Opened URL (default): {url}")


# =========================================================
# 📄 FILE HANDLING
# =========================================================

def _open_file(path: str) -> None:
    """Open a file with its OS-default app via `open <path>`."""
    import os
    expanded = os.path.expanduser(_strip_quotes(path))
    try:
        subprocess.run(["open", expanded], check=False)
        log(f"[INFO] Opened file: {expanded}")
    except Exception as e:
        log(f"[ERROR] Failed to open file {expanded!r}: {e}")


# =========================================================
# 🖥️ APP HANDLING
# =========================================================

def _open_app(app: str) -> None:
    """Launch macOS application by name (e.g. 'Google Chrome')."""
    try:
        subprocess.run(["open", "-a", app], check=False)
        log(f"[INFO] Opened app: {app}")
    except Exception as e:
        log(f"[ERROR] Failed to open app {app!r}: {e}")


# =========================================================
# 🪟 LAYOUT ENGINE (BEST-EFFORT)
# =========================================================

def _apply_layout(
    app_name: Optional[str],
    layout: Optional[Dict],
    display_spec=None,
) -> None:
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
        _impl(app_name, layout, display_spec)
    except Exception as e:
        log(f"[WARN] Layout failed: {e}")


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
                f"[WARN] {tag!r} uses the legacy grid order — canonical is "
                f"`#grid(<cell>@<cols>x<rows>)` (v1.1.19+). Interpreting as "
                f"#grid({m.group(3)}@{m.group(1)}x{m.group(2)})."
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
                log(f"[WARN] #area: bad coordinate(s) in {tag!r}")
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
            log(f"[WARN] Unrecognised layout tag {tag!r}{hint}")

    except Exception as e:
        log(f"[WARN] Failed to parse layout tag '{tag}': {e}")

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