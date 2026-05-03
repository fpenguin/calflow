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


# =========================================================
# 🪟 PER-WINDOW DISPLAY FILTER (v1.1.7 — hide display(N))
# =========================================================
#
# `hide display(N)` semantics: hide every visible non-background app
# whose frontmost window's CENTRE point falls inside display N's
# visibleFrame. Ties (window straddles two displays) go to the display
# the centre lands on.
#
# Requires Accessibility permission (System Events needs to read
# `position` and `size` of windows). If permission is missing the
# JXA call fails with -10003; we log the standard hint.

_JXA_HIDE_ON_DISPLAY = r"""
ObjC.import("AppKit");

function run(argv) {
    var dx = parseInt(argv[0], 10);
    var dy = parseInt(argv[1], 10);
    var dw = parseInt(argv[2], 10);
    var dh = parseInt(argv[3], 10);
    var keepArr = (argv[4] || "").split("").filter(function (s) { return s.length > 0; });
    var keep = {};
    for (var i = 0; i < keepArr.length; i++) keep[keepArr[i]] = true;

    var SE = Application("System Events");
    var procs = SE.processes.whose({ visible: true, backgroundOnly: false })();
    var frontmost = "";
    try {
        var fronts = SE.processes.whose({ frontmost: true })();
        if (fronts.length > 0) frontmost = fronts[0].name();
    } catch (e) {}

    var hid = [], kept = [], errored = [];

    // Probe Accessibility ONCE on the first non-trivial app. If reading
    // window geometry fails with the AX-permission signature, abort the
    // whole pass with a sentinel — no point in trying 30 more apps that
    // will all fail the same way.
    var axChecked = false;
    var axDenied = false;

    for (var i = 0; i < procs.length; i++) {
        if (axDenied) break;

        var p = procs[i];
        var name = "";
        try { name = p.name(); } catch (e) { continue; }
        if (!name) continue;

        if (name === frontmost || keep[name]) {
            kept.push(name);
            continue;
        }

        try {
            var wins = p.windows();
            var match = false;
            for (var w = 0; w < wins.length; w++) {
                var pos, sz;
                try {
                    pos = wins[w].position();
                    sz  = wins[w].size();
                    axChecked = true;
                } catch (e) {
                    var msg = (e && e.message) ? e.message : String(e);
                    if (msg.indexOf("assistive access") !== -1
                        || msg.indexOf("not allowed") !== -1
                        || msg.indexOf("-1719") !== -1
                        || msg.indexOf("-25204") !== -1) {
                        axDenied = true;
                        break;
                    }
                    continue;
                }
                if (!pos || !sz) continue;
                var cx = pos[0] + sz[0] / 2;
                var cy = pos[1] + sz[1] / 2;
                if (cx >= dx && cx < dx + dw && cy >= dy && cy < dy + dh) {
                    match = true;
                    break;
                }
            }
            if (axDenied) break;
            if (match) {
                p.visible = false;
                hid.push(name);
            } else {
                kept.push(name);
            }
        } catch (e) {
            errored.push(name + " (" + (e.message || e) + ")");
        }
    }

    if (axDenied) {
        return "AX_DENIED";
    }
    return "KEPT\t" + kept.join(", ") +
           "\nHIDDEN\t" + hid.join(", ") +
           "\nERRORED\t" + errored.join(", ");
}
"""


