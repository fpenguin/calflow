"""
CalFlow Smart Mode Parser (v2.0).

Responsible for:
- extracting URLs
- normalizing URLs
- extracting tags
- filtering (protocol, map, blacklist)
- producing execution entries
- maintaining Smart Mode global modifier state across lines
  (DSL_SPEC §2.2, parser-behavior §4.2)

Design:
- deterministic
- non-blocking
- idempotent
- back-compat: `extract_url_entries(text, title)` returns the same
  shape it always did (List[Dict]) — but with global state merged
  into each entry's tags
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from config.settings import (
    BLACKLIST_ONLY_IF_MULTIPLE,
    BLACKLIST_REGEX,
    DEFAULT_ALERT_SECONDS,
    FORCE_FILL_TAG,
    FORCE_SUBMIT_TAG,
    FORCE_URL_TAG,
    IGNORE_BLACKLIST_FOR_TITLE_URLS,
    IGNORE_MAP_LINKS,
    IGNORED_PROTOCOLS,
    MAP_DOMAINS,
    MAX_URLS,
    NO_AUTOFILL_TAG,
    TITLE_URL_AUTOFILL_DEFAULT,
    TITLE_URL_OPEN_DEFAULT,
)
from core.utils import log, strip_inline_comment


# =========================================================
# 🔎 REGEX
# =========================================================

# URL char class: anything except whitespace, angle brackets, quotes,
# square/curly brackets. We then allow EMBEDDED `{…}` dynamic blocks
# (which may themselves contain whitespace) by alternating chunks +
# braced groups. This lets Smart Mode handle URLs like
#   https://report.com?date={now > YYYY-MM-DD}
# without breaking at the inner whitespace.
_URL_CHARS = r'[^\s<>"\]\[{}]+'
_URL_DYNAMIC = r'\{[^{}]*\}'
_URL_BODY = rf'(?:{_URL_CHARS}|{_URL_DYNAMIC})+'

URL_PATTERN = re.compile(
    rf'(?i)(https?://{_URL_BODY}|www\.{_URL_BODY}|\b[a-z0-9.-]+\.[a-z]{{2,}}(?:/{_URL_BODY})?)'
)
EMAIL_PATTERN = re.compile(
    r"(?i)[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)

# Single `#…`; `##` is a comment and must be filtered before this matches.
#
# Tag forms supported:
#     #name                          (bare)
#     #name(arg)                     (parenthesized — arg may include
#                                     identifiers, % numbers, commas, @,
#                                     /, etc.)
#     #name("arg with spaces")       (parenthesized — quoted string, may
#                                     contain spaces — used by
#                                     #display("Samsung S90D") )
HASHTAG_PATTERN = re.compile(
    r'(?<!#)(#[\w][\w\-=%.,@/]*'
    r'(?:\((?:"[^"]*"|[^)]*)\))?)'
)
TARGET_PATTERN = re.compile(r'(?<!\w)(@[\w][\w\-]*)')
ALERT_PATTERN = re.compile(r"#alert=(\d+)([sm])", re.IGNORECASE)


def _find_urls(text: str) -> List[str]:
    """Return URL-like matches, excluding bare domains inside email addresses."""
    if not text:
        return []

    email_spans = [match.span() for match in EMAIL_PATTERN.finditer(text)]
    urls: List[str] = []

    for match in URL_PATTERN.finditer(text):
        start, end = match.span(1)
        if any(email_start <= start and end <= email_end for email_start, email_end in email_spans):
            continue
        urls.append(match.group(1))

    return urls


# =========================================================
# 🌐 URL NORMALIZATION
# =========================================================

def normalize_url(raw_url: str) -> Optional[str]:
    if not raw_url:
        return None

    url = raw_url.strip()

    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]

    url = url.strip("<>.,)\"'")
    lowered = url.lower()

    if lowered.startswith(tuple(IGNORED_PROTOCOLS)):
        return None

    if url.startswith("www."):
        return f"https://{url}"

    if "." in url and not url.startswith("http"):
        return f"https://{url}"

    return url


# =========================================================
# 🚫 FILTERS
# =========================================================

def is_blacklisted(url: str) -> bool:
    url_lower = url.lower()
    return any(re.search(pattern, url_lower) for pattern in BLACKLIST_REGEX)


def is_map_url(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in MAP_DOMAINS)


# =========================================================
# 🏷️ TAGS / TARGETS
# =========================================================

def _strip_comments(text: str) -> str:
    """Remove inline `## …` comments from every line in `text`."""
    if not text:
        return text
    return "\n".join(strip_inline_comment(line) for line in text.splitlines())


def extract_tags(text: str) -> Set[str]:
    """All `#tags` from text, lowercased; `##` comments stripped first."""
    if not text:
        return set()
    return {t.lower() for t in HASHTAG_PATTERN.findall(_strip_comments(text))}


def extract_targets(text: str) -> List[str]:
    """All `@target` tokens from text, lowercased, in order of appearance."""
    if not text:
        return []
    return [t.lower() for t in TARGET_PATTERN.findall(_strip_comments(text))]


# =========================================================
# ⏱️ ALERT
# =========================================================

def extract_alert_offset(tags) -> int:
    """
    Look for `#alert=<N>(s|m)` inside any of the supplied tags.
    Accepts either set/frozenset of tag strings or a list of strings.
    """
    if not tags:
        return DEFAULT_ALERT_SECONDS
    for tag in tags:
        match = ALERT_PATTERN.match(tag)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            return value if unit == "s" else value * 60
    return DEFAULT_ALERT_SECONDS


# =========================================================
# 🧠 LINE CLASSIFICATION
# =========================================================

def _is_global_modifier_line(line: str) -> bool:
    """
    A line is a global modifier line iff it contains no URL and consists
    only of `#tags` and `@targets` (and whitespace).
    """
    if not line:
        return False
    if _find_urls(line):
        return False
    tokens = [t for t in line.split() if t]
    if not tokens:
        return False
    return all(t.startswith("#") or t.startswith("@") for t in tokens)


def _tag_category(tag: str) -> str:
    """
    Map a tag string to a category label so 'same category → last wins'
    (DSL_SPEC §2.2, parser-behavior §6.2) is enforceable.
    """
    name = tag.lstrip("#")
    if "(" in name:
        name = name.split("(", 1)[0]
    if "=" in name:
        name = name.split("=", 1)[0]
    name = name.lower()

    if name in {"left", "right", "middle", "top", "bottom", "full", "area", "grid"}:
        return "layout"
    if name == "display":
        return "display"
    if name == "profile":
        return "session"
    if name in {"fill", "submit", "slow", "no-autofill", "force"}:
        return "behavior"
    if name == "alert":
        return "alert"
    return f"tag:{name}"  # unique per arbitrary tag


# =========================================================
# 🚀 MAIN PARSER
# =========================================================

def extract_url_entries(text: str, title: Optional[str] = None) -> List[Dict]:
    """
    Parse Smart Mode text into executable entries.

    Behavior (spec-aligned):
        - lines starting with `##` are comments, ignored
        - standalone tag/target lines establish persistent global state
          that is merged into every subsequent URL line
        - same-category global modifier → last wins
        - different category → merged
        - URL lines (`<url> [@target] [#tags...]`) become entries
        - protocol/map/blacklist filtering preserved from v1.0
    """
    # Strip `##` comments line-by-line BEFORE any URL/tag scanning so
    # they don't pollute counts, blacklist heuristics, or extraction.
    text = _strip_comments(text or "")
    entries: List[Dict] = []
    seen: Set[str] = set()

    # Pre-scan total URL count for blacklist semantics
    raw_urls = _find_urls(text)
    total_url_count = len(raw_urls)

    # --- Title override URLs (whitelist) --------------------------------
    title_urls: Set[str] = set()
    if title:
        for raw in _find_urls(title):
            normalized = normalize_url(raw)
            if normalized:
                title_urls.add(normalized)

    # --- Global state (Smart Mode only) ---------------------------------
    # Map of category → tag (last write wins).
    global_tags_by_cat: Dict[str, str] = {}
    global_target: Optional[str] = None  # @ alias

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Standalone modifier line → updates global state, no execute
        if _is_global_modifier_line(line):
            for tag in HASHTAG_PATTERN.findall(line):
                global_tags_by_cat[_tag_category(tag)] = tag.lower()
            tgts = TARGET_PATTERN.findall(line)
            if tgts:
                global_target = tgts[-1].lower()
            log(f"[INFO] Smart global update: {line}")
            continue

        # Skip lines starting with ignored protocols (sip:, tel:, …)
        if any(line.lower().startswith(proto) for proto in IGNORED_PROTOCOLS):
            continue

        # Per-line tags + URL
        line_tags = {t.lower() for t in HASHTAG_PATTERN.findall(line)}
        line_targets = [t.lower() for t in TARGET_PATTERN.findall(line)]

        for raw_url in _find_urls(line):
            url = normalize_url(raw_url)
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)

            # Merge global state into per-line tags (same category → line wins)
            line_categories = {_tag_category(t) for t in line_tags}
            merged_tags: Set[str] = set(line_tags)
            for cat, gtag in global_tags_by_cat.items():
                if cat not in line_categories:
                    merged_tags.add(gtag)

            # Target: line takes precedence over global
            entry_target = line_targets[0] if line_targets else global_target
            if entry_target:
                merged_tags.add(entry_target)

            # Forced URL semantics
            is_forced = (
                (IGNORE_BLACKLIST_FOR_TITLE_URLS and url in title_urls)
                or (FORCE_URL_TAG in merged_tags)
            )

            # Map filtering
            if IGNORE_MAP_LINKS and is_map_url(url) and not is_forced:
                log(f"[INFO] Ignored map URL: {url}")
                continue

            # Blacklist
            apply_blacklist = True
            if BLACKLIST_ONLY_IF_MULTIPLE:
                apply_blacklist = total_url_count > 1
            if apply_blacklist and is_blacklisted(url) and not is_forced:
                log(f"[WARN] Blacklisted: {url}")
                continue

            if is_forced:
                log(f"[INFO] Forced URL: {url}")

            entries.append({"url": url, "tags": merged_tags})

    # --- v1.1.17 — Title URLs become implicit entries (Option B) --------
    # v1.1.22 — title URLs now also get configurable autofill + open-mode
    # defaults via TITLE_URL_AUTOFILL_DEFAULT and TITLE_URL_OPEN_DEFAULT.
    # See config/settings.py for the rationale.
    #
    # The per-URL dedup (vs the body's `seen` set) means a URL that
    # appears in BOTH title and body opens exactly once — and the body
    # entry wins (it has line-level tags), so the title-URL defaults
    # don't override an explicit body line.
    for turl in title_urls:
        if turl in seen:
            continue
        seen.add(turl)

        merged_tags = set(global_tags_by_cat.values())
        if global_target:
            merged_tags.add(global_target)

        # v1.1.22 — autofill default for title URLs
        already_set_autofill = bool(
            merged_tags & {FORCE_FILL_TAG, FORCE_SUBMIT_TAG, NO_AUTOFILL_TAG}
        )
        if not already_set_autofill:
            af = (TITLE_URL_AUTOFILL_DEFAULT or "").strip().lower()
            if af == "submit":
                merged_tags.add(FORCE_SUBMIT_TAG)
            elif af == "fill":
                merged_tags.add(FORCE_FILL_TAG)
            elif af == "none":
                merged_tags.add(NO_AUTOFILL_TAG)
            # any other value: silently fall through to AUTOFILL_MODE default

        # v1.1.22 — open-mode default for title URLs.
        # Layout/display tag presence ALREADY implies window via
        # wants_new_window — only act here when no such tag is set
        # AND the user hasn't explicitly tagged #window/#tab somewhere.
        layout_prefixes = (
            "#left", "#right", "#middle", "#top", "#bottom", "#full",
            "#grid(", "#area(", "#display",
        )
        has_layout = any(
            any(t.lower().startswith(p) for p in layout_prefixes)
            for t in merged_tags
        )
        has_explicit_open = bool(
            merged_tags & {"#window", "#new-window", "#tab", "#new-tab"}
        )
        if not has_layout and not has_explicit_open:
            om = (TITLE_URL_OPEN_DEFAULT or "").strip().lower()
            if om == "window":
                merged_tags.add("#window")
            elif om == "tab":
                merged_tags.add("#tab")
            # any other value: silently fall through to global default (tab)

        log(f"[INFO] Title URL → entry: {turl}")
        entries.append({"url": turl, "tags": merged_tags})

    if len(entries) > MAX_URLS:
        log("[WARN] MAX_URLS exceeded → trimming")
        return entries[:MAX_URLS]

    return entries


# =========================================================
# 🧪 INTROSPECTION (for the dispatcher)
# =========================================================

def smart_global_state(text: str) -> Tuple[Dict[str, str], Optional[str]]:
    """
    Return (global_tags_by_category, global_target) WITHOUT executing.
    Used by the dispatcher / REPL for debug display.
    """
    if not text:
        return {}, None

    cats: Dict[str, str] = {}
    target: Optional[str] = None
    for raw in text.splitlines():
        line = strip_inline_comment(raw).strip()
        if not line:
            continue
        if not _is_global_modifier_line(line):
            continue
        for tag in HASHTAG_PATTERN.findall(line):
            cats[_tag_category(tag)] = tag.lower()
        tgts = TARGET_PATTERN.findall(line)
        if tgts:
            target = tgts[-1].lower()
    return cats, target
