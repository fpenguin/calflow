"""
core.models — typed data structures used across CalFlow v2.0.

Public surface:
    - Mode constants
    - ParseResult (parser output container)
    - Command AST (BaseCommand + concrete commands)
    - ValidationError (returned by core.validator)
"""

from __future__ import annotations

from .commands import (
    BaseCommand,
    ClickCommand,
    DragCommand,
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
from .errors import ValidationError
from .parse_result import MODE_NONE, MODE_PLUS, MODE_SMART, ParseResult

__all__ = [
    "BaseCommand",
    "ClickCommand",
    "DragCommand",
    "CloseCommand",
    "CopyCommand",
    "FocusCommand",
    "HideCommand",
    "MODE_NONE",
    "MODE_PLUS",
    "MODE_SMART",
    "OpenCommand",
    "ParseResult",
    "PasteCommand",
    "PressCommand",
    "RunCommand",
    "SaveCommand",
    "ScreenshotCommand",
    "TypeCommand",
    "ValidationError",
    "WaitCommand",
]
