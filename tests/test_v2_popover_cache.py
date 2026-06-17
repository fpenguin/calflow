from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from state import popover_cache as pc


class PopoverCacheTests(unittest.TestCase):
    def test_round_trip_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "popover_cache.json"
            pc.save_cache({
                "status": {"ok": True},
                "stats": {"actions_run": 3},
                "upcoming": {"events": []},
                "missed": {"events": []},
            }, path=path)
            data = pc.load_cache(path)
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["status"], {"ok": True})
            self.assertFalse(data["stale"])
            self.assertIn("cached_at", data)

    def test_corrupted_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "popover_cache.json"
            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(pc.load_cache(path), {})


class PopoverFeedTests(unittest.TestCase):
    def _main_or_skip(self):
        try:
            import cli.main as main
            return main
        except ModuleNotFoundError as exc:
            self.skipTest(f"cli.main optional dependency missing: {exc}")

    def test_popover_feed_saves_successful_payload(self) -> None:
        main = self._main_or_skip()

        with tempfile.TemporaryDirectory() as td, \
             patch.object(pc, "POPOVER_CACHE_PATH", Path(td) / "popover_cache.json"), \
             patch.object(main, "collect_status", return_value={"google_error": None}), \
             patch.object(main, "collect_upcoming_json", return_value={"events": [], "google_error": None}), \
             patch.object(main, "collect_missed_json", return_value={"events": [], "google_error": None}), \
             patch("state.stats_store.snapshot", return_value={"actions_run": 1}):
            out = main.collect_popover_feed()

        self.assertFalse(out["stale"])
        self.assertIsNone(out["google_error"])

    def test_popover_feed_returns_cache_on_refresh_failure(self) -> None:
        main = self._main_or_skip()

        with tempfile.TemporaryDirectory() as td, \
             patch.object(pc, "POPOVER_CACHE_PATH", Path(td) / "popover_cache.json"):
            pc.save_cache({
                "status": {"google_error": None, "version": "test"},
                "stats": {"actions_run": 1},
                "upcoming": {"events": [{"id": "cached"}], "google_error": None},
                "missed": {"events": [], "google_error": None},
            })
            with patch.object(main, "collect_status", return_value={"google_error": "network down"}), \
                 patch.object(main, "collect_upcoming_json", return_value={"events": [], "google_error": None}), \
                 patch.object(main, "collect_missed_json", return_value={"events": [], "google_error": None}), \
                 patch("state.stats_store.snapshot", return_value={"actions_run": 2}):
                out = main.collect_popover_feed()

        self.assertTrue(out["stale"])
        self.assertEqual(out["upcoming"]["events"][0]["id"], "cached")
        self.assertIn("network down", out["google_error"])

    def test_age_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(pc.cache_age_seconds(Path(td) / "missing.json"))

    def test_exactly_24_hours_is_still_usable(self) -> None:
        fixed = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed if tz is None else fixed.astimezone(tz)

        with tempfile.TemporaryDirectory() as td, patch.object(pc, "datetime", FrozenDateTime):
            path = Path(td) / "popover_cache.json"
            payload = {
                "schema_version": 1,
                "cached_at": (fixed - timedelta(seconds=pc.MAX_AGE_SECONDS)).isoformat(),
                "status": {},
                "stats": {},
                "upcoming": {"events": []},
                "missed": {"events": []},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(pc.load_cache(path))
            self.assertEqual(pc.cache_age_seconds(path), pc.MAX_AGE_SECONDS)

    def test_older_than_24_hours_is_ignored(self) -> None:
        fixed = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed if tz is None else fixed.astimezone(tz)

        with tempfile.TemporaryDirectory() as td, patch.object(pc, "datetime", FrozenDateTime):
            path = Path(td) / "popover_cache.json"
            payload = {
                "schema_version": 1,
                "cached_at": (fixed - timedelta(seconds=pc.MAX_AGE_SECONDS + 1)).isoformat(),
                "status": {},
                "stats": {},
                "upcoming": {"events": []},
                "missed": {"events": []},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(pc.load_cache(path), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
