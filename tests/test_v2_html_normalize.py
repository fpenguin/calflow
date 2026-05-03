"""
HTML-normalization tests (v2.0.10+).

Reproduces the bug David hit: Google Calendar returned the description
with HTML markup, so `+CalFlow+` wasn't on its own line and Plus Mode
detection silently failed. After normalization, the same description
parses correctly.

Run:
    python -m unittest tests.test_v2_html_normalize -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from infra.calendar.normalize import normalize_description
from core.parser.parser import parse


# =============================================================
# Unit tests for normalize_description
# =============================================================

class HtmlNormalize(unittest.TestCase):
    def test_plain_text_passes_through(self):
        text = "+CalFlow+\nopen zoom.us @chrome"
        self.assertEqual(normalize_description(text), text)

    def test_empty(self):
        self.assertEqual(normalize_description(""), "")
        self.assertEqual(normalize_description(None), None)

    # ---------- <br> handling ----------

    def test_br_tags_become_newlines(self):
        text = "+CalFlow+<br>open zoom.us<br>"
        out = normalize_description(text)
        self.assertIn("+CalFlow+", out)
        # +CalFlow+ on its own line
        self.assertEqual(out.splitlines()[0].strip(), "+CalFlow+")

    def test_br_self_closing_variants(self):
        for variant in ("<br>", "<br/>", "<br />", "<BR>", "<Br />"):
            text = f"line1{variant}line2"
            self.assertIn(
                "line1\nline2",
                normalize_description(text),
                f"variant {variant!r} failed",
            )

    # ---------- <p> wrapping ----------

    def test_p_tags_become_newlines(self):
        text = "<p>+CalFlow+</p><p>open zoom.us</p>"
        out = normalize_description(text)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(lines[0], "+CalFlow+")
        self.assertEqual(lines[1], "open zoom.us")

    def test_div_wrapping(self):
        text = "<div>+CalFlow+</div><div>open zoom.us</div>"
        lines = [ln for ln in normalize_description(text).splitlines() if ln.strip()]
        self.assertEqual(lines, ["+CalFlow+", "open zoom.us"])

    # ---------- <a href> handling ----------

    def test_anchor_tag_keeps_url(self):
        text = '<a href="https://zoom.us">https://zoom.us</a>'
        out = normalize_description(text)
        self.assertEqual(out, "https://zoom.us")

    def test_anchor_with_different_label_keeps_both(self):
        text = '<a href="https://zoom.us">Join meeting</a>'
        out = normalize_description(text)
        self.assertIn("https://zoom.us", out)
        self.assertIn("Join meeting", out)

    def test_anchor_inside_text(self):
        text = 'Visit <a href="https://x.com">our site</a> today'
        self.assertEqual(
            normalize_description(text),
            "Visit https://x.com our site today",
        )

    # ---------- HTML entities ----------

    def test_basic_entities(self):
        self.assertEqual(normalize_description("&lt;tag&gt;"), "<tag>")
        self.assertEqual(normalize_description("a &amp; b"), "a & b")
        self.assertEqual(normalize_description("&quot;hi&quot;"), '"hi"')

    def test_nbsp_becomes_space(self):
        out = normalize_description("a&nbsp;b&nbsp;c")
        self.assertEqual(out, "a\xa0b\xa0c")  # html.unescape returns nbsp char

    def test_numeric_entity(self):
        self.assertEqual(normalize_description("&#43;CalFlow&#43;"), "+CalFlow+")

    # ---------- Whitespace cleanup ----------

    def test_trailing_spaces_trimmed(self):
        text = "line1   \nline2"
        self.assertEqual(normalize_description(text), "line1\nline2")

    def test_multiple_blank_lines_collapsed(self):
        text = "a\n\n\n\n\nb"
        self.assertEqual(normalize_description(text), "a\n\nb")

    # ---------- Idempotency ----------

    def test_idempotent_on_already_clean(self):
        text = "+CalFlow+\n\nopen zoom.us @chrome #left(50%)"
        self.assertEqual(
            normalize_description(normalize_description(text)),
            normalize_description(text),
        )


# =============================================================
# Integration: Google Calendar HTML → parser correctly detects mode
# =============================================================

class HtmlIntoParser(unittest.TestCase):
    """
    Reproduces David's exact failure: a description that LOOKS like
    Plus Mode source but came back from Google Calendar wrapped in
    HTML. Before normalization, mode = SMART + zero entries. After,
    mode = PLUS with all commands intact.
    """

    def test_html_wrapped_plus_block_normalizes_then_parses_as_plus(self):
        # Mimics what Google Calendar sends after the user pastes a
        # multi-line Plus block into the rich-text editor.
        html_form = (
            "<p>+CalFlow+</p>"
            "<p>## Multi-feature smoke test</p>"
            "<p>open @safari</p>"
            '<p>open <a href="https://news.ycombinator.com">'
            "https://news.ycombinator.com</a> @chrome</p>"
            '<p>open "Notion" #left(50%) #display(ext)</p>'
            '<p>focus @chrome title("Hacker")</p>'
            "<p>hide all except @work</p>"
            "<p>wait 3</p>"
            '<p>close "Spotify"</p>'
        )
        # Without normalization, parse() would return Smart + 0 entries
        # because `+CalFlow+` is never on its own line.
        from infra.calendar.normalize import normalize_description
        cleaned = normalize_description(html_form)
        self.assertIn("+CalFlow+", cleaned.splitlines()[0])

        result = parse(cleaned)
        self.assertEqual(result.mode, "plus")

        verbs = [c.name for c in result.commands]
        self.assertEqual(
            verbs,
            ["OPEN", "OPEN", "OPEN", "FOCUS", "HIDE", "WAIT", "CLOSE"],
        )

    def test_br_separated_plus_block_normalizes_correctly(self):
        # Google Calendar's older formatting: <br> between lines
        html_form = (
            "+CalFlow+<br>"
            "open zoom.us @chrome #left(50%)<br>"
            "open notion.so @chrome #right(50%)"
        )
        from infra.calendar.normalize import normalize_description
        cleaned = normalize_description(html_form)
        result = parse(cleaned)
        self.assertEqual(result.mode, "plus")
        self.assertEqual(len(result.commands), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
