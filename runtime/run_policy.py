"""Permission checks for Plus Mode `run` backends."""

from __future__ import annotations

__all__ = ["is_run_backend_allowed"]

from typing import Optional

from config.settings import (
    ALLOW_RUN_BACKENDS_SELF,
    ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN,
    ALLOW_RUN_BACKENDS_TRUSTED_EMAIL,
)
from core.event_trust import (
    TRUST_SELF,
    TRUST_TRUSTED_DOMAIN,
    TRUST_TRUSTED_EMAIL,
)


def is_run_backend_allowed(backend: Optional[str], trust_level: str) -> bool:
    name = (backend or "script").strip().lower()
    if trust_level == TRUST_SELF:
        return name in ALLOW_RUN_BACKENDS_SELF
    if trust_level == TRUST_TRUSTED_DOMAIN:
        return name in ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN
    if trust_level == TRUST_TRUSTED_EMAIL:
        return name in ALLOW_RUN_BACKENDS_TRUSTED_EMAIL
    return False
