from __future__ import annotations

"""v1.5.6 regressions: truthful action outcomes with all native IO mocked.

Contract changes for integration: apply_layout and autofill now return bool;
disabled autofill is False (no keystroke sent). Unsupported new-window requests
fail without launching. Batch summaries must include an empty ERRORED row for
success. Old launch-count mocks must resolve a supported default browser first.
In test_audit_actions.py, test_every_launch_branch_has_a_bounded_timeout must
expect no launch for Other Browser. The default-browser nonzero/timeout tests
must mock a resolved supported browser to exercise the launcher failure path.
"""

import subprocess
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from runtime.actions import (
    app_control,
    applescript,
    autofill,
    browser,
    btt,
    notifications,
    shortcuts,
    window,
)

PRIVATE = "PRIVATE_ACTION_CONTENT"
DISPLAY = dict(index=1, name=PRIVATE, x=0, y=0, w=1440, h=900, primary=True)
MODULES = (app_control, applescript, autofill, browser, btt, notifications, shortcuts, window)


@pytest.fixture(autouse=True)
def isolated_actions(tmp_path):
    with ExitStack() as stack:
        stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("Native IO")))
        run = stack.enter_context(patch("subprocess.run", return_value=
                                      subprocess.CompletedProcess([], 0, "ok", "")))
        web = stack.enter_context(patch("webbrowser.open", return_value=True))
        stack.enter_context(patch("time.sleep"))
        stack.enter_context(patch.object(autofill, "_USER_CONFIG_PATH", tmp_path / "config.json"))
        stack.enter_context(patch.object(browser, "MAC_AVAILABLE", False))
        stack.enter_context(patch.object(window, "_DISPLAY_CACHE", None))
        logs = {module: stack.enter_context(patch.object(module, "log")) for module in MODULES}
        for module in (applescript, shortcuts, btt):
            stack.enter_context(patch.object(module, "notify_run_error"))
        yield SimpleNamespace(run=run, web=web, logs=logs)
        for logger in logs.values():
            assert PRIVATE not in str(logger.call_args_list)


@pytest.mark.parametrize("returncode, expected", [(0, True), (1, False)])
def test_autofill_returns_actual_keystroke_result(isolated_actions, returncode, expected):
    isolated_actions.run.return_value = subprocess.CompletedProcess([], returncode, PRIVATE, PRIVATE)
    with patch.object(autofill, "resolve_autofill_provider", return_value="test"), \
            patch.object(autofill, "AUTOFILL_SHORTCUTS", {"test": {"fill": {"key": "a"}}}):
        assert autofill.trigger_autofill() is expected
    assert autofill._execute_shortcut({"key": PRIVATE}, provider=PRIVATE, mode=PRIVATE) is expected


@pytest.mark.parametrize("provider, config, mode", [
    ("none", {}, "fill"), ("absent", {}, "fill"),
    ("test", {"test": {}}, "fill"), ("test", {"test": {"fill": {"key": "a"}}}, PRIVATE),
])
def test_unavailable_autofill_is_false_without_io(isolated_actions, provider, config, mode):
    with patch.object(autofill, "resolve_autofill_provider", return_value=provider), \
            patch.object(autofill, "AUTOFILL_SHORTCUTS", config):
        assert autofill.trigger_autofill(mode) is False
    isolated_actions.run.assert_not_called()


@pytest.mark.parametrize("action", [
    {"unknown": PRIVATE}, {"key_code": PRIVATE}, {"key": ""},
    {"key": "a", "modifiers": [PRIVATE]}, {"key": "a", "modifiers": [42]}, None,
])
def test_invalid_shortcut_is_false_without_io(isolated_actions, action):
    assert autofill._execute_shortcut(action, provider=PRIVATE, mode=PRIVATE) is False
    isolated_actions.run.assert_not_called()


@pytest.mark.parametrize("failure", [FileNotFoundError(PRIVATE), RuntimeError(PRIVATE),
                                      subprocess.TimeoutExpired([PRIVATE], 4)])
def test_autofill_subprocess_failure_is_false(isolated_actions, failure):
    isolated_actions.run.side_effect = failure
    assert autofill._execute_shortcut({"key": "a"}) is False


@pytest.mark.parametrize("config", [[], [PRIVATE], PRIVATE, 42])
def test_malformed_autofill_config_returns_false(isolated_actions, config):
    with patch.object(autofill, "resolve_autofill_provider", return_value="test"), \
            patch.object(autofill, "AUTOFILL_SHORTCUTS", {"test": config}):
        assert autofill.trigger_autofill() is False
    isolated_actions.run.assert_not_called()


