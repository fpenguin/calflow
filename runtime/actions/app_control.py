"""
CalFlow App Control (v2.0.9).

Real macOS implementations for FOCUS / CLOSE / HIDE via osascript.

Pure-AppleScript backend — no `pyobjc`. The same Accessibility
permission used for autofill keystrokes is required for `hide` and
`focus … title("…")`. `close` and bare `focus @app` use Apple Events
only (a separate TCC bucket — Automation, granted per-app).

Public surface:
    focus_app(app_name)
    focus_window_by_title(app_name, title_substring)
    close_app(app_name)
    hide_app(app_name)
    hide_all(except_apps=[])
"""

from __future__ import annotations

import subprocess
from typing import Iterable, Optional

from core.utils import log


# =========================================================
# 🔧 OSASCRIPT HELPER
# =========================================================

def _osascript(script: str, *, action_label: str) -> bool:
    """
    Run an AppleScript string. Returns True on exit 0.

    Best-effort — failures log a `[WARN]` and return False.
    Accessibility-permission errors get a clearer hint.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        log(f"[WARN] {action_label}: osascript not available")
        return False
    except Exception as exc:
        log(f"[ERROR] {action_label} subprocess failed: {exc}")
        return False

    if result.returncode == 0:
        return True

    stderr = (result.stderr or "").strip()
    log(f"[WARN] {action_label} failed: {stderr or '(no stderr)'}")
    if "not allowed" in stderr.lower() or "1002" in stderr or "errAEAccessor" in stderr:
        log(
            "[WARN] Grant Accessibility permission: "
            "System Settings → Privacy & Security → Accessibility"
        )
    return False


def _escape(name: str) -> str:
    """Escape an app name for safe insertion into an AppleScript string."""
    return (name or "").replace("\\", "\\\\").replace('"', '\\"')


def _osascript_capture(script: str, *, action_label: str) -> Optional[str]:
    """
    Like `_osascript`, but captures stdout. Returns the stdout string
    on success, or None on failure (with same error logging as
    `_osascript`).
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        log(f"[WARN] {action_label}: osascript not available")
        return None
    except Exception as exc:
        log(f"[ERROR] {action_label} subprocess failed: {exc}")
        return None

    if result.returncode == 0:
        return result.stdout

    stderr = (result.stderr or "").strip()
    log(f"[WARN] {action_label} failed: {stderr or '(no stderr)'}")
    if "not allowed" in stderr.lower() or "1002" in stderr or "errAEAccessor" in stderr:
        log(
            "[WARN] Grant Accessibility permission: "
            "System Settings → Privacy & Security → Accessibility"
        )
    return None


# =========================================================
# 👀 FRONTMOST (v1.1.2)
# =========================================================

def get_frontmost_app_name() -> Optional[str]:
    """
    Return the name of the frontmost (`active`) macOS application, or
    None if it can't be determined. Used by the `active` runtime target
    in `hide active`, `close active`, `screenshot active`, etc.
    """
    script = (
        'tell application "System Events"\n'
        '    return name of first application process whose frontmost is true\n'
        'end tell\n'
    )
    out = _osascript_capture(script, action_label="frontmost lookup")
    if out is None:
        return None
    name = out.strip()
    return name or None


# =========================================================
# 🎯 FOCUS
# =========================================================

def focus_app(app_name: str) -> bool:
    """Bring `app_name` to the front (no window targeting)."""
    if not app_name:
        log("[WARN] FOCUS: missing app name")
        return False
    safe = _escape(app_name)
    script = f'tell application "{safe}" to activate'
    ok = _osascript(script, action_label=f"FOCUS {app_name!r}")
    if ok:
        log(f"[INFO] FOCUS {app_name!r}")
    return ok


