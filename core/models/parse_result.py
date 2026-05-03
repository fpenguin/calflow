"""
ParseResult — uniform return value of `core.parser.parser.parse()`.

Encodes both Smart Mode and Plus Mode outputs in a single shape so
the main pipeline can route on `result.mode` without conditional
type juggling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Tuple

from .commands import BaseCommand
from .errors import ValidationError


# =========================================================
# 🏷️ MODE CONSTANTS
# =========================================================

MODE_SMART: str = "smart"
MODE_PLUS: str = "plus"
MODE_NONE: str = "none"

_VALID_MODES: Tuple[str, ...] = (MODE_SMART, MODE_PLUS, MODE_NONE)


# =========================================================
# 📦 RESULT CONTAINER
# =========================================================

@dataclass(frozen=True)
class ParseResult:
    """
    Output of the unified parser.

    Attributes:
        mode:         "smart" | "plus" | "none"
        entries:      Smart Mode entries (List[Dict]). Empty in Plus Mode.
        commands:     Plus Mode AST (List[BaseCommand]). Empty in Smart Mode.
        global_tags:  union of `#tags` collected at the block level
                      (used by Smart Mode for alert offset etc.).
        errors:       validation diagnostics (always present, possibly empty).
    """
    mode: str = MODE_NONE
    entries: List[Dict] = field(default_factory=list)
    commands: List[BaseCommand] = field(default_factory=list)
    global_tags: FrozenSet[str] = field(default_factory=frozenset)
    errors: List[ValidationError] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"ParseResult.mode must be one of {_VALID_MODES}, got {self.mode!r}"
            )

    # -----------------------------------------------------
    # 🧪 CONVENIENCE
    # -----------------------------------------------------

    @property
    def is_smart(self) -> bool:
        return self.mode == MODE_SMART

    @property
    def is_plus(self) -> bool:
        return self.mode == MODE_PLUS

    @property
    def is_empty(self) -> bool:
        return self.mode == MODE_NONE or (
            not self.entries and not self.commands
        )

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
