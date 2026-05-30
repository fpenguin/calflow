"""
Calendar event trust policy.

CalFlow events are executable text, so invite origin is a permission
boundary. This module is pure: callers pass the event and known owner
email, and receive a trust decision.
"""

from __future__ import annotations

__all__ = [
    "TRUST_SELF",
    "TRUST_TRUSTED_DOMAIN",
    "TRUST_TRUSTED_EMAIL",
    "TRUST_UNTRUSTED",
    "classify_event_trust",
    "is_event_trusted",
]

from dataclasses import dataclass
from typing import Dict, Optional, Set

from config.settings import (
    ALLOW_SELF_AUTHORED_EVENTS,
    TRUSTED_INVITE_DOMAINS,
    TRUSTED_INVITE_EMAILS,
)

TRUST_SELF = "self"
TRUST_TRUSTED_DOMAIN = "trusted_domain"
TRUST_TRUSTED_EMAIL = "trusted_email"
TRUST_UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class EventTrust:
    level: str
    trusted: bool
    actor: Optional[str]
    reason: str


def classify_event_trust(event: Dict, *, owner_email: Optional[str] = None) -> EventTrust:
    """Classify a calendar event according to sender allowlists."""
    owner = _normalize_email(owner_email) or _owner_from_event_calendar(event)
    actors = _event_actor_emails(event)

    if owner and ALLOW_SELF_AUTHORED_EVENTS and owner in actors:
        return EventTrust(TRUST_SELF, True, owner, "self_authored")

    trusted_emails = {_normalize_email(e) for e in TRUSTED_INVITE_EMAILS}
    trusted_emails.discard(None)
    for actor in sorted(actors):
        if actor in trusted_emails:
            return EventTrust(TRUST_TRUSTED_EMAIL, True, actor, "trusted_email")

    trusted_domains = {_normalize_domain(d) for d in TRUSTED_INVITE_DOMAINS}
    trusted_domains.discard(None)
    for actor in sorted(actors):
        domain = _email_domain(actor)
        if domain and domain in trusted_domains:
            return EventTrust(TRUST_TRUSTED_DOMAIN, True, actor, "trusted_domain")

    actor = sorted(actors)[0] if actors else None
    reason = "untrusted_inviter" if actors else "missing_event_identity"
    return EventTrust(TRUST_UNTRUSTED, False, actor, reason)


def is_event_trusted(event: Dict, *, owner_email: Optional[str] = None) -> bool:
    return classify_event_trust(event, owner_email=owner_email).trusted


def _event_actor_emails(event: Dict) -> Set[str]:
    out: Set[str] = set()
    for key in ("creator_email", "organizer_email"):
        email = _normalize_email(event.get(key))
        if email:
            out.add(email)
    for key in ("creator", "organizer"):
        value = event.get(key)
        if isinstance(value, dict):
            email = _normalize_email(value.get("email"))
            if email:
                out.add(email)
    return out


def _owner_from_event_calendar(event: Dict) -> Optional[str]:
    return _normalize_email(event.get("calendar_id"))


def _normalize_email(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if "@" not in email:
        return None
    return email


def _normalize_domain(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    domain = value.strip().lower().lstrip("@")
    return domain or None


def _email_domain(email: str) -> Optional[str]:
    if "@" not in email:
        return None
    return email.rsplit("@", 1)[1].lower() or None
