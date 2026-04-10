# =========================
# Calflow Configuration
# =========================
# You can safely tweak values in this file to customize behavior.


# --- Timing (WHEN Calflow runs) ---

# How far ahead to fetch events from Google Calendar
# This does NOT control when events trigger (#alert does that)
FETCH_WINDOW_HOURS = 2

# Default alert timing (seconds before event start)
DEFAULT_ALERT_SECONDS = 300  # 5 minutes

# Grace window AFTER trigger (seconds)
GRACE_SECONDS = 600  # 10 minutes

# Early tolerance (seconds)
EARLY_TOLERANCE = 30


# --- URL Handling ---

# Maximum number of URLs to open per event
MAX_URLS = 5


# --- Autofill (Login Automation) ---

# Mode:
# "manual"    → only run autofill when tag exists (#fill #submit)
# "semi-auto" → always fill ID/PW but DO NOT press Enter
# "auto"      → fill ID/PW AND press Enter
AUTOFILL_MODE = "semi-auto"


# --- Autofill Overrides ---
# Overrides global AUTOFILL_MODE on a per-event basis

NO_AUTOFILL_TAG = "#no-autofill"      # disable autofill entirely
FORCE_FILL_TAG = "#fill"              # fill credentials only (no submit)
FORCE_SUBMIT_TAG = "#submit"          # fill + press enter


# --- Autofill Timing ---

# Delay (in seconds) between opening page and interacting (base load time)
DEFAULT_DELAY = 2

# Delay (in seconds) when #slow tag is used
SLOW_DELAY = 5

# Additional buffer before triggering autofill
# Helps with JS-heavy login pages (React, SSO, etc.)
AUTOFILL_BUFFER = 0.2   # try 0.5 or 0.8 if needed

# Buffer after autofill
POST_AUTOFILL_DELAY = 0.5


# --- Password Manager for Autofill ---

# Preferred provider when in auto/semi-auto mode
# Options: "1password", "bitwarden", "default"
AUTOFILL_PROVIDER = "bitwarden"


# --- Autofill Shortcuts (Advanced) ---

# macOS keystroke definitions used for autofill
# Do NOT change unless you know what you're doing

AUTOFILL_SHORTCUTS = {
    "1password": {
        "fill": {"key": "\\\\", "modifiers": ["command"]},
        "submit": {"key_code": 36}
    },
    "bitwarden": {
        "fill": {"key": "l", "modifiers": ["command", "shift"]},
        "submit": {"key_code": 36}
    },
    "default": {
        "fill": {"key": "\\\\", "modifiers": ["command"]},
        "submit": {"key_code": 36}
    }
}



# --- Protocol Filtering ---

# Lines starting with these protocols will be ignored entirely
# These are non-browser protocols (VoIP, phone, email, etc.)
IGNORED_PROTOCOLS = [
    "sip:",
    "tel:",
    "mailto:",
    "ftp:",
]


# --- Map Handling ---

# Ignore map/navigation links (useful for mobile, not desktop workflows)
IGNORE_MAP_LINKS = True

MAP_DOMAINS = [
    "maps.google",
    "google.com/maps",
    "maps.apple.com",
    "bing.com/maps",
]

# --- URL Filtering Rules (Regex-based) ---

BLACKLIST_REGEX = [

    # --- Scheduling actions ---
    r"/cancel\w*",
    r"/reschedul\w*",

    # --- Zoom ---
    r"zoom\.us/u/",

    # --- Teams ---
    r"aka\.ms/jointeamsmeeting",
    r"teams\.microsoft\.com/meetingoptions",

    # --- Webex ---
    r"collaborationhelp\.cisco\.com",

    # --- Google Meet ---
    r"tel\.meet",

    # --- GoToWebinar ---
    r"additionalinfo\.tmpl",

    # --- Google Calendar system links ---
    r"g\.co/calendar",
    r"mail\.google\.com",
]

# --- Blacklist behavior ---

# Apply blacklist only when multiple URLs are detected
BLACKLIST_ONLY_IF_MULTIPLE = True

# --- Override Rules ---

# If True, URLs found in the event title will bypass blacklist rules
IGNORE_BLACKLIST_FOR_TITLE_URLS = True

# Force execution of a URL (bypass blacklist filtering)
FORCE_URL_TAG = "#force"

# --- Notes ---
# - Blacklist uses simple substring matching
# - Add new patterns as needed when you encounter unwanted links
# - If something important is blocked, remove or refine the pattern

# --- Browser Mapping ---

# Map hashtag → macOS app name
BROWSER_MAP = {
    "#chrome": "Google Chrome",
    "#edge": "Microsoft Edge",
    "#safari": "Safari",
    "#arc": "Arc",
    "#brave": "Brave Browser",
    "#firefox": "Firefox",
    "#opera": "Opera",
    "#vivaldi": "Vivaldi",
    "#tor": "Tor Browser",
    "#comet": "Comet",
}

# Max allowed delay (in seconds) 
MAX_DELAY = 15

# --- Logging ---

# Options:
# "console" → print to terminal
# "file"    → write to log file
# "both"    → both console + file
LOG_MODE = "both"

# --- State Retention ---
STATE_RETENTION_HOURS = 672   # 4 weeks
MAX_STATE_ENTRIES = 5000      # safety cap

