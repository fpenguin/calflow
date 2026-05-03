"""
CalFlow Autofill Engine (v2.0)

Responsibilities:
- resolve autofill provider
- validate provider availability
- fallback safely
- execute autofill keystrokes

Design:
- runtime-only logic (NO config decisions here)
- deterministic fallback
"""

from config.settings import AUTOFILL_PROVIDER, AUTOFILL_SHORTCUTS
from core.utils import log


# =========================================================
# 🔍 PROVIDER RESOLUTION
# =========================================================

def resolve_autofill_provider() -> str:
    """
    Resolve effective autofill provider.

    Flow:
    1. take user-configured provider
    2. check availability
    3. fallback to default if unavailable
    """

    provider = AUTOFILL_PROVIDER

    if not _is_provider_available(provider):
        log(f"[WARN] Autofill provider '{provider}' not available → fallback to 'default'")
        return "default"

    return provider


# =========================================================
# 🔧 PROVIDER AVAILABILITY CHECK
# =========================================================

def _is_provider_available(provider: str) -> bool:
    """
    Check if provider is usable on this system.

    NOTE:
    This is a heuristic check (not perfect).

    v1.0:
    - only checks config existence

    v2.0:
    - detect installed apps
    - detect browser extensions
    """

    return provider in AUTOFILL_SHORTCUTS


# =========================================================
# ⌨️ EXECUTION
# =========================================================

def trigger_autofill(mode: str = "fill"):
    """
    Execute autofill action.

    Args:
        mode: "fill" or "submit"
    """

    provider = resolve_autofill_provider()
    config = AUTOFILL_SHORTCUTS.get(provider)

    if not config:
        log("[WARN] No shortcut config found")
        return

    action = config.get(mode)

    if not action:
        log(f"[WARN] No '{mode}' action defined for provider '{provider}'")
        return

    _execute_shortcut(action)


def _execute_shortcut(action: dict):
    """
    Execute keystroke.

    Placeholder for now.

    Future:
    - integrate with Quartz / pyobjc
    """

    log(f"[INFO] Executing shortcut: {action}")

    # TODO:
    # Implement macOS key event injection