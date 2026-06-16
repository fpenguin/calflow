from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.menubar import CALENDAR_PLUS_SVG

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MENUBAR_LABEL = "com.calflow.menubar"
MENUBAR_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{MENUBAR_LABEL}.plist"
MENUBAR_LOCK_PATH = Path("/tmp/calflow_menubar.lock")


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


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
        if MENUBAR_LABEL in line:
            return line.strip()
    return None


def generate_menubar_plist() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stdout_log = DATA_DIR / "menubar.out.log"
    stderr_log = DATA_DIR / "menubar.err.log"
    python_path = sys.executable

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MENUBAR_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>cli.main</string>
        <string>menubar</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{BASE_DIR}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
</dict>
</plist>
"""


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


def install_menubar(load: bool = True) -> dict[str, Any]:
    MENUBAR_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MENUBAR_PLIST_PATH.write_text(generate_menubar_plist(), encoding="utf-8")

    unload = _run_launchctl(["unload", str(MENUBAR_PLIST_PATH)])
    load_result = None
    if load:
        load_result = _run_launchctl(["load", "-w", str(MENUBAR_PLIST_PATH)])

    status = menubar_status()
    status.update({
        "action": "install",
        "ok": load_result is None or load_result.returncode == 0 or status["loaded"],
        "unload_exit_code": unload.returncode,
        "load_exit_code": None if load_result is None else load_result.returncode,
        "load_stderr": None if load_result is None else load_result.stderr.strip(),
    })
    return status


def start_menubar() -> dict[str, Any]:
    if not MENUBAR_PLIST_PATH.exists():
        return install_menubar(load=True)

    domain_label = f"gui/{os.getuid()}/{MENUBAR_LABEL}"
    before = menubar_status()
    if before["loaded"]:
        result = _run_launchctl(["kickstart", "-k", domain_label])
    else:
        result = _run_launchctl(["load", "-w", str(MENUBAR_PLIST_PATH)])
    status = menubar_status()
    for _ in range(10):
        lock = status.get("lock") or {}
        if lock.get("alive"):
            break
        time.sleep(0.2)
        status = menubar_status()
    lock = status.get("lock") or {}
    status.update({
        "action": "start",
        "ok": result.returncode == 0 and bool(lock.get("alive")),
        "exit_code": result.returncode,
        "stderr": result.stderr.strip(),
    })
    return status


def stop_menubar() -> dict[str, Any]:
    result = _run_launchctl(["unload", str(MENUBAR_PLIST_PATH)])
    status = menubar_status()
    status.update({
        "action": "stop",
        "ok": result.returncode == 0 or not status["loaded"],
        "exit_code": result.returncode,
        "stderr": result.stderr.strip(),
    })
    return status


def restart_menubar() -> dict[str, Any]:
    stop_menubar()
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
