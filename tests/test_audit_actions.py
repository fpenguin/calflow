"""Audit regressions: native IO is mocked for every action test."""

from __future__ import annotations

import subprocess
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from runtime.actions import (
    app_control,
    applescript,
    autofill,
    browser,
    btt,
    notifications,
    screenshot,
    shortcuts,
    window,
)


class AuditActionsTests(unittest.TestCase):
    # v1.5.5 audit regressions: never launch native processes or touch the clipboard.
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch(
            "subprocess.Popen", side_effect=AssertionError("Native IO forbidden")
        ))
        self.run = self.stack.enter_context(patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "ok", ""),
        ))
        self.open_browser = self.stack.enter_context(patch("webbrowser.open", return_value=True))
        self.stack.enter_context(patch("time.sleep"))
        self.mkdir = self.stack.enter_context(patch.object(Path, "mkdir"))
        self.is_dir = self.stack.enter_context(patch.object(Path, "is_dir", return_value=False))
        self.stack.enter_context(patch.object(screenshot.os.path, "exists", return_value=True))
        self.logs = {}
        for module in (
            app_control, applescript, autofill, browser, btt, notifications,
            screenshot, shortcuts, window,
        ):
            self.logs[module] = self.stack.enter_context(patch.object(module, "log"))

    def test_shared_escaper_preserves_quotes_and_backslashes(self) -> None:
        from runtime.actions._applescript import escape_applescript_string

        self.assertEqual(escape_applescript_string('a\\"b'), 'a\\\\\\"b')
        self.assertEqual(escape_applescript_string("ordinary"), "ordinary")

    def test_safari_url_cannot_escape_generated_string(self) -> None:
        payload = 'https://example.com/\\" & (ASCII character 65)} -- '
        browser.open_target(payload, "Safari", new_window=True)
        script = self.run.call_args.args[0][2]
        escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
        self.assertIn('{URL:"' + escaped + '"}', script)

    def test_window_app_name_cannot_escape_generated_string(self) -> None:
        payload = 'Audit\\" & (ASCII character 65) -- '
        self.assertTrue(window.set_window_bounds(payload, (0, 0, 100, 100)))
        script = self.run.call_args.args[0][2]
        escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
        self.assertTrue(script.startswith('tell application "' + escaped + '"\n'))

    def test_existing_app_control_escaping_preserved(self) -> None:
        self.assertTrue(app_control.focus_app('Audit\\"'))
        self.assertEqual(self.run.call_args.args[0][2], 'tell application "Audit\\\\\\"" to activate')

    def test_existing_autofill_escaping_preserved(self) -> None:
        script = autofill._build_applescript({"key": '\\"'})
        self.assertIn('keystroke "\\\\\\""', script)

    def test_existing_notification_escaping_preserved(self) -> None:
        self.assertEqual(notifications._applescript_string('a\\"b'), '"a\\\\\\"b"')

    def test_hide_script_never_closes_a_window(self) -> None:
        script = window._JXA_HIDE_ON_DISPLAY
        self.assertIn(".miniaturized = true", script)
        self.assertNotRegex(script, r"\.close\s*\(")
        self.assertNotIn('" closed"', script)

    def test_hide_script_preserves_non_destructive_fallback(self) -> None:
        self.assertIn(".position = [-32000, -32000]", window._JXA_HIDE_ON_DISPLAY)
        self.assertIn("errored.push", window._JXA_HIDE_ON_DISPLAY)

    def test_scoped_file_capture_fails_without_io(self) -> None:
        for scope in (
            {"target_keyword": "active"}, {"display": 2}, {"window": "Audit"},
            {"area": (0, 0, 10, 10)}, {"display": 0}, {"window": ""},
        ):
            with self.subTest(scope=scope), patch.object(screenshot, "default_screenshot_path") as default:
                self.assertIsNone(screenshot.take_screenshot(**scope))
                default.assert_not_called()
        self.run.assert_not_called()
        self.mkdir.assert_not_called()

    def test_scoped_clipboard_capture_fails_without_io(self) -> None:
        for scope in (
            {"target_keyword": "active"}, {"display": 2}, {"window": "Audit"},
            {"area": (0, 0, 10, 10)}, {"display": 0}, {"window": ""},
        ):
            with self.subTest(scope=scope):
                self.assertFalse(screenshot.take_screenshot_to_clipboard(**scope))
        self.run.assert_not_called()

    def test_unscoped_screenshot_backends_still_work(self) -> None:
        self.assertEqual(screenshot.take_screenshot("/tmp/audit.png"), "/tmp/audit.png")
        self.assertTrue(screenshot.take_screenshot_to_clipboard())
        self.assertEqual(self.run.call_args.args[0], ["/usr/sbin/screencapture", "-c", "-x"])

    def test_screenshot_nonzero_and_timeout_fail_safely(self) -> None:
        for failure in (1, subprocess.TimeoutExpired("mock", 10), FileNotFoundError()):
            with self.subTest(failure=failure):
                self.run.side_effect = failure if isinstance(failure, Exception) else None
                self.run.return_value = subprocess.CompletedProcess([], 1, "", "denied")
                self.assertIsNone(screenshot.take_screenshot("/tmp/audit.png"))
                self.assertFalse(screenshot.take_screenshot_to_clipboard())

    def test_screenshot_default_path_exception_is_contained(self) -> None:
        with patch.object(screenshot, "default_screenshot_path", side_effect=OSError("unavailable")):
            self.assertIsNone(screenshot.take_screenshot())
        self.run.assert_not_called()

    def test_screenshot_expands_home_and_creates_parent(self) -> None:
        with patch.object(screenshot.os.path, "expanduser", return_value="/audit/home/Desktop/capture.png"):
            self.assertEqual(
                screenshot.take_screenshot("~/Desktop/capture.png"),
                "/audit/home/Desktop/capture.png",
            )
        self.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        self.assertEqual(self.run.call_args.args[0][-1], "/audit/home/Desktop/capture.png")

    def test_screenshot_existing_directory_gets_filename(self) -> None:
        self.is_dir.return_value = True
        with patch.object(screenshot, "PLUS_SCREENSHOT_FILENAME_FORMAT", "Audit.png"):
            self.assertEqual(screenshot.take_screenshot("/audit/folder"), "/audit/folder/Audit.png")

    def test_screenshot_trailing_slash_gets_filename(self) -> None:
        with patch.object(screenshot, "PLUS_SCREENSHOT_FILENAME_FORMAT", "Audit.png"):
            self.assertEqual(screenshot.take_screenshot("/audit/new/"), "/audit/new/Audit.png")
        self.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_screenshot_unwritable_destination_never_redirects(self) -> None:
        self.mkdir.side_effect = PermissionError("read only")
        with patch.object(screenshot, "default_screenshot_path") as fallback:
            self.assertIsNone(screenshot.take_screenshot("/audit/readonly/capture.png"))
            fallback.assert_not_called()
        self.run.assert_not_called()

    def test_screenshot_failed_capture_never_redirects(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "read only")
        with patch.object(screenshot, "default_screenshot_path") as fallback:
            self.assertIsNone(screenshot.take_screenshot("/audit/readonly/capture.png"))
            fallback.assert_not_called()
        self.run.assert_called_once()

    def test_screenshot_filename_pattern_cannot_escape_requested_directory(self) -> None:
        with patch.object(screenshot, "PLUS_SCREENSHOT_FILENAME_FORMAT", "../elsewhere.png"):
            self.assertIsNone(screenshot.take_screenshot("/audit/folder/"))
        self.run.assert_not_called()

    def _launch_cases(self):
        return (
            ("https://example.com", "Google Chrome", {"new_window": True}),
            ("https://example.com", "Safari", {"new_window": True}),
            ("https://example.com", "Firefox", {"new_window": True}),
            ("https://example.com", "Other Browser", {"new_window": True}),
            ("https://example.com", "Google Chrome", {"chrome_profile": "Default"}),
            ("https://example.com", "Safari", {}),
            ("/tmp/audit.txt", None, {}),
            ("Audit App", None, {}),
        )

    def test_every_launch_branch_has_a_bounded_timeout(self) -> None:
        for primary, app, options in self._launch_cases():
            with self.subTest(primary=primary, app=app, options=options):
                self.run.reset_mock()
                browser.open_target(primary, app, **options)
                self.run.assert_called_once()
                self.assertGreater(self.run.call_args.kwargs.get("timeout", 0), 0)
                self.assertLessEqual(self.run.call_args.kwargs["timeout"], 30)

    def test_failed_launch_never_arranges_an_existing_window(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "launch failed")
        with patch.object(browser, "_apply_layout") as layout:
            for primary, app, options in self._launch_cases():
                with self.subTest(primary=primary, app=app, options=options):
                    browser.open_target(primary, app, {"type": "full"}, **options)
            layout.assert_not_called()
        self.open_browser.assert_not_called()

    def test_launch_timeout_does_not_fall_back_or_arrange(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("mock", 10)
        with patch.object(browser, "_apply_layout") as layout:
            browser.open_target("https://example.com", "Safari", {"type": "full"}, new_window=True)
            layout.assert_not_called()
        self.run.assert_called_once()
        self.open_browser.assert_not_called()

    def test_missing_launcher_does_not_arrange(self) -> None:
        self.run.side_effect = FileNotFoundError()
        with patch.object(browser, "_apply_layout") as layout:
            browser.open_target("Audit App", layout={"type": "full"})
            layout.assert_not_called()

    def test_successful_launch_still_arranges(self) -> None:
        with patch.object(browser, "_apply_layout") as layout:
            browser.open_target("https://example.com", "Safari", {"type": "full"}, new_window=True)
            layout.assert_called_once_with("Safari", {"type": "full"}, None)

    def test_open_target_reports_launch_success(self) -> None:
        self.assertIs(browser.open_target("https://example.com", "Safari"), True)

    def test_open_target_reports_launch_failure(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "failed")
        self.assertIs(browser.open_target("https://example.com", "Safari"), False)
        self.assertIs(browser.open_target(), False)

    def test_failed_default_browser_does_not_arrange(self) -> None:
        self.open_browser.return_value = False
        with patch("sys.platform", "linux"), patch.object(browser, "_apply_layout") as layout:
            browser.open_target("https://example.com", layout={"type": "full"})
            layout.assert_not_called()

    def test_macos_default_browser_uses_bounded_open_without_appkit(self) -> None:
        with patch("sys.platform", "darwin"), patch.object(browser, "MAC_AVAILABLE", False):
            self.assertIs(browser.open_target("https://example.com"), True)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], ["open", "https://example.com"])
        self.assertEqual(self.run.call_args.kwargs["timeout"], 10)
        self.open_browser.assert_not_called()

    def test_macos_default_browser_nonzero_is_failure_without_retry(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "no handler")
        with patch("sys.platform", "darwin"), patch.object(browser, "_apply_layout") as layout:
            self.assertIs(browser.open_target("https://example.com", layout={"type": "full"}), False)
            layout.assert_not_called()
        self.run.assert_called_once()
        self.open_browser.assert_not_called()

    def test_macos_default_browser_timeout_is_failure_without_retry(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("mock", 10)
        with patch("sys.platform", "darwin"), patch.object(browser, "_apply_layout") as layout:
            self.assertIs(browser.open_target("https://example.com", layout={"type": "full"}), False)
            layout.assert_not_called()
        self.run.assert_called_once()
        self.open_browser.assert_not_called()

    def test_macos_missing_default_launcher_is_failure_without_retry(self) -> None:
        self.run.side_effect = FileNotFoundError()
        with patch("sys.platform", "darwin"):
            self.assertIs(browser.open_target("https://example.com"), False)
        self.run.assert_called_once()
        self.open_browser.assert_not_called()

    def test_non_macos_default_browser_behavior_is_preserved(self) -> None:
        with patch("sys.platform", "linux"):
            self.assertIs(browser.open_target("https://example.com"), True)
        self.open_browser.assert_called_once_with("https://example.com")
        self.run.assert_not_called()

    def test_browser_does_not_log_url_contents(self) -> None:
        browser.open_target("https://example.com/?token=AUDIT_SECRET", "Safari", new_window=True)
        self.assertNotIn("AUDIT_SECRET", str(self.logs[browser].call_args_list))

    def test_btt_and_alfred_nonzero_results_are_failures(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "no handler")
        for launch, args in (
            (btt.trigger_named_btt, ("Audit",)),
            (btt.trigger_alfred, ("com.example.audit", "audit")),
        ):
            with self.subTest(backend=launch.__name__), patch.object(btt, "notify_run_error") as notify:
                result = launch(*args)
                self.assertFalse(result.ok)
                self.assertEqual(result.returncode, 1)
                notify.assert_called_once()

    def test_btt_and_alfred_launch_success(self) -> None:
        with patch.object(btt, "notify_run_error") as notify:
            self.assertTrue(btt.trigger_named_btt("Audit").ok)
            self.assertTrue(btt.trigger_alfred("com.example.audit", "audit").ok)
            notify.assert_not_called()

    def test_run_backend_timeouts_return_failure(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("mock", 1)
        for module, launch, args in (
            (btt, btt.trigger_named_btt, ("Audit",)),
            (btt, btt.trigger_alfred, ("com.example.audit", "audit")),
            (applescript, applescript.run_applescript, ("return 1",)),
            (shortcuts, shortcuts.run_shortcut, ("Audit",)),
        ):
            with self.subTest(backend=launch.__name__), patch.object(module, "notify_run_error") as notify:
                self.assertFalse(launch(*args).ok)
                notify.assert_called_once()

    def test_notification_nonzero_status_is_reported(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "denied")
        with patch.object(notifications, "RUN_ERROR_NOTIFICATIONS", True):
            notifications.notify_run_error("Audit", "Audit")
        self.assertTrue(self.logs[notifications].called)

    def test_disabled_notifications_do_not_launch(self) -> None:
        with patch.object(notifications, "RUN_ERROR_NOTIFICATIONS", False):
            notifications.notify_run_error("Audit", "Audit")
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
