"""
CalFlow Plus Mode Parser (v2.0).

Responsibilities:
- consume the body of a Plus block (header detected anywhere in the doc)
- validate via core.validator
- build a typed AST list (List[BaseCommand])

Design:
- deterministic
- pure (no IO)
- best-effort: a single bad line never aborts the rest of the block
  unless config.settings.PLUS_STRICT_VALIDATION is True
- comments use `##`; single `#` is reserved for tags / modifiers
"""

from __future__ import annotations

import re
import json
from typing import Any, FrozenSet, List, Optional, Tuple

from config.settings import (
    PLUS_DEFAULT_WAIT,
    PLUS_HEADER,
    PLUS_STRICT_VALIDATION,
)
from core.models import (
    BaseCommand,
    ClickCommand,
    CloseCommand,
    CopyCommand,
    FocusCommand,
    HideCommand,
    OpenCommand,
    PasteCommand,
    PressCommand,
    RunCommand,
    SaveCommand,
    ScreenshotCommand,
    TypeCommand,
    ValidationError,
    WaitCommand,
)
from core.utils import log, strip_inline_comment
from core.validator.validator import (
    _split_verb_function,
    tokenize,
    validate_plus_block,
)


# =========================================================
# 🔎 REGEX
# =========================================================

_HASHTAG_RE = re.compile(r"^#\w[\w\-=()%.,@/]*$")
_AT_RE = re.compile(r"^@\w[\w\-]*$")
_COORD_RE = re.compile(r"^(-?\d+)\s*,\s*(-?\d+)$")
_FUNCTION_CALL_RE = re.compile(r"^([A-Za-z_][\w\-]*)\((.*)\)$")
_TIME_RE = re.compile(r"^(\d+(?:\.\d+)?)(s|m|h|ms)?$", re.IGNORECASE)
_KEY_TOKEN_RE = re.compile(r"^\{([^{}]+)\}$")
_SEQ_TOKEN_RE = re.compile(r"^\[(.*)\]$")
_REP_RE = re.compile(r"^\(?(\{[^{}]+\}|\([^()]*\))\)?x(\d+)$")  # ({left})x5
_URL_HINT_RE = re.compile(r"://|^[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)
_QUOTED_RE = re.compile(r'^"(.*)"$|^\'(.*)\'$')

# v1.1.2 — runtime targets (bare identifiers, NOT aliases or apps).
_RUNTIME_TARGETS = frozenset({"active", "all"})

# v1.1.2 — function-shaped tag names (the "#" drop sugar). When one of
# these appears as a function-call without the leading "#" AND the line
# carries an action verb, it is promoted to a tag so the layout
# resolver can pick it up. They remain in `functions` too, so verbs
# that treat them as filters (hide / focus) still work.
_LAYOUT_FN_NAMES = frozenset({
    "display", "left", "right", "middle", "top", "bottom",
    "area", "grid", "profile",
})

# v1.5.2 — bare PARENLESS layout words are drop-sugar too. `open
# "Messages" display(2) full` previously dropped `full` silently (the
# worst outcome: user believes it worked). Promoted to the `#word`
# tag form so resolve_layout picks them up with their defaults
# (#full → 1.0, #left → 0.5, …). Quoted tokens are never promoted —
# an app literally named "full" stays an app name. Runtime targets
# (`active`, `all`) are NOT in this set and keep their meaning.
_BARE_LAYOUT_WORDS = frozenset({
    "full", "left", "right", "middle", "top", "bottom",
})

# v1.1.2 — dynamic blocks that wrap a runtime target / alias / filter
# are rejected with a clear hint (data vs. runtime separation).
_DYNAMIC_RE = re.compile(r"^\{(.+)\}$")


# =========================================================
# 🚪 HEADER DETECTION (document-wide)
# =========================================================

def is_plus_header(text: str) -> bool:
    """
    True iff `+CalFlow+` appears ANYWHERE in the document.

    The check is a case-insensitive substring search on each line,
    NOT a strict line-equality match. This is intentional — calendar
    sources mangle the marker in many predictable ways:

        '+CalFlow+         (Excel-safe leading apostrophe)
        "+CalFlow+"        (chat clients wrap pasted code in quotes)
        ‘+CalFlow+’        (rich text editors smart-quote the apostrophe)
        +CalFlow+ note     (a stray comment on the marker line)

    All of these should switch the parser into Plus Mode. Body lines
    are taken from the line AFTER the marker line (`strip_header`).
    """
    if not text:
        return False
    needle = PLUS_HEADER.lower()
    return any(needle in raw.lower() for raw in text.splitlines())


def strip_header(text: str) -> List[str]:
    """
    Return the body lines of a Plus block — everything AFTER the first
    line that contains `+CalFlow+`. The marker line itself (and any
    trailing junk on that line) is discarded; lines before the marker
    are also discarded.
    """
    if not text:
        return []
    seen = False
    body: List[str] = []
    needle = PLUS_HEADER.lower()
    for raw in text.splitlines():
        if not seen:
            if needle in raw.lower():
                seen = True
            continue
        body.append(raw)
    return body


# =========================================================
# 🚀 PUBLIC API
# =========================================================

def parse_plus(
    text: str,
) -> Tuple[List[BaseCommand], List[ValidationError]]:
    """Parse the body of a Plus block into a typed AST."""
    body = _collapse_multiline_run_blocks(strip_header(text))
    errors = validate_plus_block(body)

    if errors and PLUS_STRICT_VALIDATION:
        log(
            f"[WARN] Plus Mode validation failed (strict): "
            f"{len(errors)} error(s); aborting block."
        )
        return [], errors

    commands: List[BaseCommand] = []
    bad_lines = {e.line_no for e in errors if e.line_no > 0}

    for idx, raw in enumerate(body, start=1):
        line = strip_inline_comment(raw or "").strip()
        if not line:
            continue
        if idx in bad_lines:
            log(f"[INFO] skipped line: invalid syntax (line {idx}): {line}")
            continue

        cmd = _build_command(line, idx)
        if cmd is not None:
            commands.append(cmd)

    return commands, errors


# =========================================================
# 🏗️ COMMAND CONSTRUCTION
# =========================================================

def _build_command(line: str, line_no: int) -> Optional[BaseCommand]:
    tokens = tokenize(line)
    if not tokens:
        return None

    # Standalone modifier line (only #tags / @targets, no verb-like token):
    # silently ignored per parser-behavior §5.10 / DSL_GRAMMAR §3.2.
    if all(_HASHTAG_RE.match(t) or _AT_RE.match(t) for t in tokens):
        return None

    # Detach `verb(...)` (e.g. `type("hi")`, `wait(5s)`) into ['verb', 'verb(...)'].
    tokens = _split_verb_function(tokens)

    head = tokens[0]
    head_upper = head.upper()

    # ---------------- Implicit open ---------------------------------
    if head_upper not in {
        "OPEN", "FOCUS", "CLOSE", "HIDE", "CLICK", "TYPE", "PRESS",
        "WAIT", "SCREENSHOT", "COPY", "PASTE", "SAVE", "RUN",
    }:
        # If it looks like a URL/quoted/file path, normalize to OPEN.
        if (
            _URL_HINT_RE.search(head)
            or _QUOTED_RE.match(head)
            or head.startswith("~")
            or head.startswith("/")
            or head.startswith("@")
        ):
            tokens = ["open"] + tokens
            head = "open"
            head_upper = "OPEN"
        else:
            return None  # validator already logged

    args = tokens[1:]
    body_args, tags, targets, fns = _split_args(args)
    raw = line

    if head_upper == "OPEN":
        primary = body_args[0] if body_args else (targets[0] if targets else "")
        return OpenCommand(
            line_no=line_no,
            raw=raw,
            tags=tags,
            functions=tuple(fns),
            url=_unquote(primary) if primary else "",
            app=targets[0] if targets else None,
            targets=tuple(targets),
        )

    if head_upper == "FOCUS":
        return _build_focus(line_no, raw, body_args, tags, targets, fns)

    if head_upper == "CLOSE":
        return _build_close(line_no, raw, body_args, tags, targets, fns)

    if head_upper == "HIDE":
        return _build_hide(line_no, raw, body_args, tags, targets, fns)

    if head_upper == "CLICK":
        return _build_click(line_no, raw, body_args, tags, fns)

    if head_upper == "TYPE":
        text = ""
        if body_args:
            head_arg = body_args[0]
            m = _FUNCTION_CALL_RE.match(head_arg)
            if m:
                text = _unquote(m.group(2).strip())
            else:
                text = _unquote(head_arg)
        return TypeCommand(
            line_no=line_no,
            raw=raw,
            tags=tags,
            functions=tuple(fns),
            text=text,
        )

    if head_upper == "PRESS":
        return _build_press(line_no, raw, body_args, tags, fns)

    if head_upper == "WAIT":
        seconds = _normalize_wait(body_args[0]) if body_args else float(PLUS_DEFAULT_WAIT)
        return WaitCommand(
            line_no=line_no,
            raw=raw,
            tags=tags,
            functions=tuple(fns),
            seconds=max(0.0, seconds),
        )

    if head_upper == "SCREENSHOT":
        return _build_screenshot(line_no, raw, body_args, tags, fns)

    if head_upper == "COPY":
        # v1.5.2 — copy("text") places a literal on the clipboard.
        # Bare `copy` (selection copy) keeps text=None.
        copy_text: Optional[str] = None
        if body_args and _QUOTED_RE.match(body_args[0]):
            copy_text = _unquote(body_args[0])
        return CopyCommand(
            line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
            text=copy_text,
        )

    if head_upper == "PASTE":
        return PasteCommand(line_no=line_no, raw=raw, tags=tags, functions=tuple(fns))

    if head_upper == "SAVE":
        source = next((v for (n, v) in fns if n == "source"), None)
        to = next((v for (n, v) in fns if n == "to"), None)
        return SaveCommand(
            line_no=line_no,
            raw=raw,
            tags=tags,
            functions=tuple(fns),
            source=source,
            to=to,
        )

    if head_upper == "RUN":
        backend = None
        path = _unquote(body_args[0]) if body_args else ""
        trigger_name = ""
        script = ""
        timeout = _run_timeout(fns)
        run_handlers = _parse_run_handlers(args)
        shortcut_name = shortcut_input = ""
        alfred_bundle_id = alfred_trigger = alfred_argument = ""
        fn_backend = _run_backend_function(fns)
        if fn_backend is not None:
            backend, value = fn_backend
            path = ""
            if backend == "btt":
                trigger_name = _normalize_btt_trigger_arg(str(value or ""))
            elif backend == "shortcut":
                shortcut_name = str(value or "")
                shortcut_input = str(_run_function_value(fns, "input") or "")
            elif backend == "alfred":
                alfred_bundle_id, alfred_trigger, _arg = _parse_alfred_value(value)
                alfred_argument = str(_run_function_value(fns, "input") or _arg)
            elif backend == "applescript":
                script = _extract_run_script(body_args)
        elif body_args and body_args[0].lower() == "applescript":
            backend = "applescript"
            path = ""
            script = _extract_run_script(body_args)
        return RunCommand(
            line_no=line_no,
            raw=raw,
            tags=tags,
            functions=tuple(fns),
            path=path,
            backend=backend,
            trigger_name=trigger_name,
            script=script,
            timeout=timeout,
            shortcut_name=shortcut_name,
            shortcut_input=shortcut_input,
            alfred_bundle_id=alfred_bundle_id,
            alfred_trigger=alfred_trigger,
            alfred_argument=alfred_argument,
            run_handlers=run_handlers,
        )

    return None


# =========================================================
# 🔧 PER-VERB BUILDERS
# =========================================================

def _build_hide(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], targets: List[str], fns: List[Tuple[str, Any]],
) -> HideCommand:
    """
    HIDE forms (v1.1.2):
        hide active                      → target_keyword="active"
        hide all                         → target_keyword="all"
        hide @app                        → items=("@app",)
        hide [a, b, c]                   → items=("a","b","c")
        hide "App"                       → items=("App",)
        hide except(<arg>)               → keep_set=…
        hide except(<arg>) display(N|"name") → keep_set + display_filter
        hide display(N|"name")           → display_filter only

    Bare `hide` (no body, no targets, no filters) is REJECTED upstream
    by the validator with a v1.1.2 migration message.
    """
    fn_dict = dict(fns)
    has_filters = ("except" in fn_dict) or ("display" in fn_dict)

    # ── Runtime-target keyword (`active`, `all`) ──────────────────────
    target_keyword: Optional[str] = None
    if body and body[0].lower() in _RUNTIME_TARGETS:
        head = body[0].lower()
        if not has_filters:
            return HideCommand(
                line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
                target_keyword=head,
            )
        # v1.5.2 — `hide active display(N)` is now LEGAL: miniaturize the
        # frontmost app's windows on display N only (per-window scope,
        # same JXA path as `hide display(N)`). `except()` still conflicts
        # with a runtime target — fall through so the validator's shape
        # checks see the raw pieces.
        display_arg = fn_dict.get("display")
        if head == "active" and display_arg is not None and "except" not in fn_dict:
            return HideCommand(
                line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
                target_keyword="active",
                display_filter=_coerce_display_filter(display_arg),
            )
        # v1.5.2 — `hide all display(N)` ≡ `hide display(N)` (the `all`
        # is implied by a bare display filter). Normalize to the filter
        # form instead of treating `all` as an app named "all".
        if head == "all" and display_arg is not None and "except" not in fn_dict:
            return HideCommand(
                line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
                display_filter=_coerce_display_filter(display_arg),
            )

    # ── Form 1: explicit list / bare-target / "App" — ignore filters ──
    items_tuple: Tuple[str, ...] = ()
    if body:
        head = body[0]
        flattened = _flatten_collection(head)
        if flattened:
            items_tuple = flattened
        else:
            items_tuple = (_unquote(head),)
    elif targets and not has_filters:
        # `hide @chrome` shorthand → items=("@chrome",) — resolver
        # will normalize the @ later.
        items_tuple = tuple(targets)

    # ── Form 2: filter form (except() / display()) ────────────────────
    keep_set: frozenset = frozenset()
    display_filter: Optional[Any] = None

    if not items_tuple:  # only relevant when there's no explicit list
        except_arg = fn_dict.get("except")
        if except_arg is not None:
            keep_set = _normalize_except_arg(except_arg, targets)

        display_arg = fn_dict.get("display")
        if display_arg is not None:
            display_filter = _coerce_display_filter(display_arg)

    return HideCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        items=items_tuple,
        keep_set=keep_set,
        display_filter=display_filter,
    )


