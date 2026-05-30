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
    RunCommand,
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




# v1.1.25 — three Plus-Mode-detection tests removed:
#   - test_header_first_line_triggers_plus
#   - test_header_case_insensitive
#   - test_empty_text_is_none_mode (above)
# All three were exact duplicates of S1_ModeDetection in test_v2_spec.py.
# `test_header_anywhere_in_doc_triggers_plus` is kept because the
# substring-match rule (v1.1.6) isn't tested in the spec file.


class PlusModeDetection(unittest.TestCase):
    def test_header_anywhere_in_doc_triggers_plus(self) -> None:
        # Per DSL_GRAMMAR §1.2 (v1.1.6 substring rule), the header
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

    def test_run_btt_named_trigger_command(self) -> None:
        result = parse("+CalFlow+\nrun -btt BTT-ClaudeCoworkTryAgain")
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "btt")
        self.assertEqual(cmd.trigger_name, "BTT-ClaudeCoworkTryAgain")

    def test_run_btt_quoted_named_trigger_command(self) -> None:
        result = parse('+CalFlow+\nrun -btt "BTT Claude Cowork Try Again"')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "btt")
        self.assertEqual(cmd.trigger_name, "BTT Claude Cowork Try Again")

    def test_run_btt_braced_quoted_trigger_command(self) -> None:
        result = parse('+CalFlow+\nrun -btt {"BTT-ClaudeCoworkTryAgain"}')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "btt")
        self.assertEqual(cmd.trigger_name, '{"BTT-ClaudeCoworkTryAgain"}')

    def test_run_btt_single_quoted_braced_trigger_command(self) -> None:
        result = parse('+CalFlow+\nrun -btt \'{"BTT-ClaudeCoworkTryAgain"}\'')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "btt")
        self.assertEqual(cmd.trigger_name, '{"BTT-ClaudeCoworkTryAgain"}')

    def test_run_applescript_multiline_command(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run -applescript\n'
            'tell application "Finder"\n'
            '  activate\n'
            'end tell\n'
            'end run\n'
        )
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "applescript")
        self.assertEqual(
            cmd.script,
            'tell application "Finder"\n  activate\nend tell',
        )

    def test_run_shortcut_command(self) -> None:
        result = parse('+CalFlow+\nrun -shortcut "Start Focus" "deep work"')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "shortcut")
        self.assertEqual(cmd.shortcut_name, "Start Focus")
        self.assertEqual(cmd.shortcut_input, "deep work")

    def test_run_alfred_command(self) -> None:
        result = parse(
            '+CalFlow+\nrun -alfred "com.example.workflow" "try-again" "now"'
        )
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "alfred")
        self.assertEqual(cmd.alfred_bundle_id, "com.example.workflow")
        self.assertEqual(cmd.alfred_trigger, "try-again")
        self.assertEqual(cmd.alfred_argument, "now")

    def test_run_alfred_combined_bundle_trigger_command(self) -> None:
        result = parse('+CalFlow+\nrun -alfred "com.example.workflow/try-again" "now"')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "alfred")
        self.assertEqual(cmd.alfred_bundle_id, "com.example.workflow")
        self.assertEqual(cmd.alfred_trigger, "try-again")
        self.assertEqual(cmd.alfred_argument, "now")

    def test_run_btt_function_command(self) -> None:
        result = parse('+CalFlow+\nrun btt("BTT-ClaudeCoworkTryAgain")')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "btt")
        self.assertEqual(cmd.trigger_name, "BTT-ClaudeCoworkTryAgain")

    def test_run_shortcut_function_command(self) -> None:
        result = parse('+CalFlow+\nrun shortcut("Start Focus") input("deep work")')
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "shortcut")
        self.assertEqual(cmd.shortcut_name, "Start Focus")
        self.assertEqual(cmd.shortcut_input, "deep work")

    def test_run_alfred_function_command(self) -> None:
        result = parse(
            '+CalFlow+\nrun alfred("com.example.workflow", "try-again") input("now")'
        )
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "alfred")
        self.assertEqual(cmd.alfred_bundle_id, "com.example.workflow")
        self.assertEqual(cmd.alfred_trigger, "try-again")
        self.assertEqual(cmd.alfred_argument, "now")

    def test_run_applescript_plus_block_with_handler(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run applescript timeout(10) if(error) notify(result)\n'
            '+++\n'
            'display dialog "hello"\n'
            '+++\n'
        )
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.backend, "applescript")
        self.assertEqual(cmd.timeout, 10.0)
        self.assertEqual(cmd.script, 'display dialog "hello"')
        self.assertEqual(cmd.run_handlers, (("error", "notify", "result"),))

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
            'SCREENSHOT to("/tmp/out.png")\n'
        )
        result = parse(text)
        verbs = [c.name for c in result.commands]
        self.assertEqual(verbs, ["OPEN", "WAIT", "TYPE", "SCREENSHOT"])
        self.assertFalse(result.has_errors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
