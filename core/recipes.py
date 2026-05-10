"""
CalFlow recipe catalog (v1.3.1).

Two flavours of recipes:

1. **Stock recipes** — hard-coded starter set the menubar's Recipes
   window shows under the named categories. These are CalFlow's
   "Hello, world" examples — short, copy-pasteable, illustrative.
   Add/remove by editing STOCK_RECIPES below; ids are stable so the
   user's "saved as mine" copies don't break.

2. **My recipes** — user-saved scripts in `data/my_recipes.json`.
   Owned by the user; CalFlow only reads/writes via this module.

Public API:
    list_stock()          → list[dict]
    list_my_recipes()     → list[dict]
    save_my_recipe(payload)  → dict   (upsert by id; creates id if absent)
    delete_my_recipe(rid) → bool
    list_categories()     → list[str]
    all_recipes()         → dict     (for the menubar's `recipes` op)

The dict shape per recipe is:
    {
        "id":          str,    # "stock-…" or "mine-XXXXXXXX"
        "name":        str,
        "category":    str,    # one of CATEGORIES
        "description": str,
        "body":        str,    # the actual +CalFlow+ / Smart-Mode script
        "icon":        str,    # tabler-icon hint, optional
        "owner":       "stock" | "mine",
        "created_at":  ISO-8601 (mine only)
        "updated_at":  ISO-8601 (mine only)
    }
"""

from __future__ import annotations

# v1.3.1 — public surface lock.
__all__ = [
    "CATEGORIES",
    "STOCK_RECIPES",
    "all_recipes",
    "delete_my_recipe",
    "list_categories",
    "list_my_recipes",
    "list_stock",
    "save_my_recipe",
]

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.config import DATA_DIR
from core.utils import log


MY_RECIPES_PATH = Path(DATA_DIR) / "my_recipes.json"

CATEGORIES = ["Meetings", "Focus", "Daily", "Multi-monitor"]


# =========================================================
# 📚 STOCK RECIPES
# =========================================================
#
# Order matters — the UI shows in declaration order within a category.
# Keep each body short (≤8 lines) so the editor preview isn't crowded.
# Use only verbs/tags that exist in the current parser.

STOCK_RECIPES: List[Dict[str, Any]] = [
    {
        "id":          "stock-zoom-notes",
        "name":        "Zoom + notes side by side",
        "category":    "Meetings",
        "description": "Opens the meeting on the left half, Notes on the right.",
        "icon":        "users",
        "body": (
            "+CalFlow+\n"
            "open zoom.us @chrome #left(50%)\n"
            "open notes.app #right(50%)\n"
            "hide @slack\n"
        ),
    },
    {
        "id":          "stock-standup-briefing",
        "name":        "Standup briefing",
        "category":    "Meetings",
        "description": "Opens your team's dashboard, Slack standup channel, and Zoom in one window.",
        "icon":        "presentation",
        "body": (
            "+CalFlow+\n"
            "open https://your-dashboard.example.com @chrome #left(33%)\n"
            "open slack.com #middle\n"
            "open zoom.us @chrome new(window) #right(33%)\n"
        ),
    },
    {
        "id":          "stock-deep-work",
        "name":        "Deep work mode",
        "category":    "Focus",
        "description": "Hides Slack and Mail, opens your task list, full-screens the editor.",
        "icon":        "target",
        "body": (
            "+CalFlow+\n"
            "hide @comm\n"
            "open todoist.com @chrome #left(30%)\n"
            "focus @editor\n"
        ),
    },
    {
        "id":          "stock-pomodoro",
        "name":        "Pomodoro start",
        "category":    "Focus",
        "description": "25-minute Pomodoro: hides distractions, opens timer, takes a screenshot at the end.",
        "icon":        "clock",
        "body": (
            "+CalFlow+\n"
            "hide @comm\n"
            "open https://pomofocus.io @chrome #right(25%)\n"
            "wait 25m\n"
            "screenshot\n"
        ),
    },
    {
        "id":          "stock-morning-routine",
        "name":        "Morning routine",
        "category":    "Daily",
        "description": "Calendar, email, news, and metrics — one tab each, in order.",
        "icon":        "sun",
        "body": (
            "+CalFlow+\n"
            "open calendar.google.com @chrome\n"
            "open mail.google.com @chrome\n"
            "open news.ycombinator.com @chrome\n"
        ),
    },
    {
        "id":          "stock-inbox-sweep",
        "name":        "Inbox sweep",
        "category":    "Daily",
        "description": "Opens Gmail and your task inbox side-by-side for a 10-minute triage.",
        "icon":        "mail",
        "body": (
            "+CalFlow+\n"
            "open mail.google.com @chrome #left(60%)\n"
            "open todoist.com @chrome #right(40%)\n"
        ),
    },
    {
        "id":          "stock-triple-monitor-research",
        "name":        "Triple-monitor research",
        "category":    "Multi-monitor",
        "description": "Source on display 1, notes on display 2, reference on display 3.",
        "icon":        "device-laptop",
        "body": (
            "+CalFlow+\n"
            "open https://example.com @chrome #display(1)\n"
            "open notes.app #display(2)\n"
            "open https://reference.example.com @chrome #display(3)\n"
        ),
    },
    {
        "id":          "stock-grid-dashboard",
        "name":        "Quad dashboard",
        "category":    "Multi-monitor",
        "description": "Four panels in a 2×2 grid on your secondary display.",
        "icon":        "grid-pattern",
        "body": (
            "+CalFlow+\n"
            "open https://dashboard1.example.com @chrome #grid(1,1@2x2) #display(2)\n"
            "open https://dashboard2.example.com @chrome #grid(2,1@2x2) #display(2)\n"
            "open https://dashboard3.example.com @chrome #grid(1,2@2x2) #display(2)\n"
            "open https://dashboard4.example.com @chrome #grid(2,2@2x2) #display(2)\n"
        ),
    },
]