def hide_apps_on_display(
    display_target: Any,
    except_apps: List[str] = (),
) -> bool:
    """
    Hide every visible non-background app whose frontmost window's
    centre point falls within the requested display.

    `display_target` accepts the same shapes as `move_app_to_display`:
        int      → 1-based display index
        "ext"    → first external monitor
        str      → substring match against display name

    `except_apps` are kept visible; the frontmost is also always kept.

    Returns True iff the JXA call succeeded.
    """
    if display_target is None:
        log("[WARN] hide display(): missing target")
        return False

    # Translate into the resolver tuple shape, same as move_app_to_display.
    spec: Optional[Tuple[str, Any]]
    if isinstance(display_target, int):
        spec = ("index", display_target)
    elif isinstance(display_target, str):
        s = display_target.strip().lower()
        if s in ("", "ext", "external"):
            spec = ("external", None)
        elif s.isdigit():
            spec = ("index", int(s))
        else:
            spec = ("name", display_target)
    else:
        log(f"[WARN] hide display(): bad target {display_target!r}")
        return False

    displays = enumerate_displays()
    if not displays:
        log("[WARN] hide display(): no displays detected")
        return False

    target = resolve_display_target(spec, displays)
    if target is None:
        return False  # resolver already logged

    # The except-list is delimited with U+001F (information-separator-one)
    # because spaces / commas / hyphens can appear in macOS app names.
    keep_arg = "".join(a for a in except_apps if a)

    label = (
        f"HIDE display({target['index']}) [{target.get('name','?')}]"
        + (f" except {', '.join(except_apps)}" if except_apps else "")
    )

    try:
        result = subprocess.run(
            [
                "osascript", "-l", "JavaScript", "-e", _JXA_HIDE_ON_DISPLAY,
                str(target["x"]), str(target["y"]),
                str(target["w"]), str(target["h"]),
                keep_arg,
            ],
            capture_output=True, text=True, timeout=8,
        )
    except FileNotFoundError:
        log("[WARN] osascript not available — hide-on-display disabled")
        return False
    except Exception as exc:
        log(f"[WARN] {label} subprocess failed: {exc}")
        return False

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        log(f"[WARN] {label} failed: {stderr or '(no stderr)'}")
        if "not allowed" in stderr.lower() or "1002" in stderr or "-10003" in stderr:
            _log_accessibility_hint()
        return False

    stdout = (result.stdout or "").strip()

    # v1.1.8 — JXA short-circuited on Accessibility denial. Surface ONE
    # clear, actionable message instead of 30 'not allowed' lines.
    if stdout == "AX_DENIED" or stdout.startswith("AX_DENIED"):
        log(f"[ERROR] {label}: Accessibility permission denied for osascript.")
        _log_accessibility_hint()
        return False

    for line in stdout.splitlines():
        if "\t" in line:
            tag, _, names = line.partition("\t")
            log(f"[INFO] {label}: {tag.lower()} = [{names.strip() or '∅'}]")
    return True


def _log_accessibility_hint() -> None:
    """
    Print the canonical 'how to grant Accessibility permission'
    instruction. Used by every macOS UI-scripting path that needs
    AX attribute reads (hide_apps_on_display, future window-aware
    selectors, etc.).
    """
    log(
        "[INFO] Reading window geometry needs Accessibility for "
        "/usr/bin/osascript:"
    )
    log("[INFO]   1. Open System Settings → Privacy & Security → Accessibility")
    log("[INFO]   2. Click [+] and add /usr/bin/osascript (Cmd+Shift+G to type)")
    log("[INFO]   3. Toggle it ON")
    log(
        "[INFO]   (Note: granting Apple Events / Automation is NOT enough — "
        "AX attribute reads need the separate Accessibility grant.)"
    )


# =========================================================
# 🚚 MOVE APP TO DISPLAY (v1.1.2 — focus @app display(N))
# =========================================================

def move_app_to_display(
    app_name: str,
    display_target: Any,
) -> bool:
    """
    Activate `app_name` and move its frontmost window to the requested
    display. Used by `focus @app display(N|"name")` in Plus Mode.

    `display_target` accepts:
        - int      → 1-based display index
        - "ext"    → first external monitor
        - str      → substring match against display name

    Behavior:
        - looks up the display via `resolve_display_target`
        - logs and returns False if the display can't be resolved
        - sizes to the display's full visible frame (no inner layout)
        - per-window timeout enforced via subprocess timeout in
          set_window_bounds (~4s)

    Returns True iff the bounds-set succeeded.
    """
    if not app_name:
        log("[WARN] move_app_to_display: missing app name")
        return False
    if display_target is None:
        log("[WARN] move_app_to_display: missing display target")
        return False

    # Translate the parser-level display value into the resolver-level
    # tuple format that resolve_display_target expects.
    spec: Optional[Tuple[str, Any]]
    if isinstance(display_target, int):
        spec = ("index", display_target)
    elif isinstance(display_target, str):
        s = display_target.strip().lower()
        if s in ("", "ext", "external"):
            spec = ("external", None)
        elif s.isdigit():
            spec = ("index", int(s))
        else:
            spec = ("name", display_target)
    else:
        log(f"[WARN] move_app_to_display: bad target {display_target!r}")
        return False

    displays = enumerate_displays()
    if not displays:
        log("[WARN] move_app_to_display: no displays detected")
        return False

    target = resolve_display_target(spec, displays)
    if target is None:
        return False  # resolver already logged

    rect = (target["x"], target["y"], target["w"], target["h"])
    log(
        f"[INFO] move {app_name!r} → display {target['index']} "
        f"({target.get('name','?')}) @ {rect}"
    )
    return set_window_bounds(app_name, rect)
