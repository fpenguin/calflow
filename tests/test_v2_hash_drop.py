"""
`#` drop sugar tests (v1.1.2).

In Plus Mode, attached function-shaped tags can drop the `#` prefix:
    open zoom.us @chrome display(2)   ≡   open zoom.us @chrome #display(2)
    open zoom.us @chrome left(50%)    ≡   open zoom.us @chrome #left(50%)

The function-call form is also kept in `functions` so HIDE/FOCUS can
use the same parsed value as a filter.

Run:
    python -m unittest tests.test_v2_hash_drop -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse


class HashDropPromotion(unittest.TestCase):
    def test_display_without_hash_promotes_to_tag(self) -> None:
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome display(2)"
        ).commands[0]
        self.assertIn("#display(2)", cmd.tags)

    def test_left_without_hash_promotes_to_tag(self) -> None:
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome left(50%)"
        ).commands[0]
        self.assertIn("#left(50%)", cmd.tags)

    def test_area_without_hash_promotes(self) -> None:
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome area(0,0,1920,1080)"
        ).commands[0]
        self.assertIn("#area(0,0,1920,1080)", cmd.tags)

    def test_grid_without_hash_promotes(self) -> None:
        # v1.1.19 — canonical grid order is cell@cols x rows.
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome grid(1@3x2)"
        ).commands[0]
        self.assertIn("#grid(1@3x2)", cmd.tags)

    def test_profile_without_hash_promotes(self) -> None:
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome profile(2)"
        ).commands[0]
        self.assertIn("#profile(2)", cmd.tags)

    def test_with_and_without_hash_are_equivalent_tags(self) -> None:
        with_hash = parse(
            "+CalFlow+\nopen https://x.com @chrome #display(2)"
        ).commands[0]
        without = parse(
            "+CalFlow+\nopen https://x.com @chrome display(2)"
        ).commands[0]
        # Both should carry the same canonical tag.
        self.assertIn("#display(2)", with_hash.tags)
        self.assertIn("#display(2)", without.tags)

    def test_non_layout_function_not_promoted(self) -> None:
        # `text(...)` is a click modifier, not a layout — must NOT
        # leak into tags.
        cmd = parse(
            '+CalFlow+\nclick text("Sign in")'
        ).commands[0]
        for t in cmd.tags:
            self.assertFalse(
                t.startswith("#text("),
                f"text() leaked into tags: {cmd.tags!r}",
            )

    def test_function_still_in_functions_dict(self) -> None:
        # HIDE/FOCUS need it as a filter; OPEN needs it as a tag.
        # We promote to tags AND keep in functions.
        cmd = parse(
            "+CalFlow+\nopen https://x.com @chrome display(2)"
        ).commands[0]
        self.assertIn(("display", 2), cmd.functions)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
