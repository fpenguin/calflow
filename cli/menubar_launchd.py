from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

from runtime.menubar import CALENDAR_PLUS_SVG

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MENUBAR_LABEL = "com.calflow.menubar"
MENUBAR_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{MENUBAR_LABEL}.plist"
MENUBAR_LOCK_PATH = Path("/tmp/calflow_menubar.lock")


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    command = ["launchctl", *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=str(exc))


def _read_lock() -> dict[str, Any] | None:
    try:
        pid_s, ts_s = MENUBAR_LOCK_PATH.read_text(encoding="utf-8").strip().split("|")
        pid = int(pid_s)
        command = _pid_command(pid)
        return {
            "pid": pid,
            "timestamp": int(ts_s),
            "alive": _is_menubar_pid(pid, command),
            "command": command,
        }
    except Exception:
        return None


def _pid_command(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        command = result.stdout.strip()
        return command or None
    except Exception:
        return None


def _is_menubar_pid(pid: int, command: str | None = None) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    command = command if command is not None else _pid_command(pid)
    return bool(command and "cli.main" in command and "menubar" in command)


def _loaded_line() -> str | None:
    result = _run_launchctl(["list"])
    for line in result.stdout.splitlines():
        if line.split() and line.split()[-1] == MENUBAR_LABEL:
            return line.strip()
    return None


def generate_menubar_plist() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return plistlib.dumps({
        "Label": MENUBAR_LABEL,
        "ProgramArguments": [sys.executable, "-m", "cli.main", "menubar"],
        "WorkingDirectory": str(BASE_DIR),
        "EnvironmentVariables": {"PYTHONPATH": str(BASE_DIR)},
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "RunAtLoad": True,
        # Recover crashes and login-time failures, but respect the Quit button.
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "StandardOutPath": str(DATA_DIR / "menubar.out.log"),
        "StandardErrorPath": str(DATA_DIR / "menubar.err.log"),
    }, sort_keys=False).decode("utf-8")


def _service_target() -> str:
    return f"gui/{os.getuid()}/{MENUBAR_LABEL}"


def _wait_until_ready() -> dict[str, Any]:
    status = menubar_status()
    for _ in range(50):
        if status["loaded"] and (status.get("lock") or {}).get("alive"):
            break
        time.sleep(0.2)
        status = menubar_status()
    return status


def _plist_is_current() -> bool:
    try:
        installed = plistlib.loads(MENUBAR_PLIST_PATH.read_bytes())
        expected = plistlib.loads(generate_menubar_plist().encode("utf-8"))
        return all(installed.get(key) == value for key, value in expected.items())
    except (OSError, ValueError, ExpatError, plistlib.InvalidFileException):
        return False


def menubar_status() -> dict[str, Any]:
    raw_line = _loaded_line()
    lock = _read_lock()
    return {
        "label": MENUBAR_LABEL,
        "loaded": raw_line is not None,
        "raw_line": raw_line,
        "plist_path": str(MENUBAR_PLIST_PATH),
        "plist_exists": MENUBAR_PLIST_PATH.exists(),
        "lock": lock,
        "icon": "dynamic-date",
        "fallback_icon": "calendar-plus",
        "fallback_icon_path": str(CALENDAR_PLUS_SVG),
        "stdout_log": str(DATA_DIR / "menubar.out.log"),
        "stderr_log": str(DATA_DIR / "menubar.err.log"),
    }


def _recovery_steps(reason: str) -> list[str]:
    return [
        f"Reason: {reason}",
        "Repair the menu bar LaunchAgent: .venv/bin/python -m cli.main menubar-install",
        f"Inspect logs: tail -n 80 {DATA_DIR / 'menubar.err.log'}",
        f"If launchctl is wedged, remove the loaded job: launchctl bootout {_service_target()}",
    ]


def _attach_failure_recovery(status: dict[str, Any], reason: str) -> dict[str, Any]:
    status["ok"] = False
    status["error"] = reason
    status["recovery"] = _recovery_steps(reason)
    return status


def _preserve_login_preference(status: dict[str, Any]) -> dict[str, Any]:
    from state.lifecycle import load
    if not load()["menubar_login"]:
        result = _run_launchctl(["disable", _service_target()])
        if result.returncode:
            return _attach_failure_recovery(status, "Could not restore menu bar login preference")
    return status


def install_menubar(load: bool = True) -> dict[str, Any]:
    MENUBAR_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MENUBAR_PLIST_PATH.write_text(generate_menubar_plist(), encoding="utf-8")

    unload = None
    load_result = None
    if load:
        enabled = _run_launchctl(["enable", _service_target()])
        if enabled.returncode:
            return _attach_failure_recovery(menubar_status(), enabled.stderr.strip())
        unload = _run_launchctl(["bootout", _service_target()])
        load_result = _run_launchctl(["bootstrap", f"gui/{os.getuid()}", str(MENUBAR_PLIST_PATH)])

    status = _wait_until_ready() if load_result is not None and load_result.returncode == 0 else menubar_status()
    ok = load_result is None or (
        load_result.returncode == 0 and bool((status.get("lock") or {}).get("alive"))
    )
    status.update({
        "action": "install",
        "ok": ok,
        "unload_exit_code": None if unload is None else unload.returncode,
        "load_exit_code": None if load_result is None else load_result.returncode,
        "load_stderr": None if load_result is None else load_result.stderr.strip(),
    })
    if not ok:
        reason = (load_result.stderr or "LaunchAgent loaded, but the menu bar process did not become ready").strip() if load_result else "install failed"
        _attach_failure_recovery(status, reason)
    return _preserve_login_preference(status) if load else status


def start_menubar() -> dict[str, Any]:
    if not _plist_is_current():
        status = install_menubar(load=True)
        status["action"] = "start"
        return status

    domain_label = _service_target()
    before = menubar_status()
    if before["loaded"]:
        result = _run_launchctl(["kickstart", domain_label])
    else:
        result = _run_launchctl(["enable", domain_label])
        if result.returncode == 0:
            result = _run_launchctl(["bootstrap", f"gui/{os.getuid()}", str(MENUBAR_PLIST_PATH)])
    status = _wait_until_ready() if result.returncode == 0 else menubar_status()
    lock = status.get("lock") or {}
    status.update({
        "action": "start",
        "ok": result.returncode == 0 and bool(lock.get("alive")),
        "exit_code": result.returncode,
        "stderr": result.stderr.strip(),
    })
    if not status["ok"]:
        if result.returncode != 0:
            reason = result.stderr.strip() or "launchctl start failed"
        elif not lock.get("alive"):
            reason = "LaunchAgent loaded, but the menu bar process did not become ready"
        else:
            reason = "menu bar start failed"
        _attach_failure_recovery(status, reason)
    return _preserve_login_preference(status)


def stop_menubar() -> dict[str, Any]:
    result = _run_launchctl(["bootout", _service_target()])
    status = menubar_status()
    status.update({
        "action": "stop",
        "ok": result.returncode == 0 or not status["loaded"],
        "exit_code": result.returncode,
        "stderr": result.stderr.strip(),
    })
    if not status["ok"]:
        _attach_failure_recovery(status, result.stderr.strip() or "launchctl bootout failed")
    return status


def restart_menubar() -> dict[str, Any]:
    stopped = stop_menubar()
    if not stopped["ok"]:
        stopped["action"] = "restart"
        return stopped
    status = start_menubar()
    status["action"] = "restart"
    return status


def uninstall_menubar() -> dict[str, Any]:
    stop_result = stop_menubar()
    removed = False
    if MENUBAR_PLIST_PATH.exists():
        MENUBAR_PLIST_PATH.unlink()
        removed = True
    status = menubar_status()
    status.update({
        "action": "uninstall",
        "ok": not status["loaded"] and not status["plist_exists"],
        "removed": removed,
        "stop": stop_result,
    })
    return status


def print_menubar_action_json(action: str) -> None:
    if action == "status":
        out = menubar_status()
    elif action == "install":
        out = install_menubar(load=True)
    elif action == "start":
        out = start_menubar()
    elif action == "stop":
        out = stop_menubar()
    elif action == "restart":
        out = restart_menubar()
    elif action == "uninstall":
        out = uninstall_menubar()
    else:
        out = {"action": action, "ok": False, "error": f"unknown menubar action {action!r}"}
    print(json.dumps(out, indent=2, default=str))
