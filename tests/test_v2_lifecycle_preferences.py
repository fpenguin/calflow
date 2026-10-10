from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from cli import onboarding
from core import settings_writer


def test_restart_does_not_resume_a_stopped_daemon():
    # v1.5.6 - saving settings must preserve a paused service.
    with patch.object(onboarding.subprocess, "run", return_value=Mock(stdout="", returncode=0)), \
            patch.object(onboarding, "start_launchd") as start:
        onboarding.restart_launchd()
    start.assert_not_called()


@pytest.mark.parametrize("value", ["false", 1, None, []])
def test_login_toggle_requires_boolean(value):
    with patch.object(settings_writer, "_run_launchctl") as run:
        result = settings_writer.apply_settings({"general.auto_start_at_login": value})
    assert result["rejected"]
    run.assert_not_called()


def test_paused_daemon_does_not_query_calendar(monkeypatch):
    from cli import main
    from state import lifecycle
    lifecycle.update(paused=True)
    service = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(main, "build_service", service)
    main.main()
    service.assert_not_called()


def test_login_choice_does_not_start_or_stop_current_run(monkeypatch):
    from state import lifecycle
    monkeypatch.setattr(onboarding.os.path, "exists", lambda _: True)
    with patch.object(onboarding.subprocess, "run", return_value=Mock(returncode=0)) as run:
        onboarding.set_login_preference("daemon", False)
    assert lifecycle.load()["daemon_login"] is False
    assert run.call_args.args[0][1] == "disable"
    assert all(call.args[0][1] not in {"load", "unload", "bootout"} for call in run.call_args_list)


def test_failed_launchctl_does_not_save_login_choice(monkeypatch):
    from state import lifecycle
    monkeypatch.setattr(onboarding.os.path, "exists", lambda _: True)
    with patch.object(onboarding.subprocess, "run", side_effect=OSError("Example")):
        with pytest.raises(OSError):
            onboarding.set_login_preference("daemon", False)
    assert lifecycle.load()["daemon_login"] is True


def test_generated_daemon_plist_escapes_installation_path(monkeypatch):
    import plistlib
    monkeypatch.setattr(onboarding, "BASE_DIR", "/tmp/Example & Work")
    values = plistlib.loads(onboarding.generate_plist(30).encode())
    assert values["WorkingDirectory"] == "/tmp/Example & Work"
    assert values["RunAtLoad"] is True


def test_daemon_install_failure_is_not_announced_as_success(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.setattr(onboarding, "PLIST_PATH", str(tmp_path / "agent.plist"))
    with patch.object(onboarding.subprocess, "run", side_effect=subprocess.CalledProcessError(5, "launchctl")):
        with pytest.raises(subprocess.CalledProcessError):
            onboarding.install_launchd(30)
    assert "enabled" not in capsys.readouterr().out


@pytest.mark.parametrize("first", ["core.utils", "core.settings_reader", "core.targets_reader", "config.settings"])
def test_saved_preferences_and_aliases_do_not_depend_on_import_order(tmp_path, first):
    import json
    import subprocess
    import sys
    (tmp_path / "user_settings.json").write_text(json.dumps({
        "schema_version": 1, "overrides": {"MAX_URLS": 17, "LOG_MODE": "stderr"},
    }))
    (tmp_path / "user_targets.json").write_text(json.dumps({
        "schema_version": 1, "targets": {"@example": "Notes"},
    }))
    source = '''
import importlib,sys
from pathlib import Path
import config.config as paths
paths.DATA_DIR = Path(sys.argv[1])
importlib.import_module(sys.argv[2])
from config import settings
from core.utils import log
assert settings.MAX_URLS == 17
assert settings.TARGETS["@example"] == "Notes"
log("synthetic-log")
'''
    proc = subprocess.run([sys.executable, "-c", source, str(tmp_path), first],
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    assert not proc.stdout
    assert "synthetic-log" in proc.stderr
