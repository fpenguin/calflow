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

    def test_screenshot_with_to(self) -> None:
        # v1.1.2 — canonical sink is `to("…")`
        self.assertEqual(
            validate_plus_line('SCREENSHOT to("/tmp/x.png")', 1), []
        )

    def test_run_btt_named_trigger(self) -> None:
        self.assertEqual(
            validate_plus_line("run -btt BTT-ClaudeCoworkTryAgain", 1),
            [],
        )

    def test_run_btt_quoted_named_trigger(self) -> None:
        self.assertEqual(
            validate_plus_line('run -btt "BTT Claude Cowork Try Again"', 1),
            [],
        )

    def test_run_btt_braced_named_trigger(self) -> None:
        self.assertEqual(
            validate_plus_line('run -btt {"BTT-ClaudeCoworkTryAgain"}', 1),
            [],
        )

    def test_run_applescript_quoted_script(self) -> None:
        self.assertEqual(
            validate_plus_line('run -applescript "tell app \\"Finder\\" to activate"', 1),
            [],
        )

    def test_run_shortcut(self) -> None:
        self.assertEqual(
            validate_plus_line('run -shortcut "Start Focus" "deep work"', 1),
            [],
        )

    def test_run_alfred(self) -> None:
        self.assertEqual(
            validate_plus_line(
                'run -alfred "com.example.workflow" "try-again" "now"', 1
            ),
            [],
        )

    def test_run_alfred_combined_bundle_trigger(self) -> None:
        self.assertEqual(
            validate_plus_line('run -alfred "com.example.workflow/try-again" "now"', 1),
            [],
        )


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

    def test_run_btt_unquoted_trigger_with_spaces_rejected(self) -> None:
        errs = validate_plus_line("run -btt My Trigger", 9)
        self.assertEqual(len(errs), 1)
        self.assertIn("with spaces must be quoted", errs[0].message)

    def test_run_alfred_requires_trigger(self) -> None:
        errs = validate_plus_line('run -alfred "com.example.workflow"', 9)
        self.assertEqual(len(errs), 1)
        self.assertIn("bundle id and external trigger id", errs[0].message)


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
# v1.1.2 — HIDE / CLOSE / FOCUS / SCREENSHOT type system
# =========================================================

class HideCloseV1_1_2(unittest.TestCase):
    """v1.1.2 — runtime-target keywords, type-system contract, hard-fails."""

    # ── HIDE: runtime targets + new accepted forms ───────
    def test_hide_active(self) -> None:
        self.assertEqual(validate_plus_line("hide active", 1), [])

    def test_hide_all(self) -> None:
        self.assertEqual(validate_plus_line("hide all", 1), [])

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

    def test_hide_except_active_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide except(active)", 1), [])

    def test_hide_except_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('hide except(["Slack","Notion"])', 1), []
        )

    def test_hide_display_filter_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("hide display(2)", 1), [])

    def test_hide_display_named_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('hide display("Samsung S90D")', 1), []
        )

    def test_hide_except_with_display_filter_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line("hide except(@work) display(2)", 1), []
        )

    # ── HIDE: hard-fails ─────────────────────────────────
    def test_hide_bare_is_hard_fail(self) -> None:
        errs = validate_plus_line("hide", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1.2", errs[0].message)
        self.assertIn("hide except(active)", errs[0].message)

    def test_hide_all_except_is_hard_fail(self) -> None:
        errs = validate_plus_line("hide all except @work", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1", errs[0].message)

    # ── CLOSE: runtime targets + new accepted forms ──────
    def test_close_active(self) -> None:
        self.assertEqual(validate_plus_line("close active", 1), [])

    def test_close_all(self) -> None:
        self.assertEqual(validate_plus_line("close all", 1), [])

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

    def test_close_except_active_is_valid(self) -> None:
        self.assertEqual(validate_plus_line("close except(active)", 1), [])

    def test_close_except_list_is_valid(self) -> None:
        self.assertEqual(
            validate_plus_line('close except(["Slack","Notion"])', 1), []
        )

    # ── CLOSE: bare `close` rejected ─────────────────────
    def test_close_bare_is_rejected(self) -> None:
        errs = validate_plus_line("close", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("Bare `close`", errs[0].message)

    # ── FOCUS: display() now ACCEPTED ────────────────────
    def test_focus_display_is_accepted(self) -> None:
        # v1.1.2 — focus @app display(N) moves the app to display N.
        self.assertEqual(
            validate_plus_line("focus @chrome display(2)", 1), []
        )

    def test_focus_active_is_accepted(self) -> None:
        # `focus active` is a no-op runtime target — accepted by validator.
        self.assertEqual(validate_plus_line("focus active", 1), [])

    # ── SCREENSHOT: positional path REJECTED ─────────────
    def test_screenshot_positional_path_rejected(self) -> None:
        errs = validate_plus_line("screenshot /tmp/x.png", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1.2", errs[0].message)
        self.assertIn("to(", errs[0].message)

    def test_screenshot_quoted_positional_rejected(self) -> None:
        errs = validate_plus_line('screenshot "/tmp/x.png"', 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("removed in v1.1.2", errs[0].message)

    def test_screenshot_to_function_accepted(self) -> None:
        self.assertEqual(
            validate_plus_line('screenshot to("/tmp/x.png")', 1), []
        )

    def test_screenshot_active_accepted(self) -> None:
        self.assertEqual(validate_plus_line("screenshot active", 1), [])

    # ── Type-system contract: {} is for VALUES only ──────
    def test_dynamic_block_with_runtime_target_rejected(self) -> None:
        errs = validate_plus_line("hide {active}", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("`{ … }` is for dynamic VALUE expressions only",
                      errs[0].message)

    def test_dynamic_block_with_alias_rejected(self) -> None:
        errs = validate_plus_line("hide except({@work})", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("VALUE expressions only", errs[0].message)

    def test_dynamic_block_with_filter_rejected(self) -> None:
        errs = validate_plus_line("hide {display(2)}", 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("VALUE expressions only", errs[0].message)

    def test_dynamic_block_with_now_still_works(self) -> None:
        # The whole point — `{now}` and friends MUST keep working.
        self.assertEqual(
            validate_plus_line('open "https://x.com?d={now}"', 1), []
        )

    # ── WAIT: v1.1.2 accepts hours ───────────────────────
    def test_wait_hours(self) -> None:
        self.assertEqual(validate_plus_line("wait 1h", 1), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
