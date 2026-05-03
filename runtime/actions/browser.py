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
# 🚀 PUBLIC API
# =========================================================

def open_target(
    url: Optional[str] = None,
    app: Optional[str] = None,
    layout: Optional[Dict] = None,
    display_spec=None,
) -> None:
    """
    Open a URL or application and optionally apply layout.

    Args:
        url:          normalized URL (e.g. https://example.com)
        app:          macOS app name (e.g. "Google Chrome")
        layout:       normalized layout dict from parse_layout_tag()
        display_spec: target display from core.resolver.resolve_display()

    Constraints:
        - exactly one of (url, app) should be provided
        - layout / display_spec are best-effort only
    """
    if not url and not app:
        log("[WARN] open_target: no url or app provided")
        return

    try:
        if url:
            _open_url(url, app)
        else:
            _open_app(app)

        # Allow OS time to spawn window
        time.sleep(0.8)

        if layout or display_spec:
            _apply_layout(app, layout, display_spec)

    except Exception as e:
        log(f"[ERROR] open_target failed: {e}")


# =========================================================
# 🌐 URL HANDLING
# =========================================================

def _open_url(url: str, app: Optional[str]) -> None:
    """
    Open URL in specified browser or fallback.

    Resolution:
        1. app provided → open via macOS `open -a`
        2. fallback → default browser

    Constraint:
        - url must already be normalized
    """

    if app:
        try:
            subprocess.run(["open", "-a", app, url], check=False)
            log(f"[INFO] Opened URL in {app}: {url}")
            return
        except Exception as e:
            log(f"[WARN] Failed to open in {app}, fallback: {e}")

    # Fallback → default browser
    webbrowser.open(url)
    log(f"[INFO] Opened URL (default): {url}")


# =========================================================
# 🖥️ APP HANDLING
# =========================================================

def _open_app(app: str) -> None:
    """
    Launch macOS application.

    Constraint:
        - app must be a valid macOS application name
    """

    try:
        subprocess.run(["open", "-a", app], check=False)
        log(f"[INFO] Opened app: {app}")

    except Exception as e:
        log(f"[ERROR] Failed to open app '{app}': {e}")


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

# #grid(NxM@D)  — N cols × M rows, occupy cell D (1-indexed, row-major).
import re as _re
_GRID_RE = _re.compile(r"^#grid\(\s*(\d+)\s*x\s*(\d+)\s*@\s*(\d+)\s*\)$", _re.IGNORECASE)

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
        #grid(3x2@1)          → {"type": "grid",  "cols": 3, "rows": 2, "cell": 1}
        #area(0,0,1920,1080)  → {"type": "area",  "x": ..., "y": ..., "w": ..., "h": ...}
        #area(0,0,50%,50%)    → percentage components (mixed units allowed)

    Anything else (`#left30`, `#leftish`, …) → None.
    """
    if not tag:
        return None

    try:
        tag_lower = tag.lower().strip()

        # ---- #grid(NxM@D) -------------------------------------------
        m = _GRID_RE.match(tag_lower)
        if m:
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