def test_invalid_user_provider_does_not_raise():
    with patch.object(autofill, "_read_user_provider", return_value=[PRIVATE]):
        assert isinstance(autofill.resolve_autofill_provider(), str)


def test_key_code_modifiers_are_not_silently_ignored(isolated_actions):
    assert autofill._execute_shortcut({"key_code": 36, "modifiers": ["command"]}) is False
    isolated_actions.run.assert_not_called()


def test_open_propagates_requested_layout_failure():
    with patch.object(browser, "_open_url", return_value=True), \
            patch.object(browser, "_apply_layout", return_value=False) as layout:
        assert browser.open_target("https://example.com", "Safari", {"type": "full"}) is False
        layout.assert_called_once_with("Safari", {"type": "full"}, None)


def test_layout_wrapper_propagates_success_and_failure():
    for result in (True, False):
        with patch.object(window, "apply_layout", return_value=result):
            assert browser._apply_layout("Safari", {"type": "full"}) is result
    with patch.object(window, "apply_layout", side_effect=RuntimeError(PRIVATE)):
        assert browser._apply_layout("Safari", {"type": "full"}) is False


@pytest.mark.parametrize("options", [
    {"layout": {"type": "full"}}, {"display_spec": ("index", 1)},
    {"new_window": True}, {"chrome_profile": "Default"},
])
def test_unresolved_default_browser_fails_before_opening(isolated_actions, options):
    assert browser.open_target("https://example.com", **options) is False
    isolated_actions.run.assert_not_called()
    isolated_actions.web.assert_not_called()


def test_unknown_browser_new_window_is_not_best_effort_success(isolated_actions):
    assert browser.open_target("https://example.com", PRIVATE, new_window=True) is False
    isolated_actions.run.assert_not_called()


def test_file_layout_cannot_move_an_unrelated_app(isolated_actions):
    with patch.object(browser, "_apply_layout") as layout:
        assert browser.open_target("/tmp/example.pdf", "Safari", {"type": "full"}) is False
    isolated_actions.run.assert_not_called()
    layout.assert_not_called()


def test_profile_for_non_chrome_fails_before_opening(isolated_actions):
    assert browser.open_target("https://example.com", "Safari", chrome_profile="Default") is False
    isolated_actions.run.assert_not_called()


@pytest.mark.parametrize("bundle_id, app", [
    ("com.apple.Safari", "Safari"), ("com.google.Chrome", "Google Chrome"),
    ("org.mozilla.firefox", "Firefox"), ("com.brave.Browser", "Brave Browser"),
    ("com.microsoft.edgemac", "Microsoft Edge"), ("company.thebrowser.Browser", "Arc"),
])
def test_appkit_resolves_default_browser_for_window_control(isolated_actions, bundle_id, app):
    workspace, nsurl, nsbundle = Mock(), Mock(), Mock()
    nsbundle.bundleWithURL_.return_value.bundleIdentifier.return_value = bundle_id
    with patch.object(browser, "MAC_AVAILABLE", True), \
            patch.object(browser, "NSWorkspace", workspace, create=True), \
            patch.object(browser, "NSURL", nsurl, create=True), \
            patch.object(browser, "NSBundle", nsbundle, create=True), \
            patch.object(browser, "_apply_layout", return_value=True) as layout:
        assert browser.open_target("https://example.com", layout={"type": "full"},
                                   new_window=True) is True
    workspace.sharedWorkspace.return_value.URLForApplicationToOpenURL_.assert_called_once_with(
        nsurl.URLWithString_.return_value
    )
    layout.assert_called_once_with(app, {"type": "full"}, None)
    isolated_actions.run.assert_called_once()
    isolated_actions.web.assert_not_called()


@pytest.mark.parametrize("failure", [None, RuntimeError(PRIVATE), PRIVATE])
def test_failed_appkit_resolution_does_not_launch(isolated_actions, failure):
    workspace, nsurl, nsbundle = Mock(), Mock(), Mock()
    lookup = workspace.sharedWorkspace.return_value.URLForApplicationToOpenURL_
    if isinstance(failure, Exception):
        lookup.side_effect = failure
    elif failure is None:
        lookup.return_value = None
    else:
        nsbundle.bundleWithURL_.return_value.bundleIdentifier.return_value = failure
    with patch.object(browser, "MAC_AVAILABLE", True), \
            patch.object(browser, "NSWorkspace", workspace, create=True), \
            patch.object(browser, "NSURL", nsurl, create=True), \
            patch.object(browser, "NSBundle", nsbundle, create=True):
        assert browser.open_target("https://example.com", new_window=True) is False
    isolated_actions.run.assert_not_called()
    isolated_actions.web.assert_not_called()


