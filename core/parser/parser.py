"""
CalFlow Parser Dispatcher (v2.0).

Responsibilities:
- detect execution mode (Smart vs Plus) — document-wide
- route to correct parser engine
- provide a single entry point for the rest of the system
- preserve the v1.0 callable surface
  (`extract_url_entries`, `extract_tags`, `extract_alert_offset`)

Pipeline (per call):
    text → mode-detect → dispatch → ParseResult

Design:
- deterministic
- extensible
- zero business logic (only routing + assembly)
- exceptions never escape — they become empty ParseResults
"""

from __future__ import annotations

from typing import Optional

from core.models import (
    MODE_NONE,
    MODE_PLUS,
    MODE_SMART,
    ParseResult,
)
from core.utils import log
from core.parser.plus_parser import is_plus_header, parse_plus
from core.parser.smart_parser import (
    extract_alert_offset as _smart_extract_alert_offset,
)
from core.parser.smart_parser import (
    extract_tags as _smart_extract_tags,
)
from core.parser.smart_parser import (
    extract_url_entries as _smart_extract_url_entries,
)


# ---------------------------------------------------------------------------
# 🔁 BACKWARD-COMPAT RE-EXPORTS (v1.0 surface)
# ---------------------------------------------------------------------------

extract_url_entries = _smart_extract_url_entries
extract_tags = _smart_extract_tags
extract_alert_offset = _smart_extract_alert_offset


# ---------------------------------------------------------------------------
# 🧠 MODE DETECTION
# ---------------------------------------------------------------------------

def is_plus_mode(text: str) -> bool:
    """
    A document is Plus Mode iff `+CalFlow+` appears as a standalone line
    ANYWHERE in the doc (DSL_GRAMMAR §1.2, parser-behavior §2.4).
    """
    return is_plus_header(text)


# ---------------------------------------------------------------------------
# 🚀 PUBLIC API — UNIFIED PARSE
# ---------------------------------------------------------------------------

def parse(text: str, title: Optional[str] = None) -> ParseResult:
    """
    Unified parser entrypoint. Never None, never raises.

    v1.1.21 — when `text` is empty, we no longer short-circuit to
    MODE_NONE. The smart parser's v1.1.17 title-URL extraction fires
    on the title argument alone, so an event with a URL ONLY in its
    title (and an empty body) still produces a Smart-Mode entry.
    """
    if not text and not title:
        return ParseResult(mode=MODE_NONE)

    text = text or ""

    try:
        if is_plus_mode(text):
            commands, errors = parse_plus(text)
            return ParseResult(
                mode=MODE_PLUS,
                commands=commands,
                errors=errors,
            )

        entries = _smart_extract_url_entries(text, title=title)
        global_tags = frozenset(_smart_extract_tags(text))
        return ParseResult(
            mode=MODE_SMART,
            entries=entries,
            global_tags=global_tags,
        )

    except Exception as exc:  # pragma: no cover
        log(f"[ERROR] Parser failed: {exc}")
        return ParseResult(mode=MODE_NONE)


__all__ = [
    "extract_alert_offset",
    "extract_tags",
    "extract_url_entries",
    "is_plus_mode",
    "parse",
]
