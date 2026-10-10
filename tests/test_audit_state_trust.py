"""v1.5.5 audit regressions: synthetic calendars and temporary persistence only."""

from __future__ import annotations

import fcntl
import importlib
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unmocked external IO")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with patch.object(Path, "mkdir"):
        config = importlib.import_module("config.config")
    data = tmp_path / "data"
    data.mkdir()
    for key, value in {
        "BASE_DIR": tmp_path, "DATA_DIR": data, "SECRETS_DIR": tmp_path / "unused",
        "STATE_PATH": data / "state.json", "TOKEN_PATH": tmp_path / "unused-token.json",
        "CREDENTIALS_PATH": tmp_path / "unused-credentials.json",
    }.items():
        monkeypatch.setattr(config, key, value)

    modules = {
        "main": "cli.main", "trust": "core.event_trust",
        "settings": "core.settings_reader", "targets": "core.targets_reader",
        "state": "state.state_manager", "calendar": "infra.calendar.calendar_client",
        "cache": "state.popover_cache", "recipes": "core.recipes",
    }
    result = SimpleNamespace(root=tmp_path, data=data)
    for name, module_name in modules.items():
        module = importlib.import_module(module_name)
        setattr(result, name, module)
        if hasattr(module, "log"):
            monkeypatch.setattr(module, "log", Mock())
    for module in (result.settings, result.targets):
        monkeypatch.setattr(module, "DATA_DIR", data)
        monkeypatch.setattr(module, "SETTINGS_PATH", tmp_path / "settings.py")
        monkeypatch.setattr(module, "DEFAULT_SETTINGS_PATH", tmp_path / "settings.defaults.py")
    for module, fields in (
        (result.settings, {"USER_SETTINGS_PATH": "settings.json", "USER_SETTINGS_BACKUP_PATH": "settings.bak"}),
        (result.targets, {"USER_TARGETS_PATH": "targets.json", "USER_TARGETS_BACKUP_PATH": "targets.bak"}),
        (result.state, {"STATE_PATH": "state.json"}),
        (result.cache, {"POPOVER_CACHE_PATH": "popover.json"}),
        (result.recipes, {"MY_RECIPES_PATH": "recipes.json"}),
    ):
        for name, filename in fields.items():
            monkeypatch.setattr(module, name, data / filename)
    monkeypatch.setattr(result.main, "DATA_DIR", data)
    monkeypatch.setattr(result.main, "DEBUG", False)
    monkeypatch.setattr(result.main, "build_service", forbidden)
    monkeypatch.setattr(result.calendar, "build_service", forbidden)
    monkeypatch.setattr(result.main, "_google_account_label", forbidden)
    monkeypatch.setattr(result.main, "get_selected_calendars", lambda: ["primary"])
    monkeypatch.setattr(result.main, "execute_entries", Mock())
    monkeypatch.setattr(result.main, "execute_commands", Mock())
    monkeypatch.setattr(result.trust, "ALLOW_SELF_AUTHORED_EVENTS", True)
    monkeypatch.setattr(result.trust, "TRUSTED_INVITE_EMAILS", set())
    monkeypatch.setattr(result.trust, "TRUSTED_INVITE_DOMAINS", set())
    return result


@pytest.mark.parametrize("calendar_id", ["other@example.com", "shared@group.calendar.google.com"])
@pytest.mark.parametrize("self_flag", [False, True])
def test_shared_calendar_is_not_self(isolated, calendar_id, self_flag):
    event = {"calendar_id": calendar_id, "organizer_email": calendar_id,
             "organizer_self": self_flag, "organizer": {"email": calendar_id, "self": self_flag}}
    assert not isolated.trust.classify_event_trust(event).trusted
    assert not isolated.trust.classify_event_trust(event, owner_email="me@example.com").trusted


