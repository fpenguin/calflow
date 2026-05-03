"""
Runtime-target tests (v1.1.2).

Locks the type-system contract:
    Dynamic value : `{ … }`         → produces data
    Runtime target: bare ident       → selects system entity
    Alias         : `@…`             → predefined set
    Filter        : `name(…)`        → modifies selection

`active` and `all` are bare identifiers (NOT `{active}` and NOT `@active`).

Run:
    python -m unittest tests.test_v2_runtime_targets -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.models import (
    CloseCommand, FocusCommand, HideCommand, ScreenshotCommand,
)
from core.parser.parser import parse


class HideRuntimeTargets(unittest.TestCase):
    def test_hide_active_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nhide active").commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertEqual(cmd.target_keyword, "active")
        self.assertEqual(cmd.items, ())
        self.assertEqual(cmd.keep_set, frozenset())

    def test_hide_all_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nhide all").commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertEqual(cmd.target_keyword, "all")

    def test_hide_except_active_keeps_keep_set(self) -> None:
        # `active` inside except() flows through as a raw token; the
        # resolver/executor look it up at runtime.
        cmd = parse("+CalFlow+\nhide except(active)").commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertIn("active", cmd.keep_set)


class CloseRuntimeTargets(unittest.TestCase):
    def test_close_active_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nclose active").commands[0]
        self.assertIsInstance(cmd, CloseCommand)
        self.assertEqual(cmd.target_keyword, "active")

    def test_close_all_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nclose all").commands[0]
        self.assertIsInstance(cmd, CloseCommand)
        self.assertEqual(cmd.target_keyword, "all")

    def test_close_except_active_keeps_keep_set(self) -> None:
        cmd = parse("+CalFlow+\nclose except(active)").commands[0]
        self.assertIsInstance(cmd, CloseCommand)
        self.assertIn("active", cmd.keep_set)


class FocusRuntimeTargets(unittest.TestCase):
    def test_focus_active_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nfocus active").commands[0]
        self.assertIsInstance(cmd, FocusCommand)
        self.assertEqual(cmd.target_keyword, "active")

    def test_focus_with_display_captures_target(self) -> None:
        cmd = parse("+CalFlow+\nfocus @chrome display(2)").commands[0]
        self.assertIsInstance(cmd, FocusCommand)
        self.assertEqual(cmd.display_target, 2)

    def test_focus_with_named_display(self) -> None:
        cmd = parse(
            '+CalFlow+\nfocus @chrome display("Samsung S90D")'
        ).commands[0]
        self.assertIsInstance(cmd, FocusCommand)
        self.assertEqual(cmd.display_target, "Samsung S90D")


class ScreenshotRuntimeTargets(unittest.TestCase):
    def test_screenshot_active_sets_target_keyword(self) -> None:
        cmd = parse("+CalFlow+\nscreenshot active").commands[0]
        self.assertIsInstance(cmd, ScreenshotCommand)
        self.assertEqual(cmd.target_keyword, "active")

    def test_screenshot_to_function(self) -> None:
        cmd = parse(
            '+CalFlow+\nscreenshot to("~/x.png")'
        ).commands[0]
        self.assertIsInstance(cmd, ScreenshotCommand)
        self.assertEqual(cmd.path, "~/x.png")

    def test_screenshot_no_args_default_path(self) -> None:
        cmd = parse("+CalFlow+\nscreenshot").commands[0]
        self.assertIsInstance(cmd, ScreenshotCommand)
        self.assertIsNone(cmd.path)


class TypeSystemContract(unittest.TestCase):
    """`{ … }` is for dynamic VALUES only — runtime targets / aliases /
    filters MUST be bare."""

    def test_dynamic_block_with_runtime_target_rejected(self) -> None:
        result = parse("+CalFlow+\nhide {active}")
        self.assertTrue(result.has_errors)
        # Validator emits a single error then returns; AST is empty.
        self.assertEqual(result.commands, [])

    def test_dynamic_block_with_alias_rejected(self) -> None:
        result = parse("+CalFlow+\nhide except({@work})")
        self.assertTrue(result.has_errors)

    def test_dynamic_block_with_filter_rejected(self) -> None:
        result = parse("+CalFlow+\nhide {display(2)}")
        self.assertTrue(result.has_errors)

    def test_dynamic_now_still_works(self) -> None:
        result = parse(
            '+CalFlow+\nopen "https://x.com?d={now}"'
        )
        self.assertFalse(result.has_errors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
