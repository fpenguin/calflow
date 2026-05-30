from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import runtime.actions.applescript as applescript
import runtime.actions.btt as btt
import runtime.actions.shortcuts as shortcuts


class RunBackendNotificationTests(unittest.TestCase):
    def test_applescript_nonzero_notifies(self) -> None:
        with mock.patch.object(applescript.subprocess, "run") as run, \
                mock.patch.object(applescript, "notify_run_error") as notify:
            run.return_value = mock.Mock(returncode=1, stderr="boom")
            applescript.run_applescript('tell application "Finder" to activate')

        notify.assert_called_once()
        self.assertIn("exited 1", notify.call_args.args[1])

    def test_shortcut_nonzero_notifies(self) -> None:
        with mock.patch.object(shortcuts.subprocess, "run") as run, \
                mock.patch.object(shortcuts, "notify_run_error") as notify:
            run.return_value = mock.Mock(returncode=1, stderr="missing shortcut")
            shortcuts.run_shortcut("No Such Shortcut")

        notify.assert_called_once()
        self.assertIn("missing shortcut", notify.call_args.args[1])

    def test_btt_launch_exception_notifies(self) -> None:
        with mock.patch.object(btt.subprocess, "run", side_effect=RuntimeError("open failed")), \
                mock.patch.object(btt, "notify_run_error") as notify:
            btt.trigger_named_btt("Trigger")

        notify.assert_called_once()
        self.assertIn("open failed", notify.call_args.args[1])

    def test_alfred_missing_fields_notifies(self) -> None:
        with mock.patch.object(btt, "notify_run_error") as notify:
            btt.trigger_alfred("", "")

        notify.assert_called_once()
        self.assertIn("missing workflow", notify.call_args.args[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
