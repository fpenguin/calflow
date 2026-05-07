"""
CalFlow Reserved Keywords (v1.1.2).

Identifiers that the DSL grammar reserves for runtime semantics. User
config (TARGETS, BUNDLES) MUST NOT shadow these — config load fails
fast with a rename suggestion if it does.

Reserved categories:
    - Runtime targets:   `active`, `all`
    - Filter functions:  `display`, `except`

Rationale:
    - deterministic DSL (same script behaves identically on every machine)
    - prevents silent shadowing where user-config wins over engine semantics
    - keeps parser + resolver simple (no precedence rules to remember)

Usage:
    from core.reserved import validate_user_config
    validate_user_config(TARGETS, BUNDLES)  # raises on collision
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'RESERVED_KEYWORDS',
    'ReservedKeywordError',
    'enforce_or_exit',
    'is_reserved',
    'validate_user_config',
]

import sys
from typing import FrozenSet, Mapping


RESERVED_KEYWORDS: FrozenSet[str] = frozenset({
    "active",
    "all",
    "display",
    "except",
})


class ReservedKeywordError(Exception):
    """Raised at config load when user TARGETS/BUNDLES shadow a reserved word."""


def _strip_at(name: str) -> str:
    """Drop a leading '@' so `@active` and `active` collide identically."""
    return name.lstrip("@") if isinstance(name, str) else str(name)


def is_reserved(name: str) -> bool:
    """True if `name` (with or without `@` prefix) is a reserved keyword."""
    return _strip_at(name).lower() in RESERVED_KEYWORDS


def validate_user_config(*tables: Mapping[str, object]) -> None:
    """
    Raise `ReservedKeywordError` if any table has a key colliding with a
    reserved keyword. Tables are checked in order; the FIRST collision is
    reported with a rename suggestion.

    Tables that are not mappings are silently ignored (defensive — settings
    that fail to load shouldn't cascade into a confusing reserved-keyword
    error here).

    Example:
        validate_user_config(TARGETS, BUNDLES)
    """
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        for key in table.keys():
            stripped = _strip_at(str(key)).lower()
            if stripped in RESERVED_KEYWORDS:
                suggestion = f"{stripped}_app"
                prefix = "@" if str(key).startswith("@") else ""
                msg = (
                    f"Reserved keyword conflict: {key!r} is a CalFlow DSL "
                    f"keyword and cannot be used as an alias.\n"
                    f"  → Rename to {prefix + suggestion!r}\n"
                    f"\nReserved keywords: {sorted(RESERVED_KEYWORDS)}"
                )
                raise ReservedKeywordError(msg)


def enforce_or_exit(*tables: Mapping[str, object]) -> None:
    """
    Same as `validate_user_config` but writes a clean error to stderr and
    calls `sys.exit(1)` instead of raising. Used at config-load time when
    the logging system may not yet be initialised.
    """
    try:
        validate_user_config(*tables)
    except ReservedKeywordError as exc:
        sys.stderr.write(f"\n[CalFlow CONFIG ERROR]\n{exc}\n\n")
        sys.exit(1)
