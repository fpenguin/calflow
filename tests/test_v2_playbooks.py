"""
Playbook scenario tests (v2.0).

Each test loads a real playbook script from /playbooks (or the
canonical example block from inside a playbook .md) and verifies:
- mode detection
- expected verbs in expected order
- no validation errors
- the resolver produces sane parameter dicts (no `invalid` flags)
- runtime executor accepts the AST without raising

Backends for CLICK/TYPE/PRESS/SAVE/RUN are stubs in v2.0; we still
test that the dispatch path runs to completion via mocking.

Run:
    python -m unittest tests.test_v2_playbooks -v
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
from core.resolver import resolve_command
import runtime.command_executor as ce


PLAYBOOKS_DIR = os.path.join(ROOT, "playbooks")


# =============================================================
# 🧰 HELPERS
# =============================================================

_FENCE_RE = re.compile(r"```text\s*\n(.*?)```", re.DOTALL)


def first_plus_block(md_text: str) -> str:
    """Extract the first ```text block``` containing `+CalFlow+`."""
    for block in _FENCE_RE.findall(md_text):
        if "+CalFlow+" in block:
            return block.strip()
    raise AssertionError("No `+CalFlow+` block found in playbook")


def all_plus_blocks(md_text: str) -> List[str]:
    return [
        block.strip()
        for block in _FENCE_RE.findall(md_text)
        if "+CalFlow+" in block
    ]


def load_playbook(name: str) -> str:
    path = os.path.join(PLAYBOOKS_DIR, name)
    with open(path) as f:
        return f.read()


def install_action_mocks(testcase: unittest.TestCase) -> None:
    """Patch runtime side-effects so playbook tests don't actually
    open browsers / take screenshots / call autofill.
    """
    saves = {
        "open_target":      ce.open_target,
        "take_screenshot":  ce.take_screenshot,
        "trigger_autofill": ce.trigger_autofill,
        "sleep":            ce.time.sleep,
    }
    ce.open_target = lambda **kw: None
    ce.take_screenshot = lambda *a, **kw: "/tmp/mock.png"
    ce.trigger_autofill = lambda mode="fill": None
    ce.time.sleep = lambda *_a, **_kw: None

    def restore():
        ce.open_target = saves["open_target"]
        ce.take_screenshot = saves["take_screenshot"]
        ce.trigger_autofill = saves["trigger_autofill"]
        ce.time.sleep = saves["sleep"]

    testcase.addCleanup(restore)


# =============================================================
# 📕 BASE PLAYBOOK CLASS
# =============================================================

class _PlaybookBase(unittest.TestCase):
    """Common assertions every playbook should pass."""

    playbook_file: str = ""
    expected_verbs: List[str] = []

    def setUp(self) -> None:
        if not self.playbook_file:
            self.skipTest("base class")
        self.text = first_plus_block(load_playbook(self.playbook_file))
        self.result = parse(self.text)
        install_action_mocks(self)

    def test_is_plus_mode(self):
        self.assertEqual(self.result.mode, "plus")

    def test_expected_verbs_in_order(self):
        actual = [c.name for c in self.result.commands]
        self.assertEqual(actual, self.expected_verbs)

    def test_no_validation_errors(self):
        if self.result.errors:
            self.fail("Validation errors:\n  " + "\n  ".join(
                f"L{e.line_no}: {e.message}" for e in self.result.errors
            ))

    def test_resolver_produces_no_invalid(self):
        for cmd in self.result.commands:
            params = resolve_command(cmd)
            self.assertNotIn(
                "invalid", params,
                msg=f"resolver flagged {cmd.raw!r} as invalid: {params.get('invalid')}",
            )

    def test_executor_runs_without_exception(self):
        # Mocked side effects → just verifying dispatch wires up.
        ce.execute_commands(self.result.commands)


# =============================================================
# 📕 PER-PLAYBOOK CASES
# =============================================================

class PB_DailySetup(_PlaybookBase):
    playbook_file = "daily-setup.md"
    expected_verbs = ["OPEN", "OPEN", "OPEN"]


class PB_FocusMode(_PlaybookBase):
    """playbooks/focus-mode.md — first block is the simple one."""
    playbook_file = "focus-mode.md"
    expected_verbs = ["CLOSE", "HIDE", "FOCUS"]


class PB_QuickOpen(_PlaybookBase):
    playbook_file = "quick-open.md"
    expected_verbs = ["OPEN", "OPEN", "OPEN", "CLOSE"]


class PB_SlackScreenshot(_PlaybookBase):
    playbook_file = "slack-screenshot.md"
    expected_verbs = ["FOCUS", "SCREENSHOT", "SAVE"]


class PB_WeeklyReport(_PlaybookBase):
    playbook_file = "weekly-report.md"
    expected_verbs = ["OPEN", "FOCUS", "SCREENSHOT", "SAVE"]


# =============================================================
# 📕 README playbook (playbooks.md) — multiple example blocks
# =============================================================

class PB_README(unittest.TestCase):
    """playbooks/playbooks.md ships several example blocks; each must parse."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.blocks = all_plus_blocks(load_playbook("playbooks.md"))

    def test_at_least_one_block(self):
        self.assertGreaterEqual(len(self.blocks), 5)

    def test_every_readme_block_parses_in_plus_mode(self):
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                result = parse(block)
                self.assertEqual(result.mode, "plus", f"block #{i} not Plus")
                # Header-only blocks (like the docs example illustrating
                # `+CalFlow+` itself) are legitimate and may have 0 commands.
                if block.strip() != "+CalFlow+":
                    self.assertGreater(
                        len(result.commands), 0,
                        f"block #{i} produced no commands",
                    )

    def test_every_readme_block_resolves_cleanly(self):
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                for cmd in parse(block).commands:
                    params = resolve_command(cmd)
                    if "invalid" in params:
                        self.fail(
                            f"block #{i} cmd L{cmd.line_no} {cmd.raw!r} "
                            f"flagged invalid: {params['invalid']}"
                        )


# =============================================================
# 📕 In-doc secondary blocks (real-life setups inside playbooks)
# =============================================================

class PB_AllSecondaryBlocks(unittest.TestCase):
    """Every `+CalFlow+` block across every playbook must parse."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.blocks: List[tuple] = []
        for name in os.listdir(PLAYBOOKS_DIR):
            if not name.endswith(".md"):
                continue
            for i, block in enumerate(
                all_plus_blocks(load_playbook(name)), start=1
            ):
                cls.blocks.append((name, i, block))

    def test_every_block_is_plus_mode_and_has_commands(self):
        failed: List[str] = []
        for name, i, block in self.blocks:
            if block.strip() == "+CalFlow+":
                continue  # header-only doc illustration
            result = parse(block)
            if result.mode != "plus" or not result.commands:
                failed.append(f"{name} block #{i}")
        if failed:
            self.fail("Unparsable blocks:\n  " + "\n  ".join(failed))

    def test_every_block_has_no_validation_errors(self):
        failed: List[str] = []
        for name, i, block in self.blocks:
            result = parse(block)
            if result.errors:
                msgs = "; ".join(f"L{e.line_no}:{e.message}" for e in result.errors)
                failed.append(f"{name} block #{i} → {msgs}")
        if failed:
            self.fail("Blocks with validation errors:\n  " + "\n  ".join(failed))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