@pytest.mark.parametrize("actor", ["creator", "organizer"])
@pytest.mark.parametrize("calendar_id", ["primary", "me@example.com"])
def test_self_flags_require_independently_known_primary(isolated, actor, calendar_id):
    event = {"calendar_id": calendar_id, f"{actor}_self": True}
    assert not isolated.trust.classify_event_trust(event).trusted
    assert isolated.trust.classify_event_trust(event, owner_email="me@example.com").level == "self"


def test_actual_owner_can_author_on_shared_calendar(isolated):
    event = {"calendar_id": "other@example.com", "creator_email": "me@example.com"}
    assert isolated.trust.classify_event_trust(event, owner_email="me@example.com").level == "self"


def test_primary_self_flags_honor_opt_out_and_boolean_type(isolated, monkeypatch):
    event = {"calendar_id": "primary", "creator_self": "true"}
    assert not isolated.trust.classify_event_trust(event, owner_email="me@example.com").trusted
    event["creator_self"] = True
    monkeypatch.setattr(isolated.trust, "ALLOW_SELF_AUTHORED_EVENTS", False)
    assert not isolated.trust.classify_event_trust(event, owner_email="me@example.com").trusted


def test_owner_identity_comes_from_primary_api_not_account_label(isolated):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.return_value = {"id": "me@example.com"}
    assert isolated.main._owner_email_hint(service) == "me@example.com"
    service.calendars.return_value.get.assert_called_once_with(calendarId="primary")


def test_owner_metadata_failure_fails_closed(isolated):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.side_effect = RuntimeError("offline")
    assert isolated.main._owner_email_hint(service) is None


@pytest.mark.parametrize("manual", [False, True])
def test_shared_self_flags_cannot_reach_executor(isolated, monkeypatch, capsys, manual):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.return_value = {"id": "me@example.com"}
    raw = _raw_event("test")
    raw["creator"] = {"email": "other@example.com", "self": True}
    raw["organizer"] = {"email": "other@example.com", "self": True}
    service.events.return_value.list.return_value.execute.return_value = {"items": [raw]}
    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    monkeypatch.setattr(isolated.main, "get_selected_calendars", lambda: ["other@example.com"])
    if manual:
        isolated.main.run_event_by_id("test")
        assert json.loads(capsys.readouterr().out)["error"] == "untrusted event source"
    else:
        isolated.main.main()
    isolated.main.execute_entries.assert_not_called()
    isolated.main.execute_commands.assert_not_called()


@pytest.mark.parametrize("manual", [False, True])
def test_primary_identity_failure_denies_self_execution(isolated, monkeypatch, capsys, manual):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.side_effect = RuntimeError("offline")
    service.events.return_value.list.return_value.execute.return_value = {"items": [_raw_event("test")]}
    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    if manual:
        isolated.main.run_event_by_id("test")
        assert json.loads(capsys.readouterr().out)["error"] == "untrusted event source"
    else:
        isolated.main.main()
    isolated.main.execute_entries.assert_not_called()
    isolated.main.execute_commands.assert_not_called()


def test_trust_rejection_does_not_log_event_content(isolated):
    isolated.main._event_trust_or_log({"title": "Standup", "organizer_email": "other@example.com"})
    logged = " ".join(call.args[0] for call in isolated.main.log.call_args_list)
    assert "Standup" not in logged and "other@example.com" not in logged


def test_interactive_candidate_fetch_failure_is_bounded(isolated, monkeypatch):
    monkeypatch.setattr(isolated.main, "build_service", Mock(return_value=object()))
    monkeypatch.setattr(isolated.main, "get_upcoming_events", Mock(side_effect=RuntimeError("offline")))
    assert isolated.main._list_test_candidates() == []


def _raw_event(event_id):
    return {"id": event_id, "summary": "Standup", "description": "https://example.com",
            "start": {"dateTime": datetime.now(timezone.utc).isoformat()},
            "creator": {"email": "me@example.com", "self": True},
            "organizer": {"email": "me@example.com", "self": False}}


