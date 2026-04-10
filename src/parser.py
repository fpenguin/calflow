import re
from settings import (
    BLACKLIST_REGEX,
    IGNORED_PROTOCOLS,
    DEFAULT_ALERT_SECONDS,
    MAX_URLS,
    IGNORE_BLACKLIST_FOR_TITLE_URLS,
    FORCE_URL_TAG,
    BLACKLIST_ONLY_IF_MULTIPLE,
    IGNORE_MAP_LINKS,
    MAP_DOMAINS,
)
from utils import log


# --- Regex ---
URL_PATTERN = re.compile(
    r'(?i)(https?://[^\s<>"\]]+|www\.[^\s<>"\]]+|\b[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s<>"\]]*)?)'
)
HASHTAG_PATTERN = re.compile(r'(?i)(#\w+)')
ALERT_PATTERN = re.compile(r"#alert=(\d+)([sm])", re.IGNORECASE)


# --- Helpers ---
def normalize_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]

    url = url.strip("<>.,)\"'")

    lowered = url.lower()

    if lowered.startswith(tuple(IGNORED_PROTOCOLS)):
        return None

    if url.startswith("www."):
        return "https://" + url

    if "." in url and not url.startswith("http"):
        return "https://" + url

    return url


def is_blacklisted(url):
    url_lower = url.lower()
    return any(re.search(pattern, url_lower) for pattern in BLACKLIST_REGEX)


def is_map_url(url):
    url_lower = url.lower()
    return any(domain in url_lower for domain in MAP_DOMAINS)


# --- Tag extraction ---
def extract_global_tags(text):
    return set(tag.lower() for tag in HASHTAG_PATTERN.findall(text or ""))


# --- Alert parsing ---
def extract_alert_offset(tags):
    for tag in tags:
        match = ALERT_PATTERN.match(tag)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            return value if unit == "s" else value * 60

    return DEFAULT_ALERT_SECONDS


# --- Core ---
def extract_url_entries(text, title=None):
    seen = set()
    entries = []

    text = text or ""

    # --- Count URLs (for conditional blacklist) ---
    all_raw_urls = URL_PATTERN.findall(text)
    total_url_count = len(all_raw_urls)

    # --- Title URLs (override support) ---
    title_urls = set()
    if title:
        for raw in URL_PATTERN.findall(title):
            url = normalize_url(raw)
            if url:
                title_urls.add(url)

    lines = text.splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line_lower = line.lower()

        # --- Skip protocol lines ---
        if any(line_lower.startswith(proto) for proto in IGNORED_PROTOCOLS):
            continue

        urls = URL_PATTERN.findall(line)
        tags = set(tag.lower() for tag in HASHTAG_PATTERN.findall(line))

        for raw_url in urls:
            url = normalize_url(raw_url)
            if not url:
                continue

            if url in seen:
                continue
            seen.add(url)

            # --- Force override ---
            is_forced = (
                (IGNORE_BLACKLIST_FOR_TITLE_URLS and url in title_urls)
                or (FORCE_URL_TAG in tags)
            )

            # --- Map filtering ---
            if IGNORE_MAP_LINKS and is_map_url(url) and not is_forced:
                log(f"🗺️ Ignored map URL: {url}")
                continue

            # --- Conditional blacklist ---
            apply_blacklist = True
            if BLACKLIST_ONLY_IF_MULTIPLE:
                apply_blacklist = total_url_count > 1

            if apply_blacklist and is_blacklisted(url) and not is_forced:
                log(f"🚫 Blacklisted: {url}")
                continue

            if is_forced:
                log(f"⚡ Forced: {url}")

            entries.append({
                "url": url,
                "tags": tags
            })

    # --- Limit URLs ---
    if len(entries) > MAX_URLS:
        log(f"⚠️ MAX_URLS={MAX_URLS}, trimming extra URLs")
        return entries[:MAX_URLS]

    return entries