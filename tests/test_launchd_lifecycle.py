from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cli import onboarding


def test_start_daemon_when_only_menubar_is_loaded():
    listed = SimpleNamespace(returncode=0, stdout="123\t0\tcom.calflow.menubar\n", stderr="")
    loaded = SimpleNamespace(returncode=0, stdout="", stderr="")
    with (
        patch.object(onboarding.os.path, "exists", return_value=True),
        patch.object(onboarding.subprocess, "run", side_effect=[listed, loaded, loaded]) as run,
    ):
        onboarding.start_launchd()
    assert run.call_count == 3
    assert run.call_args.args[0] == ["launchctl", "load", onboarding.PLIST_PATH]


def test_start_daemon_reports_load_failure():
    listed = SimpleNamespace(returncode=0, stdout="", stderr="")
    with (
        patch.object(onboarding.os.path, "exists", return_value=True),
        patch.object(onboarding.subprocess, "run", side_effect=[
            listed, listed, subprocess.CalledProcessError(5, "launchctl", stderr="bad plist")
        ]),
        pytest.raises(subprocess.CalledProcessError),
    ):
        onboarding.start_launchd()


def test_daemon_status_does_not_confuse_menubar():
    from cli.main import _daemon_state

    listed = SimpleNamespace(returncode=0, stdout="123\t0\tcom.calflow.menubar\n", stderr="")
    with patch("subprocess.run", return_value=listed):
        assert _daemon_state() == {"loaded": False, "raw_line": None}


def test_stop_already_stopped_daemon_is_idempotent():
    listed = SimpleNamespace(returncode=0, stdout="123\t0\tcom.calflow.menubar\n", stderr="")
    with (
        patch.object(onboarding.os.path, "exists", return_value=True),
        patch.object(onboarding.subprocess, "run", return_value=listed) as run,
    ):
        onboarding.stop_launchd()
    assert run.call_count == 1


def test_stop_reports_unload_failure():
    listed = SimpleNamespace(returncode=0, stdout="-\t0\tcom.calflow\n", stderr="")
    with (
        patch.object(onboarding.os.path, "exists", return_value=True),
        patch.object(onboarding.subprocess, "run", side_effect=[
            listed, subprocess.CalledProcessError(5, "launchctl")
        ]),
        pytest.raises(subprocess.CalledProcessError),
    ):
        onboarding.stop_launchd()


def test_menubar_entrypoint_does_not_require_calendar_dependencies():
    code = """
import runpy, sys, types
menubar = types.ModuleType('cli.menubar')
menubar.main = lambda: print('menubar-ready')
sys.modules['cli.menubar'] = menubar
sys.argv = ['cli.main', 'menubar']
runpy.run_module('cli.main', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "menubar-ready"
