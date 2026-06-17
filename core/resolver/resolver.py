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

import re
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
from core.utils import log
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


def _expand_targets(items) -> Tuple[str, ...]:
    """
    Expand any iterable of tokens (raw user-typed names + @aliases)
    into a flat tuple of macOS app names.

    For each token:
        - "@bundle" or "@target" → resolve via TARGETS (bundle gives a
          list, single target gives a 1-element list)
        - quoted/plain "App Name" → kept as-is (after stripping quotes)

    Bundles inside bundles are NOT expanded recursively (TARGETS values
    are flat per the v1.0 contract).
    """
    out: List[str] = []
    for tok in items:
        if not tok:
            continue
        if isinstance(tok, str) and tok.startswith("@"):
            out.extend(resolve_target_expansion(tok))
        else:
            cleaned = tok.strip()
            if (cleaned.startswith('"') and cleaned.endswith('"')) or (
                cleaned.startswith("'") and cleaned.endswith("'")
            ):
                cleaned = cleaned[1:-1]
            if cleaned:
                out.append(cleaned)
    return tuple(out)


def resolve_target_expansion(token: Optional[str]) -> List[str]:
    """
    Expand a single `@alias` (or quoted "App Name") into a list of apps.

    - "@chrome"        → ["Google Chrome"]                   (TARGETS hit)
    - "@work"          → ["Google Chrome", "Notion", "Figma"] (bundle)
    - "@cmux"          → ["cmux"]   + [WARN]                 (unknown — fall
                                                              back to literal)
    - '"Google Chrome"' / 'Google Chrome' → ["Google Chrome"]

    v1.1.14 — unknown @aliases used to return `[]`. That made calls
    like `hide @cmux` (where `@cmux` isn't in TARGETS) collapse to
    empty items, and downstream the executor would silently fall
    through to a *hide-all* path. Returning `[token-without-@]` plus
    a warning is far safer: the literal app name is what the user
    almost certainly meant, and worst case the OS-level `hide_app`
    no-ops (no other apps get touched).
    """
    if not token:
        return []
    if token.startswith("@"):
        value = TARGETS.get(token.lower())
        if value is None:
            literal = token.lstrip("@")
            log(
                f"[WARN] Unknown @alias {token!r}; treating as a literal "
                f"app name ({literal!r}). Add it in Settings → Aliases "
                f"to silence this warning."
            )
            return [literal] if literal else []
        return list(value) if isinstance(value, list) else [value]
    # Strip surrounding quotes if any
    bare = token.strip()
    if (bare.startswith('"') and bare.endswith('"')) or (
        bare.startswith("'") and bare.endswith("'")
    ):
        bare = bare[1:-1]
    return [bare] if bare else []


# =========================================================
# 🖥 DISPLAY (#display tag)
# =========================================================
# Returns:
#   None                   → no #display tag → caller uses primary
#   ("external", None)     → #display | #display() | #display(<unquoted>)
#   ("index",   N)         → #display(N) (1-based; no fallback)
#   ("name",    "Samsung") → #display("…") (substring; no fallback)

_DISPLAY_QUOTED = re.compile(r'^#display\("(.+)"\)$', re.IGNORECASE)
_DISPLAY_NUMBER = re.compile(r'^#display\((\d+)\)$',  re.IGNORECASE)
_DISPLAY_PARENS = re.compile(r'^#display\(([^)]*)\)$', re.IGNORECASE)
_DISPLAY_BARE   = re.compile(r'^#display$',            re.IGNORECASE)

# #profile(N): 1-based, where N=1 maps to Chrome's "Default" directory
# and N≥2 maps to "Profile {N-1}".
_PROFILE_RE = re.compile(r'^#profile\((\d+)\)$', re.IGNORECASE)


def resolve_chrome_profile(tags: Set[str]) -> Optional[str]:
    """
    Translate a `#profile(N)` tag into the Chrome `--profile-directory`
    value:
        N=1   → "Default"
        N=2   → "Profile 1"
        N=k   → "Profile {k-1}"

    Returns None when no #profile tag is present (or N is invalid).
    """
    for tag in tags:
        m = _PROFILE_RE.match(tag)
        if m:
            n = int(m.group(1))
            if n < 1:
                return None
            return "Default" if n == 1 else f"Profile {n - 1}"
    return None


