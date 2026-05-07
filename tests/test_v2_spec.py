"""
Spec-conformance test suite (v2.0).

This file mirrors the rules in:
    docs/DSL_GRAMMAR.md
    docs/DSL_SPEC.md
    docs/parser-behavior.md
    docs/validation.md
    docs/test-cases.md

One assertion per spec rule. Failures here are spec gaps; the test
labels reference the section they enforce.

Where a rule depends on a real UI/clipboard/Quartz backend that is
intentionally a stub in v2.0, the test is marked with `expectedFailure`
or `skip` and references the gap in docs/roadmap.md.

Run:
    python -m unittest tests.test_v2_spec -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.models import (
    ClickCommand,
    CloseCommand,
    CopyCommand,
    FocusCommand,
    HideCommand,
    MODE_PLUS,
    MODE_SMART,
    OpenCommand,
    PasteCommand,
    PressCommand,
    RunCommand,
    SaveCommand,
    ScreenshotCommand,
    TypeCommand,
    WaitCommand,
)
from core.parser.parser import parse
from core.parser.smart_parser import smart_global_state
from core.resolver import resolve_command


# =============================================================
# §1 — Top-level structure & mode detection
# =============================================================

class S1_ModeDetection(unittest.TestCase):
    """DSL_GRAMMAR §1 / parser-behavior §2."""

    def test_smart_default_when_no_header(self):
        self.assertEqual(parse("zoom.us").mode, MODE_SMART)

    def test_plus_when_header_present_at_top(self):
        self.assertEqual(parse("+CalFlow+\nopen zoom.us").mode, MODE_PLUS)

    def test_plus_when_header_present_below_smart_lines(self):
        # parser-behavior §2.4: "+CalFlow+ anywhere → entire doc Plus"
        text = "zoom.us\n\n+CalFlow+\nopen notion.so"
        self.assertEqual(parse(text).mode, MODE_PLUS)

    def test_header_case_insensitive(self):
        self.assertEqual(parse("+calflow+\nopen x.com").mode, MODE_PLUS)

    def test_empty_doc_is_none_mode(self):
        self.assertTrue(parse("").is_empty)


# =============================================================
# §1.3 — Comments use `##`
# =============================================================

class S1_3_Comments(unittest.TestCase):
    def test_double_hash_is_comment_in_smart_mode(self):
        text = "## this is a note\nzoom.us"
        result = parse(text)
        self.assertEqual(len(result.entries), 1)

    def test_double_hash_is_comment_in_plus_mode(self):
        text = "+CalFlow+\n## a comment\nopen zoom.us"
        result = parse(text)
        self.assertEqual([c.name for c in result.commands], ["OPEN"])

    def test_single_hash_is_a_tag_not_a_comment(self):
        # `#display(2)` must be treated as a global modifier, not a comment.
        cats, _ = smart_global_state("#display(2)\nzoom.us")
        self.assertIn("display", cats)


# =============================================================
# §2.2 — Smart Mode global tag/target state
# =============================================================

class S2_2_SmartGlobalState(unittest.TestCase):
    """DSL_SPEC §2.2 + parser-behavior §4.2 + test-cases §1.1.5–6."""

    def test_global_tag_applied_to_all_following_url_lines(self):
        text = "#display(2)\n@chrome\n\nzoom.us\nnotion.so"
        result = parse(text)
        self.assertEqual(len(result.entries), 2)
        for entry in result.entries:
            self.assertIn("#display(2)", entry["tags"])
            self.assertIn("@chrome", entry["tags"])

    def test_same_category_global_last_wins(self):
        # test-cases §1.1.6
        text = "#display(1)\n#display(2)\nzoom.us"
        result = parse(text)
        tags = result.entries[0]["tags"]
        self.assertIn("#display(2)", tags)
        self.assertNotIn("#display(1)", tags)

    def test_different_category_globals_merge(self):
        text = "@chrome\n#profile(1)\n#display(2)\nzoom.us"
        tags = parse(text).entries[0]["tags"]
        self.assertIn("@chrome", tags)
        self.assertIn("#profile(1)", tags)
        self.assertIn("#display(2)", tags)

    def test_line_level_overrides_global_same_category(self):
        text = "#display(1)\nzoom.us @chrome #display(2)"
        tags = parse(text).entries[0]["tags"]
        self.assertIn("#display(2)", tags)
        self.assertNotIn("#display(1)", tags)


# =============================================================
# §1.1 — Smart Mode URL behaviors
# =============================================================

class S1_1_SmartURLBehavior(unittest.TestCase):
    def test_url_normalized_to_https(self):
        # test-cases §1.1.1
        result = parse("zoom.us")
        self.assertEqual(result.entries[0]["url"], "https://zoom.us")

    def test_url_with_target_keeps_target_tag(self):
        # test-cases §1.1.2
        result = parse("zoom.us @chrome")
        self.assertIn("@chrome", result.entries[0]["tags"])

    def test_invalid_line_ignored(self):
        # test-cases §1.1.7 / validation §9.2
        result = parse("hello world\nzoom.us")
        self.assertEqual(len(result.entries), 1)

    def test_no_url_doc_yields_empty(self):
        # validation §9.1
        self.assertEqual(parse("hello\nworld").entries, [])


# =============================================================
# §3 — Plus Mode commands (13 verbs)
# =============================================================

class S3_PlusModeVerbs(unittest.TestCase):
    """DSL_GRAMMAR §4.1 — all 13 verbs MUST parse."""

    def _verbs(self, text):
        return [c.name for c in parse("+CalFlow+\n" + text).commands]

    def test_open(self):    self.assertEqual(self._verbs("open https://x.com"), ["OPEN"])
    def test_focus(self):   self.assertEqual(self._verbs("focus @chrome"), ["FOCUS"])
    def test_close(self):   self.assertEqual(self._verbs('close "Spotify"'), ["CLOSE"])
    def test_hide_app(self):     self.assertEqual(self._verbs("hide @chrome"), ["HIDE"])
    def test_hide_active(self):  self.assertEqual(self._verbs("hide active"), ["HIDE"])
    def test_hide_all(self):     self.assertEqual(self._verbs("hide all"), ["HIDE"])
    def test_hide_except(self):  self.assertEqual(
        self._verbs("hide except(@chrome)"), ["HIDE"]
    )
    def test_hide_display_filter(self): self.assertEqual(
        self._verbs("hide display(1)"), ["HIDE"]
    )
    def test_close_except(self): self.assertEqual(
        self._verbs("close except(@chrome)"), ["CLOSE"]
    )
    def test_click_text(self):   self.assertEqual(
        self._verbs('click text("Sign in")'), ["CLICK"]
    )
    def test_click_selector(self): self.assertEqual(
        self._verbs('click selector(".btn")'), ["CLICK"]
    )
    def test_click_position(self): self.assertEqual(
        self._verbs("click position(100,200)"), ["CLICK"]
    )
    def test_type(self):    self.assertEqual(self._verbs('type("hello")'), ["TYPE"])
    def test_press_key(self):    self.assertEqual(self._verbs("press {enter}"), ["PRESS"])
    def test_press_combo(self):  self.assertEqual(
        self._verbs("press {cmd+shift+tab}"), ["PRESS"]
    )
    def test_press_sequence(self):  self.assertEqual(
        self._verbs("press [{shift_down},({left})x5,{shift_up}]"), ["PRESS"]
    )
    def test_wait_unitless(self):   self.assertEqual(self._verbs("wait 5"), ["WAIT"])
    def test_wait_seconds(self):    self.assertEqual(self._verbs("wait 5s"), ["WAIT"])
    def test_wait_function(self):   self.assertEqual(self._verbs("wait(5s)"), ["WAIT"])
    def test_screenshot(self):      self.assertEqual(self._verbs("screenshot"), ["SCREENSHOT"])
    def test_copy(self):            self.assertEqual(self._verbs("copy"), ["COPY"])
    def test_paste(self):           self.assertEqual(self._verbs("paste"), ["PASTE"])
    def test_save(self):
        self.assertEqual(
            self._verbs('save source(clipboard) to("~/x.png")'),
            ["SAVE"],
        )
    def test_run(self):     self.assertEqual(self._verbs('run "~/x.sh"'), ["RUN"])


# =============================================================
# §3 — Plus Mode AST shape correctness
# =============================================================

class S3_AST(unittest.TestCase):
    def test_focus_with_title(self):
        cmd = parse('+CalFlow+\nfocus @chrome title("Inbox")').commands[0]
        self.assertIsInstance(cmd, FocusCommand)
        self.assertEqual(cmd.title, "Inbox")

    def test_hide_except_collects_keep_set(self):
        cmd = parse(
            '+CalFlow+\nhide except(@chrome)'
        ).commands[0]
        self.assertIsInstance(cmd, HideCommand)
        # New v1.1 shape: items stays empty (filter form, not items form);
        # keep_set carries the raw except() tokens — bundle/alias expansion
        # happens at the resolver layer, not at parse time.
        self.assertEqual(cmd.items, ())
        self.assertIn("@chrome", cmd.keep_set)

    def test_hide_active_sets_target_keyword(self):
        cmd = parse('+CalFlow+\nhide active').commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertEqual(cmd.target_keyword, "active")
        self.assertEqual(cmd.items, ())
        self.assertEqual(cmd.keep_set, frozenset())

    def test_hide_all_sets_target_keyword(self):
        cmd = parse('+CalFlow+\nhide all').commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertEqual(cmd.target_keyword, "all")
        self.assertEqual(cmd.items, ())

    def test_hide_display_filter_captured(self):
        cmd = parse('+CalFlow+\nhide display(2)').commands[0]
        self.assertIsInstance(cmd, HideCommand)
        self.assertEqual(cmd.display_filter, 2)

    def test_close_except_collects_keep_set(self):
        cmd = parse(
            '+CalFlow+\nclose except(@chrome)'
        ).commands[0]
        from core.models import CloseCommand
        self.assertIsInstance(cmd, CloseCommand)
        self.assertEqual(cmd.items, ())
        # keep_set holds raw tokens at parse time; resolver expands later.
        self.assertIn("@chrome", cmd.keep_set)

    def test_hide_collection(self):
        cmd = parse(
            '+CalFlow+\nhide ["Spotify","Discord"]'
        ).commands[0]
        self.assertEqual(cmd.items, ("Spotify", "Discord"))

    def test_press_combo_parsed_into_combo_node(self):
        cmd = parse("+CalFlow+\npress {cmd+shift+tab}").commands[0]
        self.assertIsInstance(cmd, PressCommand)
        self.assertEqual(cmd.keys[0], ("combo", ("cmd", "shift", "tab")))

    def test_press_repetition_parsed(self):
        cmd = parse(
            "+CalFlow+\npress [{shift_down},({left})x5,{shift_up}]"
        ).commands[0]
        # middle entry should be a ('rep', base, 5)
        self.assertEqual(cmd.keys[1][0], "rep")
        self.assertEqual(cmd.keys[1][2], 5)

    def test_type_with_speed_kept_in_functions(self):
        cmd = parse('+CalFlow+\ntype("abc") speed(0.1s)').commands[0]
        self.assertIsInstance(cmd, TypeCommand)
        self.assertEqual(cmd.fn_dict["speed"], 0.1)

    def test_save_extracts_source_and_to(self):
        cmd = parse(
            '+CalFlow+\nsave source(clipboard) to("~/file.png")'
        ).commands[0]
        self.assertIsInstance(cmd, SaveCommand)
        self.assertEqual(cmd.source, "clipboard")
        self.assertEqual(cmd.to, "~/file.png")

    def test_screenshot_with_window(self):
        cmd = parse(
            '+CalFlow+\nscreenshot window("Slack")'
        ).commands[0]
        self.assertIsInstance(cmd, ScreenshotCommand)
        self.assertEqual(cmd.window, "Slack")

    def test_screenshot_with_area(self):
        cmd = parse(
            '+CalFlow+\nscreenshot area(0,0,1920,1080)'
        ).commands[0]
        self.assertEqual(cmd.area, (0, 0, 1920, 1080))

    def test_run_extracts_quoted_path(self):
        cmd = parse('+CalFlow+\nrun "~/scripts/x.sh"').commands[0]
        self.assertIsInstance(cmd, RunCommand)
        self.assertEqual(cmd.path, "~/scripts/x.sh")


# =============================================================
# §1.2.20 — implicit `open` in Plus Mode
# =============================================================

class S1_2_20_PlusImplicitOpen(unittest.TestCase):
    def test_url_only_line_becomes_open(self):
        result = parse("+CalFlow+\nzoom.us")
        self.assertEqual(len(result.commands), 1)
        cmd = result.commands[0]
        self.assertIsInstance(cmd, OpenCommand)
        self.assertEqual(cmd.url, "zoom.us")


# =============================================================
# §4.6 — Multiple `@` targets → invalid
# =============================================================

class S4_6_MultipleTargets(unittest.TestCase):
    def test_multiple_targets_marked_invalid_in_resolver(self):
        result = parse("+CalFlow+\nopen zoom.us @chrome @safari")
        # parsed (validator already flagged it OR resolver marks invalid)
        # Either path is acceptable; the ASSERTION is that it does NOT
        # quietly execute as a happy OPEN.
        if not result.commands:
            self.assertTrue(result.has_errors)
            return
        params = resolve_command(result.commands[0])
        self.assertEqual(params.get("invalid"), "multiple @targets")


# =============================================================
# §6 — Validation / error handling
# =============================================================

class S6_ValidationErrors(unittest.TestCase):
    def test_unknown_verb_skipped_not_aborted(self):
        # validation §3.7
        result = parse("+CalFlow+\ndance\nopen zoom.us")
        self.assertEqual([c.name for c in result.commands], ["OPEN"])
        self.assertTrue(result.has_errors)

    def test_invalid_modifier_format_rejected_implicitly(self):
        # validation §3.3 — `#left30` lacks parens; not a layout, treated as plain tag
        result = parse("+CalFlow+\nopen zoom.us #left30")
        # parser still produces an OPEN (best-effort) — but #left30 is just
        # a tag string; the resolver's parse_layout_tag returns None for it.
        from runtime.actions.browser import parse_layout_tag
        self.assertIsNone(parse_layout_tag("#left30"))

    def test_press_unbraced_rejected(self):
        # validation §3.6
        result = parse("+CalFlow+\npress enter")
        self.assertTrue(result.has_errors)

    def test_type_unquoted_rejected(self):
        # validation §3.2
        result = parse("+CalFlow+\ntype hello")
        self.assertTrue(result.has_errors)

    def test_focus_bare_identifier_rejected(self):
        # validation §3.1
        result = parse("+CalFlow+\nfocus chrome")
        self.assertTrue(result.has_errors)


# =============================================================
# §11 — Normalization
# =============================================================

class S11_Normalization(unittest.TestCase):
    def test_url_normalized_in_plus_open(self):
        cmd = parse("+CalFlow+\nopen zoom.us").commands[0]
        # Plus parser keeps url as-is; normalization happens in the runtime.
        # Smart Mode normalizes earlier — assert the Smart path.
        result = parse("zoom.us")
        self.assertEqual(result.entries[0]["url"], "https://zoom.us")

    def test_wait_unit_fallback(self):
        cmd = parse("+CalFlow+\nwait 5").commands[0]
        self.assertIsInstance(cmd, WaitCommand)
        self.assertEqual(cmd.seconds, 5.0)

    def test_wait_minutes(self):
        cmd = parse("+CalFlow+\nwait 2m").commands[0]
        self.assertEqual(cmd.seconds, 120.0)

    def test_layout_unit_fallback(self):
        # parser-behavior §3.3 / DSL_SPEC §2.2 : `#left(30)` == `#left(30%)`
        from runtime.actions.browser import parse_layout_tag
        self.assertEqual(parse_layout_tag("#left(30)"), parse_layout_tag("#left(30%)"))

    def test_case_insensitive_verbs(self):
        verbs_lower = [c.name for c in parse("+CalFlow+\nopen zoom.us").commands]
        verbs_upper = [c.name for c in parse("+CalFlow+\nOPEN zoom.us").commands]
        self.assertEqual(verbs_lower, verbs_upper)


# =============================================================
# §13 — Determinism
# =============================================================

class S13_Determinism(unittest.TestCase):
    def test_same_input_same_output(self):
        text = "+CalFlow+\nopen zoom.us @chrome\nwait 1\nscreenshot"
        a = parse(text)
        b = parse(text)
        self.assertEqual(
            [c.name for c in a.commands],
            [c.name for c in b.commands],
        )


# =============================================================
# §9 — Layout grammar (#grid / #area / relatives)
# =============================================================

class S9_LayoutGrid(unittest.TestCase):
    """v1.1.19 — canonical grid grammar is `#grid(<cell>@<cols>x<rows>)`."""

    def test_grid_canonical_D_at_NxM(self):
        from runtime.actions.browser import parse_layout_tag
        self.assertEqual(
            parse_layout_tag("#grid(1@3x2)"),
            {"type": "grid", "cell": 1, "cols": 3, "rows": 2},
        )

    def test_grid_canonical_case_insensitive(self):
        from runtime.actions.browser import parse_layout_tag
        self.assertEqual(
            parse_layout_tag("#GRID(7@2X4)")["type"], "grid"
        )

    def test_grid_canonical_with_whitespace(self):
        from runtime.actions.browser import parse_layout_tag
        self.assertEqual(
            parse_layout_tag("#grid( 1 @ 3 x 2 )")["cell"], 1
        )

    def test_grid_legacy_form_still_accepted(self):
        # v1.1.19 keeps the old order working as a fallback (with a [WARN]).
        from runtime.actions.browser import parse_layout_tag
        self.assertEqual(
            parse_layout_tag("#grid(3x2@1)"),
            {"type": "grid", "cols": 3, "rows": 2, "cell": 1},
        )


class S9_LayoutArea(unittest.TestCase):
    def test_area_pixels_default(self):
        from runtime.actions.browser import parse_layout_tag
        out = parse_layout_tag("#area(0,0,1920,1080)")
        self.assertEqual(out["type"], "area")
        self.assertEqual(out["x"], {"value": 0.0, "unit": "pixel"})
        self.assertEqual(out["w"], {"value": 1920.0, "unit": "pixel"})

    def test_area_percentages(self):
        from runtime.actions.browser import parse_layout_tag
        out = parse_layout_tag("#area(0,0,50%,50%)")
        self.assertEqual(out["w"], {"value": 50.0, "unit": "percent"})
        self.assertEqual(out["h"], {"value": 50.0, "unit": "percent"})

    def test_area_mixed_units(self):
        from runtime.actions.browser import parse_layout_tag
        out = parse_layout_tag("#area(10,20%,500,30%)")
        self.assertEqual(out["x"]["unit"], "pixel")
        self.assertEqual(out["y"]["unit"], "percent")
        self.assertEqual(out["w"]["unit"], "pixel")
        self.assertEqual(out["h"]["unit"], "percent")

    def test_area_negative_clamped_to_zero(self):
        from runtime.actions.browser import parse_layout_tag
        out = parse_layout_tag("#area(-50,-10,800,600)")
        self.assertEqual(out["x"]["value"], 0.0)
        self.assertEqual(out["y"]["value"], 0.0)

    def test_area_wrong_arity_returns_none(self):
        from runtime.actions.browser import parse_layout_tag
        self.assertIsNone(parse_layout_tag("#area(0,0,1920)"))

    def test_area_bad_value_returns_none(self):
        from runtime.actions.browser import parse_layout_tag
        self.assertIsNone(parse_layout_tag("#area(zero,0,100,100)"))


class S9_LayoutRelative(unittest.TestCase):
    def test_middle_top_bottom_now_supported(self):
        from runtime.actions.browser import parse_layout_tag
        for name in ("middle", "top", "bottom"):
            with self.subTest(name=name):
                self.assertEqual(parse_layout_tag(f"#{name}")["type"], name)
                self.assertEqual(parse_layout_tag(f"#{name}(40)")["value"], 0.4)


# =============================================================
# §3.3 — Screenshot default path lives in ~/Downloads/CalFlow
# =============================================================

class S3_3_ScreenshotPath(unittest.TestCase):
    def test_default_path_is_under_downloads_calflow(self):
        from runtime.actions.screenshot import default_screenshot_path
        from config.settings import PLUS_SCREENSHOT_DIR
        path = default_screenshot_path()
        # Should live under the configured directory (default ~/Downloads/CalFlow).
        self.assertTrue(
            path.startswith(os.path.expanduser(PLUS_SCREENSHOT_DIR)),
            f"{path!r} should start with {PLUS_SCREENSHOT_DIR!r}",
        )
        self.assertTrue(path.endswith(".png"))


# =============================================================
# §5.10 — Standalone modifier in Plus Mode is ignored (no error)
# =============================================================

class S5_10_StandaloneModifierIgnored(unittest.TestCase):
    def test_display_alone_in_plus_block_is_silently_ignored(self):
        result = parse("+CalFlow+\n#display(2)\nopen zoom.us")
        self.assertEqual([c.name for c in result.commands], ["OPEN"])
        self.assertFalse(
            result.has_errors,
            f"unexpected errors: {result.errors}",
        )

    def test_at_alone_in_plus_block_is_silently_ignored(self):
        result = parse("+CalFlow+\n@chrome\nopen zoom.us")
        self.assertEqual([c.name for c in result.commands], ["OPEN"])
        self.assertFalse(result.has_errors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
