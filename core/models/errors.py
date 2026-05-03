"""
Validator error type — surfaced by core.validator and bubbled up
through ParseResult so the dispatcher stays IO-free.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationError:
    """
    A single grammar / syntax violation encountered while parsing
    a Plus Mode block.

    Attributes:
        line_no: 1-based line number within the Plus block (0 = block-level).
        message: human-readable diagnostic.
    """
    line_no: int
    message: str

    def __str__(self) -> str:  # pragma: no cover (trivial)
        return f"line {self.line_no}: {self.message}"
