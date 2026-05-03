"""
Window/display unit tests (v2.0.4).

Pure unit tests — no real osascript subprocess, no real displays.

Covers:
    - core.resolver.resolve_display: tag → spec
    - runtime.actions.window.resolve_display_target: spec → display dict
    - runtime.actions.window.compute_rect: layout + display → (x,y,w,h)
    - core.parser.smart_parser.HASHTAG_PATTERN captures #display("…")

Run:
    python -m unittest tests.test_v2_window -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.resolver import resolve_display
from core.parser.smart_parser import HASHTAG_PATTERN
from runtime.actions.window import (
    compute_rect,
    resolve_display_target,
)


# A standard fake display layout used across most tests:
#   [1] primary built-in laptop @ (0, 0) 1512×944
#   [2] external Samsung        @ (1512, -158) 3840×2160
#   [3] external Dell           @ (-1920, 0) 1920×1080
DISPLAYS_3 = [
    {"index": 1, "name": "Built-in Retina Display", "x": 0,    "y": 0,
     "w": 1512, "h": 944,  "primary": True,  "builtin": True,  "external": False},
    {"index": 2, "name": "Samsung S90D",            "x": 1512, "y": -158,
     "w": 3840, "h": 2160, "primary": False, "builtin": False, "external": True},
    {"index": 3, "name": "Dell AW3225QF",           "x": -1920,"y": 0,
     "w": 1920, "h": 1080, "primary": False, "builtin": False, "external": True},
]

ONLY_LAPTOP = [DISPLAYS_3[0]]

LAPTOP_PLUS_ONE_EXT = DISPLAYS_3[:2]


# =============================================================
# Tag → spec
# =============================================================

class ResolveDisplaySpec(unittest.TestCase):
    def test_no_tag(self):
        self.assertIsNone(resolve_display(set()))

    def test_no_display_tag_among_others(self):
        self.assertIsNone(resolve_display({"#left(50%)", "@chrome"}))

    def test_bare_tag(self):
        self.assertEqual(resolve_display({"#display"}), ("external", None))

    def test_empty_parens(self):
        self.assertEqual(resolve_display({"#display()"}), ("external", None))

    def test_unquoted_keyword_ext(self):
        self.assertEqual(resolve_display({"#display(ext)"}), ("external", None))

    def test_unquoted_arbitrary_token(self):
        # any non-quoted, non-numeric token → first external
        self.assertEqual(resolve_display({"#display(secondary)"}), ("external", None))

    def test_numeric(self):
        self.assertEqual(resolve_display({"#display(2)"}), ("index", 2))

    def test_quoted_name(self):
        self.assertEqual(
            resolve_display({'#display("Samsung S90D")'}),
            ("name", "Samsung S90D"),
        )

    def test_quoted_substring(self):
        self.assertEqual(
            resolve_display({'#display("Samsung")'}),
            ("name", "Samsung"),
        )

    def test_case_insensitive(self):
        self.assertEqual(resolve_display({"#DISPLAY"}), ("external", None))


# =============================================================
# spec → concrete display
# =============================================================

class ResolveDisplayTarget(unittest.TestCase):
    def test_no_spec_returns_primary(self):
        self.assertEqual(
            resolve_display_target(None, DISPLAYS_3)["name"],
            "Built-in Retina Display",
        )

    def test_external_with_one_ext(self):
        self.assertEqual(
            resolve_display_target(("external", None), LAPTOP_PLUS_ONE_EXT)["name"],
            "Samsung S90D",
        )

    def test_external_with_no_ext_falls_back_to_primary(self):
        # No external connected — falls back to primary (with [WARN])
        self.assertEqual(
            resolve_display_target(("external", None), ONLY_LAPTOP)["name"],
            "Built-in Retina Display",
        )

    def test_external_with_multiple_ext_picks_first(self):
        # Two externals — picks first (with [WARN] to disambiguate)
        self.assertEqual(
            resolve_display_target(("external", None), DISPLAYS_3)["name"],
            "Samsung S90D",
        )

    def test_index_in_range(self):
        self.assertEqual(
            resolve_display_target(("index", 2), DISPLAYS_3)["name"],
            "Samsung S90D",
        )
        self.assertEqual(
            resolve_display_target(("index", 3), DISPLAYS_3)["name"],
            "Dell AW3225QF",
        )

    def test_index_out_of_range_returns_none(self):
        # No fallback per spec
        self.assertIsNone(resolve_display_target(("index", 9), DISPLAYS_3))
        self.assertIsNone(resolve_display_target(("index", 0), DISPLAYS_3))

    def test_name_substring_match(self):
        self.assertEqual(
            resolve_display_target(("name", "Samsung"), DISPLAYS_3)["name"],
            "Samsung S90D",
        )
        self.assertEqual(
            resolve_display_target(("name", "Dell"), DISPLAYS_3)["name"],
            "Dell AW3225QF",
        )

    def test_name_case_insensitive(self):
        self.assertEqual(
            resolve_display_target(("name", "samsung"), DISPLAYS_3)["name"],
            "Samsung S90D",
        )

    def test_name_no_match_returns_none(self):
        # No fallback per spec
        self.assertIsNone(
            resolve_display_target(("name", "LG"), DISPLAYS_3)
        )

    def test_no_displays_returns_none(self):
        self.assertIsNone(resolve_display_target(None, []))


# =============================================================
# layout + display → rect
# =============================================================

class ComputeRect(unittest.TestCase):
    def test_full_on_primary(self):
        d = DISPLAYS_3[0]
        self.assertEqual(
            compute_rect({"type": "full"}, d),
            (0, 0, 1512, 944),
        )

    def test_left_50_on_primary(self):
        d = DISPLAYS_3[0]
        self.assertEqual(
            compute_rect({"type": "left", "value": 0.5}, d),
            (0, 0, 756, 944),
        )

    def test_right_30_on_primary(self):
        d = DISPLAYS_3[0]
        # 30% of 1512 = 453; right strip starts at 1512 - 453 = 1059
        self.assertEqual(
            compute_rect({"type": "right", "value": 0.3}, d),
            (1059, 0, 453, 944),
        )

    def test_left_70_on_external_2(self):
        # External @ (1512, -158) 3840×2160. 70% wide = 2688.
        d = DISPLAYS_3[1]
        self.assertEqual(
            compute_rect({"type": "left", "value": 0.7}, d),
            (1512, -158, 2688, 2160),
        )

    def test_middle_40(self):
        d = DISPLAYS_3[0]
        # 40% wide = 604; centered → x = (1512 - 604)/2 = 454
        self.assertEqual(
            compute_rect({"type": "middle", "value": 0.4}, d),
            (454, 0, 604, 944),
        )

    def test_top_25(self):
        d = DISPLAYS_3[0]
        self.assertEqual(
            compute_rect({"type": "top", "value": 0.25}, d),
            (0, 0, 1512, 236),
        )

    def test_bottom_25(self):
        d = DISPLAYS_3[0]
        # 25% of 944 = 236; y = 944 - 236 = 708
        self.assertEqual(
            compute_rect({"type": "bottom", "value": 0.25}, d),
            (0, 708, 1512, 236),
        )

    def test_grid_2x2_cell_1(self):
        d = DISPLAYS_3[0]  # 1512×944
        self.assertEqual(
            compute_rect({"type": "grid", "cols": 2, "rows": 2, "cell": 1}, d),
            (0, 0, 756, 472),
        )

    def test_grid_3x2_cell_5(self):
        # cols=3, rows=2, cell=5 → row 1, col 1 (0-indexed: idx=4 → row=1, col=1)
        # cw = 1512/3 = 504; ch = 944/2 = 472
        # x = 0 + 1*504 = 504; y = 0 + 1*472 = 472
        d = DISPLAYS_3[0]
        self.assertEqual(
            compute_rect({"type": "grid", "cols": 3, "rows": 2, "cell": 5}, d),
            (504, 472, 504, 472),
        )

    def test_area_pixels(self):
        d = DISPLAYS_3[0]
        layout = {
            "type": "area",
            "x": {"value": 100, "unit": "pixel"},
            "y": {"value": 50,  "unit": "pixel"},
            "w": {"value": 800, "unit": "pixel"},
            "h": {"value": 600, "unit": "pixel"},
        }
        self.assertEqual(compute_rect(layout, d), (100, 50, 800, 600))

    def test_area_percentages(self):
        d = DISPLAYS_3[0]  # 1512×944
        layout = {
            "type": "area",
            "x": {"value": 0,   "unit": "percent"},
            "y": {"value": 0,   "unit": "percent"},
            "w": {"value": 50,  "unit": "percent"},
            "h": {"value": 50,  "unit": "percent"},
        }
        # 50% of 1512 = 756; 50% of 944 = 472
        self.assertEqual(compute_rect(layout, d), (0, 0, 756, 472))


# =============================================================
# HASHTAG_PATTERN captures #display("…") with spaces
# =============================================================

class HashtagRegex(unittest.TestCase):
    def test_bare_display(self):
        self.assertEqual(HASHTAG_PATTERN.findall("zoom.us #display"), ["#display"])

    def test_display_empty_parens(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall("zoom.us #display()"),
            ["#display()"],
        )

    def test_display_unquoted(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall("zoom.us #display(ext)"),
            ["#display(ext)"],
        )

    def test_display_numeric(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall("zoom.us #display(2)"),
            ["#display(2)"],
        )

    def test_display_quoted_simple(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall('zoom.us #display("Samsung")'),
            ['#display("Samsung")'],
        )

    def test_display_quoted_with_spaces(self):
        # Previously truncated at the first quote; verify it now captures whole tag
        self.assertEqual(
            HASHTAG_PATTERN.findall('zoom.us #display("Samsung S90D")'),
            ['#display("Samsung S90D")'],
        )

    def test_display_quoted_with_more_spaces(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall('foo #display("Dell U3219Q UltraSharp") bar'),
            ['#display("Dell U3219Q UltraSharp")'],
        )

    def test_layout_tag_still_works(self):
        self.assertEqual(
            HASHTAG_PATTERN.findall("zoom.us #left(50%) #display"),
            ["#left(50%)", "#display"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
