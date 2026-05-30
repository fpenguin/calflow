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
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
import runtime.command_executor as ce
from runtime.actions.run_result import RunResult, error_result, ok_result


class FakeActions:
    """Captures calls instead of executing them."""

    def __init__(self) -> None:
        self.opens: List[Dict[str, Any]] = []
        self.shots: List[Any] = []
        self.fills: List[str] = []
        self.sleeps: List[float] = []
        self.btt: List[str] = []
        self.applescripts: List[str] = []
        self.shortcuts: List[Dict[str, str]] = []
        self.alfred: List[Dict[str, str]] = []
        self.notifications: List[Dict[str, str]] = []
        self.clipboard: List[str] = []
        self.applescript_result: RunResult = ok_result("applescript", "done")

    def open_target(self, url=None, app=None, layout=None, display_spec=None,
                    chrome_profile=None, new_window=False) -> None:
        self.opens.append({
            "url": url, "app": app, "layout": layout,
            "display_spec": display_spec, "chrome_profile": chrome_profile,
            "new_window": new_window,
        })

    def take_screenshot(self, path=None):
        self.shots.append(path)
        return path or "/tmp/calflow_test.png"

    def trigger_autofill(self, mode="fill") -> None:
        self.fills.append(mode)

    def sleep(self, seconds) -> None:
        self.sleeps.append(seconds)

    def trigger_named_btt(self, trigger_name: str) -> RunResult:
        self.btt.append(trigger_name)
        return ok_result("btt", f"launched {trigger_name}")

    def run_applescript(self, script: str) -> RunResult:
        self.applescripts.append(script)
        return self.applescript_result

    def run_shortcut(self, name: str, input_text: str = "") -> RunResult:
        self.shortcuts.append({"name": name, "input": input_text})
        return ok_result("shortcut", f"ran {name}")

    def trigger_alfred(
        self,
        bundle_id: str,
        trigger_id: str,
        argument: str = "",
    ) -> RunResult:
        self.alfred.append({
            "bundle_id": bundle_id,
            "trigger_id": trigger_id,
            "argument": argument,
        })
        return ok_result("alfred", f"launched {bundle_id}/{trigger_id}")

    def notify_run_error(self, title: str, message: str) -> None:
        self.notifications.append({"title": title, "message": message})

    def copy_text_to_clipboard(self, text: str) -> None:
        self.clipboard.append(text)


class CommandExecutorRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeActions()
        # Patch the names that command_executor imported.
        self._orig = {
            "open_target": ce.open_target,
            "take_screenshot": ce.take_screenshot,
            "trigger_autofill": ce.trigger_autofill,
            "trigger_named_btt": ce.trigger_named_btt,
            "run_applescript": ce.run_applescript,
            "run_shortcut": ce.run_shortcut,
            "trigger_alfred": ce.trigger_alfred,
            "notify_run_error": ce.notify_run_error,
            "_copy_text_to_clipboard": ce._copy_text_to_clipboard,
            "sleep": ce.time.sleep,
        }
        ce.open_target = self.fake.open_target
        ce.take_screenshot = self.fake.take_screenshot
        ce.trigger_autofill = self.fake.trigger_autofill
        ce.trigger_named_btt = self.fake.trigger_named_btt
        ce.run_applescript = self.fake.run_applescript
        ce.run_shortcut = self.fake.run_shortcut
        ce.trigger_alfred = self.fake.trigger_alfred
        ce.notify_run_error = self.fake.notify_run_error
        ce._copy_text_to_clipboard = self.fake.copy_text_to_clipboard
        ce.time.sleep = self.fake.sleep

    def tearDown(self) -> None:
        ce.open_target = self._orig["open_target"]
        ce.take_screenshot = self._orig["take_screenshot"]
        ce.trigger_autofill = self._orig["trigger_autofill"]
        ce.trigger_named_btt = self._orig["trigger_named_btt"]
        ce.run_applescript = self._orig["run_applescript"]
        ce.run_shortcut = self._orig["run_shortcut"]
        ce.trigger_alfred = self._orig["trigger_alfred"]
        ce.notify_run_error = self._orig["notify_run_error"]
        ce._copy_text_to_clipboard = self._orig["_copy_text_to_clipboard"]
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

    def test_run_btt_routes_to_named_trigger(self) -> None:
        result = parse('+CalFlow+\nrun btt("BTT-ClaudeCoworkTryAgain")')
        ce.execute_commands(result.commands)
        self.assertEqual(self.fake.btt, ["BTT-ClaudeCoworkTryAgain"])

    def test_run_applescript_routes_for_self(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run applescript\n'
            '+++\n'
            'tell application "Finder" to activate\n'
            '+++\n'
        )
        ce.execute_commands(result.commands)
        self.assertEqual(
            self.fake.applescripts,
            ['tell application "Finder" to activate'],
        )

    def test_run_applescript_blocked_for_trusted_domain_by_default(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run applescript\n'
            '+++\n'
            'tell application "Finder" to activate\n'
            '+++\n'
        )
        ce.execute_commands(result.commands, trust_level="trusted_domain")
        self.assertEqual(self.fake.applescripts, [])

    def test_run_shortcut_routes_for_self(self) -> None:
        result = parse('+CalFlow+\nrun shortcut("Start Focus") input("deep work")')
        ce.execute_commands(result.commands)
        self.assertEqual(
            self.fake.shortcuts,
            [{"name": "Start Focus", "input": "deep work"}],
        )

    def test_run_shortcut_routes_for_trusted_domain(self) -> None:
        result = parse('+CalFlow+\nrun shortcut("Start Focus")')
        ce.execute_commands(result.commands, trust_level="trusted_domain")
        self.assertEqual(
            self.fake.shortcuts,
            [{"name": "Start Focus", "input": ""}],
        )

    def test_run_alfred_routes_for_self(self) -> None:
        result = parse(
            '+CalFlow+\nrun alfred("com.example.workflow", "try-again") input("now")'
        )
        ce.execute_commands(result.commands)
        self.assertEqual(
            self.fake.alfred,
            [{
                "bundle_id": "com.example.workflow",
                "trigger_id": "try-again",
                "argument": "now",
            }],
        )

    def test_run_alfred_blocked_for_trusted_domain_by_default(self) -> None:
        result = parse(
            '+CalFlow+\nrun alfred("com.example.workflow", "try-again") input("now")'
        )
        ce.execute_commands(result.commands, trust_level="trusted_domain")
        self.assertEqual(self.fake.alfred, [])

    def test_run_function_syntax_routes(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run btt("BTT-ClaudeCoworkTryAgain")\n'
            'run shortcut("Start Focus") input("deep work")\n'
            'run alfred("com.example.workflow", "try-again") input("now")\n'
        )
        ce.execute_commands(result.commands)
        self.assertEqual(self.fake.btt, ["BTT-ClaudeCoworkTryAgain"])
        self.assertEqual(
            self.fake.shortcuts,
            [{"name": "Start Focus", "input": "deep work"}],
        )
        self.assertEqual(
            self.fake.alfred,
            [{
                "bundle_id": "com.example.workflow",
                "trigger_id": "try-again",
                "argument": "now",
            }],
        )

    def test_run_error_handlers_notify_copy_and_save(self) -> None:
        self.fake.applescript_result = error_result(
            "applescript",
            "exited 1: boom",
            stderr="boom",
            returncode=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calflow-error.txt"
            result = parse(
                '+CalFlow+\n'
                'run applescript if(error) notify(result) '
                'if(error) copy(result) if(error) save to("' + str(path) + '")\n'
                '+++\n'
                'error "boom"\n'
                '+++\n'
            )
            ce.execute_commands(result.commands)

            self.assertEqual(len(self.fake.notifications), 1)
            self.assertIn("exited 1", self.fake.notifications[0]["message"])
            self.assertEqual(self.fake.clipboard, ["exited 1: boom\nboom"])
            self.assertIn("exited 1", path.read_text(encoding="utf-8"))

    def test_disabled_run_backend_notifies(self) -> None:
        result = parse(
            '+CalFlow+\n'
            'run applescript\n'
            '+++\n'
            'tell application "Finder" to activate\n'
            '+++\n'
        )
        ce.execute_commands(result.commands, trust_level="trusted_domain")
        self.assertEqual(len(self.fake.notifications), 1)
        self.assertEqual(self.fake.notifications[0]["title"], "CalFlow run blocked")
        self.assertIn("RUN applescript disabled", self.fake.notifications[0]["message"])

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
