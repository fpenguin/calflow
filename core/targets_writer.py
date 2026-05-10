"""
CalFlow TARGETS dict reader / writer (v1.3.9).

Lets the menubar Settings → Aliases editor add / edit / remove entries
in the `TARGETS` dict in `config/settings.py` without making the user
hand-edit Python.

`TARGETS` schema:
    Mapping[str, str | List[str]]
        @alias        →  "App name"        # single-app
        @workflow     →  ["App1", "App2"]  # multi-app sequence

Public API:
    read_targets()              → dict
    apply_targets(payload)      → dict   (validate + atomic write + backup)

Validation rules (enforced both pre-write and at module load via
core.reserved.enforce_or_exit, so a bad write would crash CalFlow at
next start — we refuse the write instead):

- Alias key must start with `@`.
- Alias name must match `^@[a-zA-Z0-9_-]+$`.
- Alias name (case-insensitive, with @ stripped) must NOT be in
  RESERVED_KEYWORDS (`active / all / display / except`).
- Each alias value must be a non-empty string OR a non-empty list of strings.
- App-name strings must not contain quotes / newlines (settings.py safety).

Why parse + rewrite instead of regex-poke:
- TARGETS is a multi-line dict literal with mixed string and list values.
- A regex couldn't reliably handle quotes, commas inside lists, or future
  additions like dict-of-dict structures.
- We use `ast.literal_eval` for read (safe — no code execution) and a
  manual re-render for write that produces clean, sorted output.

Comment preservation: section-divider comments inside the existing
TARGETS dict are dropped on first write — the UI replaces that
organizational layer. The grouping is reproduced in the rendered output
(single-app aliases first, then workflow aliases, both sorted).
"""

from __future__ import annotations

# v1.3.9 — public surface lock.
__all__ = [
    "ALIAS_NAME_PATTERN",
    "apply_targets",
    "read_targets",
    "render_targets",
    "validate_alias_name",
    "validate_app_list",
]

import ast
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.reserved import is_reserved
from core.utils import log
from config.config import BASE_DIR


SETTINGS_PATH = Path(BASE_DIR) / "config" / "settings.py"
BACKUP_PATH   = Path(BASE_DIR) / "config" / "settings.py.bak"


ALIAS_NAME_PATTERN = re.compile(r"^@[a-zA-Z0-9_-]+$")


# =========================================================
# 📖 READ
# =========================================================

def read_targets() -> Dict[str, Union[str, List[str]]]:
    """
    Parse the TARGETS dict literal out of settings.py and return as a
    Python dict. Returns {} on any failure (logged).

    Uses ast.literal_eval, which only evaluates literals — no code
    execution risk even if settings.py contains arbitrary expressions.
    """
    try:
        text = SETTINGS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "TARGETS":
                    return _coerce_targets(ast.literal_eval(node.value))
    except Exception as exc:
        log(f"[WARN] read_targets failed: {exc}")
    return {}


