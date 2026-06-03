"""
CalFlow menubar runtime assets (v1.3.0).

This package holds the static HTML/CSS/JS that `cli/menubar.py` loads
into a WKWebView. Nothing here is imported as Python — it's just
co-located with the rest of `runtime/` so the install layout is one
git tree.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CALENDAR_PLUS_SVG",
    "POPOVER_HTML",
    "RECIPES_HTML",
    "SETTINGS_HTML",
]

_HERE = Path(__file__).resolve().parent
POPOVER_HTML:  Path = _HERE / "popover.html"
RECIPES_HTML:  Path = _HERE / "recipes.html"
SETTINGS_HTML: Path = _HERE / "settings.html"
CALENDAR_PLUS_SVG: Path = _HERE / "icons" / "calflow-menubar-02-calendar-plus.svg"
