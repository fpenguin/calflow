"""
Regression: per-line tags do NOT leak into other entries (v2.0.5+).

Bug story
---------
v1.0 had no per-line global state, so `cli/main.py` extracted every
#tag from the whole event description and the Smart executor merged
that polluted set into every entry's tags:

    tags = global_tags | entry_tags          # ← pollution

In v2.0 the parser already merges true Smart Mode global modifiers
(standalone tag/target lines) into each entry's tag set. Continuing
to merge `extract_tags(text)` in the executor caused entries to
inherit every #tag from every URL line — so a description like:

    https://a.com @safari #right(30%)
    https://b.com @chrome #left(70%) #fill

…produced both URLs with `{#right(30%), #left(70%), #fill, …}`.
`resolve_layout` then iterated the set non-deterministically and the
LAST-WINS rule picked one layout for both entries.

This file pins the v2.0.5 contract: per-entry tags stay per-entry.

Run:
    python -m unittest tests.test_v2_no_cross_contamination -v
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import extract_tags, parse


# =============================================================
# Parser layer — confirms the parser ALREADY did the right thing
# =============================================================

class ParserPerLineTags(unittest.TestCase):
    """Per-line layout tags must NOT leak across entries."""

    def test_two_urls_with_opposite_layouts(self):
        text = (
            "https://a.com @safari #right(30%)\n"
            "https://b.com @chrome #left(70%) #fill\n"
        )
        result = parse(text)
        self.assertEqual(len(result.entries), 2)

        a, b = result.entries
        # entry 0 must have ONLY its own layout
        self.assertIn("#right(30%)", a["tags"])
        self.assertNotIn("#left(70%)", a["tags"])
        # entry 1 must have ONLY its own layout
        self.assertIn("#left(70%)", b["tags"])
        self.assertNotIn("#right(30%)", b["tags"])
        # behavior tag stays where it was written
        self.assertIn("#fill", b["tags"])
        self.assertNotIn("#fill", a["tags"])


# =============================================================
# Smart executor — same input must NOT pollute via global_tags
# =============================================================

class SmartExecutorContamination(unittest.TestCase):
    """The bug: even though parser was right, the executor was
    re-merging extract_tags(text) and polluting layouts."""

    def setUp(self):
        # Patch side effects so we just capture what would be opened.
        import runtime.executor as ex
        import runtime.actions.autofill as af
        self.captured: List[dict] = []
        self._saves = (ex.open_target, ex.time.sleep, af.trigger_autofill)
        ex.open_target = self._fake_open
        ex.time.sleep = lambda *_a, **_k: None
        af.trigger_autofill = lambda mode="fill": None

    def tearDown(self):
        import runtime.executor as ex
        import runtime.actions.autofill as af
        ex.open_target, ex.time.sleep, af.trigger_autofill = self._saves

    def _fake_open(self, url=None, app=None, layout=None, display_spec=None,
                   chrome_profile=None):
        self.captured.append({"url": url, "app": app, "layout": layout})

    # -----------------------------------------------------

    def test_layouts_stay_per_entry_even_when_polluted_globals_passed(self):
        """Reproduces David's test event. Both URLs must keep their
        own layout regardless of what `global_tags` carries."""
        text = (
            "https://buymeacoffee.com/x @safari #right(30%)\n"
            "https://login.yahoo.com/  @chrome #left(70%) #fill\n"
        )
        parsed = parse(text)
        # cli/main.py historically passed extract_tags(text), which is
        # the polluted set. We pass it deliberately to prove the
        # executor no longer re-merges it.
        polluted = extract_tags(text)
        # Sanity: the polluted set really does contain BOTH layouts.
        self.assertIn("#left(70%)", polluted)
        self.assertIn("#right(30%)", polluted)

        from runtime.executor import execute_entries
        execute_entries(parsed.entries, global_tags=polluted, debug=False)

        self.assertEqual(len(self.captured), 2)

        a, b = self.captured
        self.assertEqual(a["url"], "https://buymeacoffee.com/x")
        self.assertEqual(a["app"], "Safari")
        self.assertIsNotNone(a["layout"], "buymeacoffee should have a layout")
        self.assertEqual(a["layout"]["type"], "right")

        self.assertEqual(b["url"], "https://login.yahoo.com/")
        self.assertEqual(b["app"], "Google Chrome")
        self.assertIsNotNone(b["layout"], "yahoo should have a layout")
        self.assertEqual(b["layout"]["type"], "left")


# =============================================================
# Plus executor — same isolation, same test shape
# =============================================================

class PlusResolverContamination(unittest.TestCase):
    """Plus Mode has NO global state by spec. Confirm resolve_command
    ignores ambient global_tags entirely."""

    def test_command_tags_isolated_from_block_tags(self):
        from core.models import OpenCommand
        from core.resolver import resolve_command

        cmd = OpenCommand(
            line_no=1,
            raw="open https://a.com #right(30%)",
            tags=frozenset({"#right(30%)"}),
            url="https://a.com",
        )
        polluted = frozenset({"#right(30%)", "#left(70%)", "#fill"})
        params = resolve_command(cmd, global_tags=polluted)

        # The merged tag set on the resolved params must equal the
        # command's own tags — NOT include other tags from elsewhere
        # in the block.
        self.assertEqual(set(params["tags"]), {"#right(30%)"})
        self.assertEqual(params["layout"]["type"], "right")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
