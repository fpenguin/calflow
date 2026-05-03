"""
v2.0 validator unit tests.

Exercises the grammar rules that core.validator enforces before AST
construction. Pure-function tests — zero IO.

Run:
    python -m unittest tests.test_v2_validator -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.validator import KNOWN_COMMANDS, validate_plus_block, validate_plus_line


class ValidLines(unittest.TestCase):
    def test_open_url(self) -> None:
        self.assertEqual(validate_plus_line("OPEN https://example.com", 1), [])

    def test_open_with_target_and_tags(self) -> None:
        self.assertEqual(
            validate_plus_line("OPEN https://example.com @chrome #left(50%)", 1),
            [],
        )

    def test_click_selector_function_call(self) -> None:
        self.assertEqual(validate_plus_line('click selector("#login")', 1), [])

    def test_click_text_function_call(self) -> None:
        self.assertEqual(validate_plus_line('click text("Sign in")', 1), [])

    def test_click_coords(self) -> None:
        self.assertEqual(validate_plus_line("CLICK 100,200", 1), [])

    def test_type_quoted(self) -> None:
        self.assertEqual(validate_plus_line('TYPE "hello"', 1), [])

    def test_wait_number(self) -> None:
        self.assertEqual(validate_plus_line("WAIT 2", 1), [])

    def test_screenshot_no_args(self) -> None:
        self.assertEqual(validate_plus_line("SCREENSHOT", 1), [])

    def test_screenshot_with_path(self) -> None:
        self.assertEqual(validate_plus_line("SCREENSHOT /tmp/x.png", 1), [])


class InvalidLines(unittest.TestCase):
    def test_unknown_verb(self) -> None:
        errs = validate_plus_line("DANCE", 7)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].line_no, 7)
        self.assertIn("unknown command", errs[0].message)

    def test_open_missing_arg(self) -> None:
        errs = validate_plus_line("OPEN", 3)
        self.assertEqual(len(errs), 1)

    def test_open_bad_url(self) -> None:
        errs = validate_plus_line("OPEN notaurl", 4)
        self.assertEqual(len(errs), 1)

    def test_click_bad_target(self) -> None:
        errs = validate_plus_line("CLICK !!!", 5)
        self.assertEqual(len(errs), 1)

    def test_type_unquoted(self) -> None:
        errs = validate_plus_line("TYPE hello", 6)
        self.assertEqual(len(errs), 1)

    def test_wait_non_numeric(self) -> None:
        errs = validate_plus_line("WAIT later", 8)
        self.assertEqual(len(errs), 1)


class BlockLevel(unittest.TestCase):
    def test_known_commands_table_complete(self) -> None:
        for verb in ("OPEN", "CLICK", "TYPE", "WAIT", "SCREENSHOT"):
            self.assertIn(verb, KNOWN_COMMANDS)

    def test_block_with_mixed_validity(self) -> None:
        lines = [
            "OPEN https://ok.com",
            "DANCE",
            "WAIT 1",
        ]
        errs = validate_plus_block(lines)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].line_no, 2)

    def test_blank_and_comment_lines_ignored(self) -> None:
        # Per spec, comments use `##` (single `#` is a tag).
        lines = ["", "## a comment", "OPEN https://x.com"]
        self.assertEqual(validate_plus_block(lines), [])


# =========================================================
# v1.1.1 — HIDE / CLOSE redesign
# =========================================================

class HideCloseV1_1_1(unittest.TestCase):
    """v1.1.1 — `hide` / `close` shapes, hard-fails, and stub filters."""

    # ── HIDE: new accepted forms ─────────────────────────
    def test_hide_bare_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide", 1), [])

    def test_hide_app_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide @chrome", 1), [])

    def test_hide_quoted_is_valid(self) -> None:
        self.assertEqual(validate_plus_line('hide "Spotify"', 1), [])

    def test_hide_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('hide ["Spotify","Discord"]', 1), []
        )

    def test_hide_except_target_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide except(@work)", 1), [])

    def test_hide_except_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('hide except(["Slack","Notion"])', 1), []
        )

    def test_hide_display_filter_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide display(2)", 1), [])

    def test_hide_except_with_display_filter_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line("hide except(@work) display(2)", 1), []
        )

    # ── HIDE: hard-fails for old (v1.0) syntax ───────────
    def test_hide_all_is_hard_fail(self) -> None:
        errs = validate_plus_line("hide all", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1", errs[0].message)
        self.assertIn("except(@bundle)", errs[0].message)

    def test_hide_all_except_is_hard_fail(self) -> None:
        errs = validate_plus_line("hide all except @work", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1", errs[0].message)

    # ── CLOSE: new accepted forms ────────────────────────
    def test_close_app_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("close @chrome", 1), [])

    def test_close_quoted_is_valid(self) -> None:
        self.assertEqual(validate_plus_line('close "Spotify"', 1), [])

    def test_close_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('close ["Spotify","Discord"]', 1), []
        )

    def test_close_except_target_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("close except(@work)", 1), [])

    def test_close_except_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('close except(["Slack","Notion"])', 1), []
        )

    # ── CLOSE: bare `close` rejected ─────────────────────
    def test_close_bare_is_rejected(self) -> None:
        errs = validate_plus_line("close", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("Bare `close`", errs[0].message)

    # ── FOCUS: display() rejected ────────────────────────
    def test_focus_display_is_rejected(self) -> None:
        errs = validate_plus_line("focus @chrome display(2)", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("display", errs[0].message.lower())
        self.assertIn("HIDE-only", errs[0].message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
