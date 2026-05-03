"""
Unknown @alias safety tests (v1.1.14).

Regression: `hide @cmux` (where `@cmux` isn't in TARGETS) used to
collapse to empty items, then the executor fell through to
`hide_all(except_apps=())` — silently hiding EVERY visible app.
Same catastrophe for `close @unknown`.

After v1.1.14:
    1. `resolve_target_expansion("@cmux")` returns `["cmux"]` (literal
       fallback) plus a `[WARN]` — not `[]`.
    2. The resolver also tags `had_items=True` on the resolved params
       when the original command had explicit items, and the executor
       refuses to fall through to `hide_all` / `close_all` when
       `had_items` is set.

Defense in depth — either layer alone prevents the disaster.

Run:
    python -m unittest tests.test_v2_unknown_alias -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
from core.resolver.resolver import resolve_command, resolve_target_expansion


class UnknownAliasFallback(unittest.TestCase):
    """Layer 1: resolve_target_expansion never returns []."""

    def test_known_target_resolves(self) -> None:
        # Sanity — TARGETS hit still works.
        self.assertEqual(
            resolve_target_expansion("@chrome"),
            ["Google Chrome"],
        )

    def test_unknown_alias_falls_back_to_literal(self) -> None:
        # The whole point — @cmux NOT in TARGETS → ["cmux"], not [].
        self.assertEqual(resolve_target_expansion("@cmux"), ["cmux"])

    def test_unknown_alias_strips_at_only(self) -> None:
        self.assertEqual(
            resolve_target_expansion("@some-app-name"),
            ["some-app-name"],
        )

    def test_quoted_app_name_still_works(self) -> None:
        self.assertEqual(
            resolve_target_expansion('"Some App"'),
            ["Some App"],
        )


class HadItemsFlag(unittest.TestCase):
    """Layer 2: the resolver tags `had_items` so the executor can
    refuse silent fall-through."""

    def test_hide_with_explicit_alias_marks_had_items(self) -> None:
        cmd = parse("+CalFlow+\nhide @cmux").commands[0]
        params = resolve_command(cmd)
        self.assertTrue(params["had_items"])
        # Fallback also expanded the alias.
        self.assertEqual(params["items"], ("cmux",))
        self.assertEqual(params["keep"], ())

    def test_hide_except_marks_no_had_items(self) -> None:
        cmd = parse("+CalFlow+\nhide except(@chrome)").commands[0]
        params = resolve_command(cmd)
        self.assertFalse(params["had_items"])
        self.assertEqual(params["items"], ())

    def test_close_with_explicit_alias_marks_had_items(self) -> None:
        cmd = parse("+CalFlow+\nclose @cmux").commands[0]
        params = resolve_command(cmd)
        self.assertTrue(params["had_items"])
        self.assertEqual(params["items"], ("cmux",))

    def test_close_except_marks_no_had_items(self) -> None:
        cmd = parse("+CalFlow+\nclose except(@chrome)").commands[0]
        params = resolve_command(cmd)
        self.assertFalse(params["had_items"])

    def test_runtime_keyword_marks_no_had_items(self) -> None:
        cmd = parse("+CalFlow+\nhide all").commands[0]
        params = resolve_command(cmd)
        self.assertFalse(params["had_items"])


class ExecutorRefusesSilentFallthrough(unittest.TestCase):
    """End-to-end: even if a fault upstream produced empty items, the
    executor refuses to call hide_all / close_all when had_items is
    set."""

    def test_hide_with_had_items_does_not_call_hide_all(self) -> None:
        from runtime import command_executor as ce

        called = {"hide_all": 0, "hide_app": 0}
        with patch("runtime.actions.app_control.hide_all",
                   side_effect=lambda **kw: called.__setitem__("hide_all",
                                                                called["hide_all"] + 1)), \
             patch("runtime.actions.app_control.hide_app",
                   side_effect=lambda *a, **kw: called.__setitem__("hide_app",
                                                                    called["hide_app"] + 1)):
            ce._do_hide({
                "verb": "HIDE",
                "items": (),         # all aliases failed to resolve
                "keep": (),
                "had_items": True,
                "display_filter": None,
            })
        self.assertEqual(called["hide_all"], 0)  # the critical assertion
        self.assertEqual(called["hide_app"], 0)

    def test_close_with_had_items_does_not_call_close_all(self) -> None:
        from runtime import command_executor as ce

        called = {"close_all": 0, "close_app": 0}
        with patch("runtime.actions.app_control.close_all",
                   side_effect=lambda **kw: called.__setitem__("close_all",
                                                                called["close_all"] + 1)), \
             patch("runtime.actions.app_control.close_app",
                   side_effect=lambda *a, **kw: called.__setitem__("close_app",
                                                                    called["close_app"] + 1)):
            ce._do_close({
                "verb": "CLOSE",
                "items": (),
                "keep": (),
                "had_items": True,
            })
        self.assertEqual(called["close_all"], 0)  # the critical assertion
        self.assertEqual(called["close_app"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