def _build_close(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], targets: List[str], fns: List[Tuple[str, Any]],
) -> CloseCommand:
    """
    CLOSE forms (v1.1.2):
        close active                          → target_keyword="active"
        close all                             → target_keyword="all"
        close @app | close "App" | close [..] → items populated
        close except(<arg>)                   → keep_set populated

    Bare `close` (no args) is rejected by the validator.
    """
    fn_dict = dict(fns)

    # ── Runtime-target keyword (`active`, `all`) ──────────────────────
    if body and "except" not in fn_dict:
        head = body[0].lower()
        if head in _RUNTIME_TARGETS:
            return CloseCommand(
                line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
                target_keyword=head,
            )

    items_tuple: Tuple[str, ...] = ()
    if body:
        head = body[0]
        flattened = _flatten_collection(head)
        if flattened:
            items_tuple = flattened
        else:
            items_tuple = (_unquote(head),)
    elif targets and "except" not in fn_dict:
        items_tuple = tuple(targets)

    keep_set: frozenset = frozenset()
    if not items_tuple:
        except_arg = fn_dict.get("except")
        if except_arg is not None:
            keep_set = _normalize_except_arg(except_arg, targets)

    return CloseCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        items=items_tuple,
        keep_set=keep_set,
    )


def _build_focus(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], targets: List[str], fns: List[Tuple[str, Any]],
) -> FocusCommand:
    """
    FOCUS forms (v1.1.2):
        focus @app                  → activate app
        focus @app title("…")       → activate + raise matching window
        focus @app display(N|"name") → activate + move all windows to display
        focus active                → no-op (frontmost is already focused)
        focus "App Name"            → activate by literal name
    """
    fn_dict = dict(fns)
    title = fn_dict.get("title")

    # ── Runtime-target keyword (`active`) ─────────────────────────────
    if body:
        head_lower = body[0].lower()
        if head_lower == "active":
            return FocusCommand(
                line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
                target_keyword="active",
                title=title,
            )

    primary = body[0] if body else (targets[0] if targets else None)

    display_target: Optional[Any] = None
    if "display" in fn_dict:
        display_target = _coerce_display_filter(fn_dict["display"])

    return FocusCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        target=_unquote(primary) if primary else None,
        title=title,
        targets=tuple(targets),
        display_target=display_target,
    )


