"""
CalFlow Settings (v2.0 — Smart Mode + Plus Mode)

Default settings.

User edits from the menu bar Settings UI are stored in gitignored
`data/user_settings.json` and `data/user_targets.json`, then merged at
import time below.

Defines:
- execution timing
- target system (@aliases)
- URL filtering
- autofill behavior
- permissions
"""

from __future__ import annotations

# =========================================================
# ⏱️ EXECUTION TIMING (USER LOGIC)
# =========================================================

FETCH_WINDOW_HOURS = 2

# How far ahead the `cli.main status` dashboard looks for the
# "next event" line. Wider than the daemon window because the
# dashboard is informational ("when's my next thing?") whereas
# FETCH_WINDOW_HOURS is the daemon's per-cycle processing window.
STATUS_LOOKAHEAD_HOURS = 24

DEFAULT_ALERT_SECONDS = 180
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

MAX_URLS = 10

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

# Calendar invite trust. Self-authored events are allowed by default.
# Third-party invitations execute only when the sender's exact email or
# domain is explicitly listed here.
ALLOW_SELF_AUTHORED_EVENTS = True
TRUSTED_INVITE_DOMAINS = set()
TRUSTED_INVITE_EMAILS = set()

# Plus Mode `run` backend permissions by event trust level.
# `script`, `shell`, and `terminal` are reserved for follow-up backends
# and remain disabled until implemented.
ALLOW_RUN_BACKENDS_SELF = {"btt", "alfred", "shortcut", "applescript"}
ALLOW_RUN_BACKENDS_TRUSTED_DOMAIN = {"shortcut"}
ALLOW_RUN_BACKENDS_TRUSTED_EMAIL = {"shortcut"}

RUN_APPLESCRIPT_TIMEOUT = 10
RUN_BTT_TIMEOUT = 5
RUN_SHORTCUT_TIMEOUT = 30
RUN_ALFRED_TIMEOUT = 5
RUN_ERROR_NOTIFICATIONS = True


# =========================================================
# 🔑 AUTOFILL SYSTEM
# =========================================================

AUTOFILL_MODE = "semi-auto"

NO_AUTOFILL_TAG = "#no-autofill"
FORCE_FILL_TAG = "#fill"
FORCE_SUBMIT_TAG = "#submit"


# =========================================================
# 🎯 TITLE-URL DEFAULTS (v1.1.22)
# =========================================================
# Calendar events sometimes carry the meeting / target URL in the
# event TITLE rather than (or in addition to) the description body.
# These two settings let you control what CalFlow does with such a
# title-URL when no per-line tags spell it out.
#
# They apply ONLY to URLs found in the event title — body URLs keep
# their existing behaviour (autofill via AUTOFILL_MODE, tab unless
# layout is present).

# Autofill mode for title URLs.
#   "submit"  → press fill + submit (e.g. complete a login form)
#   "fill"    → press fill only (don't submit)
#   "none"    → no autofill keystroke
#
# If the user has a global #fill / #submit / #no-autofill tag in the
# event body, that wins over this default.
TITLE_URL_AUTOFILL_DEFAULT = "fill"

# Open mode for title URLs WHEN no layout/display tag is present.
# When a layout/display tag IS present (`#left`, `#grid(...)`,
# `#display(...)` etc., either globally or attached), this default
# is IGNORED — layout always implies a new window per v1.1.20.
#   "tab"     → new tab in the existing browser window (macOS default)
#   "window"  → fresh browser window
TITLE_URL_OPEN_DEFAULT = "tab"


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
PLUS_MAX_COMMANDS = 40

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
# 👤 USER OVERRIDES (v1.4.1)
# =========================================================

try:
    from core.settings_reader import load_user_overrides as _load_user_overrides
    globals().update(_load_user_overrides())
except Exception:
    pass

try:
    from core.targets_reader import load_user_targets as _load_user_targets
    _USER_TARGETS = _load_user_targets()
    if _USER_TARGETS is not None:
        TARGETS = _USER_TARGETS
except Exception:
    pass


# =========================================================
# 🔒 RESERVED KEYWORD GUARD (v1.1.2)
# =========================================================
# Enforces the DSL contract: user-defined aliases (TARGETS, BUNDLES)
# MUST NOT shadow CalFlow reserved keywords (`active`, `all`, `display`,
# `except`). On collision, CalFlow refuses to start with a clear message
# and a rename suggestion. See core/reserved.py for the rationale.

from core.reserved import enforce_or_exit as _enforce_reserved_keywords

_enforce_reserved_keywords(TARGETS)
