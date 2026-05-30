from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.event_trust import (
    TRUST_SELF,
    TRUST_TRUSTED_DOMAIN,
    TRUST_TRUSTED_EMAIL,
    TRUST_UNTRUSTED,
    classify_event_trust,
)


class EventTrustPolicyTests(unittest.TestCase):
    def test_self_authored_event_is_trusted(self) -> None:
        trust = classify_event_trust(
            {"creator_email": "me@example.com"},
            owner_email="me@example.com",
        )
        self.assertTrue(trust.trusted)
        self.assertEqual(trust.level, TRUST_SELF)

    def test_external_event_blocked_by_default(self) -> None:
        trust = classify_event_trust(
            {"organizer_email": "sender@other.com"},
            owner_email="me@example.com",
        )
        self.assertFalse(trust.trusted)
        self.assertEqual(trust.level, TRUST_UNTRUSTED)

    def test_trusted_domain_is_allowed_when_configured(self) -> None:
        with patch("core.event_trust.TRUSTED_INVITE_DOMAINS", {"work.com"}):
            trust = classify_event_trust(
                {"organizer_email": "coworker@work.com"},
                owner_email="me@example.com",
            )
        self.assertTrue(trust.trusted)
        self.assertEqual(trust.level, TRUST_TRUSTED_DOMAIN)

    def test_trusted_email_is_allowed_when_configured(self) -> None:
        with patch("core.event_trust.TRUSTED_INVITE_EMAILS", {"bot@vendor.com"}):
            trust = classify_event_trust(
                {"organizer_email": "bot@vendor.com"},
                owner_email="me@example.com",
            )
        self.assertTrue(trust.trusted)
        self.assertEqual(trust.level, TRUST_TRUSTED_EMAIL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
