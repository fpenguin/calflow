"""
Reserved-keyword guard tests (v1.1.2).

Locks the DSL contract that user TARGETS / BUNDLES MUST NOT shadow
reserved keywords (`active`, `all`, `display`, `except`).

Run:
    python -m unittest tests.test_v2_reserved -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.reserved import (
    RESERVED_KEYWORDS,
    ReservedKeywordError,
    is_reserved,
    validate_user_config,
)


class ReservedKeywordSet(unittest.TestCase):
    def test_set_contents(self) -> None:
        self.assertEqual(
            RESERVED_KEYWORDS,
            frozenset({"active", "all", "display", "except"}),
        )

    def test_is_reserved_handles_at_prefix(self) -> None:
        self.assertTrue(is_reserved("active"))
        self.assertTrue(is_reserved("@active"))
        self.assertTrue(is_reserved("@all"))
        self.assertTrue(is_reserved("display"))
        self.assertTrue(is_reserved("except"))

    def test_is_reserved_case_insensitive(self) -> None:
        self.assertTrue(is_reserved("Active"))
        self.assertTrue(is_reserved("@ACTIVE"))

    def test_non_reserved_passes(self) -> None:
        self.assertFalse(is_reserved("@chrome"))
        self.assertFalse(is_reserved("@work"))
        self.assertFalse(is_reserved("active_app"))
        self.assertFalse(is_reserved("activity"))


class ValidateUserConfig(unittest.TestCase):
    def test_clean_config_passes(self) -> None:
        validate_user_config(
            {"@chrome": "Google Chrome", "@work": ["Chrome", "Notion"]}
        )  # should not raise

    def test_active_alias_rejected(self) -> None:
        with self.assertRaises(ReservedKeywordError) as ctx:
            validate_user_config({"@active": "Active.app"})
        msg = str(ctx.exception)
        self.assertIn("Reserved keyword conflict", msg)
        self.assertIn("@active", msg)
        self.assertIn("@active_app", msg)

    def test_all_bundle_rejected(self) -> None:
        with self.assertRaises(ReservedKeywordError):
            validate_user_config({"all": ["Chrome", "Safari"]})

    def test_display_alias_rejected(self) -> None:
        with self.assertRaises(ReservedKeywordError):
            validate_user_config({"display": "Some.app"})

    def test_except_alias_rejected(self) -> None:
        with self.assertRaises(ReservedKeywordError):
            validate_user_config({"except": "Some.app"})

    def test_first_collision_reported(self) -> None:
        with self.assertRaises(ReservedKeywordError) as ctx:
            validate_user_config(
                {"@chrome": "Chrome", "@active": "X", "@all": "Y"}
            )
        msg = str(ctx.exception)
        # Either active or all is fine — order is dict-iteration order.
        self.assertTrue("@active" in msg or "@all" in msg)

    def test_multiple_tables_checked(self) -> None:
        targets = {"@chrome": "Chrome"}
        bundles = {"@all": ["a", "b"]}
        with self.assertRaises(ReservedKeywordError):
            validate_user_config(targets, bundles)

    def test_non_mapping_silently_ignored(self) -> None:
        # Defensive — if a settings symbol fails to load, we shouldn't
        # cascade into a confusing reserved-keyword error.
        validate_user_config(None)  # type: ignore[arg-type]
        validate_user_config([1, 2, 3])  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