def _coerce_display_filter(arg: Any) -> Any:
    """Display filter accepts int (index, 1-based), str (substring), or 'ext'."""
    if arg is None:
        return None
    if isinstance(arg, int):
        return arg
    if isinstance(arg, float):
        return int(arg)
    if isinstance(arg, str):
        s = arg.strip().strip('"').strip("'")
        if s.isdigit():
            return int(s)
        return s
    return arg


def _normalize_except_arg(arg: Any, targets: List[str]) -> frozenset:
    """
    Translate the inside of `except(...)` into a flat FrozenSet of app
    names. Accepts (per spec Q5):

        except(@bundle)        → expanded list from settings.TARGETS
        except([list])         → flatten each item
        except(@target)        → single name
        except("App Name")     → single name

    Bundle expansion is delegated to the resolver layer so this parser
    stays import-light. We just return the raw token form here; the
    resolver does the actual TARGETS lookup.

    `targets` is the list of @ tokens already peeled out by _split_args
    (in case the user wrote `hide @work except(@chrome)` — though that
    combo isn't supported, defensive).
    """
    # `arg` shapes from _coerce_function_args:
    #   - tuple of strings (multiple comma-separated values)
    #   - single string (one value)
    #   - None (empty parens)
    #   - dict / nested tuple (unlikely here)
    raw_items: List[str] = []
    if arg is None:
        return frozenset()
    if isinstance(arg, tuple):
        raw_items.extend(str(x) for x in arg)
    elif isinstance(arg, list):
        raw_items.extend(str(x) for x in arg)
    elif isinstance(arg, str):
        # Could be "@bundle", "@target", "App Name", or "[a, b]"
        flat = _flatten_collection(arg)
        if flat:
            raw_items.extend(flat)
        else:
            raw_items.append(_unquote(arg))
    else:
        raw_items.append(str(arg))

    return frozenset(s for s in raw_items if s)


