"""
v1.5.4-dev — mouse batch: click button()/count() modifiers + DRAG verb.

Locks (user decisions, 2026-06-17):

  click … button(left|right|middle)   — which mouse button; default left.
  click … count(n)                    — click-state (1 single, 2 double,
                                        3 triple); default 1. DISTINCT
                                        from repeat(): repeat(2) is two
                                        separate single clicks, count(2)
                                        is ONE double-click event.
  drag from(x,y) to(x,y)              — new verb (#14). Modifiers:
                                        button(), duration(t) (gesture
                                        length; default 0.3s).

Execution is a v2.1 stub for both verbs — these tests lock the parse /
validate / resolve surface so the syntax can't drift before the Quartz
backend lands. Element-based drag endpoints (from(text("…"))) are
specified-but-deferred; NOT tested here.

Run:
    python -m unittest tests.test_v4_click_drag -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
from core.resolver.resolver import resolve_command

P = "+CalFlow+\n"


def _one_command(text: str):
    result = parse(P + text)
    assert not result.errors, f"unexpected errors: {result.errors}"
    assert len(result.commands) == 1, f"expected 1 command, got {result.commands}"
    return result.commands[0]


def _errors(text: str):
    return parse(P + text).errors


# =========================================================
# click button()
# =========================================================

class ClickButton(unittest.TestCase):

    def test_button_right_parses(self):
        cmd = _one_command('click text("Submit") button(right)')
        self.assertEqual(cmd.button, "right")

    def test_button_middle_parses(self):
        cmd = _one_command("click position(100,200) button(middle)")
        self.assertEqual(cmd.button, "middle")

    def test_default_button_is_left_in_resolver(self):
        out = resolve_command(_one_command('click text("Submit")'))
        self.assertEqual(out["button"], "left")

    def test_button_resolves(self):
        out = resolve_command(_one_command('click text("Submit") button(right)'))
        self.assertEqual(out["button"], "right")

    def test_invalid_button_rejected(self):
        errs = _errors('click text("Submit") button(back)')
        self.assertTrue(errs, "button(back) should be rejected")
        self.assertIn("button", str(errs[0].message).lower())


# =========================================================
# click count()
# =========================================================

class ClickCount(unittest.TestCase):

    def test_count_2_parses(self):
        cmd = _one_command('click text("report.pdf") count(2)')
        self.assertEqual(cmd.count, 2)

    def test_count_3_parses(self):
        cmd = _one_command('click text("word") count(3)')
        self.assertEqual(cmd.count, 3)

    def test_default_count_is_1_in_resolver(self):
        out = resolve_command(_one_command('click text("Submit")'))
        self.assertEqual(out["count"], 1)

    def test_count_out_of_range_rejected(self):
        for bad in ("count(0)", "count(4)"):
            errs = _errors(f'click text("x") {bad}')
            self.assertTrue(errs, f"{bad} should be rejected")

    def test_count_and_repeat_coexist(self):
        # "three double-clicks" — count is click-state, repeat is
        # whole-command repetition. Both must survive to the resolver.
        out = resolve_command(
            _one_command('click text("cell") count(2) repeat(3)'))
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["repeat"], 3)

    def test_combined_modifiers(self):
        cmd = _one_command(
            'click text("row") button(right) count(2) timeout(3s)')
        self.assertEqual(cmd.button, "right")
        self.assertEqual(cmd.count, 2)


# =========================================================
# drag
# =========================================================

class DragVerb(unittest.TestCase):

    def test_basic_drag_parses(self):
        cmd = _one_command("drag from(100,200) to(300,400)")
        self.assertEqual((cmd.x1, cmd.y1, cmd.x2, cmd.y2),
                         (100, 200, 300, 400))

    def test_modifier_order_independent(self):
        cmd = _one_command("drag to(300,400) from(100,200)")
        self.assertEqual((cmd.x1, cmd.y1, cmd.x2, cmd.y2),
                         (100, 200, 300, 400))

    def test_drag_button(self):
        cmd = _one_command("drag from(0,0) to(50,50) button(right)")
        self.assertEqual(cmd.button, "right")

    def test_drag_duration(self):
        cmd = _one_command("drag from(0,0) to(50,50) duration(0.5s)")
        self.assertEqual(cmd.duration, 0.5)

    def test_drag_resolver_defaults(self):
        out = resolve_command(_one_command("drag from(0,0) to(50,50)"))
        self.assertEqual(out["button"], "left")
        self.assertAlmostEqual(out["duration"], 0.3)
        self.assertEqual(out["x1"], 0)
        self.assertEqual(out["y2"], 50)

    def test_drag_missing_to_rejected(self):
        errs = _errors("drag from(100,200)")
        self.assertTrue(errs, "drag without to() should be rejected")

    def test_drag_missing_from_rejected(self):
        errs = _errors("drag to(100,200)")
        self.assertTrue(errs, "drag without from() should be rejected")

    def test_drag_bare_rejected(self):
        errs = _errors("drag")
        self.assertTrue(errs, "bare drag should be rejected")

    def test_drag_malformed_coords_rejected(self):
        errs = _errors("drag from(100) to(300,400)")
        self.assertTrue(errs, "from(100) should be rejected")

    def test_drag_negative_coords_allowed(self):
        # Displays left of primary have negative x in Cocoa space.
        cmd = _one_command("drag from(-1920,0) to(-100,500)")
        self.assertEqual(cmd.x1, -1920)

    def test_executor_stub_does_not_crash(self):
        from runtime import command_executor as CE
        CE._do_drag({
            "verb": "DRAG", "x1": 0, "y1": 0, "x2": 50, "y2": 50,
            "button": "left", "duration": 0.3,
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
