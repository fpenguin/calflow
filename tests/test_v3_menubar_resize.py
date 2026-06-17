"""
v1.4.0-dev — dynamic popover sizing.

The `resize-popover` bridge op (cli/menubar.py) is called by
popover.html after every render(). It clamps the requested height to
[_POPOVER_MIN_H, _POPOVER_MAX_H] and routes the call to
NSPopover.setContentSize_ + WKWebView.setFrame_. Width stays canonical
at _POPOVER_W server-side.

These tests build a stub _CFApp via alloc() (without init()) so we
exercise handle_message's resize-popover branch without touching
NSStatusBar / NSPopover / WKWebView construction. MagicMock objects
stand in for the popover + webview, and instance-level _resolve /
_reject mocks let us assert on routing without patching PyObjC class
attributes.

Skipped if pyobjc isn't available (sandbox CI lacks the framework).

Run:
    python -m unittest tests.test_v3_menubar_resize -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ResizePopoverDispatch(unittest.TestCase):
    """resize-popover routes to setContentSize_ + setFrame_ with the right shape."""

    @classmethod
    def setUpClass(cls):
        try:
            import cli.menubar as menubar  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"pyobjc not installed: {exc}")
        cls.menubar = menubar

    def _make_app(self):
        # alloc() without init() bypasses NSStatusBar / NSPopover /
        # WKWebView construction. handle_message only needs ._popover
        # and ._webview to record the UI calls. Do not patch _CFApp
        # class attributes directly: PyObjC can reject restoring method
        # descriptors after unittest.mock replaces them.
        app = self.menubar._CFApp.alloc()
        app._popover = MagicMock()
        app._webview = MagicMock()
        app._resolve = MagicMock()
        app._reject = MagicMock()
        return app

    def test_in_range_height_passes_through(self):
        app = self._make_app()
        sentinel_wv = object()
        app.handle_message("1", "resize-popover", {"height": 500}, sentinel_wv)
        app._popover.setContentSize_.assert_called_once_with(
            (self.menubar._POPOVER_W, 500),
        )
        app._webview.setFrame_.assert_called_once()
        app._resolve.assert_called_once_with(
            "1",
            {"width": self.menubar._POPOVER_W, "height": 500},
            sentinel_wv,
        )
        app._reject.assert_not_called()

    def test_height_below_min_clamps_to_floor(self):
        app = self._make_app()
        app.handle_message("2", "resize-popover", {"height": 50}, None)
        app._popover.setContentSize_.assert_called_with(
            (self.menubar._POPOVER_W, self.menubar._POPOVER_MIN_H),
        )
        app._resolve.assert_called_once_with(
            "2",
            {"width": self.menubar._POPOVER_W,
             "height": self.menubar._POPOVER_MIN_H},
            None,
        )

    def test_height_above_max_clamps_to_ceiling(self):
        app = self._make_app()
        app.handle_message("3", "resize-popover", {"height": 99999}, None)
        app._popover.setContentSize_.assert_called_with(
            (self.menubar._POPOVER_W, self.menubar._POPOVER_MAX_H),
        )
        app._resolve.assert_called_once_with(
            "3",
            {"width": self.menubar._POPOVER_W,
             "height": self.menubar._POPOVER_MAX_H},
            None,
        )

    def test_non_int_height_falls_back_to_default(self):
        app = self._make_app()
        app.handle_message("4", "resize-popover", {"height": "nope"}, None)
        # _POPOVER_H is within the clamp range so it passes through.
        app._popover.setContentSize_.assert_called_with(
            (self.menubar._POPOVER_W, self.menubar._POPOVER_H),
        )

    def test_missing_height_falls_back_to_default(self):
        app = self._make_app()
        app.handle_message("5", "resize-popover", {}, None)
        app._popover.setContentSize_.assert_called_with(
            (self.menubar._POPOVER_W, self.menubar._POPOVER_H),
        )

    def test_src_wv_threaded_to_resolve(self):
        # v1.3.5 contract: every handler must route the response back
        # to the webview that originated the message. resize-popover
        # follows the same rule.
        app = self._make_app()
        sentinel = object()
        app.handle_message("6", "resize-popover", {"height": 400}, sentinel)
        self.assertIs(app._resolve.call_args.args[-1], sentinel)

    def test_setContentSize_failure_routes_reject(self):
        app = self._make_app()
        app._popover.setContentSize_.side_effect = RuntimeError("Cocoa boom")
        app.handle_message("7", "resize-popover", {"height": 400}, None)
        app._reject.assert_called_once()
        args = app._reject.call_args.args
        self.assertEqual(args[0], "7")
        self.assertIn("resize-popover failed", args[1])
        self.assertIs(args[2], None)
        app._resolve.assert_not_called()


class ResizePopoverConstants(unittest.TestCase):
    """The clamp range and canonical width must satisfy basic invariants."""

    @classmethod
    def setUpClass(cls):
        try:
            import cli.menubar as menubar  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"pyobjc not installed: {exc}")
        cls.menubar = menubar

    def test_min_is_less_than_max(self):
        self.assertLess(self.menubar._POPOVER_MIN_H,
                        self.menubar._POPOVER_MAX_H)

    def test_default_h_is_within_clamp(self):
        # _POPOVER_H is the initial popover height; it must satisfy
        # the clamp so the non-int / missing-height fallback paths
        # produce a value the OS will accept.
        self.assertGreaterEqual(self.menubar._POPOVER_H,
                                self.menubar._POPOVER_MIN_H)
        self.assertLessEqual(self.menubar._POPOVER_H,
                             self.menubar._POPOVER_MAX_H)

    def test_canonical_width_is_positive(self):
        self.assertGreater(self.menubar._POPOVER_W, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
