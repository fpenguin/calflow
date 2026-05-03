"""
v2.0 command_executor sanity tests.

We don't want unit tests to actually open browsers or take screenshots,
so we monkey-patch the action layer and verify the executor calls the
right action with the right arguments.

Run:
    python -m unittest tests.test_v2_executor -v
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
import runtime.command_executor as ce


class FakeActions:
    """Captures calls instead of executing them."""

    def __init__(self) -> None:
        self.opens: List[Dict[str, Any]] = []
        self.shots: List[Any] = []
        self.fills: List[str] = []
        self.sleeps: List[float] = []

    def open_target(self, url=None, app=None, layout=None, display_spec=None,
                    chrome_profile=None) -> None:
        self.opens.append({
            "url": url, "app": app, "layout": layout,
            "display_spec": display_spec, "chrome_profile": chrome_profile,
        })

    def take_screenshot(self, path=None):
        self.shots.append(path)
        return path or "/tmp/calflow_test.png"

    def trigger_autofill(self, mode="fill") -> None:
        self.fills.append(mode)

    def sleep(self, seconds) -> None:
        self.sleeps.append(seconds)


class CommandExecutorRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeActions()
        # Patch the names that command_executor imported.
        self._orig = {
            "open_target": ce.open_target,
            "take_screenshot": ce.take_screenshot,
            "trigger_autofill": ce.trigger_autofill,
            "sleep": ce.time.sleep,
        }
        ce.open_target = self.fake.open_target
        ce.take_screenshot = self.fake.take_screenshot
        ce.trigger_autofill = self.fake.trigger_autofill
        ce.time.sleep = self.fake.sleep

    def tearDown(self) -> None:
        ce.open_target = self._orig["open_target"]
        ce.take_screenshot = self._orig["take_screenshot"]
        ce.trigger_autofill = self._orig["trigger_autofill"]
        ce.time.sleep = self._orig["sleep"]

    # -----------------------------------------------------

    def test_open_routes_to_open_target(self) -> None:
        result = parse("+CalFlow+\nOPEN https://example.com @chrome")
        ce.execute_commands(result.commands)
        self.assertEqual(len(self.fake.opens), 1)
        self.assertEqual(self.fake.opens[0]["url"], "https://example.com")

    def test_screenshot_routes_to_take_screenshot(self) -> None:
        result = parse('+CalFlow+\nSCREENSHOT to("/tmp/x.png")')
        ce.execute_commands(result.commands)
        self.assertEqual(self.fake.shots, ["/tmp/x.png"])

    def test_wait_calls_sleep_with_seconds(self) -> None:
        result = parse("+CalFlow+\nWAIT 2")
        ce.execute_commands(result.commands)
        # Each command also pays the inter-command delay; we only assert
        # that 2.0 was among the requested sleeps.
        self.assertIn(2.0, self.fake.sleeps)

    def test_unknown_verb_does_not_blow_up(self) -> None:
        # Validator drops it, but we want to confirm executor handles
        # an empty AST gracefully.
        result = parse("+CalFlow+\nDANCE")
        ce.execute_commands(result.commands)  # should not raise
        self.assertEqual(self.fake.opens, [])

    def test_failure_in_one_command_does_not_abort(self) -> None:
        def boom(**kwargs):
            raise RuntimeError("boom")

        ce.open_target = boom
        result = parse(
            '+CalFlow+\n'
            'OPEN https://a.com\n'
            'SCREENSHOT to("/tmp/y.png")\n'
        )
        ce.execute_commands(result.commands)
        self.assertEqual(self.fake.shots, ["/tmp/y.png"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
