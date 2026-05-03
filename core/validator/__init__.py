"""
core.validator — Plus Mode DSL grammar enforcement.

This layer runs BEFORE the AST is constructed. It catches
unknown commands, malformed arguments, and arity errors so the
parser can build a typed AST from already-clean input.
"""

from .validator import (
    KNOWN_COMMANDS,
    validate_plus_block,
    validate_plus_line,
)

__all__ = [
    "KNOWN_COMMANDS",
    "validate_plus_block",
    "validate_plus_line",
]