# =========================================================
# 📖 STOCK READERS
# =========================================================

def list_stock() -> List[Dict[str, Any]]:
    """Return a fresh list of stock recipe dicts (defensive copies)."""
    return [{**r, "owner": "stock"} for r in STOCK_RECIPES]


def list_categories() -> List[str]:
    """Categories the UI groups recipes under (declaration order)."""
    return list(CATEGORIES)


# =========================================================
# 💾 MY-RECIPES STORE
# =========================================================

def list_my_recipes() -> List[Dict[str, Any]]:
    """
    Load the user-saved recipes. Returns [] if the file is missing or
    corrupted (logged as WARN; never raises).
    """
    if not MY_RECIPES_PATH.exists():
        return []
    try:
        with open(MY_RECIPES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log(f"[WARN] my_recipes.json corrupted: {exc}")
        return []
    raw = data.get("recipes") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "id":          r.get("id") or _new_id(),
            "name":        str(r.get("name") or "Untitled"),
            "category":    str(r.get("category") or "Daily"),
            "description": str(r.get("description") or ""),
            "body":        str(r.get("body") or ""),
            "icon":        str(r.get("icon") or "bookmark"),
            "owner":       "mine",
            "created_at":  r.get("created_at"),
            "updated_at":  r.get("updated_at"),
        })
    return out


def save_my_recipe(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert a user recipe.

    `payload` keys (any subset; missing fields filled in):
        id          str   (omit to create; "mine-…" prefix added if absent)
        name        str
        category    str
        description str
        body        str   (REQUIRED for create)
        icon        str

    Returns the canonical saved dict (with id, timestamps).
    """
    body = (payload.get("body") or "").strip()
    if not body:
        return {"ok": False, "error": "missing body"}

    rid = (payload.get("id") or "").strip()
    if rid and not rid.startswith("mine-"):
        rid = ""        # ignore stock ids; we only ever create our own
    if not rid:
        rid = _new_id()

    now = _now_iso()
    recipe: Dict[str, Any] = {
        "id":          rid,
        "name":        str(payload.get("name") or "Untitled").strip()[:100],
        "category":    _normalize_category(payload.get("category")),
        "description": str(payload.get("description") or "").strip()[:300],
        "body":        body,
        "icon":        str(payload.get("icon") or "bookmark"),
        "updated_at":  now,
    }

    existing = list_my_recipes()
    found = False
    for i, r in enumerate(existing):
        if r["id"] == rid:
            recipe["created_at"] = r.get("created_at") or now
            existing[i] = recipe
            found = True
            break
    if not found:
        recipe["created_at"] = now
        existing.append(recipe)

    _persist(existing)
    return {"ok": True, **recipe, "owner": "mine"}


def delete_my_recipe(rid: str) -> Dict[str, Any]:
    """Remove a user recipe by id. No-op (returns ok=False) if not found."""
    if not rid:
        return {"ok": False, "error": "missing id"}
    existing = list_my_recipes()
    kept = [r for r in existing if r["id"] != rid]
    if len(kept) == len(existing):
        return {"ok": False, "error": "id not found"}
    _persist(kept)
    return {"ok": True, "id": rid}


# =========================================================
# 🌐 COMBINED VIEW
# =========================================================

def all_recipes() -> Dict[str, Any]:
    """
    What the menubar's `recipes` op returns. Two parallel lists so the
    UI can group / filter independently.
    """
    return {
        "categories": list_categories(),
        "stock":      list_stock(),
        "mine":       list_my_recipes(),
    }


# =========================================================
# 🛠 INTERNAL
# =========================================================

def _new_id() -> str:
    return "mine-" + uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_category(value: Optional[str]) -> str:
    if not value:
        return "Daily"
    v = str(value).strip()
    for c in CATEGORIES:
        if c.lower() == v.lower():
            return c
    return "Daily"


def _persist(recipes: List[Dict[str, Any]]) -> None:
    """Atomic write of the whole my_recipes.json file."""
    payload = {"schema_version": 1, "recipes": recipes}
    try:
        MY_RECIPES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(MY_RECIPES_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, MY_RECIPES_PATH)
    except Exception as exc:
        log(f"[WARN] Failed to save my_recipes.json: {exc}")
