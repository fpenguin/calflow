"""
App-control tests (v2.0.9+).

Pure unit tests — no real apps are launched / quit / hidden. We patch
subprocess.run to capture the AppleScript that would have been sent
and assert it has the right shape.

Run:
    python -m unittest tests.test_v2_app_control -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import runtime.actions.app_control as ac


# =============================================================
# 🔧 Test helper: capture osascript invocations
# =============================================================

class _CaptureMixin:
    """Mixin that patches subprocess.run and stores invocations."""

    def setUp(self):
        self.calls = []

        def fake_run(cmd, *args, **kwargs):
            self.calls.append(cmd)
            class _R:
                returncode = 0
                stdout = ""
                stderr = ""
            return _R()

        self._patcher = mock.patch.object(ac.subprocess, "run", side_effect=fake_run)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _last_script(self) -> str:
        self.assertGreater(len(self.calls), 0, "no osascript call captured")
        cmd = self.calls[-1]
        self.assertEqual(cmd[0], "osascript")
        # cmd is ['osascript', '-e', '<script>']
        return cmd[2]


# =============================================================
# focus_app
# =============================================================

class FocusApp(_CaptureMixin, unittest.TestCase):
    def test_simple_activate(self):
        self.assertTrue(ac.focus_app("Google Chrome"))
        s = self._last_script()
        self.assertIn('tell application "Google Chrome" to activate', s)

    def test_missing_app_returns_false(self):
        self.assertFalse(ac.focus_app(""))
        self.assertEqual(self.calls, [])

    def test_double_quote_escaped(self):
        self.assertTrue(ac.focus_app('Weird "App" Name'))
        self.assertIn(r'Weird \"App\" Name', self._last_script())


# =============================================================
# focus_window_by_title
# =============================================================

class FocusWindowByTitle(_CaptureMixin, unittest.TestCase):
    def test_includes_activate_and_axraise(self):
        self.assertTrue(ac.focus_window_by_title("Google Chrome", "Inbox"))
        s = self._last_script()
        self.assertIn('tell application "Google Chrome" to activate', s)
        self.assertIn('tell process "Google Chrome"', s)
        self.assertIn('whose title contains "Inbox"', s)
        self.assertIn('AXRaise', s)

    def test_empty_title_falls_back_to_focus_app(self):
        self.assertTrue(ac.focus_window_by_title("Google Chrome", ""))
        s = self._last_script()
        # Falls back to plain activate — no AXRaise
        self.assertIn("activate", s)
        self.assertNotIn("AXRaise", s)


# =============================================================
# close_app
# =============================================================

class CloseApp(_CaptureMixin, unittest.TestCase):
    def test_quit_only_if_running(self):
        self.assertTrue(ac.close_app("Spotify"))
        s = self._last_script()
        self.assertIn('exists (process "Spotify")', s)
        self.assertIn('tell application "Spotify" to quit', s)

    def test_missing_app_returns_false(self):
        self.assertFalse(ac.close_app(""))


# =============================================================
# hide_app
# =============================================================

class HideApp(_CaptureMixin, unittest.TestCase):
    def test_sets_visible_false_via_system_events(self):
        self.assertTrue(ac.hide_app("Slack"))
        s = self._last_script()
        self.assertIn('exists (process "Slack")', s)
        self.assertIn('set visible of process "Slack" to false', s)


# =============================================================
# hide_all
# =============================================================

class HideAll(unittest.TestCase):
    """
    hide_all uses _osascript_capture (returns stdout) instead of
    plain _osascript, so we patch differently.
    """

    def setUp(self):
        self.calls = []

        def fake_run(cmd, *args, **kwargs):
            self.calls.append(cmd)
            class _R:
                returncode = 0
                # Realistic shape — three TAB-separated lines
                stdout = "KEPT\tFinder, Google Chrome, Notion\nHIDDEN\tSpotify, Discord\nERRORED\t"
                stderr = ""
            return _R()

        self._patcher = mock.patch.object(ac.subprocess, "run", side_effect=fake_run)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _last_script(self) -> str:
        return self.calls[-1][2]

    def test_no_keep_list(self):
        self.assertTrue(ac.hide_all())
        s = self._last_script()
        # Returns a TSV summary
        self.assertIn("KEPT", s)
        self.assertIn("HIDDEN", s)
        self.assertIn("ERRORED", s)
        # Skips the frontmost
        self.assertIn("frontApp", s)
        # Empty keep list
        self.assertIn("set keepList to {}", s)
        self.assertIn("set visible of p to false", s)

    def test_with_keep_list_includes_each_name(self):
        self.assertTrue(ac.hide_all(except_apps=["Notion", "Figma"]))
        s = self._last_script()
        # New shape: AppleScript list literal that the script checks via
        # `keepList contains procName`.
        self.assertIn('"Notion"', s)
        self.assertIn('"Figma"', s)
        self.assertIn("keepList contains procName", s)

    def test_returns_false_when_osascript_fails(self):
        with mock.patch.object(ac.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=1, stdout="", stderr="not allowed (1002)"
            )
            self.assertFalse(ac.hide_all(except_apps=["Notion"]))


# =============================================================
# osascript-failure handling
# =============================================================

class FailureHandling(unittest.TestCase):
    def test_returncode_nonzero_logs_warn_returns_false(self):
        with mock.patch.object(ac.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=1, stdout="",
                stderr="execution error: not allowed (1002)",
            )
            self.assertFalse(ac.focus_app("Slack"))

    def test_missing_osascript_returns_false(self):
        with mock.patch.object(ac.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertFalse(ac.focus_app("Slack"))

    def test_subprocess_exception_returns_false(self):
        with mock.patch.object(ac.subprocess, "run", side_effect=RuntimeError("boom")):
            self.assertFalse(ac.focus_app("Slack"))


# =============================================================
# resolve_chrome_profile
# =============================================================

class ChromeProfile(unittest.TestCase):
    def test_profile_1_is_default(self):
        from core.resolver import resolve_chrome_profile
        self.assertEqual(resolve_chrome_profile({"#profile(1)"}), "Default")

    def test_profile_2_is_profile_1(self):
        from core.resolver import resolve_chrome_profile
        self.assertEqual(resolve_chrome_profile({"#profile(2)"}), "Profile 1")

    def test_profile_5_is_profile_4(self):
        from core.resolver import resolve_chrome_profile
        self.assertEqual(resolve_chrome_profile({"#profile(5)"}), "Profile 4")

    def test_no_profile_tag_returns_none(self):
        from core.resolver import resolve_chrome_profile
        self.assertIsNone(resolve_chrome_profile({"#left(50%)"}))

    def test_profile_zero_is_invalid(self):
        from core.resolver import resolve_chrome_profile
        self.assertIsNone(resolve_chrome_profile({"#profile(0)"}))


# =============================================================
# open_target dispatch by primary classification
# =============================================================

class OpenTargetDispatch(unittest.TestCase):
    """Confirm open_target dispatches URL / app / file correctly."""

    def setUp(self):
        import runtime.actions.browser as br
        self.calls = []

        def fake_run(cmd, *args, **kwargs):
            self.calls.append(cmd)
            class _R:
                returncode = 0
                stdout = ""
                stderr = ""
            return _R()

        self._patcher = mock.patch.object(br.subprocess, "run", side_effect=fake_run)
        self._sleeper = mock.patch.object(br.time, "sleep", lambda *_a, **_k: None)
        self._patcher.start()
        self._sleeper.start()

    def tearDown(self):
        self._patcher.stop()
        self._sleeper.stop()

    def test_url_with_chrome_profile_uses_profile_directory(self):
        from runtime.actions.browser import open_target
        open_target(
            url="https://example.com",
            app="Google Chrome",
            chrome_profile="Profile 1",
        )
        self.assertEqual(len(self.calls), 1)
        cmd = self.calls[0]
        self.assertEqual(cmd[0], "open")
        self.assertIn("--args", cmd)
        self.assertIn("--profile-directory=Profile 1", cmd)
        self.assertIn("https://example.com", cmd)

    def test_quoted_app_name_launches_app_not_url(self):
        from runtime.actions.browser import open_target
        open_target(url='"Google Chrome"')
        self.assertEqual(self.calls[0], ["open", "-a", "Google Chrome"])

    def test_file_path_uses_open_path(self):
        from runtime.actions.browser import open_target
        open_target(url='"~/Downloads/test.pdf"')
        cmd = self.calls[0]
        self.assertEqual(cmd[0], "open")
        self.assertTrue(cmd[1].endswith("Downloads/test.pdf"))
        # ~ should be expanded
        self.assertNotIn("~", cmd[1])

    def test_url_routes_to_specific_browser(self):
        from runtime.actions.browser import open_target
        open_target(url="https://zoom.us", app="Safari")
        self.assertEqual(self.calls[0], ["open", "-a", "Safari", "https://zoom.us"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