def _build_click(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], fns: List[Tuple[str, Any]],
) -> ClickCommand:
    text = next((v for (n, v) in fns if n == "text"), None)
    selector = next((v for (n, v) in fns if n == "selector"), None)
    pos = next((v for (n, v) in fns if n == "position"), None)
    x = y = None
    if isinstance(pos, tuple) and len(pos) == 2:
        try:
            x, y = int(pos[0]), int(pos[1])
        except Exception:
            pass

    if text or selector or pos:
        return ClickCommand(
            line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
            text=text, selector=selector, x=x, y=y,
        )

    if not body:
        return ClickCommand(line_no=line_no, raw=raw, tags=tags, functions=tuple(fns))

    head = body[0]
    coord = _COORD_RE.match(head)
    if coord:
        return ClickCommand(
            line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
            x=int(coord.group(1)), y=int(coord.group(2)),
        )
    return ClickCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        selector=" ".join(body),
    )


def _build_press(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], fns: List[Tuple[str, Any]],
) -> PressCommand:
    if not body:
        return PressCommand(line_no=line_no, raw=raw, tags=tags, functions=tuple(fns))

    head = body[0]
    seq = _SEQ_TOKEN_RE.match(head)
    if seq:
        keys = _parse_press_sequence(seq.group(1))
    else:
        keys = (_parse_key_token(head),) if _KEY_TOKEN_RE.match(head) else ()
    return PressCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        keys=keys,
    )