def resolve_display(tags: Set[str]) -> Optional[Tuple[str, Any]]:
    """
    Pick the first #display tag from `tags` and return its spec.

    Order matters when matching a single tag string:
        quoted("…")  →  numeric(N)  →  any-other-parens(text|empty)  →  bare
    """
    for tag in tags:
        m = _DISPLAY_QUOTED.match(tag)
        if m:
            return ("name", m.group(1))
        m = _DISPLAY_NUMBER.match(tag)
        if m:
            return ("index", int(m.group(1)))
        if _DISPLAY_PARENS.match(tag):
            # Anything in parens that wasn't quoted or numeric → external.
            # `#display(ext)`, `#display(external)`, `#display()`, etc.
            return ("external", None)
        if _DISPLAY_BARE.match(tag):
            return ("external", None)
    return None


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

    Per spec, Plus Mode has NO global state — every command's tags
    must come exclusively from the command itself. We accept the
    `global_tags` parameter for API compatibility but DO NOT merge it
    into the command's tag set. Doing so would pull every #tag in the
    block into every command and cross-contaminate per-command layouts
    (e.g. one OPEN's `#left(70%)` leaking into another OPEN's
    `#right(30%)`).
    """
    cmd_tags: FrozenSet[str] = frozenset(command.tags)
    merged: FrozenSet[str] = cmd_tags

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
        # v1.1.2 — runtime-target keyword `active` short-circuits.
        if command.target_keyword == "active":
            base.update({
                "target_keyword": "active",
                "target": None,
                "title": command.title,
                "apps": (),
                "display_target": None,
            })
            return base
        apps = resolve_target_expansion(command.target)
        base.update({
            "target": command.target,
            "title": command.title,
            "apps": apps,
            "display_target": command.display_target,
        })
        return base

    if isinstance(command, CloseCommand):
        # v1.1.2 shapes (mutually exclusive at parse time):
        #   target_keyword=="active"|"all" → runtime target
        #   items populated                → close just those
        #   keep_set populated             → close everything except those
        if command.target_keyword:
            base["target_keyword"] = command.target_keyword
            base["items"] = ()
            base["keep"] = ()
            base["had_items"] = False
            return base
        # v1.1.14 — `had_items` records whether the user originally
        # asked for explicit items (vs `except(...)`). Resolution can
        # legitimately produce `items=()` if every alias was unknown
        # AND the unknown-alias fallback fails to find a literal name;
        # the executor uses `had_items` to refuse silent fall-through
        # to close_all (which would close everything visible).
        base["had_items"] = bool(command.items)
        if command.items:
            base["items"] = _expand_targets(command.items)
        else:
            base["items"] = ()
        if command.keep_set:
            base["keep"] = _expand_targets(command.keep_set)
        else:
            base["keep"] = ()
        return base

    if isinstance(command, HideCommand):
        # v1.1.2 shapes:
        #   target_keyword=="active"|"all" → runtime target
        #   items populated                → hide just those
        #   keep_set / display_filter      → filter form (hide-all-except + scope)
        if command.target_keyword:
            base["target_keyword"] = command.target_keyword
            base["items"] = ()
            base["keep"] = ()
            base["display_filter"] = None
            base["had_items"] = False
            return base
        base["had_items"] = bool(command.items)  # see CloseCommand note
        if command.items:
            base["items"] = _expand_targets(command.items)
            base["keep"] = ()
        else:
            base["items"] = ()
            base["keep"] = _expand_targets(command.keep_set)
        base["display_filter"] = command.display_filter
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
            "target_keyword": command.target_keyword,  # v1.1.2 — `active`
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
        base["backend"] = command.backend
        base["trigger_name"] = command.trigger_name
        base["script"] = command.script
        base["timeout"] = command.timeout
        base["shortcut_name"] = command.shortcut_name
        base["shortcut_input"] = command.shortcut_input
        base["alfred_bundle_id"] = command.alfred_bundle_id
        base["alfred_trigger"] = command.alfred_trigger
        base["alfred_argument"] = command.alfred_argument
        base["run_handlers"] = command.run_handlers
        return base

    return base
