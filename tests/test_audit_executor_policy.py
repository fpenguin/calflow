from __future__ import annotations

from unittest.mock import patch

import pytest

from core.parser.parser import parse
from runtime import command_executor as executor
from runtime.actions.run_result import ok_result


@pytest.fixture(autouse=True)
def no_side_effects():
    with (
        patch.object(executor.time, "sleep"),
        patch.object(executor, "record_action"),
        patch.object(executor, "notify_run_error"),
        patch.object(executor, "log"),
        patch.object(executor, "trigger_autofill"),
    ):
        yield


@pytest.mark.parametrize("url", [
    "btt://trigger_named/?trigger_name=Example", "alfred://runtrigger/example/test",
    "unknown-automation://run", "file:///tmp/example.command", "~/example.command",
])
def test_invitation_open_cannot_bypass_run_policy(url):
    commands = parse(f'+CalFlow+\nopen "{url}"').commands
    assert commands
    with patch.object(executor, "open_target") as opened:
        executor.execute_commands(commands, trust_level="trusted_domain")
    opened.assert_not_called()


def test_invitation_can_open_web_url_and_allowed_shortcut():
    commands = parse('+CalFlow+\nopen https://example.com\nopen shortcuts://run-shortcut?name=Example').commands
    with patch.object(executor, "open_target") as opened:
        executor.execute_commands(commands, trust_level="trusted_domain")
    assert opened.call_count == 2


def test_single_alias_is_expanded_and_policy_checked():
    with patch("core.resolver.resolver.TARGETS", {"@example": "btt://trigger_named/?trigger_name=Example"}):
        commands = parse('+CalFlow+\nopen @example').commands
        with patch.object(executor, "open_target") as opened:
            executor.execute_commands(commands, trust_level="trusted_domain")
        opened.assert_not_called()


def test_one_item_app_alias_opens_its_value():
    with patch("core.resolver.resolver.TARGETS", {"@example": "Notes"}):
        commands = parse('+CalFlow+\nopen @example').commands
        with patch.object(executor, "open_target") as opened:
            executor.execute_commands(commands)
        assert opened.call_args.kwargs["url"] == "Notes"


def test_denied_backend_cannot_run_result_handlers():
    with patch.object(executor, "_apply_run_handlers") as handlers:
        executor._do_run({"backend": "applescript", "run_handlers": (("error", "save", "/tmp/example"),)}, trust_level="trusted_domain")
    handlers.assert_not_called()


def test_invitation_cannot_write_handler_output_even_for_allowed_backend():
    with (
        patch.object(executor, "run_shortcut", return_value=ok_result("shortcut", "text")),
        patch.object(executor, "_write_text") as write,
    ):
        executor._do_run({"backend": "shortcut", "shortcut_name": "Example", "run_handlers": (("success", "save", "/tmp/example"),)}, trust_level="trusted_domain")
    write.assert_not_called()


@pytest.mark.parametrize("selector", ['active', 'display(2)', 'window("Notes")', 'area(0,0,10,10)', '#display(2)', '#area(0,0,10,10)'])
def test_scoped_screenshot_never_captures_full_screen(selector):
    commands = parse(f'+CalFlow+\nscreenshot {selector}').commands
    assert commands
    with patch.object(executor, "take_screenshot_to_clipboard") as capture:
        executor.execute_commands(commands)
    capture.assert_not_called()


def test_smart_executor_applies_the_same_invitation_policy():
    from runtime import executor as smart

    with patch.object(smart, "open_target") as opened, patch.object(smart, "log"):
        smart.execute_entries([{"url": "btt://trigger_named/?trigger_name=Example"}], set(), trust_level="trusted_domain")
    opened.assert_not_called()


def test_failed_open_never_autofills_the_previous_window():
    commands = parse('+CalFlow+\nopen https://example.com #fill').commands
    with patch.object(executor, "open_target", return_value=False), patch.object(executor, "trigger_autofill") as fill:
        executor.execute_commands(commands)
    fill.assert_not_called()


def test_command_limit_is_enforced_even_with_non_strict_validation():
    commands = parse('+CalFlow+\nwait 0\nwait 0\nwait 0').commands
    with patch.object(executor, "PLUS_MAX_COMMANDS", 2, create=True), patch.object(executor, "_dispatch") as dispatch:
        executor.execute_commands(commands)
    assert dispatch.call_count <= 2
