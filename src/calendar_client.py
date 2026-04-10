import os
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from settings import FETCH_WINDOW_HOURS
from utils import log

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

TOKEN_PATH = "secrets/token.json"
CREDENTIALS_PATH = "secrets/credentials.json"


def build_service():
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        log("🔄 Refreshing expired token")
        creds.refresh(Request())

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    elif not creds or not creds.valid:
        if not os.path.exists(CREDENTIALS_PATH):
            raise RuntimeError("credentials.json not found. Run setup first.")

        log("🔐 Starting OAuth flow")

        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_PATH,
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        os.makedirs("secrets", exist_ok=True)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_upcoming_events(service, calendar_id="primary"):
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=FETCH_WINDOW_HOURS)

    log(f"📅 [{calendar_id}] Fetching events from {now} → {future}")

    try:
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=future.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])
    except Exception as e:
        log(f"❌ [{calendar_id}] Failed to fetch events: {e}")
        return []

    result = []

    for e in events:
        start = e.get("start", {})

        if "dateTime" not in start:
            continue

        try:
            summary = e.get("summary", "")
            description = e.get("description", "")
            location = e.get("location", "")

            text = "\n".join(filter(None, [description, location]))

            result.append({
                "id": e["id"],
                "calendar_id": calendar_id,
                "title": summary,
                "text": text,
                "start": dateparser.parse(start["dateTime"])
            })

        except Exception as err:
            log(f"⚠️ [{calendar_id}] Failed to parse event: {err}")

    log(f"✅ [{calendar_id}] Loaded {len(result)} events")

    return result