def _build_screenshot(
    line_no: int, raw: str, body: List[str],
    tags: FrozenSet[str], fns: List[Tuple[str, Any]],
) -> ScreenshotCommand:
    """
    SCREENSHOT forms (v1.1.2):
        screenshot                          → default → settings dir
        screenshot to("~/x.png")            → explicit path (canonical)
        screenshot active                   → frontmost-window capture
        screenshot display(N|"name")        → by display
        screenshot window("…")              → by window title
        screenshot area(x,y,w,h)            → by region

    The legacy positional `screenshot "~/x.png"` form is REJECTED by
    the validator with a hint to use `to("…")` (parity with `save … to(…)`).
    """
    fn_dict = dict(fns)

    display_arg = fn_dict.get("display")
    display = _coerce_display_filter(display_arg) if display_arg is not None else None

    window = fn_dict.get("window")

    area_raw = fn_dict.get("area")
    area = None
    if isinstance(area_raw, tuple) and len(area_raw) == 4:
        try:
            area = (int(area_raw[0]), int(area_raw[1]),
                    int(area_raw[2]), int(area_raw[3]))
        except Exception:
            area = None

    # v1.1.2 — `to(...)` is the canonical sink.
    to_path = fn_dict.get("to")
    path: Optional[str] = None
    if to_path is not None:
        path = _unquote(str(to_path))

    # Runtime-target keyword (`active`)
    target_keyword: Optional[str] = None
    if body and body[0].lower() == "active":
        target_keyword = "active"

    return ScreenshotCommand(
        line_no=line_no, raw=raw, tags=tags, functions=tuple(fns),
        path=path,
        display=display,
        window=window,
        area=area,
        target_keyword=target_keyword,
    )