def _coerce_targets(raw: Any) -> Dict[str, Union[str, List[str]]]:
    """Defensive normalisation — drop anything that isn't shaped right."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Union[str, List[str]]] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, str):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            apps = [str(a) for a in v if isinstance(a, (str, int, float))]
            if apps:
                out[k] = apps
    return out


# =========================================================
# ✅ VALIDATION
# =========================================================

def validate_alias_name(alias: str) -> Optional[str]:
    """Return None if `alias` is OK, else a human-readable reason."""
    if not isinstance(alias, str) or not alias:
        return "alias name is empty"
    if not alias.startswith("@"):
        return "must start with @"
    if not ALIAS_NAME_PATTERN.match(alias):
        return "only letters, numbers, _ and - are allowed after @"
    if is_reserved(alias):
        return f"{alias} is a reserved keyword (active / all / display / except)"
    return None


def validate_app_list(apps: Any) -> Optional[str]:
    """Return None if `apps` is a non-empty list of clean strings."""
    if isinstance(apps, str):
        apps = [apps]
    if not isinstance(apps, (list, tuple)) or len(apps) == 0:
        return "at least one app required"
    for a in apps:
        if not isinstance(a, str) or not a.strip():
            return "app names must be non-empty strings"
        if any(ch in a for ch in ('"', "'", "\n", "\r")):
            return "app names must not contain quotes or newlines"
    return None


# =========================================================
# ✏️ WRITE
# =========================================================

def apply_targets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replace the TARGETS dict in settings.py with the user's edited copy.

    `payload`:
        {"targets": {alias: "App" | ["App1", ...], ...}}

    Returns:
        {
            "ok":       bool,
            "count":    int          (number of aliases written, on success)
            "errors":   list[dict]   (per-alias errors, if any)
            "backup_path": str       (on success)
        }

    Failure modes:
        - Any single alias fails validation → no write happens, all errors
          returned. The dict is treated atomically: either the whole new
          state is valid and written, or nothing changes.
        - settings.py read or write fails → returned with `ok: False`.
    """
    raw = payload.get("targets") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {"ok": False, "errors": [{"alias": "", "reason": "payload.targets must be a dict"}]}

    # 1. Validate every entry. Collect ALL errors (don't stop at first).
    errors: List[Dict[str, str]] = []
    cleaned: Dict[str, Union[str, List[str]]] = {}
    for alias, val in raw.items():
        err = validate_alias_name(alias)
        if err:
            errors.append({"alias": str(alias), "reason": err})
            continue
        # Normalise single-string vs list, then validate.
        if isinstance(val, str):
            err2 = validate_app_list([val])
            if err2:
                errors.append({"alias": alias, "reason": err2})
                continue
            cleaned[alias] = val.strip()
        elif isinstance(val, (list, tuple)):
            err2 = validate_app_list(val)
            if err2:
                errors.append({"alias": alias, "reason": err2})
                continue
            apps = [str(a).strip() for a in val if str(a).strip()]
            cleaned[alias] = apps[0] if len(apps) == 1 else apps
        else:
            errors.append({"alias": alias, "reason": "value must be a string or a list of strings"})

    if errors:
        return {"ok": False, "errors": errors}

    # 2. Read settings.py, locate TARGETS, replace.
    try:
        text = SETTINGS_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "errors": [{"alias": "", "reason": f"could not read settings.py: {exc}"}]}

    try:
        new_text = _replace_targets_dict(text, cleaned)
    except Exception as exc:
        return {"ok": False, "errors": [{"alias": "", "reason": f"could not rewrite TARGETS: {exc}"}]}

    # 3. Backup + atomic write.
    backup_path: Optional[str] = None
    try:
        shutil.copyfile(str(SETTINGS_PATH), str(BACKUP_PATH))
        backup_path = str(BACKUP_PATH)
    except Exception as exc:
        log(f"[WARN] settings.py backup failed: {exc}")

    try:
        tmp = str(SETTINGS_PATH) + ".tmp"
        Path(tmp).write_text(new_text, encoding="utf-8")
        Path(tmp).replace(SETTINGS_PATH)
    except Exception as exc:
        return {"ok": False, "errors": [{"alias": "", "reason": f"write failed: {exc}"}]}

    return {"ok": True, "count": len(cleaned), "backup_path": backup_path}


# =========================================================
# 🔧 INTERNAL
# =========================================================

def _replace_targets_dict(text: str, new_targets: Dict[str, Union[str, List[str]]]) -> str:
    """
    Find the `TARGETS = { ... }` literal in `text` and replace its body
    with a re-rendered version. Brace-balanced search handles quotes
    and nested literals correctly.
    """
    m = re.search(r"^TARGETS\s*=\s*", text, re.MULTILINE)
    if not m:
        raise ValueError("TARGETS assignment not found in settings.py")

    open_brace = text.index("{", m.end())
    close_brace = _find_matching_brace(text, open_brace)
    if close_brace < 0:
        raise ValueError("TARGETS dict literal is unterminated")

    body = render_targets(new_targets)
    return text[:open_brace] + body + text[close_brace + 1:]


def _find_matching_brace(text: str, open_idx: int) -> int:
    """Return the index of the `}` matching `text[open_idx]`, ignoring
    braces inside string literals. Returns -1 on no match."""
    if text[open_idx] != "{":
        return -1
    depth = 0
    in_string = False
    string_char = ""
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == string_char:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def render_targets(targets: Dict[str, Union[str, List[str]]]) -> str:
    """
    Render the dict as nicely-formatted Python for settings.py.

    Single-app aliases first (sorted), then workflow aliases (sorted),
    with section-divider comments to keep the file readable when opened
    by hand.
    """
    if not targets:
        return "{}"

    single = {k: v for k, v in targets.items() if isinstance(v, str)}
    multi  = {k: v for k, v in targets.items() if isinstance(v, list)}

    lines: List[str] = ["{"]

    if single:
        lines.append("    # --- Single-app aliases ---")
        for k in sorted(single):
            lines.append(f'    "{_esc(k)}": "{_esc(single[k])}",')

    if multi:
        if single:
            lines.append("")
        lines.append("    # --- Workflow aliases (open multiple apps in order) ---")
        for k in sorted(multi):
            apps_repr = ", ".join(f'"{_esc(a)}"' for a in multi[k])
            lines.append(f'    "{_esc(k)}": [{apps_repr}],')

    lines.append("}")
    return "\n".join(lines)


def _esc(s: str) -> str:
    """Escape backslashes only — validation already rejects quotes/newlines."""
    return str(s).replace("\\", "\\\\")