@pytest.mark.parametrize("name", ["get_upcoming_events", "get_recent_events"])
def test_fetch_all_pages_and_preserve_self_flags(isolated, name):
    service = Mock()
    service.events.return_value.list.return_value.execute.side_effect = [
        {"items": [_raw_event("one")], "nextPageToken": "next"},
        {"items": [_raw_event("two")]},
    ]
    events = getattr(isolated.calendar, name)(service, "primary")
    assert [event["id"] for event in events] == ["one", "two"]
    assert events[0]["creator_self"] is True
    assert events[0]["organizer_self"] is False
    calls = service.events.return_value.list.call_args_list
    assert calls[1].kwargs["pageToken"] == "next"
    assert calls[0].kwargs["timeMin"] == calls[1].kwargs["timeMin"]


@pytest.mark.parametrize("name", ["get_upcoming_events", "get_recent_events"])
def test_later_page_failure_is_not_partial_success(isolated, name):
    service = Mock()
    service.events.return_value.list.return_value.execute.side_effect = [
        {"items": [_raw_event("one")], "nextPageToken": "next"}, RuntimeError("offline"),
    ]
    with pytest.raises(RuntimeError):
        getattr(isolated.calendar, name)(service, "primary")


@pytest.mark.parametrize("failed_query", [0, 1, 2])
def test_api_error_preserves_last_good_feed(isolated, monkeypatch, failed_query):
    isolated.cache.save_cache({"status": {}, "stats": {},
                              "upcoming": {"events": [{"id": "cached"}]},
                              "missed": {"events": []}})
    service = Mock()
    responses = [{"items": []}, {"items": []}, {"items": []}]
    responses[failed_query] = RuntimeError("offline")
    service.events.return_value.list.return_value.execute.side_effect = responses
    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    monkeypatch.setattr(isolated.main, "_daemon_state", lambda: {"loaded": False})
    monkeypatch.setattr("state.stats_store.snapshot", lambda: {})
    payload = isolated.main.collect_popover_feed()
    assert payload["stale"] is True
    assert payload["google_error"]
    assert isolated.cache.load_cache()["upcoming"]["events"] == [{"id": "cached"}]


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("level", ["self", "trusted_email"])
def test_smart_execution_receives_actual_trust(isolated, monkeypatch, capsys, manual, level):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.return_value = {"id": "me@example.com"}
    actor = "me@example.com" if level == "self" else "bot@example.net"
    monkeypatch.setattr(isolated.trust, "TRUSTED_INVITE_EMAILS", {"bot@example.net"})
    event = {"id": "test", "calendar_id": "primary", "creator_email": actor,
             "title": "Standup", "text": "https://example.com", "start": datetime.now(timezone.utc)}
    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    monkeypatch.setattr(isolated.main, "get_upcoming_events", lambda *a, **kw: [event])
    if manual:
        isolated.main.run_event_by_id("test")
        assert json.loads(capsys.readouterr().out)["success"]
    else:
        isolated.main.main()
    assert isolated.main.execute_entries.call_args.kwargs["trust_level"] == level
    service.calendars.return_value.get.assert_called_once_with(calendarId="primary")


def test_run_now_fetch_failure_returns_json(isolated, monkeypatch, capsys):
    monkeypatch.setattr(isolated.main, "build_service", Mock(return_value=object()))
    monkeypatch.setattr(isolated.main, "get_upcoming_events", Mock(side_effect=RuntimeError("offline")))
    isolated.main.run_event_by_id("test")
    payload = json.loads(capsys.readouterr().out)
    assert not payload["success"] and payload["error"]
    isolated.main.execute_entries.assert_not_called()


def test_daemon_fetch_failure_does_not_drop_other_calendars(isolated, monkeypatch):
    service = Mock()
    service.calendars.return_value.get.return_value.execute.return_value = {"id": "me@example.com"}
    event = {"id": "test", "calendar_id": "primary", "creator_email": "me@example.com",
             "title": "Standup", "text": "https://example.com", "start": datetime.now(timezone.utc)}
    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    monkeypatch.setattr(isolated.main, "get_selected_calendars", lambda: ["broken", "primary"])
    monkeypatch.setattr(isolated.main, "get_upcoming_events", Mock(side_effect=[RuntimeError("offline"), [event]]))
    isolated.main.main()
    isolated.main.execute_entries.assert_called_once()


