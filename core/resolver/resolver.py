"""
CalFlow Resolver (v2.0).

Responsible for:
- interpreting parsed tags into execution-ready values (Smart Mode)
- mapping a Plus Mode AST node into a runtime parameter dict (Plus Mode)
- expanding @target aliases (single → app; multi → list)
- normalizing layout tags (#left(30) → #left(30%))

Design:
- pure functions
- no side effects
- no IO
- Smart Mode functions are unchanged — backward compatibility is preserved
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

from config.settings import (
    AUTOFILL_MODE,
    DEFAULT_DELAY,
    FORCE_FILL_TAG,
    FORCE_SUBMIT_TAG,
    MAX_DELAY,
    NO_AUTOFILL_TAG,
    SLOW_DELAY,
    TARGETS,
)
from core.models import (
    BaseCommand,
    ClickCommand,
    CloseCommand,
    CopyCommand,
    FocusCommand,
    HideCommand,
    OpenCommand,
    PasteCommand,
    PressCommand,
    RunCommand,
    SaveCommand,
    ScreenshotCommand,
    TypeCommand,
    WaitCommand,
)
from runtime.actions.browser import parse_layout_tag


# =========================================================
# 🎯 TARGET (Smart Mode helpers — unchanged surface)
# =========================================================

def resolve_target(tags: Set[str]) -> Optional[str]:
    """Return the FIRST resolved app name from any @target tag in `tags`."""
    for tag in tags:
        if tag.startswith("@") and tag in TARGETS:
            value = TARGETS[tag]
            return value[0] if isinstance(value, list) else value
    return None


def resolve_target_expansion(token: Optional[str]) -> List[str]:
    """
    Expand a single `@alias` (or quoted "App Name") into a list of apps.

    - "@chrome"        → ["Google Chrome"]
    - "@work"          → ["Google Chrome", "Notion", "Figma"]
    - '"Google Chrome"' / 'Google Chrome' → ["Google Chrome"]
    - unknown alias    → []
    """
    if not token:
        return []
    if token.startswith("@"):
        value = TARGETS.get(token.lower())
        if value is None:
            return []
        return list(value) if isinstance(value, list) else [value]
    # Strip surrounding quotes if any
    bare = token.strip()
    if (bare.startswith('"') and bare.endswith('"')) or (
        bare.startswith("'") and bare.endswith("'")
    ):
        bare = bare[1:-1]
    return [bare] if bare else []


# =========================================================
# 🪟 LAYOUT
# =========================================================

def resolve_layout(tags: Set[str]) -> Optional[Dict]:
    """Pick the LAST layout-producing tag (spec: same category → last wins)."""
    last: Optional[Dict] = None
    for tag in tags:
        layout = parse_layout_tag(tag)
        if layout:
            last = layout
    return last


# =========================================================
# ⏱️ TIMING
# =========================================================

def resolve_delay(tags: Set[str]) -> int:
    delay = SLOW_DELAY if "#slow" in tags else DEFAULT_DELAY
    return max(1, min(delay, MAX_DELAY))


# =========================================================
# 🔑 AUTOFILL
# =========================================================

def resolve_autofill(tags: Set[str]) -> Tuple[bool, bool]:
    if NO_AUTOFILL_TAG in tags:
        return False, False
    if FORCE_SUBMIT_TAG in tags:
        return True, True
    if FORCE_FILL_TAG in tags:
        return True, False
    if AUTOFILL_MODE == "auto":
        return True, True
    if AUTOFILL_MODE == "semi-auto":
        return True, False
    return False, False


# =========================================================
# ➕ PLUS MODE COMMAND RESOLUTION
# =========================================================

def resolve_command(
    command: BaseCommand,
    global_tags: Optional[Union[Set[str], FrozenSet[str]]] = None,
) -> Dict[str, Any]:
    """
    Translate a typed Plus Mode command + ambient tags into a flat
    runtime parameter dict consumed by `runtime.command_executor`.

    Per spec, Plus Mode has NO global state — `global_tags` is only used
    if the dispatcher chooses to forward calendar-event-level tags.
    """
    block_tags: FrozenSet[str] = frozenset(global_tags or frozenset())
    cmd_tags: FrozenSet[str] = frozenset(command.tags)
    merged: FrozenSet[str] = block_tags | cmd_tags

    base: Dict[str, Any] = {
        "verb": command.name,
        "tags": merged,
        "line_no": command.line_no,
        "raw": command.raw,
        "delay": resolve_delay(set(merged)),
        "layout": resolve_layout(set(merged)),
        "functions": dict(command.functions),
    }

    if isinstance(command, OpenCommand):
        if len(command.targets) > 1:
            base["invalid"] = "multiple @targets"
            return base
        apps = resolve_target_expansion(command.app)
        if not apps:
            apps = [resolve_target(set(merged))] if resolve_target(set(merged)) else []
        base.update({
            "url": command.url,
            "app": apps[0] if apps else None,
            "apps": apps,
        })
        return base

    if isinstance(command, FocusCommand):
        if len(command.targets) > 1:
            base["invalid"] = "multiple @targets"
            return base
        apps = resolve_target_expansion(command.target)
        base.update({
            "target": command.target,
            "title": command.title,
            "apps": apps,
        })
        return base

    if isinstance(command, CloseCommand):
        items = command.items or (
            tuple(resolve_target_expansion(command.target))
            if command.target else ()
        )
        base["items"] = items
        return base

    if isinstance(command, HideCommand):
        if command.hide_all:
            except_apps: List[str] = []
            for tok in command.except_items:
                if tok.startswith("@"):
                    except_apps.extend(resolve_target_expansion(tok))
                else:
                    except_apps.append(tok)
            base.update({
                "hide_all": True,
                "except": tuple(except_apps),
            })
            return base
        items = command.items or (
            tuple(resolve_target_expansion(command.target))
            if command.target else ()
        )
        base["items"] = items
        return base

    if isinstance(command, ClickCommand):
        base.update({
            "selector": command.selector,
            "text": command.text,
            "x": command.x,
            "y": command.y,
        })
        # Conflict: text(...) AND position(...) → invalidate per spec
        if command.text and (command.x is not None or command.y is not None):
            base["invalid"] = "conflicting selectors (text + position)"
        return base

    if isinstance(command, TypeCommand):
        fns = dict(command.functions)
        base.update({
            "text": command.text,
            "speed": fns.get("speed", 0.0),
            "interval": fns.get("interval", 0.0),
            "repeat": fns.get("repeat", 1),
            "timeout": fns.get("timeout"),
        })
        return base

    if isinstance(command, PressCommand):
        base["keys"] = command.keys
        return base

    if isinstance(command, WaitCommand):
        base["seconds"] = command.seconds
        return base

    if isinstance(command, ScreenshotCommand):
        base.update({
            "path": command.path,
            "display": command.display,
            "window": command.window,
            "area": command.area,
        })
        return base

    if isinstance(command, (CopyCommand, PasteCommand)):
        return base

    if isinstance(command, SaveCommand):
        base.update({
            "source": command.source,
            "to": command.to,
        })
        return base

    if isinstance(command, RunCommand):
        base["path"] = command.path
        return base

    return base
