"""
CalFlow Google Calendar Client (v2.0).

Salvaged from v1.0 (working module-level surface).

Public API:
    build_service()         → authenticated googleapiclient service
    get_upcoming_events(svc, calendar_id="primary") → list[dict]

Each event dict:
    {
        "id":          <google event id>,
        "calendar_id": <calendar id this came from>,
        "title":       <summary>,
        "text":        <description + location, joined>,
        "start":       <datetime>,
    }

Design:
- module-level functions (no class wrapper) — direct, testable
- token refresh + first-time OAuth handled inline
- query failures raise CalendarFetchError, distinct from an empty calendar
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'CalendarFetchError',
    'build_service',
    'get_primary_account_email',
    'get_recent_events',
    'get_upcoming_events',
    'next_event_across_calendars',
]

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dateutil import parser as dateparser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.config import (
    CREDENTIALS_PATH,
    GOOGLE_SCOPES,
    TOKEN_PATH,
)
from config.settings import FETCH_WINDOW_HOURS
from core.utils import log
from infra.calendar.normalize import normalize_description


class CalendarFetchError(RuntimeError):
    """A calendar query failed; callers must not treat this as an empty feed."""


def get_primary_account_email(service: Any) -> str | None:
    """Resolve the signed-in account independently of the selected calendars."""
    try:
        metadata = service.calendars().get(calendarId="primary").execute()
        email = metadata.get("id")
        if isinstance(email, str) and "@" in email:
            return email.strip().lower()
    except Exception as exc:
        log(f"[WARN] Primary calendar identity unavailable ({type(exc).__name__})")
    return None


def _list_event_items(service, calendar_id: str, *, time_min: str, time_max: str) -> list[dict[str, Any]]:
    params = {
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    items: list[dict[str, Any]] = []
    seen_tokens = set()
    try:
        while True:
            page = service.events().list(**params).execute()
            batch = page.get("items", [])
            if not isinstance(batch, list):
                raise ValueError("Invalid event page")
            items.extend(batch)
            token = page.get("nextPageToken")
            if not token:
                return items
            if not isinstance(token, str) or token in seen_tokens:
                raise ValueError("Invalid pagination token")
            seen_tokens.add(token)
            params["pageToken"] = token
    except Exception as exc:
        # Exception text can contain request URLs or event content.
        message = f"Calendar event query failed ({type(exc).__name__})"
        log(f"[ERROR] {message}")
        raise CalendarFetchError(message) from exc


# =========================================================
# 🔐 SERVICE
# =========================================================

def build_service():
    """
    Return an authenticated Google Calendar API service.

    Flow:
        1. load existing token (if any)
        2. refresh if expired
        3. otherwise run OAuth flow (requires credentials.json)
        4. persist refreshed/new token

    Raises:
        RuntimeError if credentials.json is missing on first-time login.
    """
    creds: Optional[Credentials] = None
    token_path = Path(TOKEN_PATH)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        log("[INFO] Refreshing Google connection...")
        creds.refresh(Request())
        log("[INFO] Google connection verified")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    elif creds and creds.valid:
        log("[INFO] Google connection verified")

    # First-time login
    else:
        if not Path(CREDENTIALS_PATH).exists():
            raise RuntimeError(
                f"credentials.json not found at {CREDENTIALS_PATH}. "
                "Run: python3 -m cli.main setup"
            )

        log("[INFO] Connecting to Google...")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_PATH), GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        log("[INFO] Google connection verified")

    return build("calendar", "v3", credentials=creds)


# =========================================================
# 📥 EVENT FETCH
# =========================================================

def get_upcoming_events(
    service,
    calendar_id: str = "primary",
    *,
    hours: Optional[int] = None,
) -> List[Dict]:
    """
    Fetch events from `calendar_id` whose start falls inside the
    next `hours` window (defaults to `FETCH_WINDOW_HOURS`).

    The `hours` override exists so the daemon can keep its tight
    2-hour processing window while UI surfaces (status dashboard,
    menubar app) can look further ahead without changing settings.

    Returns:
        List of normalized event dicts (see module docstring).
        Raises CalendarFetchError on API failure, including later pages.
    """
    window_hours = hours if hours is not None else FETCH_WINDOW_HOURS
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=window_hours)

    log(f"[INFO] [{calendar_id}] Checking upcoming events")

    items = _list_event_items(
        service, calendar_id, time_min=now.isoformat(), time_max=future.isoformat(),
    )

    out: List[Dict] = []
    for ev in items:
        start = ev.get("start", {})
        if "dateTime" not in start:
            # All-day events skipped (no precise trigger time).
            continue

        try:
            description = ev.get("description", "") or ""
            location = ev.get("location", "") or ""
            # Google Calendar returns the description with HTML markup
            # whenever the user pasted from a rich-text source (chat,
            # doc, browser auto-link). Normalize so the parser sees
            # clean plain text with real newlines.
            description = normalize_description(description)
            text = "\n".join(filter(None, [description, location]))
            out.append({
                "id":          ev["id"],
                "calendar_id": calendar_id,
                "title":       ev.get("summary", ""),
                "text":        text,
                "start":       dateparser.parse(start["dateTime"]),
                "event_url":   ev.get("htmlLink", ""),
                "creator_email":   _actor_email(ev.get("creator")),
                "organizer_email": _actor_email(ev.get("organizer")),
                "creator_self":    _actor_self(ev.get("creator")),
                "organizer_self":  _actor_self(ev.get("organizer")),
            })
        except Exception as exc:
            log(f"[WARN] [{calendar_id}] Failed to parse event: {exc}")

    log(f"[INFO] [{calendar_id}] Loaded {len(out)} events")
    return out


# =========================================================
# 🕒 RECENT (BACKWARD) FETCH — menubar missed-events pane
# =========================================================
#
# Mirror of `get_upcoming_events` but pointed BACKWARDS in time.
# Used by:
#   - `cli.main missed --json`              (menubar feed)
#   - `cli/menubar.py` "Missed · last 12 h" pane
#
# Rationale: the daemon's trigger window is ~10½ minutes wide. If the
# laptop sleeps across the entire window, the event is silently skipped.
# The menubar surfaces these so the user can run them on demand.
# Auto-firing on wake violates the principle of least surprise (a
# 9 AM standup is irrelevant by 10 AM); the user picks. See
# `_workspace/specs/v1.1.18-missed-events-pane.md`.

def get_recent_events(
    service,
    calendar_id: str = "primary",
    *,
    hours: int = 12,
) -> List[Dict]:
    """
    Fetch events from `calendar_id` whose START fell inside the last
    `hours` hours (default 12 — long enough to cover overnight sleep,
    short enough that the list doesn't become noise after a long
    weekend).

    The shape of returned dicts is identical to `get_upcoming_events`
    so downstream consumers (parser, mode-detection, the menubar JS)
    can treat both feeds uniformly.

    Returns:
        List[Dict]: events sorted ASCENDING by start (oldest first),
        which the menubar reverses for display (most recent at top).

    Raises CalendarFetchError on API failure, including later pages.
    """
    if hours <= 0:
        return []
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=hours)

    log(f"[INFO] [{calendar_id}] Checking recent events (last {hours}h)")

    items = _list_event_items(
        service, calendar_id, time_min=past.isoformat(), time_max=now.isoformat(),
    )

    out: List[Dict] = []
    for ev in items:
        start = ev.get("start", {})
        if "dateTime" not in start:
            continue  # all-day events skipped — no precise trigger time
        try:
            description = ev.get("description", "") or ""
            location = ev.get("location", "") or ""
            description = normalize_description(description)
            text = "\n".join(filter(None, [description, location]))
            out.append({
                "id":          ev["id"],
                "calendar_id": calendar_id,
                "title":       ev.get("summary", ""),
                "text":        text,
                "start":       dateparser.parse(start["dateTime"]),
                "event_url":   ev.get("htmlLink", ""),
                "creator_email":   _actor_email(ev.get("creator")),
                "organizer_email": _actor_email(ev.get("organizer")),
                "creator_self":    _actor_self(ev.get("creator")),
                "organizer_self":  _actor_self(ev.get("organizer")),
            })
        except Exception as exc:
            log(f"[WARN] [{calendar_id}] Failed to parse recent event: {exc}")

    log(f"[INFO] [{calendar_id}] Loaded {len(out)} recent events")
    return out


def _actor_email(actor) -> str:
    if isinstance(actor, dict):
        return actor.get("email", "") or ""
    return ""


def _actor_self(actor) -> bool:
    return isinstance(actor, dict) and actor.get("self") is True


# =========================================================
# 🔭 AGGREGATED LOOKUP (status dashboard helper)
# =========================================================

def next_event_across_calendars(
    service,
    calendar_ids: List[str],
    *,
    hours: Optional[int] = None,
) -> Optional[Dict]:
    """
    Return the soonest upcoming event across all `calendar_ids`
    within the next `hours` window (defaults to FETCH_WINDOW_HOURS),
    or None if no events are in the window.

    Each calendar is queried independently; the result with the
    smallest `start` (whose start is in the future) wins.
    """
    soonest: Optional[Dict] = None
    now = datetime.now(timezone.utc)

    for cal_id in calendar_ids:
        for ev in get_upcoming_events(service, cal_id, hours=hours):
            start = ev.get("start")
            if not start:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start < now:
                continue
            if soonest is None or start < soonest["start"]:
                soonest = {**ev, "start": start}

    return soonest
