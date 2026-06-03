from __future__ import annotations

import unittest
from datetime import date


class MenubarIconTests(unittest.TestCase):
    def test_date_icon_labels_use_uppercase_month_and_day(self) -> None:
        try:
            from cli.menubar import _date_icon_labels
        except ImportError as exc:
            self.skipTest(f"pyobjc not installed: {exc}")

        self.assertEqual(_date_icon_labels(date(2026, 6, 3)), ("JUN", "3"))

    def test_calendar_plus_fallback_asset_exists(self) -> None:
        from runtime.menubar import CALENDAR_PLUS_SVG

        self.assertTrue(CALENDAR_PLUS_SVG.exists())
        self.assertIn("calendar plus", CALENDAR_PLUS_SVG.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