def focus_window_by_title(app_name: str, title_substring: str) -> bool:
    """
    Activate `app_name` AND raise the first window whose title contains
    `title_substring` (case-sensitive — AppleScript's `contains` is
    locale-aware but case-sensitive on most systems).
    """
    if not app_name:
        log("[WARN] FOCUS: missing app name")
        return False
    if not title_substring:
        # No title constraint → just activate the app
        return focus_app(app_name)

    safe_app = _escape(app_name)
    safe_title = _escape(title_substring)
    # Two-step: activate + raise the matching window via System Events
    # (works across browsers, mail clients, IDEs that expose AXRaise).
    script = f'''
tell application "{safe_app}" to activate
delay 0.2
tell application "System Events"
    tell process "{safe_app}"
        set candidates to (every window whose title contains "{safe_title}")
        if (count of candidates) > 0 then
            perform action "AXRaise" of (item 1 of candidates)
        end if
    end tell
end tell
'''
    ok = _osascript(
        script, action_label=f"FOCUS {app_name!r} title {title_substring!r}"
    )
    if ok:
        log(f"[INFO] FOCUS {app_name!r} title contains {title_substring!r}")
    return ok


# =========================================================
# ❎ CLOSE
# =========================================================

def close_app(app_name: str) -> bool:
    """Quit `app_name`. Best-effort; non-running app is a no-op."""
    if not app_name:
        log("[WARN] CLOSE: missing app name")
        return False
    safe = _escape(app_name)
    # `if it is running` avoids spawning the app just to quit it
    script = f'''
tell application "System Events"
    if exists (process "{safe}") then
        tell application "{safe}" to quit
    end if
end tell
'''
    ok = _osascript(script, action_label=f"CLOSE {app_name!r}")
    if ok:
        log(f"[INFO] CLOSE {app_name!r}")
    return ok


# =========================================================
# 👁 HIDE
# =========================================================

def hide_app(app_name: str) -> bool:
    """Hide `app_name`'s windows (without quitting it)."""
    if not app_name:
        log("[WARN] HIDE: missing app name")
        return False
    safe = _escape(app_name)
    script = f'''
tell application "System Events"
    if exists (process "{safe}") then
        set visible of process "{safe}" to false
    end if
end tell
'''
    ok = _osascript(script, action_label=f"HIDE {app_name!r}")
    if ok:
        log(f"[INFO] HIDE {app_name!r}")
    return ok


def close_all(except_apps: Iterable[str] = ()) -> bool:
    """
    Quit every visible non-background process EXCEPT the apps named
    in `except_apps`. Frontmost is also kept (avoids closing the user's
    active app).

    Returns True iff osascript exited 0. The script returns a TSV
    summary on stdout — `kept | closed | errored` — which we log so
    you can see exactly what the call did.
    """
    keep_names = [a.strip() for a in except_apps if a and a.strip()]
    keep_literal = "{" + ", ".join(
        '"' + _escape(name) + '"' for name in keep_names
    ) + "}"

    script = (
        'on run\n'
        '    set kept to {}\n'
        '    set closed to {}\n'
        '    set errored to {}\n'
        '    tell application "System Events"\n'
        '        set frontApp to (name of first application process whose frontmost is true)\n'
        f'        set keepList to {keep_literal}\n'
        '        set procs to (every process whose visible is true and background only is false)\n'
        '        repeat with p in procs\n'
        '            set procName to ""\n'
        '            try\n'
        '                set procName to (name of p as string)\n'
        '            end try\n'
        '            if procName is "" then\n'
        '                -- skip\n'
        '            else if procName is frontApp then\n'
        '                set end of kept to procName\n'
        '            else if keepList contains procName then\n'
        '                set end of kept to procName\n'
        '            else\n'
        '                try\n'
        '                    tell application procName to quit\n'
        '                    set end of closed to procName\n'
        '                on error errMsg\n'
        '                    set end of errored to (procName & " (" & errMsg & ")")\n'
        '                end try\n'
        '            end if\n'
        '        end repeat\n'
        '    end tell\n'
        '    set AppleScript\'s text item delimiters to ", "\n'
        '    set out to "KEPT\t" & (kept as text) & linefeed\n'
        '    set out to out & "CLOSED\t" & (closed as text) & linefeed\n'
        '    set out to out & "ERRORED\t" & (errored as text)\n'
        '    return out\n'
        'end run\n'
    )
    label = "CLOSE all" + (
        " except " + ", ".join(keep_names) if keep_names else ""
    )
    summary = _osascript_capture(script, action_label=label)
    if summary is None:
        return False
    for line in summary.strip().splitlines():
        if "\t" in line:
            tag, _, names = line.partition("\t")
            log(f"[INFO] {label}: {tag.lower()} = [{names.strip() or '∅'}]")
    return True


