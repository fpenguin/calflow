"""
Calendar description normalization (v2.0.10).

Google Calendar lets users type rich-text descriptions and returns
them in HTML form. We see things like:

    <p>+CalFlow+</p><p>open <a href="https://x.com">https://x.com</a></p>
    …<br>open @safari<br>…
    &lt;tag&gt; (HTML-encoded angles)
    &nbsp; (non-breaking space)

Without normalization, the parser:
  - never sees `+CalFlow+` on its own line (no \\n between tags)
  - extracts URLs OK (regex already handles <a href> bodies)
  - but can't see the line structure → mode detection + per-line
    tag extraction silently fail

This module is a pure-stdlib helper (no google libs) so it can be
unit-tested without the API client's heavy dependency tree.
"""

from __future__ import annotations

import html
import re
from typing import Optional


_BLOCK_TAGS = re.compile(
    r"</?(?:br|p|div|li|tr|h[1-6]|blockquote|pre)\s*/?>",
    re.IGNORECASE,
)
_LINK_TAG = re.compile(
    r'<a\b[^>]*?\bhref="([^"]+)"[^>]*?>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_ANY_TAG = re.compile(r"<[^>]+>")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_MULTI_BLANK = re.compile(r"\n{3,}")


def normalize_description(text: Optional[str]) -> Optional[str]:
    """
    Strip HTML and decode entities so the parser sees plain text.

    - <br>, <p>, <div>, <li>, <tr>, <hN>, <blockquote>, <pre> → newline
    - <a href="URL">TEXT</a> → "URL" if TEXT == URL, else "URL TEXT"
    - all other tags → stripped
    - HTML entities → decoded (`&lt;` → `<`, `&amp;` → `&`,
      `&nbsp;` → NBSP, `&#43;` → `+`, etc.)
    - trailing whitespace per line → trimmed
    - 3+ consecutive newlines → collapsed to 2

    Idempotent: safe to call on already-plain text.
    Returns input unchanged when None or empty.
    """
    if not text:
        return text
    s = text

    # Skip the HTML pipeline if there's nothing to strip — but still
    # run the whitespace cleanup so plain text gets the same treatment.
    if "<" in s or "&" in s:
        # 1. <a href="URL">TEXT</a> → "URL" or "URL TEXT"
        def _link_repl(m: re.Match) -> str:
            url = m.group(1).strip()
            inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if not inner or inner == url:
                return url
            return f"{url} {inner}"

        s = _LINK_TAG.sub(_link_repl, s)
        # 2. Block-level tags → newline
        s = _BLOCK_TAGS.sub("\n", s)
        # 3. Strip every remaining tag
        s = _ANY_TAG.sub("", s)
        # 4. Decode HTML entities
        s = html.unescape(s)

    # 5. Whitespace cleanup (always)
    s = _TRAILING_SPACE.sub("\n", s)
    s = _MULTI_BLANK.sub("\n\n", s)

    return s.strip()
