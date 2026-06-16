"""
CalFlow version — single source of truth.

Read by:
    cli/main.py        — `--version` flag, status dashboard
    cli/repl.py        — REPL banner
    setup.sh / install — package metadata (future)

Update on every release:
    1. bump __version__ here
    2. tag the commit (`git tag v<version>`)
    3. push tag

Format: PEP 440 (MAJOR.MINOR.PATCH).
"""

from __future__ import annotations

__version__ = "2.0.3"

# Stable release vs. work-in-progress flag. Toggle to True only on a
# tagged release; flip back to False on the next dev commit.
__is_release__ = False


def version_string() -> str:
    """Render `2.0.3` (or `2.0.3-dev` mid-cycle)."""
    return __version__ if __is_release__ else f"{__version__}-dev"
