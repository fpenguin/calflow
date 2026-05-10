"""
v1.3.2 — settings_writer tests.

Covers:
- whitelist enforcement (unknown UI keys rejected)
- type coercion (str / int / float)
- range validation (min / max inclusive)
- choices validation
- minutes ↔ seconds unit conversion (open_minutes_early)
- launchd-controlled keys return requires_terminal (no file write)
- atomic write replaces only the target line
- backup file is created on successful write
- string safety: rejects values containing quotes / newlines

Each test runs against a tempfile copy of settings.py so we never
mutate the user's real config.

Run:
    python -m unittest tests.test_v3_settings_writer -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.settings_writer import (
    EDITABLE_SETTINGS,
    apply_settings,
)


# Minimal fake settings.py used as the write target. Includes all the
# constants the whitelist references, plus a couple of decoys we want to
# make sure are NOT touched.
FAKE_SETTINGS = """\
from __future__ import annotations

FETCH_WINDOW_HOURS = 2
STATUS_LOOKAHEAD_HOURS = 24
DEFAULT_ALERT_SECONDS = 300
GRACE_SECONDS = 600
EARLY_TOLERANCE = 30
MAX_URLS = 5
LOG_MODE = "both"

TITLE_URL_OPEN_DEFAULT = "tab"
TITLE_URL_AUTOFILL_DEFAULT = "submit"
AUTOFILL_PROVIDER = "apple"
AUTOFILL_MODE = "semi-auto"

PLUS_MAX_COMMANDS = 50
PLUS_INTER_COMMAND_DELAY = 0.3
PLUS_SCREENSHOT_DIR = "~/Downloads/CalFlow"