def hide_all(except_apps: Iterable[str] = ()) -> bool:
    """
    Hide every visible non-background process EXCEPT the apps named
    in `except_apps`. Comparison is case-sensitive (matches macOS's
    own process name table).

    The current frontmost app is also kept visible — hiding it would
    leave macOS focus on whatever Finder picks next, surprising the
    user. (`cmd+option+H` works the same way.)

    Returns True iff osascript exited 0. The script returns a TSV
    summary on stdout — `kept | hidden | errored` — which we log so
    you can see exactly what the call did.
    """
    keep_names = [a.strip() for a in except_apps if a and a.strip()]

    # Build the AppleScript list literal: {"Google Chrome", "Notion", "Figma"}
    keep_literal = "{" + ", ".join(
        '"' + _escape(name) + '"' for name in keep_names
    ) + "}"
    keep_clause = (
        f"                set keepList to {keep_literal}\n"
        if keep_names else
        '                set keepList to {}\n'
    )

    # The script returns three TAB-separated lines on stdout:
    #     KEPT\t<comma-sep-list>
    #     HIDDEN\t<comma-sep-list>
    #     ERRORED\t<comma-sep-list>
    # so we can log a precise summary instead of guessing.
    #
    # NOTE: We CANNOT name the 'hidden apps' list `hidden` — that's a
    # reserved property of System Events processes, and AppleScript
    # interprets `set hidden to {}` as an attempt to set the System
    # Events `hidden` attribute (error -10003: 'Access not allowed').
    # Use `hid` for the local list variable.
    script = (
        'on run\n'
        '    set kept to {}\n'
        '    set hid to {}\n'
        '    set errored to {}\n'
        '    tell application "System Events"\n'
        '        set frontApp to (name of first application process whose frontmost is true)\n'
        + keep_clause +
        '        set procs to (every process whose visible is true and background only is false)\n'
        '        repeat with p in procs\n'
        '            set procName to ""\n'
        '            try\n'
        '                set procName to (name of p as string)\n'
        '            end try\n'
        '            if procName is "" then\n'
        '                -- skip\n'
        '            else if procName is frontApp then\n'
        '                set end of kept to procName\n'
        '            else if keepList contains procName then\n'
        '                set end of kept to procName\n'
        '            else\n'
        '                try\n'
        '                    set visible of p to false\n'
        '                    set end of hid to procName\n'
        '                on error errMsg\n'
        '                    set end of errored to (procName & " (" & errMsg & ")")\n'
        '                end try\n'
        '            end if\n'
        '        end repeat\n'
        '    end tell\n'
        '    set AppleScript\'s text item delimiters to ", "\n'
        '    set out to "KEPT\t" & (kept as text) & linefeed\n'
        '    set out to out & "HIDDEN\t" & (hid as text) & linefeed\n'
        '    set out to out & "ERRORED\t" & (errored as text)\n'
        '    return out\n'
        'end run\n'
    )

    label = "HIDE all" + (
        " except " + ", ".join(keep_names) if keep_names else ""
    )
    summary = _osascript_capture(script, action_label=label)
    if summary is None:
        return False

    # Parse the TSV summary and log it
    for line in summary.strip().splitlines():
        if "\t" in line:
            tag, _, names = line.partition("\t")
            log(f"[INFO] {label}: {tag.lower()} = [{names.strip() or '∅'}]")
    return True
