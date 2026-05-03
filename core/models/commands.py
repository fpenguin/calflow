"""
Plus Mode AST — typed command nodes (v2.0).

Each command represents ONE explicit, atomic action that
runtime.command_executor will execute.

Design rules:
- Every command is a frozen dataclass (immutable, hashable).
- Every command carries source metadata (line_no, raw) so the
  executor and the validator can produce precise diagnostics.
- Tags are a frozenset; they are not interpreted here — the
  resolver layer maps tags into runtime parameters.
- Function-call arguments (text("…"), selector("…"), position(x,y),
  title("…"), window("…"), area(…), display(N), to("…"), source(…),
  repeat(N), interval(s), speed(s), timeout(s)) are normalized into
  a `functions` dict on the relevant commands.
- Commands NEVER perform IO and NEVER import runtime modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# =========================================================
# 🧱 BASE
# =========================================================

@dataclass(frozen=True)
class BaseCommand:
    """
    Common metadata shared by every Plus Mode command.

    Attributes:
        line_no:   1-based line number from the original Plus block.
        raw:       original line text (pre-tokenization).
        tags:      parsed `#tags` attached to the line (lowercased).
        functions: parsed function-call arguments, e.g.
                   {"text": "Sign in", "selector": ".btn", "repeat": 3, "speed": 0.1}
    """
    line_no: int
    raw: str
    tags: FrozenSet[str] = field(default_factory=frozenset)
    functions: Tuple[Tuple[str, Any], ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """Command keyword (uppercased class basename minus 'Command')."""
        return type(self).__name__.replace("Command", "").upper()

    @property
    def fn_dict(self) -> Dict[str, Any]:
        """Functions as an ordinary dict (last call wins)."""
        return dict(self.functions)


# =========================================================
# 🌐 APP CONTROL
# =========================================================

@dataclass(frozen=True)
class OpenCommand(BaseCommand):
    """OPEN <url|app|file> [@target] [#tags]"""
    url: str = ""               # may also hold an app name / file path
    app: Optional[str] = None   # @target (kept literal, e.g. "@chrome")
    targets: Tuple[str, ...] = field(default_factory=tuple)  # for invalidation


@dataclass(frozen=True)
class FocusCommand(BaseCommand):
    """FOCUS <app|@target> [title("…")] [#tags]"""
    target: Optional[str] = None  # @alias or quoted string
    title: Optional[str] = None
    targets: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CloseCommand(BaseCommand):
    """CLOSE <app|"name"> | CLOSE [list]"""
    target: Optional[str] = None
    items: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HideCommand(BaseCommand):
    """
    HIDE <app|@target>
    HIDE all
    HIDE all except @target
    HIDE [a, b]
    """
    target: Optional[str] = None
    items: Tuple[str, ...] = field(default_factory=tuple)
    hide_all: bool = False
    except_items: Tuple[str, ...] = field(default_factory=tuple)


# =========================================================
# 🖱️ MOUSE & KEYBOARD
# =========================================================

@dataclass(frozen=True)
class ClickCommand(BaseCommand):
    """
    CLICK <selector>
    CLICK x,y
    CLICK text("Sign in")
    CLICK selector(".btn")
    CLICK position(100,200)
    CLICK text("X") selector(".y")          ← AND semantics
    """
    selector: Optional[str] = None
    text: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None


@dataclass(frozen=True)
class TypeCommand(BaseCommand):
    """
    TYPE "<text>"
    TYPE("hello") repeat(3) interval(0.5s) speed(0.1s) timeout(3s)
    """
    text: str = ""


@dataclass(frozen=True)
class PressCommand(BaseCommand):
    """
    PRESS {enter}
    PRESS {cmd+shift+tab}
    PRESS [{shift_down}, ({left})x5, {shift_up}]
    """
    keys: Tuple[Any, ...] = field(default_factory=tuple)
    """
    Each entry is one of:
        ("key",   "enter")                        — single key event
        ("combo", ("cmd","shift","tab"))          — modifier combination
        ("rep",   ("key", "left"), 5)             — repeated single
        ("rep",   ("combo", ("cmd","c")), 3)      — repeated combo
    """


@dataclass(frozen=True)
class WaitCommand(BaseCommand):
    """WAIT <seconds>  |  WAIT(5s)  |  WAIT 5m"""
    seconds: float = 0.0


# =========================================================
# 📸 SCREENSHOT
# =========================================================

@dataclass(frozen=True)
class ScreenshotCommand(BaseCommand):
    """
    SCREENSHOT [<path>]
    SCREENSHOT display(2)
    SCREENSHOT window("Slack")
    SCREENSHOT area(0,0,1920,1080)
    """
    path: Optional[str] = None
    display: Optional[int] = None
    window: Optional[str] = None
    area: Optional[Tuple[int, int, int, int]] = None


# =========================================================
# 📋 CLIPBOARD / SAVE
# =========================================================

@dataclass(frozen=True)
class CopyCommand(BaseCommand):
    """COPY"""


@dataclass(frozen=True)
class PasteCommand(BaseCommand):
    """PASTE"""


@dataclass(frozen=True)
class SaveCommand(BaseCommand):
    """SAVE source(clipboard) to("~/file.png")"""
    source: Optional[str] = None
    to: Optional[str] = None


# =========================================================
# 🛠️ SCRIPT EXECUTION
# =========================================================

@dataclass(frozen=True)
class RunCommand(BaseCommand):
    """RUN "~/scripts/x.sh"  |  RUN "./script.py" """
    path: str = ""
