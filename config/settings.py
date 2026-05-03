"""
CalFlow Settings (v2.0 — Smart Mode + Plus Mode)

SAFE TO EDIT

Defines:
- execution timing
- target system (@aliases)
- URL filtering
- autofill behavior
- permissions
"""

# =========================================================
# ⏱️ EXECUTION TIMING (USER LOGIC)
# =========================================================

FETCH_WINDOW_HOURS = 2

# How far ahead the `cli.main status` dashboard looks for the
# "next event" line. Wider than the daemon window because the
# dashboard is informational ("when's my next thing?") whereas
# FETCH_WINDOW_HOURS is the daemon's per-cycle processing window.
STATUS_LOOKAHEAD_HOURS = 24

DEFAULT_ALERT_SECONDS = 300
GRACE_SECONDS = 600
EARLY_TOLERANCE = 30


# =========================================================
# 🧩 TARGET SYSTEM (@ ONLY — v2.0 READY)
# =========================================================

TARGETS = {
    # --- System targets ---
    "@chrome": "Google Chrome",
    "@safari": "Safari",
    "@edge": "Microsoft Edge",
    "@arc": "Arc",
    "@brave": "Brave Browser",
    "@firefox": "Firefox",

    # --- Workflow aliases ---
    "@work": ["Google Chrome", "Notion", "Figma"],
    "@comm": ["Slack", "Discord"],
    "@design": ["Figma", "Google Chrome"],
}

"""
Rules:
- string → single app
- list → expands to multiple apps
- undefined → skipped
- multiple @targets → invalid
"""


# =========================================================
# 🌐 URL HANDLING
# =========================================================

MAX_URLS = 5

IGNORED_PROTOCOLS = [
    "sip:",
    "tel:",
    "mailto:",
    "ftp:",
]


# =========================================================
# 🗺️ MAP FILTERING
# =========================================================

IGNORE_MAP_LINKS = True

MAP_DOMAINS = [
    "maps.google",
    "google.com/maps",
    "maps.apple.com",
    "bing.com/maps",
]


# =========================================================
# 🚫 URL BLACKLIST
# =========================================================

BLACKLIST_REGEX = [
    r"/cancel\w*",
    r"/reschedul\w*",
    r"zoom\.us/u/",
    r"aka\.ms/jointeamsmeeting",
    r"teams\.microsoft\.com/meetingoptions",
    r"collaborationhelp\.cisco\.com",
    r"tel\.meet",
    r"additionalinfo\.tmpl",
    r"g\.co/calendar",
    r"mail\.google\.com",
]

BLACKLIST_ONLY_IF_MULTIPLE = True
IGNORE_BLACKLIST_FOR_TITLE_URLS = True

FORCE_URL_TAG = "#force"


# =========================================================
# 🔐 EXECUTION PERMISSIONS
# =========================================================

SMART_MODE_EXECUTION_MODE = "allow-external"
PLUS_MODE_EXECUTION_MODE = "me-only"  # future


# =========================================================
# 🔑 AUTOFILL SYSTEM
# =========================================================

AUTOFILL_MODE = "semi-auto"

NO_AUTOFILL_TAG = "#no-autofill"
FORCE_FILL_TAG = "#fill"
FORCE_SUBMIT_TAG = "#submit"


# =========================================================
# ⏳ AUTOFILL TIMING
# =========================================================

DEFAULT_DELAY = 2
SLOW_DELAY = 5

AUTOFILL_BUFFER = 0.2
POST_AUTOFILL_DELAY = 0.5


# =========================================================
# 🔐 PASSWORD MANAGER
# =========================================================

AUTOFILL_PROVIDER = "apple"


AUTOFILL_SHORTCUTS = {
    "1password": {
        "fill": {"key": "\\", "modifiers": ["command"]},
        "submit": {"key_code": 36},
    },
    "bitwarden": {
        "fill": {"key": "l", "modifiers": ["command", "shift"]},
        "submit": {"key_code": 36},
    },
    "apple": {
        "fill": {"key": "\\", "modifiers": ["command"]},
        "submit": {"key_code": 36},
    },
    "default": {
        "fill": {"key": "\\", "modifiers": ["command"]},
        "submit": {"key_code": 36},
    },
}


# =========================================================
# ⚠️ USER-SIDE LIMITS
# =========================================================

MAX_DELAY = 15


# =========================================================
# 📊 LOGGING
# =========================================================

LOG_MODE = "both"


# =========================================================
# 🧠 STATE
# =========================================================

STATE_RETENTION_HOURS = 672
MAX_STATE_ENTRIES = 5000


# =========================================================
# ➕ PLUS MODE (v2.0)
# =========================================================
# User-facing Plus Mode behavior.
# System-level paths/limits live in config/config.py — DO NOT mix them here.

# Marker line that switches the parser into Plus Mode.
# Detection rule: first non-empty line of the event description, case-insensitive,
# stripped of whitespace, must equal this value.
PLUS_HEADER = "+CalFlow+"

# Hard cap on number of commands a single Plus Mode block may contain.
# Defensive bound — protects the runtime from runaway scripts.
PLUS_MAX_COMMANDS = 50

# Per-command default wait when the user does not specify one (seconds).
PLUS_DEFAULT_WAIT = 1

# Default delay after each command before moving to the next one (seconds).
# Keeps execution non-blocking but stable.
PLUS_INTER_COMMAND_DELAY = 0.3

# Default destination directory for screenshots taken via SCREENSHOT.
# Customize freely. `~` is expanded at use time.
PLUS_SCREENSHOT_DIR = "~/Downloads/CalFlow"

# Default filename pattern for screenshots when no `to(...)` is given.
# Tokens supported: {YYYY}, {MM}, {DD}, {HH}, {mm}, {ss}, {YYYY-MM-DD},
# {YYYY-MM-DD_HHMMSS}. Anything else is left literal.
PLUS_SCREENSHOT_FILENAME_FORMAT = "CalFlow_{YYYY-MM-DD_HHMMSS}.png"

# Strict mode: if True, any validation error aborts the whole Plus block.
# If False, valid commands run and invalid ones are logged + skipped.
PLUS_STRICT_VALIDATION = False


# =========================================================
# 🔒 RESERVED KEYWORD GUARD (v1.1.2)
# =========================================================
# Enforces the DSL contract: user-defined aliases (TARGETS, BUNDLES)
# MUST NOT shadow CalFlow reserved keywords (`active`, `all`, `display`,
# `except`). On collision, CalFlow refuses to start with a clear message
# and a rename suggestion. See core/reserved.py for the rationale.

from core.reserved import enforce_or_exit as _enforce_reserved_keywords

_enforce_reserved_keywords(TARGETS)