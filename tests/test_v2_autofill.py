"""
Autofill tests (v2.0.7+).

Covers:
    - AppleScript assembly for keystroke + key-code shapes
    - Modifier-name aliasing (cmd / command, alt / option, ctrl / control)
    - Provider resolution layering (data/config.json → settings → default)
    - 'none' provider short-circuits cleanly
    - subprocess errors don't crash the pipeline

No real keystrokes are sent — we patch subprocess.run to capture
the AppleScript string the runtime would execute.

Run:
    python -m unittest tests.test_v2_autofill -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import runtime.actions.autofill as af


# =============================================================
# AppleScript assembly
# =============================================================

class BuildAppleScript(unittest.TestCase):
    def test_simple_keystroke_no_modifiers(self):
        s = af._build_applescript({"key": "a"})
        self.assertIn('keystroke "a"', s)
        self.assertNotIn("using", s)

    def test_keystroke_with_one_modifier(self):
        s = af._build_applescript({"key": "\\", "modifiers": ["command"]})
        self.assertIn(r'keystroke "\\"', s)
        self.assertIn("command down", s)

    def test_keystroke_with_two_modifiers(self):
        s = af._build_applescript({"key": "l", "modifiers": ["command", "shift"]})
        self.assertIn('keystroke "l"', s)
        self.assertIn("command down", s)
        self.assertIn("shift down", s)

    def test_modifier_aliases(self):
        s = af._build_applescript({"key": "x", "modifiers": ["cmd", "alt", "ctrl"]})
        self.assertIn("command down", s)
        self.assertIn("option down", s)
        self.assertIn("control down", s)

    def test_unknown_modifier_silently_dropped(self):
        s = af._build_applescript({"key": "y", "modifiers": ["nonsense"]})
        self.assertIn('keystroke "y"', s)
        # No `using` clause when the only modifier was unknown
        self.assertNotIn("using", s)

    def test_key_code_form(self):
        s = af._build_applescript({"key_code": 36})
        self.assertIn("key code 36", s)
        self.assertNotIn("keystroke", s)

    def test_key_code_invalid_returns_none(self):
        self.assertIsNone(af._build_applescript({"key_code": "abc"}))

    def test_unknown_action_shape_returns_none(self):
        self.assertIsNone(af._build_applescript({"foo": "bar"}))

    def test_double_quote_escaped(self):
        s = af._build_applescript({"key": '"'})
        self.assertIn(r'keystroke "\""', s)


# =============================================================
# Provider resolution layering
# =============================================================

class ProviderResolution(unittest.TestCase):
    def setUp(self):
        # Point _USER_CONFIG_PATH at a temp file we control
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self._tmp.close()
        self._orig_path = af._USER_CONFIG_PATH
        af._USER_CONFIG_PATH = Path(self._tmp.name)

    def tearDown(self):
        af._USER_CONFIG_PATH = self._orig_path
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def _write_user_choice(self, value):
        with open(self._tmp.name, "w") as f:
            json.dump({"autofill_provider": value}, f)

    def test_user_choice_overrides_settings_default(self):
        self._write_user_choice("bitwarden")
        self.assertEqual(af.resolve_autofill_provider(), "bitwarden")

    def test_user_choice_none_returned_verbatim(self):
        self._write_user_choice("none")
        self.assertEqual(af.resolve_autofill_provider(), "none")

    def test_user_choice_unknown_falls_back_to_settings_default(self):
        self._write_user_choice("nonexistent_pm")
        # Falls back to AUTOFILL_PROVIDER from settings.py — currently "apple"
        self.assertIn(af.resolve_autofill_provider(), {"apple", "default"})

    def test_no_user_config_uses_settings_default(self):
        # Empty file → no override
        os.unlink(self._tmp.name)
        # File doesn't exist now
        self.assertIn(af.resolve_autofill_provider(), {"apple", "default"})


# =============================================================
# trigger_autofill end-to-end (with osascript mocked out)
# =============================================================

class TriggerAutofill(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_run(cmd, *args, **kwargs):
            self.calls.append(cmd)
            class _R:
                returncode = 0
                stdout = ""
                stderr = ""
            return _R()

        self._patcher = mock.patch.object(af.subprocess, "run", side_effect=fake_run)
        self._patcher.start()

        # Force user config to apple for deterministic provider
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({"autofill_provider": "apple"}, self._tmp)
        self._tmp.close()
        self._orig_path = af._USER_CONFIG_PATH
        af._USER_CONFIG_PATH = Path(self._tmp.name)

    def tearDown(self):
        self._patcher.stop()
        af._USER_CONFIG_PATH = self._orig_path
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def test_fill_sends_apple_shortcut(self):
        af.trigger_autofill(mode="fill")
        # Apple's fill is cmd+\
        self.assertEqual(len(self.calls), 1)
        cmd = self.calls[0]
        self.assertEqual(cmd[0], "osascript")
        self.assertIn("command down", cmd[2])
        self.assertIn(r'keystroke "\\"', cmd[2])

    def test_submit_sends_return_keycode(self):
        af.trigger_autofill(mode="submit")
        self.assertIn("key code 36", self.calls[0][2])


class NoneProviderShortCircuits(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({"autofill_provider": "none"}, self._tmp)
        self._tmp.close()
        self._orig_path = af._USER_CONFIG_PATH
        af._USER_CONFIG_PATH = Path(self._tmp.name)

    def tearDown(self):
        af._USER_CONFIG_PATH = self._orig_path
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def test_no_subprocess_call_when_provider_is_none(self):
        with mock.patch.object(af.subprocess, "run") as run:
            af.trigger_autofill(mode="fill")
            run.assert_not_called()


class SubprocessFailureSwallowed(unittest.TestCase):
    """A failed osascript must not crash the executor."""

    def test_failed_subprocess_does_not_raise(self):
        with mock.patch.object(af.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="execution error: not allowed (1002)",
            )
            # Must not raise
            af.trigger_autofill(mode="fill")

    def test_missing_osascript_does_not_raise(self):
        with mock.patch.object(af.subprocess, "run", side_effect=FileNotFoundError()):
            af.trigger_autofill(mode="fill")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
