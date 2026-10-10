from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cli.menubar_launchd as ml


class MenubarLaunchdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.plist = root / "Library" / "LaunchAgents" / "com.calflow.menubar.plist"
        self.data = root / "data"
        self.patches = [
            patch.object(ml, "BASE_DIR", root),
            patch.object(ml, "DATA_DIR", self.data),
            patch.object(ml, "MENUBAR_PLIST_PATH", self.plist),
            patch.object(ml, "MENUBAR_LOCK_PATH", root / "menubar.lock"),
            patch.object(ml.time, "sleep"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_generate_plist_runs_menubar_entrypoint(self) -> None:
        plist = ml.generate_menubar_plist()
        self.assertIn("<string>com.calflow.menubar</string>", plist)
        self.assertIn("<string>-m</string>", plist)
        self.assertIn("<string>cli.main</string>", plist)
        self.assertIn("<string>menubar</string>", plist)
        self.assertIn("<key>RunAtLoad</key>", plist)
        self.assertIn("menubar.out.log", plist)
        self.assertIn("menubar.err.log", plist)

    def test_login_agent_recovers_failure_but_respects_clean_quit(self) -> None:
        plist = plistlib.loads(ml.generate_menubar_plist().encode())
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertGreaterEqual(plist["ThrottleInterval"], 10)

    def test_plist_escapes_install_path(self) -> None:
        root = self.data / "Apps & Tools"
        with patch.object(ml, "BASE_DIR", root):
            plist = plistlib.loads(ml.generate_menubar_plist().encode())
        self.assertEqual(plist["WorkingDirectory"], str(root))

    def test_loaded_line_requires_exact_label(self) -> None:
        proc = SimpleNamespace(stdout="123\t0\tcom.calflow.menubar.backup\n")
        with patch.object(ml, "_run_launchctl", return_value=proc):
            self.assertIsNone(ml._loaded_line())

    def test_install_writes_plist_and_loads_launch_agent(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str]):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(ml, "_run_launchctl", side_effect=fake_run), \
             patch.object(ml, "_loaded_line", return_value="123\t0\tcom.calflow.menubar"), \
             patch.object(ml, "_read_lock", return_value={"alive": True}):
            result = ml.install_menubar(load=True)

        self.assertTrue(self.plist.exists())
        self.assertTrue(result["ok"])
        self.assertTrue(result["loaded"])
        self.assertIn(["enable", ml._service_target()], calls)
        self.assertIn(["bootout", ml._service_target()], calls)
        self.assertIn(["bootstrap", f"gui/{ml.os.getuid()}", str(self.plist)], calls)

    def test_install_failure_returns_recovery_steps(self) -> None:
        def fake_run(args: list[str]):
            if args and args[0] == "bootstrap":
                return SimpleNamespace(returncode=5, stdout="", stderr="bad plist")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(ml, "_run_launchctl", side_effect=fake_run), \
             patch.object(ml, "_loaded_line", return_value=None):
            result = ml.install_menubar(load=True)

        self.assertFalse(result["ok"])
        self.assertIn("bad plist", result["error"])
        self.assertTrue(any("menubar-install" in step for step in result["recovery"]))

    def test_start_loaded_but_process_not_ready_returns_recovery_steps(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text(ml.generate_menubar_plist(), encoding="utf-8")

        with patch.object(ml, "_run_launchctl",
                          return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
             patch.object(ml, "_loaded_line", return_value="123\t0\tcom.calflow.menubar"), \
             patch.object(ml, "_read_lock", return_value={"alive": False}):
            result = ml.start_menubar()

        self.assertFalse(result["ok"])
        self.assertIn("did not become ready", result["error"])
        self.assertTrue(any("tail -n 80" in step for step in result["recovery"]))

    def test_start_migrates_old_login_agent(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(plistlib.dumps({"KeepAlive": False}))
        with patch.object(ml, "install_menubar", return_value={"ok": True}) as install:
            result = ml.start_menubar()
        install.assert_called_once_with(load=True)
        self.assertEqual(result, {"ok": True, "action": "start"})

    def test_start_does_not_kill_a_running_app(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text(ml.generate_menubar_plist(), encoding="utf-8")
        with patch.object(ml, "_run_launchctl", return_value=SimpleNamespace(returncode=0, stderr="")) as run, \
             patch.object(ml, "_loaded_line", return_value="123\t0\tcom.calflow.menubar"), \
             patch.object(ml, "_read_lock", return_value={"alive": True}):
            self.assertTrue(ml.start_menubar()["ok"])
        run.assert_called_once_with(["kickstart", ml._service_target()])

    def test_write_only_install_does_not_change_running_job(self) -> None:
        with patch.object(ml, "_run_launchctl") as run, \
             patch.object(ml, "menubar_status", return_value={"loaded": True}):
            self.assertTrue(ml.install_menubar(load=False)["ok"])
        run.assert_not_called()

    def test_launchctl_timeout_is_reported(self) -> None:
        with patch.object(ml.subprocess, "run", side_effect=ml.subprocess.TimeoutExpired("launchctl", 10)):
            result = ml._run_launchctl(["list"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timed out", result.stderr)

    def test_status_reports_lock_and_plist_state(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("plist", encoding="utf-8")

        with patch.object(ml, "_loaded_line", return_value=None), \
             patch.object(ml, "_read_lock", return_value={"pid": 42, "alive": True}):
            result = ml.menubar_status()

        self.assertFalse(result["loaded"])
        self.assertTrue(result["plist_exists"])
        self.assertEqual(result["lock"]["pid"], 42)
        self.assertEqual(result["icon"], "dynamic-date")
        self.assertEqual(result["fallback_icon"], "calendar-plus")
        self.assertTrue(result["fallback_icon_path"].endswith("calflow-menubar-02-calendar-plus.svg"))

    def test_pid_alive_requires_menubar_command(self) -> None:
        with patch("os.kill", return_value=None), \
             patch.object(ml, "_pid_command", return_value="/usr/bin/python -m cli.main menubar"):
            self.assertTrue(ml._is_menubar_pid(123))

        with patch("os.kill", return_value=None), \
             patch.object(ml, "_pid_command", return_value="/usr/bin/python other.py"):
            self.assertFalse(ml._is_menubar_pid(123))


if __name__ == "__main__":
    unittest.main()
