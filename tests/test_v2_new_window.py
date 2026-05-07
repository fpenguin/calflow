"""
new(window) / new(tab) tests (v1.1.20).

Locks the rule: layout/display tags imply a new window; explicit
`new(window)` / `new(tab)` overrides; default is tab.

Run:
    python -m unittest tests.test_v2_new_window -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.actions.browser import wants_new_window


class DefaultIsTab(unittest.TestCase):
    def test_no_tags_no_function(self) -> None:
        self.assertFalse(wants_new_window())

    def test_no_tags_other_function(self) -> None:
        self.assertFalse(wants_new_window(functions=[("speed", 0.1)]))

    def test_only_target_tag(self) -> None:
        # @target is a tag-shaped value but doesn't imply window mode.
        self.assertFalse(wants_new_window(tags={"@chrome"}))


class LayoutImpliesWindow(unittest.TestCase):
    """Any layout/display tag flips the default to window."""

    def test_left(self) -> None:
        self.assertTrue(wants_new_window(tags={"#left(50%)"}))

    def test_right(self) -> None:
        self.assertTrue(wants_new_window(tags={"#right(30)"}))

    def test_middle_top_bottom(self) -> None:
        for tag in ("#middle(50%)", "#top(50%)", "#bottom(50%)"):
            self.assertTrue(wants_new_window(tags={tag}), tag)

    def test_full(self) -> None:
        self.assertTrue(wants_new_window(tags={"#full"}))

    def test_grid(self) -> None:
        self.assertTrue(wants_new_window(tags={"#grid(1@3x2)"}))

    def test_area(self) -> None:
        self.assertTrue(wants_new_window(tags={"#area(0,0,1920,1080)"}))

    def test_display(self) -> None:
        self.assertTrue(wants_new_window(tags={"#display(2)"}))
        self.assertTrue(wants_new_window(tags={"#display"}))
        self.assertTrue(wants_new_window(tags={'#display("Samsung")'}))


class ProfileDoesNotImplyWindow(unittest.TestCase):
    """`#profile(N)` is a session selector, not a placement modifier."""

    def test_profile_alone_stays_tab(self) -> None:
        self.assertFalse(wants_new_window(tags={"#profile(2)"}))


class ExplicitNewOverrides(unittest.TestCase):
    """`new(window)` and `new(tab)` always win."""

    def test_new_window_with_no_layout(self) -> None:
        self.assertTrue(wants_new_window(functions=[("new", "window")]))

    def test_new_tab_overrides_layout(self) -> None:
        # Layout would imply window — but explicit new(tab) wins.
        self.assertFalse(
            wants_new_window(
                tags={"#left(50%)"},
                functions=[("new", "tab")],
            )
        )

    def test_new_window_with_layout(self) -> None:
        # Both align — still a window.
        self.assertTrue(
            wants_new_window(
                tags={"#grid(1@3x2)"},
                functions=[("new", "window")],
            )
        )

    def test_quoted_value_still_works(self) -> None:
        self.assertTrue(wants_new_window(functions=[("new", '"window"')]))
        self.assertFalse(wants_new_window(functions=[("new", "'tab'")]))

    def test_unrecognised_value_falls_back_to_default(self) -> None:
        # new(something_weird) → falls back to layout-rule (default tab here).
        self.assertFalse(wants_new_window(functions=[("new", "something")]))


class CaseInsensitivity(unittest.TestCase):
    def test_uppercase_tag(self) -> None:
        self.assertTrue(wants_new_window(tags={"#GRID(1@3X2)"}))

    def test_uppercase_value(self) -> None:
        self.assertTrue(wants_new_window(functions=[("new", "WINDOW")]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