# =========================================================
# 🛠️ HELPERS
# =========================================================

def _collapse_multiline_run_blocks(lines: List[str]) -> List[str]:
    """
    Collapse:

        run applescript if(error) notify(result)
        +++
        ...
        +++

    into one parser line with a JSON-quoted script payload.
    """
    out: List[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        if (raw or "").strip().lower().startswith("run applescript"):
            j = i + 1
            if j < len(lines) and (lines[j] or "").strip() == "+++":
                script_lines = []
                j += 1
                while j < len(lines) and (lines[j] or "").strip() != "+++":
                    script_lines.append(lines[j])
                    j += 1
                if j < len(lines):
                    j += 1  # consume closing +++
                out.append(raw + " " + json.dumps("\n".join(script_lines)))
                i = j
                continue
        out.append(raw)
        i += 1
    return out


def _run_backend_function(fns: List[Tuple[str, Any]]) -> Optional[Tuple[str, Any]]:
    for name, value in fns:
        if name in {"btt", "shortcut", "alfred", "applescript"}:
            return name, value
    return None


def _run_function_value(fns: List[Tuple[str, Any]], name: str) -> Any:
    for fn_name, value in reversed(fns):
        if fn_name == name:
            return value
    return None


def _run_timeout(fns: List[Tuple[str, Any]]) -> Optional[float]:
    value = _run_function_value(fns, "timeout")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except Exception:
        return None


def _parse_alfred_value(value: Any) -> Tuple[str, str, str]:
    if isinstance(value, tuple):
        args = [str(v) for v in value if v is not None]
        return _parse_alfred_args(args)
    return _parse_alfred_args([str(value or "")])


def _extract_run_script(body_args: List[str]) -> str:
    action_words = {"applescript", "save", "append", "copy", "notify"}
    for token in reversed(body_args):
        if token.lower() not in action_words:
            return _unquote(token)
    return ""


def _parse_run_handlers(args: List[str]) -> Tuple[Tuple[str, str, str], ...]:
    handlers: List[Tuple[str, str, str]] = []
    i = 0
    while i < len(args):
        parsed = _parse_function_token(args[i])
        if not parsed or parsed[0] != "if":
            i += 1
            continue

        condition = str(parsed[1] or "").strip().lower()
        i += 1
        if i >= len(args):
            break

        token = args[i]
        action = token.lower()
        action_fn = _parse_function_token(token)
        if action_fn and action_fn[0] in {"notify", "copy"}:
            value = _run_handler_value(action_fn[1])
            handlers.append((condition, action_fn[0], value))
            i += 1
            continue

        if action in {"notify", "copy"}:
            handlers.append((condition, action, ""))
            i += 1
            continue

        if action in {"save", "append"}:
            destination = ""
            if i + 1 < len(args):
                next_fn = _parse_function_token(args[i + 1])
                if next_fn and next_fn[0] == "to":
                    destination = _run_handler_value(next_fn[1])
                    i += 1
            handlers.append((condition, action, destination))
            i += 1
            continue

        i += 1
    return tuple(handlers)


def _parse_function_token(token: str) -> Optional[Tuple[str, Any]]:
    m = _FUNCTION_CALL_RE.match(token)
    if not m:
        return None
    return m.group(1).lower(), _coerce_function_args(m.group(2).strip())


def _run_handler_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple):
        return " ".join(str(v) for v in value if v is not None)
    return str(value)

