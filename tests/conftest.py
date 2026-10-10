"""Keep newly shared workflow metadata and desktop locks inside each test."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_workflow_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("state.state_manager.STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("state.stats_store.STATS_PATH", tmp_path / "stats.json")
    monkeypatch.setattr("core.settings_reader.DATA_DIR", tmp_path)
    monkeypatch.setattr("state.lifecycle.PREFERENCES_PATH", tmp_path / "lifecycle.json")
    monkeypatch.setattr("state.jobs.JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr("runtime.actions.execution_lock.LOCK_PATH", tmp_path / "desktop.lock")
    original = subprocess.Popen

    def guarded_popen(args, *extra, **kwargs):
        executable = args[0] if isinstance(args, (tuple, list)) else str(args).split()[0]
        if Path(executable).name in {"launchctl", "osascript", "open", "shortcuts", "screencapture", "pbcopy"}:
            raise AssertionError("Test attempted an unmocked native action")
        return original(args, *extra, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