@pytest.mark.parametrize("bounds_results, expected, attempts", [
    ([True], True, 1), ([False, True], True, 2), ([False] * 5, False, 5),
])
def test_layout_returns_bounds_outcome(bounds_results, expected, attempts):
    with patch.object(window, "enumerate_displays", return_value=[DISPLAY]), \
            patch.object(window, "set_window_bounds", side_effect=bounds_results) as bounds:
        assert window.apply_layout("Safari", {"type": "full"}) is expected
    assert bounds.call_count == attempts


@pytest.mark.parametrize("app, layout, spec, displays, expected", [
    (None, None, None, [], True), (None, {"type": "full"}, None, [], False),
    ("Safari", {"type": "full"}, None, [], False),
    ("Safari", {"type": "full"}, ("index", 2), [DISPLAY], False),
    ("Safari", {"type": PRIVATE}, None, [DISPLAY], False),
    ("Safari", {"type": "left", "value": PRIVATE}, None, [DISPLAY], False),
])
def test_layout_noop_or_unavailable_target(app, layout, spec, displays, expected):
    with patch.object(window, "enumerate_displays", return_value=displays), \
            patch.object(window, "set_window_bounds") as bounds:
        assert window.apply_layout(app, layout, spec) is expected
    bounds.assert_not_called()


@pytest.mark.parametrize("operation, changed", [
    (app_control.hide_all, "HIDDEN"), (app_control.close_all, "CLOSED"),
])
@pytest.mark.parametrize("errors, expected", [("", True), (PRIVATE, False)])
def test_batch_partial_failures_propagate(isolated_actions, operation, changed, errors, expected):
    isolated_actions.run.return_value = subprocess.CompletedProcess(
        [], 0, f"KEPT\t{PRIVATE}\n{changed}\t{PRIVATE}\nERRORED\t{errors}", ""
    )
    assert operation([PRIVATE]) is expected


@pytest.mark.parametrize("summary", ["", PRIVATE, "KEPT\t\nHIDDEN\t", "ERRORED\t"])
def test_invalid_batch_summary_is_failure(isolated_actions, summary):
    isolated_actions.run.return_value = subprocess.CompletedProcess([], 0, summary, "")
    assert app_control.hide_all() is False
    assert app_control.close_all() is False


@pytest.mark.parametrize("errors, expected", [("", True), (PRIVATE, False)])
def test_display_hide_partial_failure_propagates(isolated_actions, errors, expected):
    isolated_actions.run.return_value = subprocess.CompletedProcess(
        [], 0, f"KEPT\t{PRIVATE}\nHIDDEN\t{PRIVATE}\nERRORED\t{errors}\nDIAG\t{PRIVATE}", ""
    )
    with patch.object(window, "enumerate_displays", return_value=[DISPLAY]):
        assert window.hide_apps_on_display(1, [PRIVATE]) is expected
    script = isolated_actions.run.call_args.args[0][4]
    assert ".close(" not in script
    assert ".position = [-32000, -32000]" in script


def test_hide_geometry_errors_are_not_silently_kept():
    script = window._JXA_HIDE_ON_DISPLAY
    geometry_failure = script[script.index('uiInfo.push(ui[u].kind + ":?")'):]
    assert "errored.push" in geometry_failure.split("var cx", 1)[0]


def test_title_focus_no_match_is_an_applescript_failure(isolated_actions):
    assert app_control.focus_window_by_title("Safari", PRIVATE) is True
    script = isolated_actions.run.call_args.args[0][2]
    assert 'else\n' in script
    assert 'error "No matching window" number -1728' in script
    isolated_actions.run.return_value = subprocess.CompletedProcess([], 1, "", PRIVATE)
    assert app_control.focus_window_by_title("Safari", PRIVATE) is False


@pytest.mark.parametrize("returncode", [0, 1])
def test_run_results_preserve_detail_but_logs_do_not(isolated_actions, returncode):
    isolated_actions.run.return_value = subprocess.CompletedProcess([], returncode, PRIVATE, PRIVATE)
    for operation, args in (
        (applescript.run_applescript, (PRIVATE,)), (shortcuts.run_shortcut, (PRIVATE,)),
        (btt.trigger_named_btt, (PRIVATE,)), (btt.trigger_alfred, (PRIVATE, PRIVATE, PRIVATE)),
    ):
        result = operation(*args)
        assert result.ok is (returncode == 0)
        if operation in (applescript.run_applescript, shortcuts.run_shortcut):
            assert PRIVATE in result.result_text


