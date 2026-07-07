"""
v1.5.2-dev — DSL batch: user-approved reversals of TSV "invalid" rows
plus clipboard/screenshot/layout sugar additions.

Locks (user decisions, 2026-06-17):
  1. `hide active display(N)`   — LEGAL. Miniaturize the frontmost app's
     windows on display N only (per-window, JXA path). Was "must reject"
     in the examples TSV; user reversed.
  2. `hide [active,"App"]`      — LEGAL. `active` in a list expands to
     the frontmost app name at EXECUTION time; deduped against the
     static items. Was "lists must be static"; user reversed.
  3. `copy("text")`             — copies literal text via pbcopy (real,
     not stub). Bare `copy` (copy current selection) remains a stub.
  4. `screenshot` (bare)        — sink is now the CLIPBOARD (was: file
     under PLUS_SCREENSHOT_DIR). `screenshot to(clipboard)` is the
     explicit spelling. `screenshot to("path")` still writes a file.
  5. Bare parenless layout words (`full`, `left`, `right`, `middle`,
     `top`, `bottom`) are drop-sugar for their `#tag` forms in Plus
     Mode. Previously silently dropped (worst outcome).
  7. `new(tab)` / `new(window)` + `#tab` / `#window` — already
     implemented in runtime/actions/browser.py::wants_new_window;
     locked here so it can't regress while being documented.

Run:
    python -m unittest tests.test_v4_dsl_batch -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.parser import parse
from core.resolver.resolver import resolve_command, resolve_layout

P = "+CalFlow+\n"


def _one_command(text: str):
    """Parse a single-line Plus block; assert exactly one command, no errors."""
    result = parse(P + text)
    assert not result.errors, f"unexpected errors: {result.errors}"
    assert len(result.commands) == 1, f"expected 1 command, got {result.commands}"
    return result.commands[0]


# =========================================================
# 1. hide active display(N)
# =========================================================

class HideActiveOnDisplay(unittest.TestCase):

    def test_parses_without_errors(self):
        cmd = _one_command("hide active display(2)")
        self.assertEqual(cmd.target_keyword, "active")
        self.assertEqual(cmd.display_filter, 2)

    def test_resolves_with_both_fields(self):
        cmd = _one_command("hide active display(2)")
        out = resolve_command(cmd)
        self.assertEqual(out["target_keyword"], "active")
        self.assertEqual(out["display_filter"], 2)

    def test_display_name_form(self):
        cmd = _one_command('hide active display("DELL")')
        self.assertEqual(cmd.target_keyword, "active")
        self.assertEqual(cmd.display_filter, "DELL")

    def test_plain_hide_active_unchanged(self):
        cmd = _one_command("hide active")
        self.assertEqual(cmd.target_keyword, "active")
        self.assertIsNone(cmd.display_filter)

    def test_executor_scopes_to_frontmost_windows_on_display(self):
        from runtime import command_executor as CE
        params = {
            "verb": "HIDE", "target_keyword": "active", "display_filter": 2,
            "items": (), "keep": (), "had_items": False,
        }
        with patch("runtime.actions.window.hide_apps_on_display",
                   return_value=True) as hod, \
             patch("runtime.actions.app_control.get_frontmost_app_name",
                   return_value="Safari"), \
             patch("runtime.actions.app_control.hide_app") as ha:
            CE._do_hide(params)
        hod.assert_called_once()
        _, kwargs = hod.call_args
        self.assertEqual(kwargs.get("only_app"), "Safari")
        ha.assert_not_called()  # must NOT app-level hide across displays

    def test_executor_plain_active_still_hides_app(self):
        from runtime import command_executor as CE
        params = {
            "verb": "HIDE", "target_keyword": "active", "display_filter": None,
            "items": (), "keep": (), "had_items": False,
        }
        with patch("runtime.actions.app_control.get_frontmost_app_name",
                   return_value="Safari"), \
             patch("runtime.actions.app_control.hide_app") as ha:
            CE._do_hide(params)
        ha.assert_called_once_with("Safari")


# =========================================================
# 2. hide [active,"App"]
# =========================================================

class HideListWithActive(unittest.TestCase):

    def test_parses_mixed_list(self):
        cmd = _one_command('hide [active,"Spotify"]')
        self.assertEqual(cmd.items, ("active", "Spotify"))

    def test_executor_expands_active_to_frontmost(self):
        from runtime import command_executor as CE
        params = {
            "verb": "HIDE", "target_keyword": None, "display_filter": None,
            "items": ("active", "Spotify"), "keep": (), "had_items": True,
        }
        with patch("runtime.actions.app_control.get_frontmost_app_name",
                   return_value="Notes"), \
             patch("runtime.actions.app_control.hide_app") as ha:
            CE._do_hide(params)
        hidden = [c.args[0] for c in ha.call_args_list]
        self.assertEqual(hidden, ["Notes", "Spotify"])

    def test_executor_dedupes_when_frontmost_is_listed(self):
        from runtime import command_executor as CE
        params = {
            "verb": "HIDE", "target_keyword": None, "display_filter": None,
            "items": ("active", "Spotify"), "keep": (), "had_items": True,
        }
        with patch("runtime.actions.app_control.get_frontmost_app_name",
                   return_value="Spotify"), \
             patch("runtime.actions.app_control.hide_app") as ha:
            CE._do_hide(params)
        hidden = [c.args[0] for c in ha.call_args_list]
        self.assertEqual(hidden, ["Spotify"])  # once, not twice

    def test_executor_skips_active_when_frontmost_unknown(self):
        from runtime import command_executor as CE
        params = {
            "verb": "HIDE", "target_keyword": None, "display_filter": None,
            "items": ("active", "Spotify"), "keep": (), "had_items": True,
        }
        with patch("runtime.actions.app_control.get_frontmost_app_name",
                   return_value=None), \
             patch("runtime.actions.app_control.hide_app") as ha:
            CE._do_hide(params)
        hidden = [c.args[0] for c in ha.call_args_list]
        self.assertEqual(hidden, ["Spotify"])


# =========================================================
# 3. copy("text")
# =========================================================

class CopyWithText(unittest.TestCase):

    def test_parses_with_text(self):
        cmd = _one_command('copy("hello")')
        self.assertEqual(cmd.text, "hello")

    def test_bare_copy_still_valid(self):
        cmd = _one_command("copy")
        self.assertIsNone(cmd.text)

    def test_resolves_text(self):
        out = resolve_command(_one_command('copy("hello")'))
        self.assertEqual(out["text"], "hello")

    def test_unquoted_arg_rejected(self):
        result = parse(P + "copy(hello)")
        self.assertTrue(result.errors, "copy(hello) unquoted should be rejected")

    def test_executor_pipes_to_pbcopy(self):
        from runtime import command_executor as CE
        with patch.object(CE.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=0)
            CE._do_copy({"verb": "COPY", "text": "hello"})
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["pbcopy"])
        self.assertEqual(kwargs.get("input"), "hello")

    def test_executor_bare_copy_remains_stub(self):
        from runtime import command_executor as CE
        with patch.object(CE.subprocess, "run") as run:
            CE._do_copy({"verb": "COPY", "text": None})
        run.assert_not_called()


# =========================================================
# 4. screenshot → clipboard
# =========================================================

class ScreenshotClipboard(unittest.TestCase):

    def test_bare_screenshot_resolves_no_path(self):
        out = resolve_command(_one_command("screenshot"))
        self.assertIsNone(out["path"])

    def test_to_clipboard_parses(self):
        cmd = _one_command("screenshot to(clipboard)")
        self.assertEqual(cmd.path, "clipboard")

    def test_executor_bare_goes_to_clipboard(self):
        from runtime import command_executor as CE
        with patch("runtime.command_executor.take_screenshot_to_clipboard",
                   return_value=True) as clip, \
             patch("runtime.command_executor.take_screenshot") as file_:
            CE._do_screenshot({"verb": "SCREENSHOT", "path": None})
        clip.assert_called_once()
        file_.assert_not_called()

    def test_executor_to_clipboard_goes_to_clipboard(self):
        from runtime import command_executor as CE
        with patch("runtime.command_executor.take_screenshot_to_clipboard",
                   return_value=True) as clip, \
             patch("runtime.command_executor.take_screenshot") as file_:
            CE._do_screenshot({"verb": "SCREENSHOT", "path": "clipboard"})
        clip.assert_called_once()
        file_.assert_not_called()

    def test_executor_explicit_path_still_writes_file(self):
        from runtime import command_executor as CE
        with patch("runtime.command_executor.take_screenshot_to_clipboard") as clip, \
             patch("runtime.command_executor.take_screenshot",
                   return_value="/tmp/x.png") as file_:
            CE._do_screenshot({"verb": "SCREENSHOT", "path": "~/x.png"})
        file_.assert_called_once_with("~/x.png")
        clip.assert_not_called()

    def test_clipboard_capture_uses_screencapture_dash_c(self):
        from runtime.actions import screenshot as SS
        with patch.object(SS.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=0)
            ok = SS.take_screenshot_to_clipboard()
        self.assertTrue(ok)
        cmd = run.call_args.args[0]
        self.assertIn("screencapture", cmd[0])
        self.assertIn("-c", cmd)


# =========================================================
# 5. bare parenless layout words (drop-sugar)
# =========================================================

class BareLayoutSugar(unittest.TestCase):

    def test_bare_full_promotes_to_tag(self):
        cmd = _one_command('open "Messages" display(2) full')
        self.assertIn("#full", cmd.tags)
        self.assertEqual(resolve_layout(set(cmd.tags)), {"type": "full", "value": 1.0})

    def test_bare_left_promotes_to_tag(self):
        cmd = _one_command("open zoom.us left")
        self.assertIn("#left", cmd.tags)
        self.assertEqual(resolve_layout(set(cmd.tags)),
                         {"type": "left", "value": 0.5})

    def test_hash_full_still_works(self):
        cmd = _one_command('open "Messages" #full')
        self.assertIn("#full", cmd.tags)

    def test_quoted_full_is_not_promoted(self):
        # An app literally named "full" must stay an app name.
        cmd = _one_command('open "full"')
        self.assertNotIn("#full", cmd.tags)
        self.assertEqual(cmd.url, "full")

    def test_runtime_targets_not_swallowed(self):
        # `active` / `all` must still reach the runtime-target machinery.
        cmd = _one_command("hide active")
        self.assertEqual(cmd.target_keyword, "active")


# =========================================================
# 7. new(tab) / new(window) / #tab / #window
# =========================================================

class NewTabWindow(unittest.TestCase):

    def setUp(self):
        from runtime.actions.browser import wants_new_window
        self.wants = wants_new_window

    def test_explicit_function_window(self):
        self.assertTrue(self.wants(functions=(("new", "window"),)))

    def test_explicit_function_tab(self):
        self.assertFalse(self.wants(functions=(("new", "tab"),)))

    def test_tag_window(self):
        self.assertTrue(self.wants(tags={"#window"}))

    def test_tag_tab(self):
        self.assertFalse(self.wants(tags={"#tab"}))

    def test_layout_tag_implies_window(self):
        self.assertTrue(self.wants(tags={"#left(50)"}))

    def test_default_is_tab(self):
        self.assertFalse(self.wants())

    def test_explicit_tab_beats_layout_implication(self):
        # Precedence rule 1/2 beat rule 3.
        self.assertFalse(self.wants(tags={"#tab", "#left(50)"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
