"""
Dynamic expression tests (v2.0.1).

Covers core/dynamic.py — the {…} pipeline grammar from
docs/DSL_GRAMMAR.md §7 + Rule Update.md.

Time-dependent assertions use a frozen `_now` so the suite is
deterministic on every run.

Run:
    python -m unittest tests.test_v2_dynamic -v
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.dynamic import resolve_dynamic, resolve_dynamic_expr


# Anchor: 2026-05-15 13:42:07
NOW = datetime(2026, 5, 15, 13, 42, 7)


class Base(unittest.TestCase):
    def test_now_default_format(self):
        self.assertEqual(resolve_dynamic_expr("now", _now=NOW), "2026-05-15")

    def test_now_minus_7d(self):
        self.assertEqual(resolve_dynamic_expr("now-7d", _now=NOW), "2026-05-08")

    def test_now_plus_2h_format_HHmm(self):
        # offset by 2h → 15:42; format HH:mm
        self.assertEqual(
            resolve_dynamic_expr("now+2h>HH:mm", _now=NOW), "15:42"
        )

    def test_now_minus_15m(self):
        # 13:42 - 15m = 13:27
        self.assertEqual(
            resolve_dynamic_expr("now-15m>HH:mm", _now=NOW), "13:27"
        )

    def test_now_minus_1mo(self):
        self.assertEqual(
            resolve_dynamic_expr("now-1mo", _now=NOW), "2026-04-15"
        )

    def test_now_plus_1y(self):
        self.assertEqual(
            resolve_dynamic_expr("now+1y", _now=NOW), "2027-05-15"
        )

    def test_unknown_unit_returns_unchanged(self):
        # `1x` is not a valid unit
        self.assertEqual(
            resolve_dynamic_expr("now-1x", _now=NOW), "{now-1x}"
        )


class Transforms(unittest.TestCase):
    def test_start_of_month(self):
        self.assertEqual(
            resolve_dynamic_expr("now>start_of_month", _now=NOW),
            "2026-05-01",
        )

    def test_end_of_month(self):
        self.assertEqual(
            resolve_dynamic_expr("now>end_of_month", _now=NOW),
            "2026-05-31",
        )

    def test_offset_then_transform(self):
        # April 2026 → end_of_month = April 30
        self.assertEqual(
            resolve_dynamic_expr("now-1mo>end_of_month", _now=NOW),
            "2026-04-30",
        )

    def test_start_of_week(self):
        # 2026-05-15 is a Friday; ISO week starts Monday → 2026-05-11
        self.assertEqual(
            resolve_dynamic_expr("now>start_of_week", _now=NOW),
            "2026-05-11",
        )

    def test_end_of_week(self):
        # Sunday of that ISO week → 2026-05-17
        self.assertEqual(
            resolve_dynamic_expr("now>end_of_week", _now=NOW),
            "2026-05-17",
        )

    def test_unknown_transform_skipped(self):
        # bogus transform should be ignored, not crash
        self.assertEqual(
            resolve_dynamic_expr("now>nonsense", _now=NOW),
            "2026-05-15",
        )


class FormatStage(unittest.TestCase):
    def test_shorthand_format(self):
        self.assertEqual(
            resolve_dynamic_expr("now>YYYY-MM-DD", _now=NOW), "2026-05-15"
        )

    def test_explicit_format(self):
        self.assertEqual(
            resolve_dynamic_expr('now>format("YYYY-MM-DD")', _now=NOW),
            "2026-05-15",
        )

    def test_yy_two_digit_year(self):
        self.assertEqual(
            resolve_dynamic_expr("now>YY-MM-DD", _now=NOW), "26-05-15"
        )

    def test_full_pipeline(self):
        self.assertEqual(
            resolve_dynamic_expr(
                "now-1mo>end_of_month>YYYY-MM-DD", _now=NOW
            ),
            "2026-04-30",
        )


class TextLevel(unittest.TestCase):
    def test_resolve_dynamic_substitutes_inside_text(self):
        self.assertEqual(
            resolve_dynamic("~/Reports/{now>YYYY-MM-DD}.png", _now=NOW),
            "~/Reports/2026-05-15.png",
        )

    def test_url_with_two_dynamic_blocks(self):
        url = "report.com?from={now-7d}&to={now}"
        self.assertEqual(
            resolve_dynamic(url, _now=NOW),
            "report.com?from=2026-05-08&to=2026-05-15",
        )

    def test_text_without_dynamic_blocks_passes_through(self):
        self.assertEqual(
            resolve_dynamic("hello world", _now=NOW), "hello world"
        )

    def test_none_passes_through(self):
        self.assertIsNone(resolve_dynamic(None, _now=NOW))


class LegacyColonRejected(unittest.TestCase):
    def test_colon_separator_returns_unchanged_with_warning(self):
        # Legacy `{now:YYYY-MM-DD}` form is NOT supported (Rule Update.md
        # design constraint). The expression is returned untouched so the
        # rest of the user's text is preserved.
        out = resolve_dynamic_expr("now:YYYY-MM-DD", _now=NOW)
        self.assertEqual(out, "{now:YYYY-MM-DD}")


class SmartModeDynamic(unittest.TestCase):
    """Smart Mode URL extraction + executor must honor dynamic blocks."""

    def test_smart_url_extracts_with_tight_dynamic_block(self):
        from core.parser.smart_parser import URL_PATTERN
        out = URL_PATTERN.findall("https://x.com?d={now}")
        self.assertEqual(out, ["https://x.com?d={now}"])

    def test_smart_url_extracts_with_spaced_dynamic_block(self):
        from core.parser.smart_parser import URL_PATTERN
        out = URL_PATTERN.findall("https://x.com?d={now > YYYY-MM-DD}")
        self.assertEqual(out, ["https://x.com?d={now > YYYY-MM-DD}"])

    def test_smart_url_extracts_with_two_dynamic_blocks(self):
        from core.parser.smart_parser import URL_PATTERN
        out = URL_PATTERN.findall("https://x.com?from={now-7d}&to={now}")
        self.assertEqual(out, ["https://x.com?from={now-7d}&to={now}"])

    def test_smart_executor_substitutes_dynamic_in_url(self):
        # Patch open_target so we can capture what would be opened.
        import runtime.executor as ex
        captured = {}

        def fake_open(url=None, app=None, layout=None):
            captured["url"] = url

        orig_open = ex.open_target
        orig_sleep = ex.time.sleep
        import runtime.actions.autofill as af
        orig_fill = af.trigger_autofill
        try:
            ex.open_target = fake_open
            ex.time.sleep = lambda *_a, **_k: None
            af.trigger_autofill = lambda mode="fill": None

            # Patch datetime so result is deterministic
            import core.dynamic as d
            from unittest.mock import patch
            with patch.object(d, "datetime") as m:
                m.now.return_value = NOW
                from core.parser.parser import parse
                result = parse("https://x.com?d={now > YYYY-MM-DD}")
                ex.execute_entries(result.entries, global_tags=set(), debug=False)
        finally:
            ex.open_target = orig_open
            ex.time.sleep = orig_sleep
            af.trigger_autofill = orig_fill

        self.assertEqual(captured.get("url"), "https://x.com?d=2026-05-15")


class WhitespaceTolerance(unittest.TestCase):
    """Spaced and tight forms of the pipeline operator are equivalent."""

    def test_tight_form(self):
        self.assertEqual(
            resolve_dynamic_expr("now-1mo>end_of_month", _now=NOW),
            "2026-04-30",
        )

    def test_spaced_form(self):
        self.assertEqual(
            resolve_dynamic_expr("now-1mo > end_of_month", _now=NOW),
            "2026-04-30",
        )

    def test_mixed_spacing(self):
        # Reader-friendly examples may have inconsistent spacing; both
        # forms must parse identically.
        self.assertEqual(
            resolve_dynamic_expr("now-1mo > end_of_month>YYYY-MM-DD", _now=NOW),
            "2026-04-30",
        )

    def test_spaces_inside_text_blocks(self):
        self.assertEqual(
            resolve_dynamic("~/Reports/{now > YYYY-MM-DD}.png", _now=NOW),
            "~/Reports/2026-05-15.png",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
