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

    def test_header_inside_token_does_not_match(self) -> None:
        # The marker MUST be on its own line.
        self.assertFalse(is_plus_header("open +CalFlow+ inline"))


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
