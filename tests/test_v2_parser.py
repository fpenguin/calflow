"""
v2.0 parser & dispatcher regression tests.

Covers:
- mode detection (Smart vs Plus)
- Smart Mode entry extraction unchanged from v1.0
- Plus Mode AST construction
- Validator surfaces useful errors
- ParseResult invariants

Run:
    python -m unittest tests.test_v2_parser -v
"""

from __future__ import annotations

import os
import sys
import unittest

# Make project root importable when running directly.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.models import (
    ClickCommand,
    MODE_PLUS,
    MODE_SMART,
    OpenCommand,
    ScreenshotCommand,
    TypeCommand,
    WaitCommand,
)
from core.parser.parser import parse


class SmartModeRegression(unittest.TestCase):
    """Smart Mode behavior must match v1.0 contract."""

    def test_plain_url_extracted(self) -> None:
        result = parse("zoom.us")
        self.assertEqual(result.mode, MODE_SMART)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0]["url"], "https://zoom.us")

    def test_tagged_url_keeps_tags(self) -> None:
        result = parse("zoom.us #left(50%) #force")
        self.assertEqual(result.mode, MODE_SMART)
        self.assertEqual(len(result.entries), 1)
        self.assertIn("#force", result.entries[0]["tags"])

    def test_empty_text_is_none_mode(self) -> None:
        result = parse("")
        self.assertTrue(result.is_empty)


class PlusModeDetection(unittest.TestCase):
    def test_header_first_line_triggers_plus(self) -> None:
        text = "+CalFlow+\nOPEN https://example.com"
        self.assertEqual(parse(text).mode, MODE_PLUS)

    def test_header_case_insensitive(self) -> None:
        text = "+calflow+\nWAIT 1"
        self.assertEqual(parse(text).mode, MODE_PLUS)

    def test_header_anywhere_in_doc_triggers_plus(self) -> None:
        # Per DSL_GRAMMAR §1.2 / parser-behavior §2.4, the header
        # switches the WHOLE document to Plus Mode regardless of position.
        text = "zoom.us\n\n+CalFlow+\nopen notion.so"
        self.assertEqual(parse(text).mode, MODE_PLUS)


class PlusModeAST(unittest.TestCase):
    def test_open_command_built(self) -> None:
        result = parse("+CalFlow+\nOPEN https://example.com @chrome #left(50%)")
        self.assertEqual(result.mode, MODE_PLUS)
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, OpenCommand)
        self.assertEqual(cmd.url, "https://example.com")
        self.assertEqual(cmd.app, "@chrome")
        self.assertIn("#left(50%)", cmd.tags)

    def test_click_coordinates_command(self) -> None:
        result = parse("+CalFlow+\nCLICK 100,200")
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, ClickCommand)
        self.assertEqual(cmd.x, 100)
        self.assertEqual(cmd.y, 200)

    def test_click_selector_function_call(self) -> None:
        # Spec-preferred form: click selector("…")
        result = parse('+CalFlow+\nclick selector("#login-button")')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, ClickCommand)
        self.assertEqual(cmd.selector, "#login-button")

    def test_click_text_function_call(self) -> None:
        result = parse('+CalFlow+\nclick text("Sign in")')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, ClickCommand)
        self.assertEqual(cmd.text, "Sign in")

    def test_type_quoted_text(self) -> None:
        result = parse('+CalFlow+\nTYPE "hello world"')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, TypeCommand)
        self.assertEqual(cmd.text, "hello world")

    def test_wait_seconds(self) -> None:
        result = parse("+CalFlow+\nWAIT 3")
        cmd = result.commands[0]
        self.assertIsInstance(cmd, WaitCommand)
        self.assertEqual(cmd.seconds, 3.0)

    def test_screenshot_optional_path(self) -> None:
        result = parse("+CalFlow+\nSCREENSHOT")
        cmd = result.commands[0]
        self.assertIsInstance(cmd, ScreenshotCommand)
        self.assertIsNone(cmd.path)

    def test_unknown_verb_yields_error_and_no_command(self) -> None:
        result = parse("+CalFlow+\nDANCE")
        self.assertTrue(result.has_errors)
        self.assertEqual(result.commands, [])

    def test_open_invalid_url_validated(self) -> None:
        result = parse("+CalFlow+\nOPEN notaurl")
        self.assertTrue(result.has_errors)


class PlusModeBlock(unittest.TestCase):
    def test_full_block(self) -> None:
        text = (
            "+CalFlow+\n"
            "OPEN https://example.com @chrome\n"
            "WAIT 1\n"
            'TYPE "hello"\n'
            "SCREENSHOT /tmp/out.png\n"
        )
        result = parse(text)
        verbs = [c.name for c in result.commands]
        self.assertEqual(verbs, ["OPEN", "WAIT", "TYPE", "SCREENSHOT"])
        self.assertFalse(result.has_errors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
