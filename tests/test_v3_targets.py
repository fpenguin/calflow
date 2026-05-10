"""
v1.3.9 — TARGETS reader + apply_targets writer tests.

Covers:
- read_targets returns the parsed dict from a fixture settings.py
- validate_alias_name catches: missing @, bad chars, reserved keywords
- validate_app_list catches: empty list, non-string items, embedded quotes
- apply_targets atomically rewrites the dict + makes a backup
- apply_targets refuses ANY-error payloads (no partial writes)
- render_targets emits sorted, grouped output

Each test uses a tempfile copy of settings.py so we never mutate the user's.

Run:
    python -m unittest tests.test_v3_targets -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.targets_writer import (
    apply_targets,
    read_targets,
    render_targets,
    validate_alias_name,
    validate_app_list,
)


FAKE_SETTINGS = '''\
from __future__ import annotations

FETCH_WINDOW_HOURS = 2

TARGETS = {
    # --- System targets ---
    "@chrome": "Google Chrome",
    "@safari": "Safari",
    "@firefox": "Firefox",

    # --- Workflow aliases ---
    "@work": ["Google Chrome", "Notion", "Figma"],
    "@comm": ["Slack", "Discord"],
}

OTHER_SETTING = 42
BLACKLIST_REGEX = ["/cancel"]
'''


class TargetsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="calflow_tg_"))
        self._settings = self._tmp / "settings.py"
        self._backup   = self._tmp / "settings.py.bak"
        self._settings.write_text(FAKE_SETTINGS, encoding="utf-8")
        self._patches = [
            patch("core.targets_writer.SETTINGS_PATH", self._settings),
            patch("core.targets_writer.BACKUP_PATH",   self._backup),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def read(self) -> str:
        return self._settings.read_text(encoding="utf-8")


# =============================================================
# Reader
# =============================================================

class Reader(TargetsBase):
    def test_reads_all(self):
        out = read_targets()
        self.assertEqual(out["@chrome"], "Google Chrome")
        self.assertEqual(out["@work"], ["Google Chrome", "Notion", "Figma"])
        self.assertEqual(set(out.keys()),
                         {"@chrome", "@safari", "@firefox", "@work", "@comm"})

    def test_returns_empty_on_missing_targets(self):
        # Strip TARGETS from settings.py.
        text = self._settings.read_text()
        text = text.replace("TARGETS = {", "OTHER_TARGETS = {")
        self._settings.write_text(text)
        self.assertEqual(read_targets(), {})

    def test_returns_empty_on_unparseable(self):
        self._settings.write_text("not python {")
        self.assertEqual(read_targets(), {})


# =============================================================
# Validation
# =============================================================

class AliasName(unittest.TestCase):
    def test_ok(self):
        for n in ["@chrome", "@my-alias", "@app_2", "@A"]:
            self.assertIsNone(validate_alias_name(n), n)

    def test_missing_at(self):
        self.assertIn("@", validate_alias_name("chrome"))

    def test_empty(self):
        self.assertIsNotNone(validate_alias_name(""))
        self.assertIsNotNone(validate_alias_name("@"))

    def test_bad_chars(self):
        for n in ["@my alias", "@my.alias", "@my!", "@a/b"]:
            self.assertIsNotNone(validate_alias_name(n), n)

    def test_reserved(self):
        for n in ["@active", "@all", "@display", "@except", "@ALL"]:
            err = validate_alias_name(n)
            self.assertIsNotNone(err)
            self.assertIn("reserved", err.lower())


class AppList(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(validate_app_list(["Chrome"]))
        self.assertIsNone(validate_app_list(["A", "B", "C"]))
        self.assertIsNone(validate_app_list("SingleString"))

    def test_empty(self):
        self.assertIsNotNone(validate_app_list([]))
        self.assertIsNotNone(validate_app_list([""]))

    def test_non_strings(self):
        self.assertIsNotNone(validate_app_list([1, 2]))
        self.assertIsNotNone(validate_app_list([None]))

    def test_embedded_quotes(self):
        self.assertIsNotNone(validate_app_list(['App"; rm']))
        self.assertIsNotNone(validate_app_list(["App\nname"]))


# =============================================================
# Writer — happy path
# =============================================================

class WriterHappyPath(TargetsBase):
    def test_full_replace(self):
        result = apply_targets({"targets": {
            "@chrome": "Chromium",
            "@notes":  "Notes",
            "@work":   ["Slack", "Linear"],
        }})
        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["count"], 3)

        # Re-read should reflect the new state.
        new = read_targets()
        self.assertEqual(new, {
            "@chrome": "Chromium",
            "@notes":  "Notes",
            "@work":   ["Slack", "Linear"],
        })

        # Other settings must remain untouched.
        text = self.read()
        self.assertIn("FETCH_WINDOW_HOURS = 2", text)
        self.assertIn("OTHER_SETTING = 42", text)
        self.assertIn('BLACKLIST_REGEX = ["/cancel"]', text)

    def test_creates_backup(self):
        self.assertFalse(self._backup.exists())
        apply_targets({"targets": {"@a": "App"}})
        self.assertTrue(self._backup.exists())
        self.assertIn("@chrome", self._backup.read_text())  # original content

    def test_single_string_value_round_trips(self):
        apply_targets({"targets": {"@x": "App X"}})
        self.assertEqual(read_targets()["@x"], "App X")

    def test_one_item_list_collapses_to_string(self):
        apply_targets({"targets": {"@x": ["App X"]}})
        self.assertEqual(read_targets()["@x"], "App X")

    def test_empty_targets_dict(self):
        result = apply_targets({"targets": {}})
        self.assertTrue(result["ok"])
        self.assertEqual(read_targets(), {})


# =============================================================
# Writer — rejection paths
# =============================================================

class WriterRejection(TargetsBase):
    def test_reserved_keyword_blocks_whole_write(self):
        original = self.read()
        result = apply_targets({"targets": {
            "@chrome": "Google Chrome",
            "@all":    "Anything",      # reserved
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(self.read(), original, "no writes should happen on rejection")
        # All errors collected, not just first.
        names = [e["alias"] for e in result["errors"]]
        self.assertIn("@all", names)

    def test_invalid_alias_format(self):
        result = apply_targets({"targets": {"chrome": "App"}})
        self.assertFalse(result["ok"])
        self.assertIn("@", result["errors"][0]["reason"])

    def test_empty_app_list_rejected(self):
        result = apply_targets({"targets": {"@x": []}})
        self.assertFalse(result["ok"])

    def test_quotes_in_app_name_rejected(self):
        result = apply_targets({"targets": {"@x": ['App"; rm -rf /']}})
        self.assertFalse(result["ok"])
        self.assertIn("quotes", result["errors"][0]["reason"])

    def test_non_dict_payload(self):
        result = apply_targets({"targets": "not a dict"})
        self.assertFalse(result["ok"])
        result = apply_targets({})
        self.assertFalse(result["ok"])


# =============================================================
# Renderer — output format
# =============================================================

class Render(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(render_targets({}), "{}")

    def test_groups_singles_first_then_workflows(self):
        out = render_targets({
            "@work":   ["A", "B"],
            "@chrome": "Chrome",
            "@design": ["C", "D"],
            "@safari": "Safari",
        })
        # Single-app section comes before workflow.
        i_chrome = out.index('"@chrome"')
        i_safari = out.index('"@safari"')
        i_design = out.index('"@design"')
        i_work   = out.index('"@work"')
        self.assertLess(i_chrome, i_design)
        self.assertLess(i_safari, i_work)
        # Sorted within section.
        self.assertLess(i_chrome, i_safari)
        self.assertLess(i_design, i_work)

    def test_workflow_inline_render(self):
        out = render_targets({"@x": ["A", "B", "C"]})
        self.assertIn('"@x": ["A", "B", "C"]', out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
