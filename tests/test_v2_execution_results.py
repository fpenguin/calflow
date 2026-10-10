from __future__ import annotations

from unittest.mock import patch

import pytest

from core.execution_result import ExecutionReport, StepResult
from core.parser.parser import parse
from runtime import command_executor as executor
from runtime.actions.run_result import error_result, ok_result


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # v1.5.6 - regressions must never launch apps or use personal statistics.
    monkeypatch.setattr("runtime.actions.execution_lock.LOCK_PATH", tmp_path / "desktop.lock")
    monkeypatch.setattr(executor, "record_action", lambda *a, **k: None)
    monkeypatch.setattr(executor.time, "sleep", lambda *a: None)
    monkeypatch.setattr(executor, "notify_run_error", lambda *a: None)


def execute(text):
    return executor.execute_commands(parse("+CalFlow+\n" + text).commands)


def test_run_failure_is_reported_and_next_step_runs():
    with patch.object(executor, "run_applescript", return_value=error_result("applescript", "Example failure")):
        report = execute('run applescript\n+++\nerror "Example failure"\n+++\nwait 0')
    assert not report.ok
    assert [step.status for step in report.steps] == ["failed", "succeeded"]
    assert "Example failure" in report.to_dict()["error"]


def test_handoff_is_not_workflow_completion():
    with patch.object(executor, "trigger_named_btt", return_value=ok_result("btt")):
        report = execute('run btt("Example")')
    assert report.status == "handed_off"


@pytest.mark.parametrize("source", ['click text("Example")', 'type "Example"', 'paste', 'save to("/tmp/example.txt")'])
def test_stubs_are_not_success(source):
    assert execute(source).status == "unsupported"


def test_failed_open_never_reports_success_or_autofills():
    with patch.object(executor, "open_target", return_value=False), patch.object(executor, "trigger_autofill") as fill:
        report = execute('open https://example.com #fill')
    assert not report.ok
    fill.assert_not_called()


def test_report_retains_step_details():
    report = ExecutionReport([StepResult("blocked", "Denied", "RUN", 2)])
    assert report.to_dict()["steps"][0]["line"] == 2


def test_failed_calendar_attempt_is_not_marked_done_or_automatically_retried(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import Mock

    from cli import main
    from state import load_state

    event = {"id": "synthetic", "start": datetime.now(timezone.utc),
             "text": "+CalFlow+\nwait 0"}
    action = Mock(return_value=ExecutionReport([StepResult("failed", "Example", "WAIT", 1)]))
    monkeypatch.setattr(main, "execute_commands", action)
    assert not main._run_event_payload(event, "self", manual=False)["success"]
    assert load_state() == {}
    assert main._run_event_payload(event, "self", manual=False)["status"] == "skipped"
    action.assert_called_once()
    main._run_event_payload(event, "self", manual=True)
    assert action.call_count == 2


def test_ordinary_logs_do_not_include_calendar_payload(capsys):
    marker = "PRIVATE_SYNTHETIC_SENTINEL"
    parse(f"https://example.com/?token={marker}\n#display(2)", title=f"https://example.com/{marker}")
    with patch.object(executor, "open_target", return_value=True):
        execute(f'type "{marker}"\nnotacommand "{marker}"\nopen https://example.com/{marker}')
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
