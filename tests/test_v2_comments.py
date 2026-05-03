"""
Comment-syntax tests (v2.0).

Covers core.utils.strip_inline_comment + the integration into the
Smart parser, Plus parser, and validator.

Spec: docs/DSL_GRAMMAR.md §1.3, docs/parser-behavior.md §3.2.

Run:
    python -m unittest tests.test_v2_comments -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
from core.utils import strip_inline_comment
from core.validator import validate_plus_block


# =============================================================
# Unit: strip_inline_comment
# =============================================================

class StripInlineComment(unittest.TestCase):
    def test_whole_line_collapses_to_empty(self):
        self.assertEqual(strip_inline_comment("## just a note"), "")

    def test_inline_strips_tail(self):
        self.assertEqual(
            strip_inline_comment("open zoom.us @chrome  ## meeting"),
            "open zoom.us @chrome",
        )

    def test_no_comment_passes_through(self):
        self.assertEqual(
            strip_inline_comment("open zoom.us @chrome"),
            "open zoom.us @chrome",
        )

    def test_single_hash_is_a_tag_not_a_comment(self):
        self.assertEqual(
            strip_inline_comment("zoom.us #left(50%)"),
            "zoom.us #left(50%)",
        )

    def test_hash_inside_double_quotes_preserved(self):
        self.assertEqual(
            strip_inline_comment('type("hello ## world")'),
            'type("hello ## world")',
        )

    def test_hash_inside_single_quotes_preserved(self):
        self.assertEqual(
            strip_inline_comment("type('hello ## world')"),
            "type('hello ## world')",
        )

    def test_hash_inside_parens_preserved(self):
        self.assertEqual(
            strip_inline_comment('click text("step ## 2")'),
            'click text("step ## 2")',
        )

    def test_hash_inside_collection_preserved(self):
        self.assertEqual(
            strip_inline_comment('hide ["A ## B", "C"]'),
            'hide ["A ## B", "C"]',
        )

    def test_hash_inside_dynamic_block_preserved(self):
        self.assertEqual(
            strip_inline_comment("save to({now ## kept})"),
            "save to({now ## kept})",
        )

    def test_inline_after_balanced_quotes_strips(self):
        self.assertEqual(
            strip_inline_comment('type("hi") ## tail'),
            'type("hi")',
        )

    def test_empty_string(self):
        self.assertEqual(strip_inline_comment(""), "")

    def test_lone_hash_is_not_comment(self):
        # A single '#' is a tag marker; only doubled '##' is a comment.
        self.assertEqual(
            strip_inline_comment("open x.com #left(50%)"),
            "open x.com #left(50%)",
        )


# =============================================================
# Plus Mode integration
# =============================================================

class PlusModeComments(unittest.TestCase):
    def test_whole_line_comment_in_plus_block(self):
        text = "+CalFlow+\n## step zero\nopen zoom.us"
        r = parse(text)
        self.assertEqual([c.name for c in r.commands], ["OPEN"])
        self.assertFalse(r.has_errors)

    def test_inline_comment_after_command(self):
        text = "+CalFlow+\nopen zoom.us @chrome  ## the meeting"
        r = parse(text)
        self.assertEqual(len(r.commands), 1)
        self.assertEqual(r.commands[0].name, "OPEN")
        self.assertFalse(r.has_errors)

    def test_inline_comment_does_not_break_tag_parsing(self):
        text = "+CalFlow+\nopen zoom.us @chrome #left(50%)  ## standup"
        r = parse(text)
        self.assertEqual(len(r.commands), 1)
        self.assertIn("#left(50%)", r.commands[0].tags)

    def test_hash_inside_string_kept_in_text(self):
        text = '+CalFlow+\ntype("hello ## world")'
        r = parse(text)
        self.assertEqual(r.commands[0].text, "hello ## world")

    def test_hash_inside_dynamic_block_kept_literal(self):
        # The block isn't a valid dynamic expression, so resolver
        # returns it unchanged — but the parser must NOT chop the line.
        text = '+CalFlow+\nsave source(clipboard) to("~/x_{now ## kept}.png")'
        r = parse(text)
        self.assertFalse(r.has_errors)
        self.assertEqual(len(r.commands), 1)
        self.assertEqual(r.commands[0].name, "SAVE")

    def test_inline_comment_with_no_space_before(self):
        text = "+CalFlow+\nopen zoom.us@chrome## meeting"
        # Note: this still tokenizes correctly because `##` is at top
        # level. The result depends on tokenization, but the line must
        # not produce a stray validation error from the comment text.
        r = parse(text)
        # Either it's a clean OPEN or a single validation error — but
        # the comment text "meeting" must NEVER appear as a token error.
        for e in r.errors:
            self.assertNotIn("meeting", e.message)


class PlusModeValidator(unittest.TestCase):
    def test_validator_treats_inline_comment_as_invisible(self):
        errs = validate_plus_block(["open zoom.us  ## ok"])
        self.assertEqual(errs, [])

    def test_validator_treats_whole_line_comment_as_empty(self):
        errs = validate_plus_block(["## comment", "open zoom.us"])
        self.assertEqual(errs, [])


# =============================================================
# Smart Mode integration
# =============================================================

class SmartModeComments(unittest.TestCase):
    def test_whole_line_comment_in_smart_block(self):
        text = "## morning routine\nzoom.us @chrome"
        r = parse(text)
        self.assertEqual(len(r.entries), 1)
        self.assertEqual(r.entries[0]["url"], "https://zoom.us")

    def test_inline_comment_after_url(self):
        text = "zoom.us @chrome  ## the meeting"
        r = parse(text)
        self.assertEqual(len(r.entries), 1)
        self.assertEqual(r.entries[0]["url"], "https://zoom.us")
        self.assertIn("@chrome", r.entries[0]["tags"])

    def test_inline_comment_does_not_get_tagged(self):
        text = "zoom.us  ## #not_a_tag"
        r = parse(text)
        self.assertEqual(len(r.entries), 1)
        self.assertNotIn("#not_a_tag", r.entries[0]["tags"])

    def test_global_modifier_comment_stripped(self):
        text = "#display(2)  ## monitor 2\n@chrome\nzoom.us"
        r = parse(text)
        self.assertEqual(len(r.entries), 1)
        self.assertIn("#display(2)", r.entries[0]["tags"])
        self.assertIn("@chrome", r.entries[0]["tags"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