def _normalize_btt_trigger_arg(token: str) -> str:
    """
    Normalize `run btt("...")` trigger syntax.
    """
    text = (token or "").strip()
    return _unquote(text)


def _parse_shortcut_args(args: List[str]) -> Tuple[str, str]:
    if not args:
        return "", ""
    name = _unquote(args[0])
    input_text = _unquote(" ".join(args[1:])) if len(args) > 1 else ""
    return name, input_text


def _parse_alfred_args(args: List[str]) -> Tuple[str, str, str]:
    if not args:
        return "", "", ""

    first = _unquote(args[0])
    if "/" in first and len(args) >= 1:
        bundle_id, trigger = first.split("/", 1)
        argument = _unquote(" ".join(args[1:])) if len(args) > 1 else ""
        return bundle_id, trigger, argument

    bundle_id = first
    trigger = _unquote(args[1]) if len(args) > 1 else ""
    argument = _unquote(" ".join(args[2:])) if len(args) > 2 else ""
    return bundle_id, trigger, argument


def _split_args(
    args: List[str],
) -> Tuple[List[str], FrozenSet[str], List[str], List[Tuple[str, Any]]]:
    """
    Partition argument tokens into:
        body        → positional arguments (not @, #, or function-calls)
        tags        → frozenset of #tags (lowercased)
        targets     → @ tokens (lowercased)
        functions   → list of (name, value) tuples preserving order
                      value is str | int | float | tuple of args

    v1.1.2 changes:
        - function-shaped layout tokens (`display(...)`, `left(...)`, etc.)
          are also promoted into `tags` (as if the `#` was present), so the
          layout resolver picks them up. They stay in `functions` too — that
          way HIDE/FOCUS can use the same parsed value as a filter.
        - bare runtime targets (`active`, `all`) flow through to `body`
          unchanged; the per-verb builder converts them to `target_keyword`.
    """
    body: List[str] = []
    tags: List[str] = []
    targets: List[str] = []
    functions: List[Tuple[str, Any]] = []

    for token in args:
        if _HASHTAG_RE.match(token):
            tags.append(token.lower())
            continue
        if _AT_RE.match(token):
            targets.append(token.lower())
            continue
        m = _FUNCTION_CALL_RE.match(token)
        if m:
            name = m.group(1).lower()
            inner = m.group(2).strip()
            value = _coerce_function_args(inner)
            functions.append((name, value))
            # v1.1.2 — `#` drop sugar: promote layout-named function calls
            # to tags so the existing layout resolver sees them. The tag
            # is reconstructed in the canonical `#name(args)` form.
            if name in _LAYOUT_FN_NAMES:
                tags.append(f"#{name}({inner})".lower())
            continue
        # v1.5.2 — bare parenless layout words (`full`, `left`, …) are
        # drop-sugar for their `#tag` forms. Quoted tokens never reach
        # this branch as bare words (the token still carries quotes).
        if token.lower() in _BARE_LAYOUT_WORDS:
            tags.append(f"#{token.lower()}")
            continue
        body.append(token)

    return body, frozenset(tags), targets, functions


def _coerce_function_args(inner: str) -> Any:
    """
    Parse the inside of `name(...)` into a Python value.

    - "x"           → "x"            (single quoted string)
    - 1, 2, 3       → (1, 2, 3)      (ints)
    - 0.1s          → 0.1            (seconds, normalized)
    - clipboard     → "clipboard"    (bare identifier)
    - "a", "b"      → ("a", "b")     (tuple of strings)
    """
    if inner == "":
        return None

    parts = _split_top_level(inner, sep=",")
    if len(parts) == 1:
        return _coerce_single(parts[0].strip())
    return tuple(_coerce_single(p.strip()) for p in parts)