def _migration_files(isolated, *, extra_live="", extra_default=""):
    live = isolated.settings.SETTINGS_PATH
    defaults = isolated.settings.DEFAULT_SETTINGS_PATH
    live.write_text("FETCH_WINDOW_HOURS = 8\nTARGETS = {'@custom': 'Notes'}\n" + extra_live)
    defaults.write_text("FETCH_WINDOW_HOURS = 2\nTARGETS = {'@safari': 'Safari'}\n" + extra_default)
    return live, defaults


def test_combined_migration_preserves_aliases_before_restore(isolated, capsys):
    live, defaults = _migration_files(isolated)
    isolated.main.migrate_settings_command()
    assert json.loads(capsys.readouterr().out)["ok"]
    assert isolated.targets.load_user_targets() == {"@custom": "Notes"}
    assert isolated.settings.load_user_overrides()["FETCH_WINDOW_HOURS"] == 8
    assert live.read_text() == defaults.read_text()


@pytest.mark.parametrize("customization", [
    "ALLOW_RUN_BACKENDS_SELF = {'shortcut'}\n",
    "TRUSTED_INVITE_EMAILS = {'bot@example.net'}\n",
    "BLACKLIST_REGEX = ['blocked']\n",
    "def custom_policy():\n    return False\n",
])
def test_migration_aborts_for_unpreservable_customizations(isolated, capsys, customization):
    live, _ = _migration_files(isolated, extra_live=customization)
    original = live.read_bytes()
    isolated.main.migrate_settings_command()
    assert not json.loads(capsys.readouterr().out)["ok"]
    assert live.read_bytes() == original
    assert not isolated.settings.USER_SETTINGS_PATH.exists()
    assert not isolated.targets.USER_TARGETS_PATH.exists()


def test_migration_aborts_when_target_write_fails(isolated, monkeypatch):
    live, _ = _migration_files(isolated)
    original = live.read_bytes()
    monkeypatch.setattr(isolated.targets, "save_user_targets", Mock(side_effect=PermissionError("denied")))
    result = isolated.settings.migrate_settings_to_sidecars()
    assert not result["ok"]
    assert live.read_bytes() == original


def test_migration_does_not_overwrite_conflicting_targets_sidecar(isolated):
    live, _ = _migration_files(isolated)
    original = live.read_bytes()
    isolated.targets.save_user_targets({"@current": "Safari"})
    result = isolated.settings.migrate_settings_to_sidecars()
    assert not result["ok"]
    assert live.read_bytes() == original
    assert isolated.targets.load_user_targets() == {"@current": "Safari"}


def test_migration_parse_failure_does_not_report_success(isolated):
    live, _ = _migration_files(isolated)
    live.write_text("FETCH_WINDOW_HOURS =\n")
    assert not isolated.settings.migrate_settings_to_sidecars()["ok"]
    assert live.read_text() == "FETCH_WINDOW_HOURS =\n"


def test_migration_rejects_changed_security_values_not_just_new_keys(isolated):
    live, _ = _migration_files(
        isolated, extra_live="ALLOW_RUN_BACKENDS_SELF = {'shortcut'}\n",
        extra_default="ALLOW_RUN_BACKENDS_SELF = {'shortcut', 'applescript'}\n",
    )
    original = live.read_bytes()
    assert not isolated.settings.migrate_settings_to_sidecars()["ok"]
    assert live.read_bytes() == original


def test_migration_requires_source_backup_before_restore(isolated, monkeypatch):
    live, _ = _migration_files(isolated)
    original = live.read_bytes()
    monkeypatch.setattr(isolated.settings.shutil, "copyfile", Mock(side_effect=PermissionError("denied")))
    assert not isolated.settings.migrate_settings_to_sidecars()["ok"]
    assert live.read_bytes() == original


