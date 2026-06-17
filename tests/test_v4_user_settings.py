from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.settings_reader import (
    load_user_overrides,
    migrate_settings_to_sidecars,
    save_user_overrides,
)
from core.targets_reader import (
    load_user_targets,
    migrate_targets_to_sidecar,
    save_user_targets,
)


class UserSettingsSidecarTests(unittest.TestCase):
    def test_missing_settings_sidecar_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_user_overrides(Path(td) / "missing.json"), {})

    def test_valid_settings_sidecar_loads_constants(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "overrides": {"FETCH_WINDOW_HOURS": "4", "LOG_MODE": "stderr"},
            }), encoding="utf-8")
            self.assertEqual(load_user_overrides(path), {
                "FETCH_WINDOW_HOURS": 4,
                "LOG_MODE": "stderr",
            })

    def test_unknown_settings_key_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "overrides": {"NOPE": 1, "MAX_URLS": 12},
            }), encoding="utf-8")
            self.assertEqual(load_user_overrides(path), {"MAX_URLS": 12})

    def test_malformed_settings_sidecar_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(load_user_overrides(path), {})

    def test_save_settings_sidecar_round_trips_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            bak = Path(td) / "user_settings.json.bak"
            self.assertIsNone(save_user_overrides({"MAX_URLS": 5}, path=path, backup_path=bak))
            self.assertEqual(save_user_overrides({"MAX_URLS": 6}, path=path, backup_path=bak), str(bak))
            self.assertEqual(load_user_overrides(path)["MAX_URLS"], 6)
            self.assertEqual(json.loads(bak.read_text())["overrides"]["MAX_URLS"], 5)


class UserTargetsSidecarTests(unittest.TestCase):
    def test_missing_targets_sidecar_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(load_user_targets(Path(td) / "missing.json"))

    def test_targets_sidecar_allows_empty_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_targets.json"
            save_user_targets({}, path=path, backup_path=Path(td) / "bak.json")
            self.assertEqual(load_user_targets(path), {})

    def test_targets_sidecar_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_targets.json"
            save_user_targets({"@chrome": "Google Chrome", "@work": ["Slack", "Notion"]},
                              path=path, backup_path=Path(td) / "bak.json")
            self.assertEqual(load_user_targets(path), {
                "@chrome": "Google Chrome",
                "@work": ["Slack", "Notion"],
            })


class MigrationTests(unittest.TestCase):
    def test_settings_migration_moves_drift_to_sidecar_and_restores_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            live = root / "settings.py"
            defaults = root / "settings.defaults.py"
            sidecar = root / "user_settings.json"
            backup = root / "user_settings.json.bak"
            live.write_text("FETCH_WINDOW_HOURS = 8\nMAX_URLS = 5\nTARGETS = {}\n", encoding="utf-8")
            defaults.write_text("FETCH_WINDOW_HOURS = 2\nMAX_URLS = 5\nTARGETS = {}\n", encoding="utf-8")

            with patch("core.settings_reader.SETTINGS_PATH", live), \
                 patch("core.settings_reader.DEFAULT_SETTINGS_PATH", defaults), \
                 patch("core.settings_reader.USER_SETTINGS_PATH", sidecar), \
                 patch("core.settings_reader.USER_SETTINGS_BACKUP_PATH", backup):
                result = migrate_settings_to_sidecars()

            self.assertEqual(result["migrated"], ["FETCH_WINDOW_HOURS"])
            self.assertEqual(json.loads(sidecar.read_text())["overrides"]["FETCH_WINDOW_HOURS"], 8)
            self.assertEqual(live.read_text(), defaults.read_text())

    def test_targets_migration_writes_sidecar_when_defaults_differ(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            live = root / "settings.py"
            defaults = root / "settings.defaults.py"
            sidecar = root / "user_targets.json"
            backup = root / "user_targets.json.bak"
            live.write_text('TARGETS = {"@chrome": "Chrome"}\n', encoding="utf-8")
            defaults.write_text('TARGETS = {"@safari": "Safari"}\n', encoding="utf-8")

            with patch("core.targets_reader.SETTINGS_PATH", live), \
                 patch("core.targets_reader.DEFAULT_SETTINGS_PATH", defaults), \
                 patch("core.targets_reader.USER_TARGETS_PATH", sidecar), \
                 patch("core.targets_reader.USER_TARGETS_BACKUP_PATH", backup):
                result = migrate_targets_to_sidecar()

            self.assertTrue(result["migrated"])
            self.assertEqual(load_user_targets(sidecar), {"@chrome": "Chrome"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