def test_run_exception_details_only_go_to_direct_result(isolated_actions):
    isolated_actions.run.side_effect = subprocess.TimeoutExpired([PRIVATE], 10)
    for operation, args in (
        (applescript.run_applescript, (PRIVATE,)), (shortcuts.run_shortcut, (PRIVATE,)),
        (btt.trigger_named_btt, (PRIVATE,)), (btt.trigger_alfred, (PRIVATE, PRIVATE)),
    ):
        result = operation(*args)
        assert result.ok is False
        assert PRIVATE in result.result_text


def test_browser_parser_logs_do_not_include_content():
    browser.wants_new_window(functions=[("new", PRIVATE)])
    browser.parse_layout_tag(f"#area({PRIVATE},0,0,0)")
    browser.parse_layout_tag(f"#grid({PRIVATE})")
    browser.open_target("https://example.com", PRIVATE)
    browser.open_target(PRIVATE)
    browser.open_target("https://example.com", "Google Chrome", chrome_profile=PRIVATE)


def test_window_failure_logs_do_not_include_content(isolated_actions):
    for stdout, stderr, returncode in [(PRIVATE, PRIVATE, 1), (PRIVATE, "", 0)]:
        isolated_actions.run.return_value = subprocess.CompletedProcess([], returncode, stdout, stderr)
        assert window.set_window_bounds(PRIVATE, (0, 0, 100, 100)) is False
        assert window.enumerate_displays(force_refresh=True) == []
        with patch.object(window, "enumerate_displays", return_value=[DISPLAY]):
            assert window.hide_apps_on_display(1, [PRIVATE], only_app=PRIVATE) is False
    window.resolve_display_target(("name", PRIVATE), [DISPLAY | {"name": "other"}])
    window.resolve_display_target((PRIVATE, PRIVATE), [DISPLAY])
    window.compute_rect({"type": PRIVATE}, DISPLAY)


@pytest.mark.parametrize("response", ["{}", "null", "[1]", '[{"w": 0}]'])
def test_malformed_display_data_is_a_failed_enumeration(isolated_actions, response):
    isolated_actions.run.return_value = subprocess.CompletedProcess([], 0, response, "")
    assert window.enumerate_displays(force_refresh=True) == []


@pytest.mark.parametrize("failure", [RuntimeError(PRIVATE),
                                      subprocess.TimeoutExpired([PRIVATE], 4)])
def test_window_subprocess_exceptions_are_false(isolated_actions, failure):
    isolated_actions.run.side_effect = failure
    assert window.enumerate_displays(force_refresh=True) == []
    assert window.set_window_bounds(PRIVATE, (0, 0, 100, 100)) is False
    with patch.object(window, "enumerate_displays", return_value=[DISPLAY]):
        assert window.hide_apps_on_display(1) is False
        assert window.move_app_to_display(PRIVATE, 1) is False


def test_shortcut_failed_input_write_cleans_up(isolated_actions):
    temporary = Mock()
    temporary.__enter__ = Mock(return_value=temporary)
    temporary.__exit__ = Mock(return_value=False)
    temporary.name = "/tmp/synthetic-shortcut-input.txt"
    temporary.write.side_effect = OSError(PRIVATE)
    with patch.object(shortcuts.tempfile, "NamedTemporaryFile", return_value=temporary), \
            patch.object(shortcuts.os, "unlink") as unlink:
        assert shortcuts.run_shortcut(PRIVATE, PRIVATE).ok is False
        unlink.assert_called_once_with(temporary.name)
    isolated_actions.run.assert_not_called()


def test_notification_failure_logs_do_not_include_content(isolated_actions):
    with patch.object(notifications, "RUN_ERROR_NOTIFICATIONS", True):
        isolated_actions.run.return_value = subprocess.CompletedProcess([], 1, PRIVATE, PRIVATE)
        notifications.notify_run_error(PRIVATE, PRIVATE)
        isolated_actions.run.side_effect = RuntimeError(PRIVATE)
        notifications.notify_run_error(PRIVATE, PRIVATE)


def test_app_control_failure_logs_do_not_include_content(isolated_actions):
    for operation in (app_control.focus_app, app_control.close_app, app_control.hide_app):
        isolated_actions.run.return_value = subprocess.CompletedProcess([], 0, PRIVATE, PRIVATE)
        assert operation(PRIVATE) is True
        isolated_actions.run.return_value = subprocess.CompletedProcess([], 1, PRIVATE, PRIVATE)
        assert operation(PRIVATE) is False
    isolated_actions.run.side_effect = RuntimeError(PRIVATE)
    assert app_control.focus_app(PRIVATE) is False
    assert app_control.get_frontmost_app_name() is None
