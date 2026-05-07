"""
CalFlow dynamic expression resolver (v2.0.1).

Implements the {…} pipeline grammar from docs/DSL_GRAMMAR.md +
the Rule Update:

    {<base> ['>' <transform>]* ['>' <format_stage>]?}

    base          ::= 'now' (('+'|'-') <int> <unit>)?
    unit          ::= 's' | 'm' | 'h' | 'd' | 'w' | 'mo' | 'y'
    transform     ::= start_of_day | end_of_day
                    | start_of_week | end_of_week
                    | start_of_month | end_of_month
                    | start_of_year | end_of_year
    format_stage  ::= <token-string>           # e.g. YYYY-MM-DD
                    | format("<token-string>") # explicit

    Format tokens: YYYY, YY, MM, DD, HH, hh, mm, ss

Rules:
- '>' is the only pipeline operator (':' is NOT supported)
- format is always the FINAL stage
- default format = "YYYY-MM-DD"
- unknown transforms / formats are logged and skipped
- never raises — invalid expressions are returned unchanged so the
  caller's text isn't destroyed (per validation §3.5: "skip + log")

Public surface:
    resolve_dynamic(text)            → text with all {…} substituted
    resolve_dynamic_expr(expr)       → resolved scalar string
"""

from __future__ import annotations

# v1.1.27 — public surface lock. See pyproject.toml for the rationale.
__all__ = [
    'resolve_dynamic',
    'resolve_dynamic_expr',
]

import re
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

from dateutil.relativedelta import relativedelta

from core.utils import log


# =========================================================
# 🧱 REGEX
# =========================================================

_BLOCK_RE = re.compile(r"\{([^{}]+)\}")

# now, now-1mo, now+2h, now-15m
_BASE_RE = re.compile(
    r"^\s*now\s*(?:([+\-])\s*(\d+)\s*(s|m|h|d|w|mo|y))?\s*$",
    re.IGNORECASE,
)

_FORMAT_FN_RE = re.compile(r'^\s*format\(\s*([\'"])(.+?)\1\s*\)\s*$', re.IGNORECASE)

# Format-token detection: a stage is a format if it contains any of these.
_FORMAT_TOKENS = ("YYYY", "YY", "MM", "DD", "HH", "hh", "mm", "ss")
_FORMAT_TOKEN_RE = re.compile("|".join(_FORMAT_TOKENS))

# strftime translation. Order matters — longest first.
_TOKEN_MAP = [
    ("YYYY", "%Y"),
    ("YY",   "%y"),
    ("MM",   "%m"),
    ("DD",   "%d"),
    ("HH",   "%H"),
    ("hh",   "%I"),
    ("mm",   "%M"),
    ("ss",   "%S"),
]
_TOKEN_RE = re.compile("|".join(re.escape(tok) for tok, _ in _TOKEN_MAP))


# =========================================================
# 🔁 TRANSFORMS
# =========================================================

def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def _start_of_week(dt: datetime) -> datetime:
    """ISO week starts Monday."""
    return _start_of_day(dt - timedelta(days=dt.weekday()))


def _end_of_week(dt: datetime) -> datetime:
    return _end_of_day(_start_of_week(dt) + timedelta(days=6))


def _start_of_month(dt: datetime) -> datetime:
    return _start_of_day(dt.replace(day=1))