# Decoys — these should remain untouched.
TARGETS = {"@chrome": "Google Chrome"}
BLACKLIST_REGEX = ["/cancel\\\\w*"]
"""


class SettingsWriterBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="calflow_set_"))
        self._settings = self._tmp / "settings.py"
        self._backup   = self._tmp / "settings.py.bak"
        self._settings.write_text(FAKE_SETTINGS, encoding="utf-8")

        self._patches = [
            patch("core.settings_writer.SETTINGS_PATH", self._settings),
            patch("core.settings_writer.BACKUP_PATH",   self._backup),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def read(self) -> str:
        return self._settings.read_text(encoding="utf-8")


# =============================================================
# Whitelist / unknown keys
# =============================================================

class Whitelist(SettingsWriterBase):
    def test_unknown_key_rejected(self):
        result = apply_settings({"made.up.key": 123})
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["key"], "made.up.key")
        self.assertIn("not editable", result["rejected"][0]["reason"])

    def test_empty_payload(self):
        result = apply_settings({})
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["rejected"]), 1)

    def test_whitelist_keys_align_with_settings_constants(self):
        """Every whitelisted UI key maps to a constant that exists in our fixture."""
        for ui_key, spec in EDITABLE_SETTINGS.items():
            self.assertIn(spec["const"] + " =", FAKE_SETTINGS,
                f"{ui_key!r} maps to {spec['const']!r} which is not in the fixture")


# =============================================================
# Apply happy path
# =============================================================

class ApplyHappyPath(SettingsWriterBase):
    def test_int_replace(self):
        result = apply_settings({"events.fetch_window_hours": 4})
        self.assertEqual(result["applied"], ["events.fetch_window_hours"])
        self.assertEqual(result["rejected"], [])
        self.assertIn("FETCH_WINDOW_HOURS = 4", self.read())
        self.assertNotIn("FETCH_WINDOW_HOURS = 2", self.read())

    def test_choice_replace(self):
        result = apply_settings({"title_links.open_mode": "window"})
        self.assertEqual(result["applied"], ["title_links.open_mode"])
        self.assertIn('TITLE_URL_OPEN_DEFAULT = "window"', self.read())

    def test_float_replace(self):
        result = apply_settings({"advanced.plus_inter_command_delay_sec": 0.7})
        self.assertEqual(result["applied"], ["advanced.plus_inter_command_delay_sec"])
        self.assertIn("PLUS_INTER_COMMAND_DELAY = 0.7", self.read())

    def test_minutes_to_seconds_conversion(self):
        # UI sends 10 minutes; settings.py stores 600 seconds.
        result = apply_settings({"events.open_minutes_early": 10})
        self.assertEqual(result["applied"], ["events.open_minutes_early"])
        self.assertIn("DEFAULT_ALERT_SECONDS = 600", self.read())

    def test_string_replace(self):
        result = apply_settings({"advanced.plus_screenshot_dir": "~/Pictures/CF"})
        self.assertEqual(result["applied"], ["advanced.plus_screenshot_dir"])
        self.assertIn('PLUS_SCREENSHOT_DIR = "~/Pictures/CF"', self.read())

    def test_bool_to_string_mapping_on(self):
        # v1.3.7 — UI sends bool; writer maps True → "semi-auto".
        result = apply_settings({"passwords.autofill_on_open": True})
        self.assertEqual(result["applied"], ["passwords.autofill_on_open"])
        self.assertIn('AUTOFILL_MODE = "semi-auto"', self.read())

    def test_bool_to_string_mapping_off(self):
        result = apply_settings({"passwords.autofill_on_open": False})
        self.assertEqual(result["applied"], ["passwords.autofill_on_open"])
        self.assertIn('AUTOFILL_MODE = "off"', self.read())

    def test_batch_apply(self):
        result = apply_settings({
            "events.fetch_window_hours": 6,
            "advanced.log_mode": "stderr",
            "passwords.provider": "1password",
        })
        self.assertEqual(set(result["applied"]),
                         {"events.fetch_window_hours", "advanced.log_mode", "passwords.provider"})
        text = self.read()
        self.assertIn("FETCH_WINDOW_HOURS = 6", text)
        self.assertIn('LOG_MODE = "stderr"', text)
        self.assertIn('AUTOFILL_PROVIDER = "1password"', text)


# =============================================================
# Validation rejects
# =============================================================

class Validation(SettingsWriterBase):
    def test_below_min(self):
        result = apply_settings({"events.fetch_window_hours": 0})
        self.assertEqual(result["applied"], [])
        self.assertIn(">= 1", result["rejected"][0]["reason"])

    def test_above_max(self):
        result = apply_settings({"events.fetch_window_hours": 999})
        self.assertEqual(result["applied"], [])
        self.assertIn("<= 24", result["rejected"][0]["reason"])

    def test_invalid_choice(self):
        result = apply_settings({"title_links.open_mode": "popover"})
        self.assertEqual(result["applied"], [])
        self.assertIn("must be one of", result["rejected"][0]["reason"])

    def test_uncoercible(self):
        result = apply_settings({"events.fetch_window_hours": "not a number"})
        self.assertEqual(result["applied"], [])
        self.assertIn("could not coerce", result["rejected"][0]["reason"])

    def test_string_with_quote_rejected(self):
        result = apply_settings({"advanced.plus_screenshot_dir": '~/Pictures"; rm -rf /'})
        self.assertEqual(result["applied"], [])
        self.assertIn("must not contain quotes", result["rejected"][0]["reason"])

    def test_string_with_newline_rejected(self):
        result = apply_settings({"advanced.plus_screenshot_dir": "~/foo\nbar"})
        self.assertEqual(result["applied"], [])
        self.assertIn("quotes or newlines", result["rejected"][0]["reason"])


# =============================================================
# Launchd-controlled keys
# =============================================================

class Launchd(SettingsWriterBase):
    """v1.3.6 — launchd ops now execute natively. Mock the helpers so the
    test suite doesn't actually touch the real launchctl."""

    def test_auto_start_on_runs_start_launchd(self):
        with patch("cli.onboarding.start_launchd") as mock_start, \
             patch("cli.onboarding.stop_launchd"):
            result = apply_settings({"general.auto_start_at_login": True})
            mock_start.assert_called_once()
        self.assertIn("general.auto_start_at_login", result["applied"])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["requires_terminal"], [])
        self.assertEqual(result["daemon_actions"][0]["action"], "start")

    def test_auto_start_off_runs_stop_launchd(self):
        with patch("cli.onboarding.start_launchd"), \
             patch("cli.onboarding.stop_launchd") as mock_stop:
            result = apply_settings({"general.auto_start_at_login": False})
            mock_stop.assert_called_once()
        self.assertIn("general.auto_start_at_login", result["applied"])
        self.assertEqual(result["daemon_actions"][0]["action"], "stop")

    def test_launchd_failure_is_rejected(self):
        with patch("cli.onboarding.start_launchd",
                   side_effect=FileNotFoundError("plist missing")):
            result = apply_settings({"general.auto_start_at_login": True})
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("plist missing", result["rejected"][0]["reason"])

    def test_no_file_write_for_launchd_only_payload(self):
        original = self.read()
        with patch("cli.onboarding.start_launchd"):
            apply_settings({"general.auto_start_at_login": True})
        self.assertEqual(self.read(), original,
                         "launchd ops must not touch settings.py")


# =============================================================
# Backup
# =============================================================

class Backup(SettingsWriterBase):
    def test_backup_created_on_write(self):
        self.assertFalse(self._backup.exists())
        result = apply_settings({"events.fetch_window_hours": 4})
        self.assertTrue(self._backup.exists())
        self.assertEqual(result["backup_path"], str(self._backup))
        # Backup must equal the ORIGINAL pre-write content.
        self.assertIn("FETCH_WINDOW_HOURS = 2", self._backup.read_text())

    def test_no_backup_when_only_validation_failures(self):
        apply_settings({"events.fetch_window_hours": 999})  # all fail
        self.assertFalse(self._backup.exists())

    def test_no_backup_for_pure_terminal_payload(self):
        apply_settings({"general.auto_start_at_login": True})
        self.assertFalse(self._backup.exists())


# =============================================================
# Decoys are not touched
# =============================================================

class Decoys(SettingsWriterBase):
    def test_targets_not_modified(self):
        apply_settings({"events.fetch_window_hours": 4})
        text = self.read()
        self.assertIn('TARGETS = {"@chrome": "Google Chrome"}', text)

    def test_blacklist_not_modified(self):
        apply_settings({"events.fetch_window_hours": 4})
        text = self.read()
        self.assertIn('BLACKLIST_REGEX = ["/cancel', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
