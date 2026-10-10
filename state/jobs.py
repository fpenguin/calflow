"""Private job metadata and atomic event claims, separate from legacy state.json."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from config.config import DATA_DIR

__all__ = ["create", "get", "recent", "lease", "start", "finish", "claim_event", "request_cancel",
           "attempt", "job_path", "ACTIVE"]

JOBS_DIR = Path(DATA_DIR) / "jobs"
ACTIVE = {"queued", "running", "cancelling"}


def _root() -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    JOBS_DIR.chmod(0o700)
    return JOBS_DIR


def job_path(job_id: str, suffix: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid job identifier")
    return _root() / (job_id + suffix)


@contextmanager
def _db():
    path = _root() / "jobs.sqlite3"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    path.chmod(0o600)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, status TEXT, "
                     "pid INTEGER, created REAL, updated REAL, result TEXT, detached INTEGER DEFAULT 0)")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "detached" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN detached INTEGER DEFAULT 0")
        conn.execute("CREATE TABLE IF NOT EXISTS claims (event_key TEXT PRIMARY KEY, job_id TEXT)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def create(kind: str, *, detached: bool = False) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _db() as conn:
        conn.execute("INSERT INTO jobs VALUES (?, ?, 'queued', NULL, ?, ?, NULL, ?)",
                     (job_id, kind, now, now, int(detached)))
        # Keep claims for replay protection, but discard old detailed outputs.
        conn.execute("UPDATE jobs SET result=NULL WHERE updated < ? AND status NOT IN "
                     "('queued','running','cancelling')", (now - 7 * 86400,))
    return job_id


@contextmanager
def lease(job_id: str):
    path = job_path(job_id, ".lease")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _alive(job_id: str) -> bool:
    try:
        with lease(job_id):
            return False
    except BlockingIOError:
        return True


def start(job_id: str) -> bool:
    with _db() as conn:
        cur = conn.execute("UPDATE jobs SET status='running', pid=?, updated=? "
                           "WHERE id=? AND status='queued'", (os.getpid(), time.time(), job_id))
        return cur.rowcount == 1


def finish(job_id: str, result: dict) -> None:
    status = result.get("status", "failed")
    if status not in {"succeeded", "handed_off", "failed", "blocked", "unsupported",
                      "skipped", "cancelled", "interrupted"}:
        status = "failed"
    encoded = json.dumps(result, ensure_ascii=True)
    if len(encoded) > 128_000:
        encoded = json.dumps({"status": status, "success": result.get("success", False),
                              "error": result.get("error", "")[:4000],
                              "details_truncated": True})
    with _db() as conn:
        conn.execute("UPDATE jobs SET status=?, result=?, updated=? WHERE id=?",
                     (status, encoded, time.time(), job_id))


def get(job_id: str) -> dict:
    job_path(job_id, ".lease")  # validate before any lookup
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError("Job not found")
    result = dict(row)
    # A live lease has no age limit. A dead worker is never replayed silently.
    if result["status"] in ACTIVE:
        try:
            with lease(job_id), _db() as conn:
                # Re-read under both locks: a worker may have finished since the first lookup.
                result = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                if result["status"] in ACTIVE and (
                    result["status"] != "queued" or time.time() - result["created"] > 30
                ):
                    cancelled = result["status"] == "cancelling"
                    outcome = {"success": False, "status": "cancelled" if cancelled else "interrupted",
                               "error": "Run cancelled" if cancelled else "Worker stopped; retry explicitly"}
                    conn.execute("UPDATE jobs SET status=?, result=?, updated=? WHERE id=?",
                                 (outcome["status"], json.dumps(outcome), time.time(), job_id))
                    result.update(status=outcome["status"], result=json.dumps(outcome))
                    job_path(job_id, ".request").unlink(missing_ok=True)
        except BlockingIOError:
            pass
    result["result"] = json.loads(result["result"]) if result["result"] else None
    result["cancellable"] = bool(result["detached"]) and result["status"] in ACTIVE
    return result


def recent(limit: int = 20) -> list[dict]:
    with _db() as conn:
        ids = [row[0] for row in conn.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT ?",
                                             (min(max(limit, 1), 50),))]
    return [get(job_id) for job_id in ids]


def attempt(event_key: str) -> str | None:
    with _db() as conn:
        row = conn.execute("SELECT job_id FROM claims WHERE event_key=?", (event_key,)).fetchone()
    return row[0] if row else None


def claim_event(job_id: str, event_key: str, *, retry: bool) -> tuple[bool, str | None]:
    with _db() as conn:
        row = conn.execute("SELECT job_id FROM claims WHERE event_key=?", (event_key,)).fetchone()
    if row:
        get(row[0])  # reconcile a dead worker before the atomic claim
    with _db() as conn:
        row = conn.execute("SELECT c.job_id, j.status, j.updated FROM claims c JOIN jobs j ON j.id=c.job_id "
                           "WHERE c.event_key=?", (event_key,)).fetchone()
        submitted = conn.execute("SELECT created FROM jobs WHERE id=?", (job_id,)).fetchone()
        if submitted is None:
            raise ValueError("Job not found")
        if row and (not retry or row[1] in ACTIVE or submitted[0] < row[2]):
            return False, row[0]
        conn.execute("INSERT INTO claims VALUES (?, ?) ON CONFLICT(event_key) "
                     "DO UPDATE SET job_id=excluded.job_id", (event_key, job_id))
        return True, None


def request_cancel(job_id: str) -> dict:
    current = get(job_id)
    if current["status"] in ACTIVE:
        with _db() as conn:
            conn.execute("UPDATE jobs SET status='cancelling', updated=? WHERE id=? "
                         "AND status IN ('queued','running')", (time.time(), job_id))
    return current
