"""
CalFlow Executor (v2.0 — Smart Mode)

Responsibilities:
- execute parsed + resolved entries
- apply runtime sequencing (open → autofill → delay)
- substitute `{…}` dynamic blocks in URLs before opening
- isolate execution logic from main runtime

Design:
- deterministic
- non-blocking
- stateless (no persistence here)
"""

import time
from typing import Dict, List, Set

# Dynamic substitution (v2.0)
from core.dynamic import resolve_dynamic

# Resolver
from core.resolver import (
    resolve_autofill,
    resolve_chrome_profile,
    resolve_delay,
    resolve_display,
    resolve_layout,
    resolve_target,
)

# Actions
from runtime.actions.autofill import trigger_autofill
from runtime.actions.browser import open_target

# Settings
from config.settings import (
    AUTOFILL_BUFFER,
    POST_AUTOFILL_DELAY,
)

# Utils
from core.utils import log


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def execute_entries(
    entries: List[Dict],
    global_tags: Set[str],
    debug: bool = False,
) -> None:
    """
    Execute parsed Smart Mode entries.

    Args:
        entries: output from parser
        global_tags: extracted from event-level text
        debug: enable verbose logging

    Behavior:
        For each entry:
            resolve → open → autofill → delay
    """

    for entry in entries:
        try:
            _execute_single(entry, global_tags, debug)

        except Exception as e:
            # Never break execution pipeline
            log(f"[ERROR] Entry execution failed: {e}")


# =========================================================
# 🔁 SINGLE ENTRY EXECUTION
# =========================================================

def _execute_single(
    entry: Dict,
    global_tags: Set[str],
    debug: bool,
) -> None:
    """
    Execute a single Smart Mode entry.

    Steps:
        1. merge tags
        2. resolve execution parameters
        3. open target
        4. optional autofill
        5. stabilization delay
    """

    url = entry.get("url")
    entry_tags = entry.get("tags", set())

    # Resolve `{…}` dynamic blocks in the URL (v2.0).
    # Done at execute time (not parse time) so timestamps reflect the
    # actual moment of execution, not the moment the description was read.
    if url:
        url = resolve_dynamic(url)

    # IMPORTANT: do NOT merge `global_tags` here. In v2.0 the Smart
    # parser already merges true Smart Mode global state (standalone
    # tag/target lines) into each entry's `tags` set. Re-merging the
    # block-wide `extract_tags(text)` here would pull every #tag from
    # every URL line into every entry — cross-contaminating per-line
    # layouts (e.g. `#left(70%)` and `#right(30%)` both ending up in
    # both entries, then `resolve_layout` non-deterministically picks
    # whichever the set iteration yields last).
    tags = set(entry_tags)

    if debug:
        log(f"[DEBUG] URL: {url}")
        log(f"[DEBUG] Tags: {sorted(tags)}")

    # =====================================================
    # 🔧 RESOLVE
    # =====================================================

    app = resolve_target(tags)
    layout = resolve_layout(tags)
    display_spec = resolve_display(tags)
    delay = resolve_delay(tags)
    should_fill, should_submit = resolve_autofill(tags)
    chrome_profile = resolve_chrome_profile(tags)
    # v1.1.20 — layout/display tags imply new window in Smart Mode too
    from runtime.actions.browser import wants_new_window
    new_win = wants_new_window(tags=tags)

    # =====================================================
    # 🌐 OPEN
    # =====================================================

    open_target(
        url=url,
        app=app,
        layout=layout,
        display_spec=display_spec,
        chrome_profile=chrome_profile,
        new_window=new_win,
    )

    # =====================================================
    # ⏳ BUFFER (page load)
    # =====================================================

    time.sleep(AUTOFILL_BUFFER)

    # =====================================================
    # 🔑 AUTOFILL
    # =====================================================

    if should_fill:
        trigger_autofill(mode="fill")

        if should_submit:
            trigger_autofill(mode="submit")

        time.sleep(POST_AUTOFILL_DELAY)

    # =====================================================
    # ⏱️ STABILIZATION
    # =====================================================

    time.sleep(delay)