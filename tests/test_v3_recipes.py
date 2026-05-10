"""
v1.3.1 — recipes catalog + my_recipes store tests.

Covers:
- core.recipes.list_stock() shape contract
- save_my_recipe / list_my_recipes round-trip with isolated tempfile
- delete_my_recipe by id
- _normalize_category clamps unknown values to "Daily"
- save_my_recipe rejects empty body

Each test isolates `core.recipes.MY_RECIPES_PATH` to a tempfile so the
suite never touches the user's real data/my_recipes.json.

Run:
    python -m unittest tests.test_v3_recipes -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.recipes import (
    CATEGORIES,
    STOCK_RECIPES,
    list_stock,
    list_categories,
)


# =============================================================
# Stock catalog — pure function, always available
# =============================================================

class StockCatalog(unittest.TestCase):
    def test_eight_starters(self):
        self.assertGreaterEqual(len(STOCK_RECIPES), 8,
            "Expected at least 8 stock recipes for the menubar starter set")

    def test_required_keys(self):
        required = {"id", "name", "category", "description", "body"}
        for r in list_stock():
            missing = required - r.keys()
            self.assertFalse(missing, f"recipe {r.get('id')!r} missing {missing}")
            self.assertEqual(r["owner"], "stock")
            self.assertTrue(r["id"].startswith("stock-"),
                f"stock id {r['id']!r} should start with 'stock-'")
            self.assertIn(r["category"], CATEGORIES,
                f"recipe {r['id']!r} has unknown category {r['category']!r}")

    def test_categories_balanced(self):
        # Each category should have at least one starter recipe.
        cats_with_recipes = {r["category"] for r in STOCK_RECIPES}
        for c in CATEGORIES:
            self.assertIn(c, cats_with_recipes,
                f"category {c!r} has zero starter recipes")

    def test_bodies_have_calflow_marker_or_smart_url(self):
        """Each starter must be runnable — Plus marker or a URL."""
        import re
        for r in STOCK_RECIPES:
            body = r["body"]
            has_plus = "+CalFlow+" in body
            has_url  = bool(re.search(r"https?://|@chrome|@safari|notes\.app", body))
            self.assertTrue(has_plus or has_url,
                f"recipe {r['id']!r} has no executable content")


class Categories(unittest.TestCase):
    def test_returns_copy(self):
        a = list_categories()
        b = list_categories()
        a.append("DROP")
        self.assertNotEqual(a, b, "list_categories should return a fresh copy each call")


# =============================================================
# my_recipes.json store — isolated tempfile per test
# =============================================================

class MyRecipesStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        self._tmp.close()
        os.unlink(self._tmp.name)
        self._tmp_path = Path(self._tmp.name)
        self._patch = patch("core.recipes.MY_RECIPES_PATH", self._tmp_path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        if self._tmp_path.exists():
            self._tmp_path.unlink()

    def test_empty_when_missing(self):
        from core.recipes import list_my_recipes
        self.assertEqual(list_my_recipes(), [])

    def test_save_creates_id(self):
        from core.recipes import list_my_recipes, save_my_recipe
        result = save_my_recipe({
            "name": "My morning",
            "category": "Daily",
            "body": "+CalFlow+\nopen news.ycombinator.com\n",
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["id"].startswith("mine-"),
            f"id should start with 'mine-' got {result['id']!r}")
        self.assertEqual(result["name"], "My morning")
        self.assertIsNotNone(result.get("created_at"))
        self.assertIsNotNone(result.get("updated_at"))
        self.assertEqual(len(list_my_recipes()), 1)

    def test_save_updates_existing(self):
        from core.recipes import list_my_recipes, save_my_recipe
        first = save_my_recipe({
            "name": "v1", "category": "Daily", "body": "+CalFlow+\nopen a.com\n",
        })
        rid = first["id"]
        created_at = first["created_at"]
        # Update by id; created_at should be preserved.
        second = save_my_recipe({
            "id": rid, "name": "v2", "category": "Focus", "body": "+CalFlow+\nopen b.com\n",
        })
        self.assertEqual(second["id"], rid)
        self.assertEqual(second["name"], "v2")
        self.assertEqual(second["category"], "Focus")
        self.assertEqual(second["created_at"], created_at)
        # Updated_at should be at least as recent as created_at (string compare OK
        # because both are ISO-8601 in the same TZ).
        self.assertGreaterEqual(second["updated_at"], created_at)
        self.assertEqual(len(list_my_recipes()), 1)

    def test_save_ignores_stock_id(self):
        """Trying to upsert with a 'stock-…' id silently mints a new mine-… id."""
        from core.recipes import save_my_recipe
        result = save_my_recipe({
            "id": "stock-zoom-notes",  # not allowed
            "name": "Hijack attempt",
            "category": "Meetings",
            "body": "+CalFlow+\nopen a.com\n",
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["id"].startswith("mine-"))

    def test_save_rejects_empty_body(self):
        from core.recipes import save_my_recipe
        r = save_my_recipe({"name": "Empty", "body": "   "})
        self.assertFalse(r["ok"])
        self.assertIn("missing body", r["error"])

    def test_save_normalises_unknown_category(self):
        from core.recipes import save_my_recipe
        r = save_my_recipe({
            "name": "x", "category": "MadeUp",
            "body": "+CalFlow+\nopen a.com\n",
        })
        self.assertEqual(r["category"], "Daily")

    def test_delete_existing(self):
        from core.recipes import delete_my_recipe, list_my_recipes, save_my_recipe
        a = save_my_recipe({"name": "a", "body": "+CalFlow+\nopen a.com\n"})
        b = save_my_recipe({"name": "b", "body": "+CalFlow+\nopen b.com\n"})
        del_a = delete_my_recipe(a["id"])
        self.assertTrue(del_a["ok"])
        remaining = list_my_recipes()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], b["id"])

    def test_delete_unknown(self):
        from core.recipes import delete_my_recipe
        r = delete_my_recipe("mine-00000000")
        self.assertFalse(r["ok"])

    def test_corrupt_file_returns_empty(self):
        from core.recipes import list_my_recipes
        self._tmp_path.write_text("not json {")
        self.assertEqual(list_my_recipes(), [])


# =============================================================
# all_recipes() — what the menubar's `recipes` op returns
# =============================================================

class AllRecipes(unittest.TestCase):
    def test_shape(self):
        from core.recipes import all_recipes
        out = all_recipes()
        self.assertIn("categories", out)
        self.assertIn("stock", out)
        self.assertIn("mine", out)
        self.assertIsInstance(out["categories"], list)
        self.assertIsInstance(out["stock"], list)
        self.assertIsInstance(out["mine"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
