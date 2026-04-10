from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import TOKEN_FILE, CREDENTIALS_FILE
from settings import FETCH_WINDOW_HOURS
from utils import log


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# --- Google API Service ---
def get_service():
    creds = None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        log("⚠️ No existing token found or failed to load")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("🔄 Refreshing expired token")
            creds.refresh(Request())
        else:
            log("🔐 Starting OAuth flow")
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


# --- Fetch Events ---
def get_upcoming_events():
    service = get_service()

    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=FETCH_WINDOW_HOURS)

    log(f"📅 Fetching events from {now} → {future}")

    try:
        events = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=future.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])
    except Exception as e:
        log(f"❌ Failed to fetch events: {e}")
        return []

    result = []

    for e in events:
        start = e.get("start", {})

        if "dateTime" not in start:
            continue  # skip all-day events

        try:
            summary = e.get("summary", "")
            description = e.get("description", "")
            location = e.get("location", "")

            text = "\n".join(filter(None, [description, location]))

            event_obj = {
                "id": e["id"],
                "title": summary,
                "text": text,
                "start": dateparser.parse(start["dateTime"])
            }

            result.append(event_obj)

        except Exception as err:
            log(f"⚠️ Failed to parse event: {err}")
            continue

    log(f"✅ Loaded {len(result)} events")

    return result