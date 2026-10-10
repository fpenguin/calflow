from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from core.parser.parser import parse
from runtime.run_policy import is_open_target_allowed


@pytest.mark.parametrize("command", [
    'close @chrome except("Notes")', 'close "Notes" except("Safari")',
    'close all except("Notes")', "close except()", "close except([])",
    'close except("")', 'close @chrome @safari',
])
def test_close_never_widens_ambiguous_scope(command):
    # v1.5.6 - malformed named targets must not become close-all.
    result = parse("+CalFlow+\n" + command)
    assert result.errors
    assert not result.commands


@pytest.mark.parametrize("target", ["folder/Example.app", "folder/script.scpt", "./Example.app", "~/Example.app", "file:///tmp/Example.app"])
def test_invitation_cannot_launch_relative_files(target):
    assert not is_open_target_allowed(target, "trusted_domain")
    assert is_open_target_allowed(target, "self")


@pytest.mark.parametrize("args,code", [("--help", 0), ("statuz", 2), ("--unknown", 2), ("status --unknown", 2)])
def test_help_and_invalid_cli_never_import_calendar_dependencies(args, code):
    result = subprocess.run([sys.executable, "-S", "-m", "cli.main", *args.split()],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == code, result.stderr
    assert "Traceback" not in result.stderr


def test_interactive_event_execution_preserves_inviter_trust(monkeypatch):
    from cli import main
    event = {"id": "example", "start": datetime.now(timezone.utc),
             "creator_email": "outside@example.net", "calendar_id": "primary",
             "_owner_email": "me@example.com", "text": "+CalFlow+\nrun applescript\n+++\nreturn 1\n+++"}
    execute = Mock()
    monkeypatch.setattr(main, "execute_commands", execute)
    with patch("builtins.input", return_value="q"):
        main._step2b_execute_loop(event, parse(event["text"]))
    execute.assert_not_called()


def test_large_numeric_argument_rejects_one_line_only():
    result = parse("+CalFlow+\nwait 1\ndrag from(" + "9" * 311 + ",0) to(1,1)\nwait 2")
    assert [command.name for command in result.commands] == ["WAIT", "WAIT"]
    assert result.errors


@pytest.mark.parametrize("command", ["submit-event", "job-status", "job-cancel"])
def test_job_id_is_canonicalized_before_json_flag(command):
    from cli.arguments import validate_arguments

    assert validate_arguments([command, "--json", "example"]) == [command, "example", "--json"]


def test_close_without_resolved_scope_does_not_close_everything():
    from runtime.command_executor import _do_close

    with patch("runtime.actions.app_control.close_all") as close_all:
        result = _do_close({})
    close_all.assert_not_called()
    assert not result.ok