def _end_of_month(dt: datetime) -> datetime:
    next_month = (dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    return _end_of_day(next_month - timedelta(days=1))


def _start_of_year(dt: datetime) -> datetime:
    return _start_of_day(dt.replace(month=1, day=1))


def _end_of_year(dt: datetime) -> datetime:
    return _end_of_day(dt.replace(month=12, day=31))


TRANSFORMS: Dict[str, Callable[[datetime], datetime]] = {
    "start_of_day":   _start_of_day,
    "end_of_day":     _end_of_day,
    "start_of_week":  _start_of_week,
    "end_of_week":    _end_of_week,
    "start_of_month": _start_of_month,
    "end_of_month":   _end_of_month,
    "start_of_year":  _start_of_year,
    "end_of_year":    _end_of_year,
}


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def resolve_dynamic(text: Optional[str], *, _now: Optional[datetime] = None) -> Optional[str]:
    """
    Replace every `{…}` block in `text` with its resolved value.

    Returns the original text unchanged if no `{…}` blocks are found
    or if `text` is None/empty.
    """
    if not text:
        return text
    if "{" not in text:
        return text
    return _BLOCK_RE.sub(
        lambda m: resolve_dynamic_expr(m.group(1), _now=_now), text
    )


def resolve_dynamic_expr(expr: str, *, _now: Optional[datetime] = None) -> str:
    """
    Resolve one bare expression (without surrounding `{}`).

    On any failure: log a warning and return `{<expr>}` unchanged so
    the caller's string isn't silently destroyed.
    """
    if not expr or not expr.strip():
        return f"{{{expr}}}"

    # Per Rule Update.md "Design Constraint" the only pipeline operator
    # is `>`. We split on `>` only — a `:` that survives into a stage
    # remains literal (e.g. inside `HH:mm`). The legacy `{now:YYYY-MM-DD}`
    # form fails base-parsing further down and is returned unchanged.
    parts = [p.strip() for p in expr.split(">")]
    base_str = parts[0]
    pipeline = parts[1:]

    # ---- base -------------------------------------------------------
    base_dt = _eval_base(base_str, now=_now)
    if base_dt is None:
        log(f"[WARN] dynamic: unknown base {base_str!r}")
        return f"{{{expr}}}"

    # ---- pipeline (transforms + optional final format) -------------
    fmt: str = "YYYY-MM-DD"  # default
    dt = base_dt
    seen_format = False

    for stage in pipeline:
        if seen_format:
            log(f"[WARN] dynamic: stage after format ignored: {stage!r}")
            break
        if _is_format_stage(stage):
            fmt = _normalize_format_stage(stage)
            seen_format = True
            continue
        fn = TRANSFORMS.get(stage.lower())
        if fn is None:
            log(f"[WARN] dynamic: unknown transform {stage!r}; skipping")
            continue
        dt = fn(dt)

    return _apply_format(dt, fmt)


# =========================================================
# 🛠️ INTERNALS
# =========================================================

def _eval_base(base: str, now: Optional[datetime] = None) -> Optional[datetime]:
    m = _BASE_RE.match(base)
    if not m:
        return None
    sign, num, unit = m.group(1), m.group(2), m.group(3)
    dt = now or datetime.now()
    if sign is None:
        return dt
    delta = _make_delta(int(num), unit.lower())
    if delta is None:
        return None
    return dt - delta if sign == "-" else dt + delta


def _make_delta(value: int, unit: str):
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    if unit == "mo":
        return relativedelta(months=value)
    if unit == "y":
        return relativedelta(years=value)
    return None


def _is_format_stage(stage: str) -> bool:
    if _FORMAT_FN_RE.match(stage):
        return True
    return bool(_FORMAT_TOKEN_RE.search(stage))


def _normalize_format_stage(stage: str) -> str:
    m = _FORMAT_FN_RE.match(stage)
    return m.group(2) if m else stage


def _apply_format(dt: datetime, fmt: str) -> str:
    """Translate CalFlow tokens to strftime tokens, then format."""
    def repl(m: re.Match) -> str:
        token = m.group(0)
        for cf_tok, py_tok in _TOKEN_MAP:
            if token == cf_tok:
                return py_tok
        return token

    py_fmt = _TOKEN_RE.sub(repl, fmt)
    try:
        return dt.strftime(py_fmt)
    except Exception as exc:
        log(f"[WARN] dynamic: format failed for {fmt!r}: {exc}")
        return dt.strftime("%Y-%m-%d")
