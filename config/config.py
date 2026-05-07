"""
CalFlow Internal Configuration (v2.0)

DO NOT EDIT unless developing CalFlow itself.
"""

from __future__ import annotations

from pathlib import Path
import os

# =========================================================
# 🧠 APP
# =========================================================

APP_NAME = "CalFlow"
APP_VERSION = "1.1"


# =========================================================
# 📁 ROOT PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
SECRETS_DIR = BASE_DIR / "secrets"

CONFIG_DIR = BASE_DIR / "config"


# =========================================================
# 🔐 SECRETS
# =========================================================

TOKEN_PATH = SECRETS_DIR / "token.json"
CREDENTIALS_PATH = SECRETS_DIR / "credentials.json"


# =========================================================
# 📊 DATA FILES
# =========================================================

CALENDARS_PATH = DATA_DIR / "calendars.json"
DAEMON_PATH = DATA_DIR / "daemon.json"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "run.log"


# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
SECRETS_DIR.mkdir(exist_ok=True)


# =========================================================
# 🌐 GOOGLE CALENDAR
# =========================================================

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly"
]

DEFAULT_CALENDAR_ID = "primary"


# =========================================================
# ⏱️ TIMING LIMITS (SYSTEM)
# =========================================================

POLL_INTERVAL_SECONDS = 60

MIN_LOOKAHEAD_SECONDS = 30
MAX_LOOKAHEAD_SECONDS = 3600


# =========================================================
# ⚙️ EXECUTION LIMITS
# =========================================================

MAX_REPEAT = 100

MAX_SPEED_SECONDS = 60
MAX_INTERVAL_SECONDS = 60
MAX_TIMEOUT_SECONDS = 60
MAX_WAIT_SECONDS = 3600


# =========================================================
# 🪟 WINDOW SAFETY
# =========================================================

MIN_WINDOW_WIDTH = 200
MIN_WINDOW_HEIGHT = 200


# =========================================================
# 🖥️ PLATFORM
# =========================================================

IS_MAC = os.name == "posix"


# =========================================================
# 🚧 FEATURE FLAGS
# =========================================================

FEATURE_FLAGS = {
    "ENABLE_PLUS_MODE": False,
}


# =========================================================
# 🔧 HELPERS
# =========================================================

def clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))