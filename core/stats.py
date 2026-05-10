"""
CalFlow lifetime stats — pure functions (v1.3.0).

Single source of truth for:
- ACTION_WEIGHTS — per-action-type seconds saved
- format_time_saved() — human-readable "21h 14m"
- compute_time_saved() — sum a `by_type` map into seconds

This module is IO-free. Persistence lives in `state/stats_store.py`.

Why this lives in `core/` and not `runtime/`:
The menubar reads stats; the executors write stats; tests assert on
formatting. None of that is runtime side-effects, so the formula belongs
in `core/` next to the rest of the business logic.

Action weight rationale (each is the manual time CalFlow saves you):
    open_url       5s   open URL in default browser (Cmd+T + paste + Enter)
    open_profile   8s   open URL in specific browser/profile (extra menu clicks)
    arrange        4s   drag-snap a window to a half/grid cell
    hide           2s   Cmd+H or click-away
    focus          1s   Cmd+Tab cycle
    autofill       8s   1Password / iCloud Keychain lookup + paste
    screenshot     3s   Cmd+Shift+4 + drag + click
    wait           0s   doesn't save user time; not counted

Users can override the weights by setting STATS_ACTION_WEIGHTS in
`config/settings.py` (a partial dict; missing keys fall back to the
defaults below). See docs/menubar.md.
"""

from __future__ import annotations

# v1.3.0 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    "ACTION_WEIGHTS",
    "compute_time_saved",
    "format_time_saved",
    "resolve_weights",
]

from typing import Dict, Mapping


# =========================================================
# ⚖️ DEFAULT WEIGHTS
# =========================================================
#
# Keep these conservative. The goal of the stat is "honestly suggestive,"
# not "maximally impressive." Users who feel the default undersells their
# situation can dial up via STATS_ACTION_WEIGHTS in settings.

ACTION_WEIGHTS: Dict[str, int] = {
    "open_url":     5,
    "open_profile": 8,
    "arrange":      4,
    "hide":         2,
    "focus":        1,
    "autofill":     8,
    "screenshot":   3,
    "wait":         0,
}


# =========================================================
# 🔢 COMPUTATION
# =========================================================

def resolve_weights() -> Dict[str, int]:
    """
    Resolve the active weight table.

    Reads `STATS_ACTION_WEIGHTS` from settings if present (a partial
    dict of overrides) and merges over the defaults. Missing keys keep
    their default; unknown keys are ignored (we never extend the
    weight surface from settings — that requires a code change).
    """
    try:
        from config.settings import STATS_ACTION_WEIGHTS  # type: ignore[attr-defined]
        overrides = STATS_ACTION_WEIGHTS or {}
    except Exception:
        overrides = {}

    merged = dict(ACTION_WEIGHTS)
    for key, val in overrides.items():
        if key in merged and isinstance(val, (int, float)) and val >= 0:
            merged[key] = int(val)
    return merged


def compute_time_saved(by_type: Mapping[str, int]) -> int:
    """
    Sum (count × weight) across all action types.

    Args:
        by_type: mapping of action key → execution count

    Returns:
        total seconds saved (int)

    Unknown keys in `by_type` are silently ignored (forward-compat:
    if a future executor records a new verb before the weight table
    knows about it, we don't crash — we just don't credit it yet).
    """
    weights = resolve_weights()
    total = 0
    for key, count in by_type.items():
        if not isinstance(count, (int, float)) or count <= 0:
            continue
        weight = weights.get(key)
        if weight is None:
            continue
        total += int(count) * int(weight)
    return total


# =========================================================
# 🖼 FORMATTING
# =========================================================

def format_time_saved(seconds: int) -> str:
    """
    Render seconds as a compact human string for the menubar stats card.

    Boundaries:
        0          → "0m"
        <60        → "<1m"
        <3600      → "{m}m"
        <86400     → "{h}h {m}m"     (omit "0m" → just "{h}h")
        ≥86400     → "{d}d {h}h"     (omit "0h" → just "{d}d")

    Examples:
        format_time_saved(0)      → "0m"
        format_time_saved(45)     → "<1m"
        format_time_saved(60)     → "1m"
        format_time_saved(120)    → "2m"
        format_time_saved(3600)   → "1h"
        format_time_saved(3660)   → "1h 1m"
        format_time_saved(76410)  → "21h 14m"
        format_time_saved(90000)  → "1d 1h"
        format_time_saved(172800) → "2d"

    Negative or non-int values are clamped to 0.
    """
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        secs = 0
    if secs <= 0:
        return "0m"
    if secs < 60:
        return "<1m"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h" if m == 0 else f"{h}h {m}m"
    d, rem = divmod(secs, 86400)
    h = rem // 3600
    return f"{d}d" if h == 0 else f"{d}d {h}h"
