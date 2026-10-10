"""Permission checks for Plus Mode `run` backends."""

from __future__ import annotations

__all__ = ["is_run_backend_allowed", "is_open_target_allowed"]

from urllib.parse import urlsplit
import re

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


def is_run_backend_allowed(backend: str | None, trust_level: str) -> bool:
    name = (backend or "script").strip().lower()
    if trust_level == TRUST_SELF:
        return name in ALLOW_RUN_BACKENDS_SELF
    if trust_level == TRUST_TRUSTED_DOMAIN:
        return name in ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN
    if trust_level == TRUST_TRUSTED_EMAIL:
        return name in ALLOW_RUN_BACKENDS_TRUSTED_EMAIL
    return False


def is_open_target_allowed(target: str, trust_level: str) -> bool:
    """Keep OPEN/deep links from bypassing calendar RUN permissions."""
    value = target.strip().strip("\"'")
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return False
    backend = {
        "btt": "btt",
        "bettertouchtool": "btt",
        "alfred": "alfred",
        "shortcuts": "shortcut",
        "applescript": "applescript",
    }.get(scheme)
    if backend:
        return is_run_backend_allowed(backend, trust_level)
    if trust_level == TRUST_SELF:
        return True
    if trust_level not in (TRUST_TRUSTED_DOMAIN, TRUST_TRUSTED_EMAIL):
        return False
    if scheme:
        return scheme in ("http", "https")
    # Local paths may launch executables via LaunchServices.
    if value.startswith(("/", "~", "./", "../")):
        return False
    if "/" in value:
        # Bare web domains with paths are URLs; directory/app paths are not.
        return bool(re.match(r"^[a-z0-9.\-]+\.[a-z]{2,}(?:[/?#]|$)", value, re.IGNORECASE))
    return True
