from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from runtime import jobs as runner
from state import jobs


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")


def test_failed_attempt_is_not_replayed_automatically():
    # v1.5.6 - a failed attempt must not rerun each scheduler tick.
    callback = Mock(return_value={"success": False, "status": "failed", "error": "Example"})
    first = runner.run_inline(callback, kind="event", key="event", retry=False)
    second = runner.run_inline(callback, kind="event", key="event", retry=False)
    assert first["status"] == "failed"
    assert second["status"] == "skipped"
    assert callback.call_count == 1
    runner.run_inline(callback, kind="event", key="event", retry=True)
    assert callback.call_count == 2


def test_manual_and_scheduled_share_active_claim():
    one, two = jobs.create("event"), jobs.create("event")
    with jobs.lease(one):
        jobs.start(one)
        assert jobs.claim_event(one, "event", retry=False)[0]
        assert not jobs.claim_event(two, "event", retry=True)[0]


def test_overlapping_manual_requests_cannot_become_sequential_retries():
    first = jobs.create("event")
    with jobs.lease(first):
        jobs.start(first)
        assert jobs.claim_event(first, "event", retry=True)[0]
        overlapping = jobs.create("event")
        jobs.finish(first, {"success": True, "status": "succeeded"})
    assert not jobs.claim_event(overlapping, "event", retry=True)[0]
    explicit_later_retry = jobs.create("event")
    assert jobs.claim_event(explicit_later_retry, "event", retry=True)[0]


def test_crashed_worker_requires_explicit_retry():
    one = jobs.create("event")
    with jobs.lease(one):
        jobs.start(one)
        jobs.claim_event(one, "event", retry=False)
    assert jobs.get(one)["status"] == "interrupted"
    two = jobs.create("event")
    assert not jobs.claim_event(two, "event", retry=False)[0]
    assert jobs.claim_event(two, "event", retry=True)[0]


def test_long_lived_lease_does_not_expire():
    one = jobs.create("event")
    with jobs.lease(one):
        jobs.start(one)
        with patch.object(jobs.time, "time", return_value=10**12):
            assert jobs.get(one)["status"] == "running"


def test_submission_detaches_and_keeps_payload_private():
    with patch.object(runner.subprocess, "Popen") as launch:
        result = runner.submit("script", "+CalFlow+\nwait 100")
    assert launch.call_args.kwargs["start_new_session"] is True
    path = jobs.job_path(result["job_id"], ".request")
    assert path.stat().st_mode & 0o777 == 0o600
    assert "+CalFlow+" not in str(launch.call_args)


def test_cancel_never_signals_reused_pid():
    one = jobs.create("script")
    with jobs.lease(one):
        jobs.start(one)
        with patch.object(runner.subprocess, "run", return_value=Mock(stdout="other-process")), patch.object(runner.os, "killpg") as kill:
            runner.cancel(one)
        kill.assert_not_called()


def test_invalid_job_identifier_cannot_escape_directory():
    with pytest.raises(ValueError):
        jobs.get("../../example")


def test_two_processes_cannot_claim_the_same_occurrence(tmp_path):
    source = '''
import json,sys,time
from pathlib import Path
from state import jobs
from runtime.jobs import run_inline
jobs.JOBS_DIR = Path(sys.argv[1])
def callback():
    time.sleep(0.1)
    return {"success": True, "status": "succeeded"}
print(json.dumps(run_inline(callback, kind="event", key="shared", retry=False)))
'''

    def invoke(_):
        proc = subprocess.run([sys.executable, "-c", source, str(tmp_path / "process-jobs")],
                              capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(invoke, range(2))) == ["skipped", "succeeded"]


def test_cancellation_signals_only_the_verified_worker_group():
    one = jobs.create("script", detached=True)
    with jobs.lease(one):
        jobs.start(one)
        with patch.object(runner.subprocess, "run", return_value=Mock(stdout=f"python -m cli.main job-worker {one}")), \
                patch.object(runner.os, "getpgid", return_value=os.getpid()), \
                patch.object(runner.os, "killpg") as kill:
            assert runner.cancel(one)["status"] == "cancelling"
        kill.assert_called_once_with(os.getpid(), runner.signal.SIGTERM)


def test_cancel_before_worker_start_never_executes():
    with patch.object(runner.subprocess, "Popen"):
        submitted = runner.submit("script", "+CalFlow+\nwait 0")
    runner.cancel(submitted["job_id"])
    execute = Mock()
    with patch.object(runner.signal, "signal"):
        runner.worker(submitted["job_id"], execute, execute)
    execute.assert_not_called()
    assert jobs.get(submitted["job_id"])["status"] == "cancelled"
    assert not jobs.job_path(submitted["job_id"], ".request").exists()


def test_worker_retains_failure_and_removes_private_request():
    with patch.object(runner.subprocess, "Popen"):
        submitted = runner.submit("script", "+CalFlow+\nwait 0")
    execute = Mock(return_value={"success": False, "status": "failed", "error": "Example failure"})
    with patch.object(runner.signal, "signal"):
        runner.worker(submitted["job_id"], Mock(), execute)
    result = jobs.get(submitted["job_id"])
    assert result["result"]["error"] == "Example failure"
    assert not result["cancellable"]
    assert not jobs.job_path(submitted["job_id"], ".request").exists()
