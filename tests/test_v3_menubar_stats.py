"""
v1.3.0 — stats backend + menubar JSON contract tests.

Covers:
- core.stats: format_time_saved boundary cases, compute_time_saved,
  resolve_weights with override semantics
- state.stats_store: first-run init, atomic save, record_action,
  record_actions batch, snapshot shape
- cli.main: stats --json prints valid JSON
- cli.menubar: importability is OPTIONAL (skipped if pyobjc missing)

Each test isolates state.stats_store.STATS_PATH to a tempfile so the
suite never touches the user's real data/stats.json.

Run:
    python -m unittest tests.test_v3_menubar_stats -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.stats import (
    ACTION_WEIGHTS,
    compute_time_saved,
    format_time_saved,
    resolve_weights,
)


# =============================================================
# core.stats — pure functions
# =============================================================

class FormatTimeSaved(unittest.TestCase):
    """format_time_saved boundary cases — these are the contract."""

    def test_zero(self):
        self.assertEqual(format_time_saved(0), "0m")

    def test_negative_clamps_to_zero(self):
        self.assertEqual(format_time_saved(-5), "0m")

    def test_non_int_clamps_to_zero(self):
        self.assertEqual(format_time_saved(None), "0m")
        self.assertEqual(format_time_saved("nope"), "0m")

    def test_under_one_minute(self):
        self.assertEqual(format_time_saved(45), "<1m")
        self.assertEqual(format_time_saved(59), "<1m")

    def test_minutes(self):
        self.assertEqual(format_time_saved(60), "1m")
        self.assertEqual(format_time_saved(120), "2m")
        self.assertEqual(format_time_saved(3599), "59m")

    def test_hours_with_minutes(self):
        self.assertEqual(format_time_saved(3600), "1h")
        self.assertEqual(format_time_saved(3660), "1h 1m")
        # 21h 14m exact = 21*3600 + 14*60 = 76440.
        # 76410 = 21h 13m 30s → floors to "21h 13m" (we never round up;
        # users shouldn't see minutes they didn't earn).
        self.assertEqual(format_time_saved(76440), "21h 14m")
        self.assertEqual(format_time_saved(76410), "21h 13m")

    def test_days(self):
        self.assertEqual(format_time_saved(86400), "1d")
        self.assertEqual(format_time_saved(90000), "1d 1h")
        self.assertEqual(format_time_saved(172800), "2d")
        self.assertEqual(format_time_saved(180000), "2d 2h")


class ComputeTimeSaved(unittest.TestCase):
    """compute_time_saved sums by_type with weights."""

    def test_empty(self):
        self.assertEqual(compute_time_saved({}), 0)

    def test_single_type(self):
        # 100 open_url × 5 = 500
        self.assertEqual(compute_time_saved({"open_url": 100}), 500)

    def test_unknown_keys_ignored(self):
        # The forward-compat property: future verbs without weights
        # don't crash; they're silently uncounted.
        self.assertEqual(compute_time_saved({"future_verb": 999}), 0)

    def test_negative_counts_ignored(self):
        self.assertEqual(compute_time_saved({"open_url": -10}), 0)
        self.assertEqual(compute_time_saved({"open_url": 0}), 0)

    def test_realistic_mix(self):
        # The example from the spec: 4,182 events ≈ 12,546 actions →
        # ~21h 14m. Use the by_type breakdown the spec spelled out.
        by_type = {
            "open_url":     6500,   # × 5 = 32500
            "open_profile": 1500,   # × 8 = 12000
            "arrange":      2000,   # × 4 =  8000
            "hide":         1000,   # × 2 =  2000
            "autofill":     1200,   # × 8 =  9600
            "focus":         300,   # × 1 =   300
            "screenshot":     46,   # × 3 =   138
        }
        # = 64538 s
        self.assertEqual(compute_time_saved(by_type), 64538)
        # Rendered: 17h 55m (not 21h — different mix than the spec's
        # back-of-envelope, but verifies the math is right).
        self.assertEqual(format_time_saved(64538), "17h 55m")


class ResolveWeights(unittest.TestCase):
    """User overrides via STATS_ACTION_WEIGHTS (settings.py)."""

    def test_no_overrides(self):
        # Without overrides, resolve_weights returns the default copy.
        weights = resolve_weights()
        self.assertEqual(weights, ACTION_WEIGHTS)
        self.assertIsNot(weights, ACTION_WEIGHTS)  # it's a copy

    def test_override_is_applied(self):
        with patch.dict(
            "config.settings.__dict__",
            {"STATS_ACTION_WEIGHTS": {"open_url": 12}},
            clear=False,
        ):
            weights = resolve_weights()
            self.assertEqual(weights["open_url"], 12)
            self.assertEqual(weights["focus"], 1)  # untouched

    def test_unknown_override_keys_ignored(self):
        with patch.dict(
            "config.settings.__dict__",
            {"STATS_ACTION_WEIGHTS": {"future_verb": 99}},
            clear=False,
        ):
            weights = resolve_weights()
            self.assertNotIn("future_verb", weights)

    def test_negative_override_ignored(self):
        with patch.dict(
            "config.settings.__dict__",
            {"STATS_ACTION_WEIGHTS": {"open_url": -1}},
            clear=False,
        ):
            weights = resolve_weights()
            self.assertEqual(weights["open_url"], ACTION_WEIGHTS["open_url"])


# =============================================================
# state.stats_store — IO, isolated to a tempfile
# =============================================================

class StatsStore(unittest.TestCase):
    """Each test runs against its own STATS_PATH so we never touch real data."""

    def setUp(self):
        # New tempfile per test → no cross-contamination.
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        )
        self._tmp.close()
        os.unlink(self._tmp.name)  # let load_stats see "missing" first
        self._tmp_path = Path(self._tmp.name)
        self._patch = patch(
            "state.stats_store.STATS_PATH", self._tmp_path,
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        if self._tmp_path.exists():
            self._tmp_path.unlink()

    def test_load_missing_returns_defaults(self):
        from state.stats_store import load_stats
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 0)
        self.assertEqual(stats["actions_failed"], 0)
        self.assertEqual(stats["by_type"], {})
        self.assertIsNone(stats["first_run_date"])

    def test_record_action_initializes_first_run(self):
        from state.stats_store import load_stats, record_action
        record_action("open_url")
        stats = load_stats()
        self.assertIsNotNone(stats["first_run_date"])
        self.assertEqual(stats["actions_run"], 1)
        self.assertEqual(stats["by_type"]["open_url"], 1)

    def test_record_action_subsequent_keeps_first_run(self):
        from state.stats_store import load_stats, record_action
        record_action("open_url")
        first = load_stats()["first_run_date"]
        record_action("hide")
        record_action("hide")
        second = load_stats()["first_run_date"]
        self.assertEqual(first, second)
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 3)
        self.assertEqual(stats["by_type"], {"open_url": 1, "hide": 2})

    def test_record_action_failure_path(self):
        from state.stats_store import load_stats, record_action
        record_action("screenshot", success=False)
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 0)
        self.assertEqual(stats["actions_failed"], 1)
        self.assertEqual(stats["by_type"], {})

    def test_record_action_no_op_on_empty_key(self):
        from state.stats_store import load_stats, record_action
        record_action("")
        record_action(None)  # type: ignore[arg-type]
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 0)

    def test_record_actions_batch(self):
        from state.stats_store import load_stats, record_actions
        record_actions({"open_url": 3, "hide": 2, "focus": 0, "ignored": -1})
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 5)
        self.assertEqual(stats["by_type"], {"open_url": 3, "hide": 2})

    def test_corrupt_file_returns_defaults(self):
        from state.stats_store import load_stats
        self._tmp_path.write_text("not json {")
        stats = load_stats()
        self.assertEqual(stats["actions_run"], 0)
        # Subsequent record should still work (load returned defaults).
        from state.stats_store import record_action
        record_action("focus")
        self.assertEqual(load_stats()["actions_run"], 1)

    def test_snapshot_shape(self):
        from state.stats_store import record_actions, snapshot
        record_actions({"open_url": 10, "autofill": 2})
        snap = snapshot()
        self.assertEqual(snap["actions_run"], 12)
        self.assertEqual(snap["by_type"], {"open_url": 10, "autofill": 2})
        # 10*5 + 2*8 = 66 s
        self.assertEqual(snap["time_saved_seconds"], 66)
        self.assertEqual(snap["time_saved_human"], "1m")
        self.assertEqual(snap["schema_version"], 1)
        self.assertIsNotNone(snap["first_run_date"])


# =============================================================
# cli.main stats --json — JSON contract smoke test
# =============================================================

class StatsCli(unittest.TestCase):
    """
    End-to-end check that the menubar's JSON contract is well-formed.

    Two layers:
        1. snapshot() returns a JSON-serializable dict (always runs).
        2. `python -m cli.main stats` prints valid JSON (skipped on
           machines without google-api-python-client; the sandbox-CI
           runner is one such machine).
    """

    def test_snapshot_is_json_serializable(self):
        # In-process: doesn't depend on google deps.
        from state.stats_store import snapshot
        snap = snapshot()
        # round-trip through json — anything not serialisable raises.
        round_tripped = json.loads(json.dumps(snap, default=str))
        for key in (
            "first_run_date", "actions_run", "actions_failed",
            "by_type", "time_saved_seconds", "time_saved_human",
            "schema_version",
        ):
            self.assertIn(key, round_tripped, f"missing key {key!r}")

    def test_stats_json_via_subprocess(self):
        # Probe via subprocess — checking sys.modules in the test process
        # is unreliable because earlier tests in the suite may have
        # injected `google.auth` as a Mock, which would make a naive
        # `import google.auth` succeed even though the real package
        # isn't installed (and the subprocess will fail).
        probe = subprocess.run(
            [sys.executable, "-c", "import google.auth"],
            capture_output=True, text=True, timeout=5,
        )
        if probe.returncode != 0:
            self.skipTest("google-api-python-client not in subprocess env")
        proc = subprocess.run(
            [sys.executable, "-m", "cli.main", "stats"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"stats exited {proc.returncode}: stderr={proc.stderr!r}",
        )
        out = proc.stdout.strip()
        brace = out.find("{")
        self.assertGreaterEqual(brace, 0, f"no JSON in stdout: {out!r}")
        payload = json.loads(out[brace:])
        for key in (
            "first_run_date", "actions_run", "actions_failed",
            "by_type", "time_saved_seconds", "time_saved_human",
            "schema_version",
        ):
            self.assertIn(key, payload, f"missing key {key!r}")


# =============================================================
# cli.menubar — optional-import smoke
# =============================================================

class MenubarImport(unittest.TestCase):
    """
    Best-effort: if pyobjc is available, `import cli.menubar` must succeed
    cleanly. If not, skip — CalFlow's CLI must keep working without it.
    """

    def test_import_or_skip(self):
        try:
            import cli.menubar  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"pyobjc not installed: {exc}")
        else:
            # Module exposes a callable `main`.
            from cli.menubar import main
            self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main(verbosity=2)
