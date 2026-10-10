"""String escaping for generated AppleScript, not user-authored scripts."""

from __future__ import annotations

__all__ = ["escape_applescript_string"]


def escape_applescript_string(value: str) -> str:
    """Escape literal contents; callers supply the surrounding double quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
