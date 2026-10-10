from __future__ import annotations

import unittest
from unittest.mock import patch

from core.parser.parser import parse
from core.parser.smart_parser import extract_tags, extract_targets
from core.resolver import resolve_command


class SmartAutofillSafetyTests(unittest.TestCase):
    # v1.5.5 - audit regressions: URL data and timing must not enable autofill.
    def test_timing_and_force_preserve_inherited_autofill_opt_out(self):
        for modifier in ("#slow", "#force"):
            for source in (
                f"#no-autofill\nhttps://example.com {modifier}",
                f"#no-autofill\n{modifier}\nhttps://example.com",
                f"#no-autofill {modifier}\nhttps://example.com",
            ):
                with self.subTest(source=source):
                    tags = parse(source).entries[0]["tags"]
                    self.assertIn("#no-autofill", tags)
                    self.assertIn(modifier, tags)

    def test_url_payload_is_not_a_modifier(self):
        for url in (
            "https://example.com/#submit", "https://example.com/?x=#submit",
            "example.com#submit", "example.com?x=#submit",
            "https://example.com/@chrome/#force", "https://example.com/#left(50)",
        ):
            with self.subTest(url=url):
                self.assertEqual(extract_tags(url), set())
                self.assertEqual(extract_targets(url), [])
                self.assertEqual(parse(url).entries[0]["tags"], set())

    def test_explicit_modifiers_after_url_still_work(self):
        source = "https://example.com/#submit @safari #no-autofill #slow"
        tags = parse(source).entries[0]["tags"]
        self.assertEqual(tags, {"@safari", "#no-autofill", "#slow"})

    def test_url_shaped_display_name_is_not_removed_from_modifier(self):
        self.assertEqual(
            extract_tags('https://example.com #display("Panel.example")'),
            {'#display("panel.example")'},
        )

    def test_bare_domain_query_is_preserved_when_masking_url_data(self):
        source = "example.com?x=#submit"
        self.assertEqual(parse(source).entries[0]["url"], "https://" + source)

    def test_autofill_opt_out_survives_to_executor(self):
        from runtime.executor import execute_entries
        with patch("runtime.executor.open_target") as opened, \
             patch("runtime.executor.trigger_autofill") as autofill, \
             patch("runtime.executor.record_action"), \
             patch("runtime.executor.time.sleep"), \
             patch("core.resolver.resolver.AUTOFILL_MODE", "auto"), \
             patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")) as process:
            parsed = parse("#no-autofill\nhttps://example.com/#submit #slow")
            execute_entries(parsed.entries, global_tags=set(), trust_level="self")
        opened.assert_called_once()
        autofill.assert_not_called()
        process.assert_not_called()

    def test_url_fragment_does_not_upgrade_fill_to_submit(self):
        from runtime.executor import execute_entries
        with patch("runtime.executor.open_target"), \
             patch("runtime.executor.trigger_autofill") as autofill, \
             patch("runtime.executor.record_action"), \
             patch("runtime.executor.time.sleep"), \
             patch("core.resolver.resolver.AUTOFILL_MODE", "semi-auto"), \
             patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")) as process:
            parsed = parse("https://example.com/#submit")
            execute_entries(parsed.entries, global_tags=set(), trust_level="self")
        autofill.assert_called_once_with(mode="fill")
        process.assert_not_called()

    def test_explicit_autofill_override_still_wins(self):
        tags = parse("#no-autofill\nhttps://example.com #submit").entries[0]["tags"]
        self.assertIn("#submit", tags)
        self.assertNotIn("#no-autofill", tags)


class HideScopeSafetyTests(unittest.TestCase):
    # v1.5.5 - audit regressions: invalid scope must never become hide-all.
    def assert_rejected(self, source):
        result = parse("+CalFlow+\n" + source)
        self.assertEqual(result.mode, "plus")
        self.assertTrue(result.errors, source)
        self.assertEqual(result.commands, [], source)

    def test_explicit_targets_cannot_be_combined_with_filters(self):
        for source in (
            'hide @chrome display(2)', 'hide "Notes" display(2)',
            'hide ["Notes"] display(2)', 'hide @chrome except("Notes")',
            'hide active except("Notes")', 'hide active @chrome display(2)',
            'hide all @chrome',
        ):
            with self.subTest(source=source):
                self.assert_rejected(source)

    def test_hash_display_filters_are_rejected_in_hide(self):
        for source in ('hide active #display(2)', 'hide @chrome #display(2)',
                       'hide active #display("DELL")', 'hide active #display'):
            with self.subTest(source=source):
                self.assert_rejected(source)

    def test_empty_except_filter_is_rejected(self):
        for argument in ('', '""', '" "', '"\\t"', ',', '[]', '[""]',
                         '["Notes", ""]'):
            with self.subTest(argument=argument):
                self.assert_rejected(f"hide except({argument})")

    def test_empty_invalid_and_nonfinite_displays_are_rejected(self):
        for argument in ('', '""', '" "', '"\\t"', '0', '-1', '1.5',
                         'nan', 'inf', '-inf', '1e309', '2,3', 'bogus', '1s',
                         '"DELL","Other"', '"\u00b2"'):
            for prefix in ('hide', 'hide active', 'focus "Notes"',
                           'open https://example.com', 'screenshot'):
                with self.subTest(prefix=prefix, argument=argument):
                    self.assert_rejected(f"{prefix} display({argument})")

    def test_invalid_display_does_not_discard_valid_neighbors(self):
        result = parse('+CalFlow+\nwait 1\nfocus "Notes" display(inf)\nwait 2')
        self.assertEqual(result.mode, "plus")
        self.assertEqual([command.seconds for command in result.commands], [1.0, 2.0])
        self.assertEqual([error.line_no for error in result.errors], [2])

    def test_supported_display_forms_keep_executor_contract(self):
        for argument, display in (('2', 2), ('"DELL"', 'DELL'), ('ext', 'ext'),
                                  ('external', 'external')):
            for primary in ('', 'active ', 'all ', 'except(active) '):
                with self.subTest(primary=primary, argument=argument):
                    result = parse(f"+CalFlow+\nhide {primary}display({argument})")
                    self.assertFalse(result.errors)
                    params = resolve_command(result.commands[0])
                    self.assertEqual(params["display_filter"], display)
                    self.assertEqual(params.get("target_keyword"),
                                     "active" if primary == 'active ' else None)
                    if primary == 'except(active) ':
                        self.assertIn('active', params["keep"])

    def test_plain_target_and_list_forms_still_work(self):
        for source in ('hide @chrome', 'hide "Notes"', 'hide [active,"Notes"]',
                       'hide except(@chrome)', 'hide except(["Notes","Safari"])'):
            with self.subTest(source=source):
                result = parse("+CalFlow+\n" + source)
                self.assertFalse(result.errors)
                self.assertEqual(len(result.commands), 1)


if __name__ == "__main__":
    unittest.main()
