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
- never raises; all failures logged and an empty list returned
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

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

def get_upcoming_events(service, calendar_id: str = "primary") -> List[Dict]:
    """
    Fetch events from `calendar_id` whose start falls inside the
    next `FETCH_WINDOW_HOURS` window.

    Returns:
        List of normalized event dicts (see module docstring).
        Returns [] on any API failure (logged).
    """
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=FETCH_WINDOW_HOURS)

    log(f"[INFO] [{calendar_id}] Checking upcoming events")

    try:
        items = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now.isoformat(),
                timeMax=future.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        )
    except Exception as exc:
        log(f"[ERROR] [{calendar_id}] Failed to fetch events: {exc}")
        return []

    out: List[Dict] = []
    for ev in items:
        start = ev.get("start", {})
        if "dateTime" not in start:
            # All-day events skipped (no precise trigger time).
            continue

        try:
            description = ev.get("description", "") or ""
            location = ev.get("location", "") or ""
            text = "\n".join(filter(None, [description, location]))
            out.append({
                "id":          ev["id"],
                "calendar_id": calendar_id,
                "title":       ev.get("summary", ""),
                "text":        text,
                "start":       dateparser.parse(start["dateTime"]),
            })
        except Exception as exc:
            log(f"[WARN] [{calendar_id}] Failed to parse event: {exc}")

    log(f"[INFO] [{calendar_id}] Loaded {len(out)} events")
    return out


# =========================================================
# 🔭 AGGREGATED LOOKUP (status dashboard helper)
# =========================================================

def next_event_across_calendars(service, calendar_ids: List[str]) -> Optional[Dict]:
    """
    Return the soonest upcoming event across all `calendar_ids`,
    or None if there are no upcoming events in the lookup window.

    Each calendar is queried independently; the result with the
    smallest `start` (whose start is in the future) wins.
    """
    soonest: Optional[Dict] = None
    now = datetime.now(timezone.utc)

    for cal_id in calendar_ids:
        for ev in get_upcoming_events(service, cal_id):
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
