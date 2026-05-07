"""
Daemon main-loop integration smoke tests (v1.1.24).

These tests run the full `cli.main.main()` pipeline end-to-end with
the IO boundaries mocked:

    fetch (Google Calendar API) ─┐
    selected calendars list ─────┼──► main() ──► open_target / execute
    state I/O ───────────────────┘                 (mocked, captured)

They exist to catch "glue" bugs that unit tests can't see — like
v1.1.23, where every individual function worked correctly but the
daemon's pre-parse filter dropped title-URL events before reaching
the parser.

Each test is fast (< 100ms) and asserts on the boundary calls.

Run:
    python -m unittest tests.test_v2_daemon_smoke -v
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# `cli.main` imports google-auth via infra.calendar.calendar_client.
# When those packages aren't installed (CI sandbox, fresh clone before
# `pip install -r requirements.txt`), stub the minimum surface so
# cli.main can import. Mocked test patches replace every google call
# at the boundary anyway — the real google libs never run here.
try:
    import google.auth  # noqa: F401
except ImportError:
    import types as _types
    for _name, _mod in [
        ("google", _types.ModuleType("google")),
        ("google.auth", _types.ModuleType("google.auth")),
        ("google.auth.transport", _types.ModuleType("google.auth.transport")),
        ("google.auth.transport.requests",
            _types.ModuleType("google.auth.transport.requests")),
        ("google.oauth2", _types.ModuleType("google.oauth2")),
        ("google.oauth2.credentials",
            _types.ModuleType("google.oauth2.credentials")),
        ("google_auth_oauthlib", _types.ModuleType("google_auth_oauthlib")),
        ("google_auth_oauthlib.flow",
            _types.ModuleType("google_auth_oauthlib.flow")),
        ("googleapiclient", _types.ModuleType("googleapiclient")),
        ("googleapiclient.discovery",
            _types.ModuleType("googleapiclient.discovery")),
    ]:
        sys.modules.setdefault(_name, _mod)
    sys.modules["google.auth.transport.requests"].Request = object
    sys.modules["google.oauth2.credentials"].Credentials = object
    sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = object

    def _stub_build(*a, **kw):
        return object()
    sys.modules["googleapiclient.discovery"].build = _stub_build


class _DaemonSmokeBase(unittest.TestCase):
    """Marker class for all smoke tests (intentionally empty)."""


def _make_event(*, title: str = "", text: str = "", offset_minutes: float = 0,
                event_id: str = "evt_default") -> dict:
    """Build a fake event dict shaped like infra.calendar.calendar_client.get_upcoming_events()."""
    when = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return {
        "id":          event_id,
        "calendar_id": "test@example.com",
        "title":       title,
        "text":        text,
        "start":       when,
    }


class _DaemonHarness:
    """
    Shared mock setup for the smoke tests.

    Patches:
      cli.main.build_service           → fake service
      cli.main.get_selected_calendars  → ['test']
      cli.main.get_upcoming_events     → returns self.events
      cli.main.load_state / save_state / is_done / mark_done → in-memory
      runtime.executor.open_target     → captured into self.opens (Smart)
      runtime.command_executor.open_target → captured (Plus)
      runtime.executor.trigger_autofill → no-op (Smart)
      time.sleep                       → no-op
    """

    def __init__(self, events: list, prior_state: dict = None) -> None:
        self.events = events
        self.opens: list = []
        self.commands_run: list = []
        self.state = prior_state or {}
        self._patchers: list = []

    def __enter__(self):
        # ── Calendar IO ─────────────────────────────────────────
        self._patch("cli.main.build_service", return_value=object())
        self._patch("cli.main.get_selected_calendars", return_value=["test"])
        self._patch("cli.main.get_upcoming_events",
                    side_effect=lambda svc, cal_id, *a, **kw: list(self.events))

        # ── State (in-memory dict, no disk I/O) ────────────────
        self._patch("cli.main.load_state", return_value=self.state)
        self._patch("cli.main.save_state", side_effect=lambda *a, **kw: None)
        # is_done / mark_done are imported into cli.main as well
        # AND into runtime.command_executor (transitively). Patch
        # both so the in-memory state stays consistent.
        from state import state_manager as sm
        self._patch("cli.main.is_done", side_effect=sm.is_done)
        self._patch("cli.main.mark_done", side_effect=sm.mark_done)

        # ── Side-effect actions ────────────────────────────────
        self._patch("runtime.executor.open_target",
                    side_effect=self._capture_open)
        self._patch("runtime.command_executor.open_target",
                    side_effect=self._capture_open)
        self._patch("runtime.executor.trigger_autofill",
                    side_effect=lambda mode="fill": None)
        self._patch("runtime.command_executor.trigger_autofill",
                    side_effect=lambda mode="fill": None)
        self._patch("runtime.command_executor.take_screenshot",
                    side_effect=lambda *a, **kw: "/tmp/mock.png")
        self._patch("time.sleep", side_effect=lambda *_a, **_kw: None)

        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()
        return False

    def _patch(self, target: str, **kwargs) -> None:
        self._patchers.append(patch(target, **kwargs))

    def _capture_open(self, **kwargs) -> None:
        self.opens.append(kwargs)


class DaemonSmokeTests(_DaemonSmokeBase):
    """
    Each test boots the daemon's main() with a representative event
    set and asserts on what got captured.
    """

    # =========================================================
    # 1. v1.1.23 regression — title URL + empty body
    # =========================================================

    def test_title_url_event_with_empty_body_fires(self) -> None:
        """The bug fixed in v1.1.23: a calendar event with a URL ONLY
        in the title and an empty body must fire."""
        # `now + 0` puts the event squarely inside the trigger window.
        events = [_make_event(
            title="https://example.com",
            text="",
            offset_minutes=0,
            event_id="evt_title_only",
        )]
        with _DaemonHarness(events) as h:
            from cli.main import main
            main()

        self.assertEqual(
            len(h.opens), 1,
            f"daemon should fire 1 OPEN for the title URL; got {h.opens}"
        )
        self.assertEqual(h.opens[0]["url"], "https://example.com")

    # =========================================================
    # 2. Plus block end-to-end
    # =========================================================

    def test_plus_block_event_fires_each_open(self) -> None:
        """A `+CalFlow+` event with two OPEN commands fires both."""
        plus_block = (
            "+CalFlow+\n"
            "open https://a.com @chrome\n"
            "open https://b.com @safari\n"
        )
        events = [_make_event(
            title="Plus event",
            text=plus_block,
            offset_minutes=0,
            event_id="evt_plus",
        )]
        with _DaemonHarness(events) as h:
            from cli.main import main
            main()

        urls = [o["url"] for o in h.opens]
        self.assertIn("https://a.com", urls)
        self.assertIn("https://b.com", urls)

    # =========================================================
    # 3. is_done / dedup
    # =========================================================

    def test_already_done_event_does_not_refire(self) -> None:
        """An event whose run_key is already in state.done is silently
        skipped — no double-fire."""
        ev = _make_event(
            title="Standup",
            text="https://zoom.us/j/12345",
            offset_minutes=0,
            event_id="evt_dedup",
        )
        # Compute the same run_key the daemon uses, then prime the state
        # with it so is_done() returns True. State shape is a flat
        # `{run_key: ISO_timestamp}` dict (state/state_manager.py).
        from cli.main import _normalize_event_time
        from datetime import datetime, timezone
        run_key = f"{ev['id']}_{_normalize_event_time(ev['start']).isoformat()}"
        prior = {run_key: datetime.now(timezone.utc).isoformat()}

        with _DaemonHarness([ev], prior_state=prior) as h:
            from cli.main import main
            main()

        self.assertEqual(
            h.opens, [],
            f"already-done event should NOT fire; got {h.opens}"
        )

    # =========================================================
    # 4. Trigger window
    # =========================================================

    def test_event_outside_trigger_window_does_not_fire(self) -> None:
        """An event scheduled so far in the future that the trigger
        window hasn't opened yet must not fire."""
        # Event is 60 minutes from now → trigger = now + 60m - 5m = now + 55m
        # Window opens at now + 55m - 30s. We're way before that.
        events = [_make_event(
            title="Standup",
            text="https://zoom.us/j/12345",
            offset_minutes=60,
            event_id="evt_far_future",
        )]
        with _DaemonHarness(events) as h:
            from cli.main import main
            main()

        self.assertEqual(
            h.opens, [],
            "out-of-window event should NOT fire"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