def test_alias_only_migration_restores_after_preservation(isolated):
    live, defaults = _migration_files(isolated)
    live.write_text("FETCH_WINDOW_HOURS = 2\nTARGETS = {'@custom': 'Notes'}\n")
    assert isolated.settings.migrate_settings_to_sidecars()["ok"]
    assert isolated.targets.load_user_targets() == {"@custom": "Notes"}
    assert live.read_text() == defaults.read_text()


def test_state_stale_snapshots_merge_without_rewinding_timestamps(isolated):
    now = datetime.now(timezone.utc)
    first = {"one": (now - timedelta(minutes=1)).isoformat()}
    second = {"two": now.isoformat(), "one": now.isoformat()}
    isolated.state.save_state(second)
    isolated.state.save_state(first)
    assert isolated.state.load_state() == second


def test_state_concurrent_saves_keep_all_completion_keys(isolated):
    now = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(isolated.state.save_state, [{str(i): now} for i in range(16)]))
    assert isolated.state.load_state() == {str(i): now for i in range(16)}


def test_state_save_respects_shared_file_lock(isolated):
    entered = Event()
    now = datetime.now(timezone.utc).isoformat()

    def save():
        entered.set()
        isolated.state.save_state({"one": now})

    with open(str(isolated.state.STATE_PATH) + ".lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(save)
            try:
                assert entered.wait(timeout=2)
                assert not future.done()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            future.result(timeout=2)
    assert isolated.state.load_state() == {"one": now}


def test_run_now_completion_survives_daemon_snapshot(isolated, monkeypatch, capsys):
    now = datetime.now(timezone.utc)
    service = Mock()
    service.calendars.return_value.get.return_value.execute.return_value = {"id": "me@example.com"}
    event = {"id": "manual", "calendar_id": "primary", "creator_email": "me@example.com",
             "title": "Standup", "text": "https://example.com", "start": now + timedelta(hours=1)}
    daemon_event = {**event, "id": "daemon", "start": now}

    def interleave(**kwargs):
        with patch.object(isolated.main, "get_upcoming_events", return_value=[event]), \
                patch.object(isolated.main, "execute_entries", Mock()):
            isolated.main.run_event_by_id("manual")
        assert json.loads(capsys.readouterr().out)["success"]

    monkeypatch.setattr(isolated.main, "build_service", lambda: service)
    monkeypatch.setattr(isolated.main, "get_upcoming_events", Mock(return_value=[daemon_event]))
    monkeypatch.setattr(isolated.main, "execute_entries", interleave)
    isolated.main.main()
    assert set(isolated.state.load_state()) == {
        f"manual_{event['start'].isoformat()}", f"daemon_{now.isoformat()}",
    }


def test_state_merge_still_prunes_and_caps(isolated, monkeypatch):
    monkeypatch.setattr(isolated.state, "MAX_STATE_ENTRIES", 2)
    now = datetime.now(timezone.utc)
    isolated.state.save_state({"old": (now - timedelta(days=100)).isoformat(),
                               "first": (now - timedelta(minutes=1)).isoformat()})
    isolated.state.save_state({"second": now.isoformat(), "third": (now + timedelta(seconds=1)).isoformat()})
    assert set(isolated.state.load_state()) == {"second", "third"}


@pytest.mark.parametrize("delete", [False, True])
def test_recipe_write_failure_is_reported(isolated, monkeypatch, delete):
    recipe = isolated.recipes.save_my_recipe({"body": "https://example.com"})
    monkeypatch.setattr(isolated.recipes.os, "replace", Mock(side_effect=PermissionError("denied")))
    if delete:
        result = isolated.recipes.delete_my_recipe(recipe["id"])
    else:
        result = isolated.recipes.save_my_recipe({"body": "https://example.com/new"})
    assert not result["ok"]
    assert len(isolated.recipes.list_my_recipes()) == 1
