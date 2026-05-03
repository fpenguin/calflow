"""
CalFlow window control (v2.0.4).

Multi-display-aware window placement that runs through plain
`osascript` (which ships with macOS). No `pyobjc`. No accessibility
permission required for what we do here.

Two macOS surfaces are used:
    1. JXA (JavaScript for Automation) → reads NSScreen for display
       enumeration (origin, size, name, primary flag, builtin flag).
    2. Plain AppleScript → sets `bounds of window 1` of the target
       application.

Public API:
    enumerate_displays()                              → List[Display]
    resolve_display_target(spec, displays)            → Optional[Display]
    compute_rect(layout, display)                     → (x, y, w, h)
    apply_layout(app_name, layout, display_spec=None) → None
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from core.utils import log


# =========================================================
# 🧱 TYPES (informal — we use plain dicts for portability)
# =========================================================
# A Display dict has these keys:
#     index    int    1-based index in NSScreen.screens
#     name     str    NSScreen.localizedName
#     x, y     int    visibleFrame origin (global coordinate space)
#     w, h     int    visibleFrame size (excludes menu bar + Dock)
#     primary  bool   True iff index == 1 (NSScreen.mainScreen)
#     builtin  bool   heuristic — name starts with 'Built-in'
#     external bool   True iff not builtin


# =========================================================
# 🔍 ENUMERATION (JXA + NSScreen)
# =========================================================

# Cache the JXA result to avoid spawning osascript on every command.
_DISPLAY_CACHE: Optional[Tuple[float, List[Dict]]] = None
_DISPLAY_CACHE_TTL = 30.0  # seconds


#
# COORDINATE-SYSTEM NOTE (this matters!):
#
# `NSScreen.visibleFrame` returns rects in COCOA coordinates:
#     - origin (0, 0) is at the BOTTOM-LEFT of the primary display
#     - y is positive going UP
#     - secondary displays sit at offsets relative to that origin
#
# `tell application "X" to set bounds of window 1 to {x1,y1,x2,y2}`
# uses AppleScript's TOP-LEFT global coordinates:
#     - origin (0, 0) is at the TOP-LEFT of the primary display
#     - y is positive going DOWN
#
# For the PRIMARY display the two systems happen to produce identical
# numbers (origin 0,0 either way) so the bug is invisible on a single-
# display setup. For any external display positioned anywhere except
# "perfectly bottom-aligned with the primary's bottom edge", the
# Cocoa y-value ends up out of range when interpreted as AppleScript-
# global, and macOS responds by clamping the requested bounds to fit
# the primary display — producing 'window only as tall as the laptop'.
#
# We do the conversion right here in JXA so the rest of the pipeline
# can stay coordinate-system-agnostic:
#
#     y_top_left = primary_h - cocoa_y - height
#
_JXA_ENUM = r"""
ObjC.import("AppKit");
var screens   = $.NSScreen.screens;
var main      = $.NSScreen.mainScreen;
var primaryH  = main.frame.size.height;     // Cocoa height of mainScreen
var out       = [];
for (var i = 0; i < screens.js.length; i++) {
    var s    = screens.js[i];
    var f    = s.visibleFrame;              // Cocoa coords (bottom-left, y↑)
    var name = ObjC.unwrap(s.localizedName) || ("Display " + (i + 1));
    var isMain = ObjC.unwrap(s.isEqual(main));

    // Convert Cocoa → AppleScript top-left global:
    //   x stays the same
    //   y = primaryH - cocoaY - h
    var xTL = Math.round(f.origin.x);
    var yTL = Math.round(primaryH - f.origin.y - f.size.height);

    out.push({
        index:    i + 1,
        name:     name,
        x:        xTL,
        y:        yTL,
        w:        Math.round(f.size.width),
        h:        Math.round(f.size.height),
        primary:  !!isMain,
        builtin:  name.toLowerCase().indexOf("built-in") === 0
    });
}
JSON.stringify(out);
"""


def enumerate_displays(*, force_refresh: bool = False) -> List[Dict]:
    """
    Return the list of connected displays (cached).

    Each entry: {index, name, x, y, w, h, primary, builtin, external}.
    Returns [] on any failure (logged).
    """
    global _DISPLAY_CACHE
    now = time.time()
    if (
        not force_refresh
        and _DISPLAY_CACHE is not None
        and now - _DISPLAY_CACHE[0] < _DISPLAY_CACHE_TTL
    ):
        return _DISPLAY_CACHE[1]

    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA_ENUM],
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        log("[WARN] osascript not available — display enumeration disabled")
        _DISPLAY_CACHE = (now, [])
        return []
    except Exception as exc:
        log(f"[WARN] enumerate_displays subprocess failed: {exc}")
        _DISPLAY_CACHE = (now, [])
        return []

    if result.returncode != 0 or not result.stdout.strip():
        log(f"[WARN] enumerate_displays JXA error: "
            f"rc={result.returncode} stderr={result.stderr.strip()!r}")
        _DISPLAY_CACHE = (now, [])
        return []

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log(f"[WARN] enumerate_displays JSON parse failed: {exc}")
        _DISPLAY_CACHE = (now, [])
        return []

    displays: List[Dict] = []
    for d in raw:
        d["external"] = not bool(d.get("builtin"))
        displays.append(d)

    _DISPLAY_CACHE = (now, displays)
    return displays


# =========================================================
# 🎯 #display TAG → DISPLAY TARGET
# =========================================================

# `spec` is the output of core.resolver.resolve_display(tags):
#     None                       — no #display tag → use primary
#     ("external", None)         — #display / #display() / #display(ext) etc.
#     ("index",    N)            — #display(N)  (1-based; no fallback)
#     ("name",     "Samsung")    — #display("…") (substring; no fallback)

DisplaySpec = Optional[Tuple[str, Any]]


def resolve_display_target(
    spec: DisplaySpec,
    displays: List[Dict],
) -> Optional[Dict]:
    """
    Resolve a display SPEC into a concrete Display dict.

    Returns None when the spec asked for something specific that
    doesn't exist (`#display(5)` with 3 displays / `#display("foo")`
    with no match) — callers should treat this as 'skip layout'.

    For "external" with no externals connected, falls back to primary.
    """
    if not displays:
        log("[WARN] no displays detected; layout skipped")
        return None

    primary = next((d for d in displays if d.get("primary")), displays[0])

    if spec is None:
        return primary

    kind, val = spec

    if kind == "external":
        externals = [d for d in displays if d.get("external")]
        if not externals:
            log("[WARN] #display: no external monitor connected; using primary")
            return primary
        if len(externals) > 1:
            names = ", ".join(d["name"] for d in externals)
            log(
                f"[WARN] #display: multiple externals ({names}); "
                f"picked {externals[0]['name']!r}; "
                f"use #display(\"name\") to disambiguate"
            )
        return externals[0]

    if kind == "index":
        n = int(val)
        if 1 <= n <= len(displays):
            return displays[n - 1]
        log(
            f"[WARN] #display({n}): only {len(displays)} display(s) "
            f"connected; layout skipped"
        )
        return None

    if kind == "name":
        needle = str(val).lower()
        for d in displays:
            if needle in (d.get("name") or "").lower():
                return d
        log(
            f"[WARN] #display({val!r}): no display matches; "
            f"layout skipped"
        )
        return None

    log(f"[WARN] resolve_display_target: unknown spec {spec!r}")
    return None


# =========================================================
# 📐 LAYOUT → RECT (display-relative)
# =========================================================

def compute_rect(layout: Dict, display: Dict) -> Tuple[int, int, int, int]:
    """
    Compute the (x, y, w, h) global-coordinate-space rect for `layout`
    inside `display`. `layout` is the dict produced by
    runtime.actions.browser.parse_layout_tag.
    """
    dx, dy, dw, dh = (
        int(display["x"]), int(display["y"]),
        int(display["w"]), int(display["h"]),
    )
    t = layout.get("type")

    if t == "full":
        return (dx, dy, dw, dh)

    if t in ("left", "right", "middle", "top", "bottom"):
        v = float(layout.get("value", 0.5))
        v = max(0.0, min(1.0, v))
        if t == "left":
            return (dx, dy, int(dw * v), dh)
        if t == "right":
            x = dx + dw - int(dw * v)
            return (x, dy, int(dw * v), dh)
        if t == "middle":
            w = int(dw * v)
            x = dx + (dw - w) // 2
            return (x, dy, w, dh)
        if t == "top":
            return (dx, dy, dw, int(dh * v))
        if t == "bottom":
            h = int(dh * v)
            y = dy + dh - h
            return (dx, y, dw, h)

    if t == "grid":
        cols = max(1, int(layout.get("cols", 1)))
        rows = max(1, int(layout.get("rows", 1)))
        cell = max(1, int(layout.get("cell", 1)))
        cw = dw // cols
        ch = dh // rows
        idx = cell - 1
        col = idx % cols
        row = idx // cols
        return (dx + col * cw, dy + row * ch, cw, ch)

    if t == "area":
        x_v = _resolve_unit(layout.get("x"), dw, base=dx)
        y_v = _resolve_unit(layout.get("y"), dh, base=dy)
        w_v = _resolve_unit(layout.get("w"), dw, base=0)
        h_v = _resolve_unit(layout.get("h"), dh, base=0)
        return (x_v, y_v, max(1, w_v), max(1, h_v))

    log(f"[WARN] compute_rect: unsupported layout type {t!r}")
    return (dx, dy, dw, dh)


def _resolve_unit(spec: Any, axis_size: int, *, base: int = 0) -> int:
    """Convert {"value": N, "unit": "pixel"|"percent"} → int (display-relative)."""
    if spec is None:
        return base
    if isinstance(spec, dict):
        v = float(spec.get("value", 0))
        unit = spec.get("unit", "pixel")
        return base + (int(round(axis_size * v / 100.0)) if unit == "percent" else int(v))
    try:
        return base + int(spec)
    except Exception:
        return base


# =========================================================
# 🪟 SET WINDOW BOUNDS (AppleScript)
# =========================================================

def set_window_bounds(app_name: str, rect: Tuple[int, int, int, int]) -> bool:
    """
    Resize+position the FRONTMOST window of `app_name` to `rect`.

    Returns True iff the AppleScript subprocess returned 0.
    Best-effort: any failure is logged and False is returned;
    the calling pipeline continues.
    """
    x, y, w, h = rect
    x2, y2 = x + w, y + h
    safe = (app_name or "").replace('"', '\\"')
    script = (
        f'tell application "{safe}"\n'
        f'    activate\n'
        f'    if (count of windows) > 0 then\n'
        f'        set bounds of window 1 to {{{x}, {y}, {x2}, {y2}}}\n'
        f'    end if\n'
        f'end tell\n'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=4,
        )
    except FileNotFoundError:
        log("[WARN] osascript not available — cannot apply window layout")
        return False
    except Exception as exc:
        log(f"[WARN] set_window_bounds subprocess failed: {exc}")
        return False

    if result.returncode != 0:
        log(
            f"[WARN] set_window_bounds({app_name!r}, {rect}) failed: "
            f"{result.stderr.strip() or '(no stderr)'}"
        )
        return False
    return True


# =========================================================
# 🚀 PUBLIC ENTRY
# =========================================================

def apply_layout(
    app_name: Optional[str],
    layout: Optional[Dict],
    display_spec: DisplaySpec = None,
) -> None:
    """
    Apply `layout` (and optionally a #display target) to the
    frontmost window of `app_name`.

    Arguments:
        app_name      — macOS app name ("Google Chrome", "Safari", …).
                        If None, no layout is applied (we don't know
                        which window to move).
        layout        — dict from parse_layout_tag(); None means no
                        relative/grid/area layout was requested.
        display_spec  — output of core.resolver.resolve_display(tags).

    Behavior matrix:
        layout=None, display=None  → no-op
        layout=None, display=set   → move to display origin (no resize)
        layout=set,  display=None  → apply layout on primary display
        layout=set,  display=set   → apply layout on resolved display

    Best-effort: any failure logs `[WARN]` and returns silently.
    """
    if app_name is None:
        if layout or display_spec:
            log("[WARN] apply_layout called without an app name; skipping")
        return

    if layout is None and display_spec is None:
        return

    displays = enumerate_displays()
    if not displays:
        return

    target = resolve_display_target(display_spec, displays)
    if target is None:
        # The user asked for a specific display that doesn't exist.
        # Per spec: skip the layout entirely (no fallback).
        return

    if layout is None:
        # Just move the window to the chosen display, no resize.
        rect = (target["x"], target["y"], target["w"], target["h"])
    else:
        rect = compute_rect(layout, target)

    set_window_bounds(app_name, rect)
