"""Detached workers and shared attempt ownership for calendar/manual workflows."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from state import jobs

__all__ = ["run_inline", "submit", "worker", "cancel", "event_key"]

BASE_DIR = Path(__file__).resolve().parents[1]


class JobCancelled(BaseException):
    pass


def event_key(event_id: str, start: str) -> str:
    return hashlib.sha256(f"{event_id}_{start}".encode()).hexdigest()


def run_inline(callback: Callable[[], dict], *, kind: str, key: str | None = None,
               retry: bool = False, job_id: str | None = None) -> dict:
    if key and not retry and job_id is None:
        previous = jobs.attempt(key)
        if previous:
            return {"success": False, "status": "skipped", "existing_job_id": previous}
    if job_id is None:
        job_id = jobs.create(kind)
        with jobs.lease(job_id):
            if not jobs.start(job_id):
                return {"success": False, "status": "cancelled", "job_id": job_id}
            return _run(callback, job_id, key, retry)
    return _run(callback, job_id, key, retry)


def _run(callback, job_id, key, retry):
    try:
        if key:
            claimed, previous = jobs.claim_event(job_id, key, retry=retry)
            if not claimed:
                result = {"success": False, "status": "skipped", "existing_job_id": previous,
                          "error": "This occurrence already has an attempt; retry after it stops"}
                jobs.finish(job_id, result)
                return {**result, "job_id": job_id}
        if jobs.get(job_id)["status"] == "cancelling":
            raise JobCancelled()
        result = callback()
    except JobCancelled:
        result = {"success": False, "status": "cancelled", "error": "Run cancelled"}
    except Exception as exc:
        result = {"success": False, "status": "failed",
                  "error": f"Run failed ({type(exc).__name__}); check permissions and configuration"}
    result = {**result, "job_id": job_id}
    jobs.finish(job_id, result)
    return result


def submit(kind: str, payload: str) -> dict:
    if kind not in {"event", "script"} or not payload or len(payload.encode()) > 128_000:
        raise ValueError("Invalid or oversized job request")
    job_id = jobs.create(kind, detached=True)
    path = jobs.job_path(job_id, ".request")
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump({"kind": kind, "payload": payload}, handle)
        subprocess.Popen(
            [sys.executable, "-m", "cli.main", "job-worker", job_id], cwd=BASE_DIR,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except OSError:
        path.unlink(missing_ok=True)
        jobs.finish(job_id, {"success": False, "status": "failed", "error": "Could not start worker"})
        raise
    return {"ok": True, "job_id": job_id, "status": "queued"}


def worker(job_id: str, event_runner, script_runner) -> None:
    def cancelled(*_args):
        raise JobCancelled()

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    with jobs.lease(job_id):
        path = jobs.job_path(job_id, ".request")
        if not jobs.start(job_id):
            path.unlink(missing_ok=True)
            jobs.finish(job_id, {"success": False, "status": "cancelled", "error": "Run cancelled"})
            return
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            if request["kind"] == "event":
                result = event_runner(request["payload"], job_id=job_id, emit=False)
            else:
                result = run_inline(lambda: script_runner(request["payload"]), kind="script", job_id=job_id)
            jobs.finish(job_id, result)
        except JobCancelled:
            jobs.finish(job_id, {"success": False, "status": "cancelled", "error": "Run cancelled"})
        except Exception as exc:
            jobs.finish(job_id, {"success": False, "status": "failed",
                                 "error": f"Worker failed ({type(exc).__name__})"})
        finally:
            path.unlink(missing_ok=True)


def cancel(job_id: str) -> dict:
    current = jobs.get(job_id)
    pid = current.get("pid")
    if pid and current["status"] in jobs.ACTIVE:
        # Never signal a recycled PID or an unrelated CLI process.
        try:
            probe = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                   capture_output=True, text=True, timeout=2, check=False)
            args = shlex.split(probe.stdout.strip())
            if args[-3:] == ["cli.main", "job-worker", job_id] and os.getpgid(pid) == pid:
                jobs.request_cancel(job_id)
                os.killpg(pid, signal.SIGTERM)
            else:
                return {"ok": False, "job_id": job_id,
                        "error": "Foreground run: cancel from its terminal"}
        except ProcessLookupError:
            pass
    elif current["status"] == "queued":
        jobs.request_cancel(job_id)
    return {"ok": True, "job_id": job_id, "status": jobs.get(job_id)["status"]}
