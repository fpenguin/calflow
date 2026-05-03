"""
Quote-tolerant Plus Mode header tests (v1.1.5).

Real bug: a user pasted `'+CalFlow+\\n…` (leading apostrophe) into the
Custom Script flow. The header didn't match, so the parser silently
fell back to Smart mode and reported "no executable content".

After v1.1.5, the header detector strips up to 2 layers of any quote
character (', ", `, ‘, ’, “, ”) from each line before comparing, so
the most common copy-paste artefacts resolve to the canonical form.

Run:
    python -m unittest tests.test_v2_quote_tolerant_header -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.plus_parser import is_plus_header
from core.parser.parser import parse


class HeaderDetection(unittest.TestCase):
    """Detect `+CalFlow+` regardless of surrounding quote characters."""

    def test_canonical_header(self) -> None:
        self.assertTrue(is_plus_header("+CalFlow+\nfocus @chrome"))

    def test_leading_apostrophe(self) -> None:
        self.assertTrue(is_plus_header("'+CalFlow+\nfocus @chrome"))

    def test_paired_apostrophes(self) -> None:
        self.assertTrue(is_plus_header("'+CalFlow+'\nfocus @chrome"))

    def test_paired_double_quotes(self) -> None:
        self.assertTrue(is_plus_header('"+CalFlow+"\nfocus @chrome'))

    def test_smart_single_quotes(self) -> None:
        self.assertTrue(is_plus_header("‘+CalFlow+’\nfocus @chrome"))

    def test_smart_double_quotes(self) -> None:
        self.assertTrue(is_plus_header("“+CalFlow+”\nfocus @chrome"))

    def test_backticks(self) -> None:
        self.assertTrue(is_plus_header("`+CalFlow+`\nfocus @chrome"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(is_plus_header("+calflow+\nfocus @chrome"))
        self.assertTrue(is_plus_header("+CALFLOW+\nfocus @chrome"))

    def test_no_header(self) -> None:
        self.assertFalse(is_plus_header("focus @chrome"))

    def test_header_inside_token_now_matches(self) -> None:
        # v1.1.6 changed the rule: substring match anywhere wins.
        # The marker line itself is discarded as the body header,
        # so this is fine — `open +CalFlow+ inline` becomes the
        # marker line, body = [] (no commands follow).
        self.assertTrue(is_plus_header("open +CalFlow+ inline"))


class ParseEnd2End(unittest.TestCase):
    """The full parser pipeline routes quoted-headers as Plus."""

    def test_apostrophe_header_yields_plus(self) -> None:
        result = parse(
            "'+CalFlow+\n"
            'focus @chrome title("Wealthsimple") display(1)'
        )
        self.assertEqual(result.mode, "plus")
        self.assertEqual([c.name for c in result.commands], ["FOCUS"])

    def test_smart_quote_header_yields_plus(self) -> None:
        result = parse(
            "“+CalFlow+”\n"
            "focus @chrome"
        )
        self.assertEqual(result.mode, "plus")
        self.assertEqual([c.name for c in result.commands], ["FOCUS"])

    def test_canonical_header_still_works(self) -> None:
        # Regression guard — the new tolerance must NOT break the
        # canonical (no-quote) form.
        result = parse(
            "+CalFlow+\n"
            "focus @chrome"
        )
        self.assertEqual(result.mode, "plus")


class SubstringHeaderDetection(unittest.TestCase):
    """v1.1.6 — `+CalFlow+` anywhere in any line switches to Plus Mode."""

    def test_marker_mid_line(self) -> None:
        # The marker on line 1 with stray text around it still wins.
        self.assertTrue(is_plus_header("note: +CalFlow+ is the header\nopen x"))

    def test_marker_on_later_line(self) -> None:
        text = "free-form preface\n+CalFlow+\nfocus @chrome"
        self.assertTrue(is_plus_header(text))
        result = parse(text)
        self.assertEqual(result.mode, "plus")
        self.assertEqual([c.name for c in result.commands], ["FOCUS"])

    def test_marker_with_excel_apostrophe(self) -> None:
        # The canonical Excel-safe form: leading apostrophe to stop the
        # spreadsheet from interpreting `+` as a formula.
        text = "'+CalFlow+\nfocus @chrome"
        self.assertTrue(is_plus_header(text))
        result = parse(text)
        self.assertEqual(result.mode, "plus")

    def test_no_marker_falls_to_smart(self) -> None:
        text = "no marker here\nopen zoom.us"
        self.assertFalse(is_plus_header(text))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
