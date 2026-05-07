"""
CalFlow Utilities (v2.0 — Smart Mode + Plus Mode)

Responsibilities:
- URL normalization & validation
- protocol & map filtering helpers
- time utilities
- safe string helpers
- lightweight token extraction (Smart Mode only)
- canonical logging entrypoint used across all layers

Design:
- deterministic
- side-effect free (except logging)
- reusable across parser/runtime
- does NOT contain business logic

Migration note (v1.0 → v2.0):
- The v1.0 module imported `settings` and `utils_logging` as top-level
  modules; neither exists in this repo, which left every importer of
  `core.utils.log` broken. This file now self-contains a `log()` and pulls
  config from the canonical `config.settings` package.
"""

from __future__ import annotations

import re
import sys
import time
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from config.settings import (
    IGNORE_MAP_LINKS,
    IGNORED_PROTOCOLS,
    LOG_MODE,
    MAP_DOMAINS,
)


# =========================================================
# 📝 LOGGING (canonical)
# =========================================================

def log(message: str) -> None:
    """
    Canonical CalFlow logger.

    Intentionally minimal: every layer (parser, resolver, executor,
    runtime/actions) calls `from core.utils import log`. Replacing the
    implementation here will redirect every log line in the system.

    Honors `config.settings.LOG_MODE`:
        - "stdout" → only stdout
        - "stderr" → only stderr
        - "both"   → stdout (kept simple — file logging is a v2.x concern)
    """
    if not message:
        return

    target = sys.stdout if LOG_MODE in ("stdout", "both") else sys.stderr
    try:
        print(message, file=target, flush=True)
    except Exception:
        # Logging must never raise.
        pass


# =========================================================
# 🌐 URL NORMALIZATION
# =========================================================

def normalize_url(url: str) -> Optional[str]:
    """
    Normalize a URL into a fully-qualified HTTPS URL.

    Rules:
        - strip whitespace & wrappers
        - ignore unsupported protocols
        - infer https for bare domains
    """
    if not url:
        return None

    url = url.strip().strip("<>.,)\"'")
    lower = url.lower()

    if lower.startswith(tuple(IGNORED_PROTOCOLS)):
        return None

    if "://" in url:
        return url

    if "." in url:
        return f"https://{url}"

    return None


# =========================================================
# ✅ URL VALIDATION
# =========================================================

def is_valid_url(url: str) -> bool:
    """Validate URL structure."""
    if not url or " " in url:
        return False

    if "://" in url:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)

    return bool(re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", url))


# =========================================================
# 🚫 FILTER HELPERS
# =========================================================

def is_ignored_protocol(url: str) -> bool:
    """Check if URL uses an ignored protocol."""
    return url.lower().startswith(tuple(IGNORED_PROTOCOLS))


def is_map_url(url: str) -> bool:
    """Detect map/navigation URLs."""
    if not IGNORE_MAP_LINKS:
        return False
    lower = url.lower()
    return any(domain in lower for domain in MAP_DOMAINS)


def should_process_url(url: str) -> bool:
    """High-level filter (protocol + map). Blacklist handled in parser."""
    if not url:
        return False
    if is_ignored_protocol(url):
        return False
    if is_map_url(url):
        return False
    return True


# =========================================================
# ⏱️ TIME UTILITIES
# =========================================================

def now_ts() -> float:
    """Return current timestamp (seconds)."""
    return time.time()


def seconds_until(timestamp: float) -> float:
    """Return seconds until timestamp (can be negative)."""
    return timestamp - now_ts()


def within_window(target_ts: float, window_seconds: float) -> bool:
    """Check if now is within window before target."""
    delta = seconds_until(target_ts)
    return 0 <= delta <= window_seconds


# =========================================================
# 🔤 SAFE STRING HELPERS
# =========================================================

def safe_strip(value: Optional[str]) -> str:
    """Safely strip string."""
    return value.strip() if isinstance(value, str) else ""


def lower_safe(value: Optional[str]) -> str:
    """Safely lowercase."""
    return value.lower() if isinstance(value, str) else ""


# =========================================================
# 🧠 SMART MODE TOKEN EXTRACTION
# =========================================================

def extract_tokens(line: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Extract Smart Mode tokens from a single line.

    Returns:
        (url, target, tags)
    """
    if not line:
        return None, None, []

    parts = line.split()

    url: Optional[str] = None
    target: Optional[str] = None
    tags: List[str] = []

    for part in parts:
        if part.startswith("@"):
            target = part
        elif part.startswith("#"):
            tags.append(part)
        elif url is None:
            url = part

    return url, target, tags


# =========================================================
# 💬 COMMENT HELPER (canonical)
# =========================================================

def strip_inline_comment(line: str) -> str:
    """
    Remove `## …` from the end of `line` when the `##` sits at top
    level — i.e. NOT inside a quoted string ("…", '…'), parenthesized
    group, square-bracketed collection, or curly-braced dynamic block.

    Behavior:
        - whole-line comment (`## blah`)        → returns ""
        - inline comment    (`open x ## blah`)  → returns "open x"
        - protected by quotes / brackets        → returns line unchanged
        - no `##` at all                        → returns line unchanged

    Examples:
        strip_inline_comment('open x.com  ## a comment')
            → 'open x.com'
        strip_inline_comment('type("hello ## world")')
            → 'type("hello ## world")'
        strip_inline_comment('save to("~/x_{now > YYYY ## not_a_comment}.png")')
            → unchanged (## is inside both ()s and {}s)

    Used by the Smart parser, Plus parser, and validator so the comment
    rule is single-sourced.
    """
    if not line:
        return line

    quote = ""
    paren = brace = bracket = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "{":
            brace += 1
        elif ch == "}":
            brace = max(0, brace - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        elif (
            ch == "#"
            and i + 1 < n
            and line[i + 1] == "#"
            and not (paren or brace or bracket)
        ):
            return line[:i].rstrip()
        i += 1
    return line


# =========================================================
# 🧪 DEBUG / LOGGING
# =========================================================

def debug(msg: str) -> None:
    """Debug helper (non-blocking)."""
    log(f"[DEBUG] {msg}")