def _coerce_single(token: str) -> Any:
    if not token:
        return None
    if _QUOTED_RE.match(token):
        return _unquote(token)
    m = _TIME_RE.match(token)
    if m:
        v = float(m.group(1))
        unit = (m.group(2) or "s").lower()
        if unit == "ms":
            return v / 1000.0
        if unit == "m":
            return v * 60.0
        if unit == "h":
            return v * 3600.0
        return v
    if token.lstrip("-").isdigit():
        try:
            return int(token)
        except Exception:
            return token
    try:
        return float(token)
    except Exception:
        return token


def _split_top_level(s: str, sep: str = ",") -> List[str]:
    """Split s by sep, respecting (), [], {}, "", ''."""
    parts: List[str] = []
    buf: List[str] = []
    quote = ""
    paren = brace = bracket = 0
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren += 1; buf.append(ch)
        elif ch == ")":
            paren = max(0, paren - 1); buf.append(ch)
        elif ch == "{":
            brace += 1; buf.append(ch)
        elif ch == "}":
            brace = max(0, brace - 1); buf.append(ch)
        elif ch == "[":
            bracket += 1; buf.append(ch)
        elif ch == "]":
            bracket = max(0, bracket - 1); buf.append(ch)
        elif ch == sep and not (paren or brace or bracket):
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _normalize_wait(token: str) -> float:
    """Accept `5`, `5s`, `5m`, `wait(5s)` (already de-wrapped by caller)."""
    inner = token
    fc = _FUNCTION_CALL_RE.match(token)
    if fc:
        inner = fc.group(2).strip()
    m = _TIME_RE.match(inner)
    if not m:
        return float(PLUS_DEFAULT_WAIT)
    value = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    if unit == "ms":
        return value / 1000.0
    if unit == "m":
        return value * 60.0
    if unit == "h":
        return value * 3600.0
    return value


def _flatten_collection(token: str) -> Tuple[str, ...]:
    """Parse `[a,b,c]` → ('a','b','c'); returns () for non-collections."""
    if not token:
        return ()
    m = _SEQ_TOKEN_RE.match(token)
    if not m:
        return ()
    inner = m.group(1).strip()
    if not inner:
        return ()
    parts = _split_top_level(inner, sep=",")
    return tuple(_unquote(p.strip()) for p in parts)


def _parse_key_token(token: str) -> Any:
    """`{enter}` → ('key','enter');  `{cmd+shift+tab}` → ('combo', ('cmd','shift','tab'))."""
    m = _KEY_TOKEN_RE.match(token)
    if not m:
        return ("invalid", token)
    inner = m.group(1).strip()
    if "+" in inner:
        return ("combo", tuple(p.strip().lower() for p in inner.split("+") if p.strip()))
    return ("key", inner.lower())


def _parse_press_sequence(inner: str) -> Tuple[Any, ...]:
    """Parse `[{a}, ({b})x5, {c}]` interior into ordered key entries."""
    parts = _split_top_level(inner, sep=",")
    out: List[Any] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        rep = _REP_RE.match(p)
        if rep:
            inner_tok = rep.group(1)
            count = int(rep.group(2))
            base = _parse_key_token(inner_tok if inner_tok.startswith("{")
                                    else "{" + inner_tok.strip("()") + "}")
            out.append(("rep", base, count))
            continue
        if _KEY_TOKEN_RE.match(p):
            out.append(_parse_key_token(p))
            continue
        # Strip outer parens for grouping
        if p.startswith("(") and p.endswith(")"):
            inner_p = p[1:-1].strip()
            if _KEY_TOKEN_RE.match(inner_p):
                out.append(_parse_key_token(inner_p))
                continue
        out.append(("invalid", p))
    return tuple(out)


def _unquote(text: str) -> str:
    if not text:
        return ""
    m = _QUOTED_RE.match(text)
    if m:
        try:
            return json.loads(text)
        except Exception:
            return m.group(1) if m.group(1) is not None else m.group(2) or ""
    return text
