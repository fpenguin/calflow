from __future__ import annotations

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

    def test_install_writes_plist_and_loads_launch_agent(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str]):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(ml, "_run_launchctl", side_effect=fake_run), \
             patch.object(ml, "_loaded_line", return_value="123\t0\tcom.calflow.menubar"):
            result = ml.install_menubar(load=True)

        self.assertTrue(self.plist.exists())
        self.assertTrue(result["ok"])
        self.assertTrue(result["loaded"])
        self.assertIn(["unload", str(self.plist)], calls)
        self.assertIn(["load", "-w", str(self.plist)], calls)

    def test_install_failure_returns_recovery_steps(self) -> None:
        def fake_run(args: list[str]):
            if args and args[0] == "load":
                return SimpleNamespace(returncode=5, stdout="", stderr="bad plist")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(ml, "_run_launchctl", side_effect=fake_run), \
             patch.object(ml, "_loaded_line", return_value=None):
            result = ml.install_menubar(load=True)

        self.assertFalse(result["ok"])
        self.assertIn("bad plist", result["error"])
        self.assertTrue(any("menubar-uninstall" in step for step in result["recovery"]))

    def test_start_loaded_but_process_not_ready_returns_recovery_steps(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("plist", encoding="utf-8")

        with patch.object(ml, "_run_launchctl",
                          return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
             patch.object(ml, "_loaded_line", return_value="123\t0\tcom.calflow.menubar"), \
             patch.object(ml, "_read_lock", return_value={"alive": False}):
            result = ml.start_menubar()

        self.assertFalse(result["ok"])
        self.assertIn("did not become ready", result["error"])
        self.assertTrue(any("tail -n 80" in step for step in result["recovery"]))

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
