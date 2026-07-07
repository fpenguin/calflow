"""
Plus Mode DSL Validator (v1.1.2).

Grammar (line-based, one command per line, case-insensitive verbs):

    open <url|app|file> [@target] [#tag ...]
    focus <app|@target> [title("…")] [display(N|"name")] [#tag ...]
    focus active
    close <app|"name"|@target> | close [list] | close except(<…>) | close active | close all
    hide <app|@target|"name"> | hide [list] | hide except(<…>) [display(N|"name")] | hide display(N|"name") | hide active | hide all
    click <selector> | click x,y |
        click text("…") [selector("…") | position(x,y)] [#tag ...]
    type "<text>"  |  type("<text>") [speed(s)] [interval(s)] [repeat(N)] [timeout(s)]
    press {key} | press {a+b+c} | press [{a},({b})xN,{c}]
    wait <seconds>  |  wait <Ns|Nm|Nh>  |  wait(<…>)
    screenshot | screenshot to("<path>") | screenshot active |
        screenshot display(N|"name") | screenshot window("…") | screenshot area(x,y,w,h)
    copy
    paste
    save source(<…>) to("<path>")
    run btt("<named-trigger>")
    run shortcut("<shortcut name>") [input("input text")]
    run alfred("<workflow.bundle.id>", "<external-trigger-id>") [input("argument")]
    run applescript [timeout(10)] [if(error) notify(result)]

v1.1.2 hard-fails:
    - bare `hide`              → use `hide except(active)` / `hide all`
    - bare `close`             → too destructive without target
    - `hide all except @x`     → use `hide except(@x)`
    - `screenshot "<path>"`    → use `screenshot to("<path>")`
    - `{active}` / `{@x}` / `{display(N)}` → `{}` is for dynamic values only;
                                              use bare `active`, `@x`, `display(N)`

Rules:
- Lines are stripped; blank lines and `## comments` are ignored.
- Verbs are case-insensitive.
- Smart Mode standalone tag/target lines (validated separately) are NOT
  classified as syntax errors here; this validator runs ONLY on Plus body.
- Implicit `open` is allowed: a line starting with a URL/domain/known
  scheme is normalized to an OPEN command upstream (parser handles it),
  so this validator accepts that shape too.
- Multiple `@` targets on a single command → invalid.

Design:
- pure functions, zero IO
- never raises (returns ValidationError list)
"""

from __future__ import annotations

import re
from typing import List, Tuple

from config.settings import PLUS_MAX_COMMANDS
from core.models import ValidationError
from core.utils import strip_inline_comment


# =========================================================
# 📚 GRAMMAR TABLE
# =========================================================

# verb → (min_positional, max_positional | None)
# `min_positional` counts BODY tokens + @targets + named-function args
# combined; the verb-specific check below decides which combinations
# are actually legal.
KNOWN_COMMANDS: dict = {
    "OPEN":       (1, None),
    "FOCUS":      (1, None),
    "CLOSE":      (0, None),  # arity gate handled per-verb (allows `close except(<…>)`)
    "HIDE":       (0, None),  # bare `hide` is legal (= hide all-except-frontmost)
    "CLICK":      (1, None),
    "DRAG":       (2, None),  # v1.5.4 — from(x,y) + to(x,y) required
    "TYPE":       (1, None),
    "PRESS":      (1, None),
    "WAIT":       (1, 1),
    "SCREENSHOT": (0, None),
    "COPY":       (0, 1),  # v1.5.2 — copy("text") literal form
    "PASTE":      (0, 0),
    "SAVE":       (0, None),
    "RUN":        (1, None),
}

# Pre-compiled patterns
_COORD_RE = re.compile(r"^-?\d+\s*,\s*-?\d+$")
_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
_TIME_RE = re.compile(r"^\d+(\.\d+)?(s|m|h|ms)?$", re.IGNORECASE)
_QUOTED_RE = re.compile(r'^".*"$|^\'.*\'$')
_FUNCTION_CALL_RE = re.compile(r"^[A-Za-z_][\w\-]*\(.*\)$")
_KEY_TOKEN_RE = re.compile(r"^\{[^{}]+\}$")
_SEQUENCE_RE = re.compile(r"^\[.*\]$")
_TAG_RE = re.compile(r"^#\w[\w\-=()%.,@/]*$")
_TARGET_RE = re.compile(r"^@\w[\w\-]*$")
_URL_HINT_RE = re.compile(r"://|^[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)
_FILE_PATH_RE = re.compile(r'^"?[~/]')

# v1.1.2 — `{ … }` is reserved for dynamic VALUE expressions only.
# Wrapping a runtime target / alias / filter in `{}` (`{active}`,
# `{@work}`, `{display(2)}`) is rejected per the type-system contract.
_RESERVED_RUNTIME_TARGETS = frozenset({"active", "all"})
_RESERVED_FILTER_NAMES = frozenset({"display", "except"})
_DYNAMIC_BLOCK_RE = re.compile(r"\{([^{}]+)\}")


# =========================================================
# 🧪 PUBLIC API
# =========================================================

def validate_plus_block(lines: List[str]) -> List[ValidationError]:
    """
    Validate a list of body lines (header already stripped by caller).
    Returns a list of ValidationError (possibly empty).
    """
    errors: List[ValidationError] = []
    seen_commands = 0

    for idx, raw in enumerate(lines, start=1):
        line = strip_inline_comment(raw or "").strip()
        if not line:
            continue

        seen_commands += 1
        line_errors = validate_plus_line(line, idx)
        errors.extend(line_errors)

    if seen_commands > PLUS_MAX_COMMANDS:
        errors.append(
            ValidationError(
                0,
                f"Plus block exceeds PLUS_MAX_COMMANDS ({PLUS_MAX_COMMANDS}): "
                f"{seen_commands} commands present.",
            )
        )

    return errors


def validate_plus_line(line: str, line_no: int) -> List[ValidationError]:
    """Validate one non-empty Plus DSL line; returns 0+ ValidationError."""
    errors: List[ValidationError] = []

    tokens = tokenize(line)
    if not tokens:
        return errors

    # v1.1.2 — type-system guard: reject `{<runtime-target>}` /
    # `{<alias>}` / `{<filter>}`. `{}` is for dynamic VALUES only
    # (`{now}`, `{now-7d > YYYY-MM-DD}`).
    for tok in tokens:
        for inner in _DYNAMIC_BLOCK_RE.findall(tok):
            stripped = inner.strip().lower()
            base = stripped.split("(", 1)[0].strip().lstrip("@")
            looks_dynamic = (
                stripped.startswith("now")
                or stripped.startswith(("+", "-"))
                or any(t in stripped for t in (" > ", ">", "format("))
            )
            if looks_dynamic:
                continue
            if (
                base in _RESERVED_RUNTIME_TARGETS
                or base in _RESERVED_FILTER_NAMES
                or stripped.startswith("@")
            ):
                errors.append(
                    ValidationError(
                        line_no,
                        f"`{{{inner}}}` is invalid — `{{ … }}` is for dynamic "
                        f"VALUE expressions only (e.g. `{{now}}`). Use bare "
                        f"`{inner.strip()}` instead. "
                        f"(See type-system rules in DSL_SPEC §7.)",
                    )
                )
                return errors

    # Detach `verb(...)` when verb name and parens are stuck together
    # (e.g. `type("hi")`, `wait(5s)`, `screenshot(area(0,0,1,1))`).
    tokens = _split_verb_function(tokens)

    verb_tok = tokens[0]
    args = tokens[1:]

    # Implicit open: line starts with a URL or quoted string or `~/path`
    if not _is_known_verb(verb_tok):
        if (
            _URL_HINT_RE.search(verb_tok)
            or _QUOTED_RE.match(verb_tok)
            or _FILE_PATH_RE.match(verb_tok)
        ):
            return errors  # parser will normalize to OPEN
        # Standalone modifier line in Plus Mode (e.g. `#display(2)` alone or
        # `@chrome` alone) → silently ignored per parser-behavior §5.10 /
        # DSL_GRAMMAR §3.2 (Plus Mode has no global state).
        if all(_TAG_RE.match(t) or _TARGET_RE.match(t) for t in tokens):
            return errors
        errors.append(
            ValidationError(line_no, f"unknown command {verb_tok!r}")
        )
        return errors

    verb = verb_tok.upper()
    min_args, max_args = KNOWN_COMMANDS[verb]

    body, _tags, targets, functions = _split_args(args)

    # @target counts as a positional for OPEN/FOCUS/CLOSE/HIDE
    # (e.g., `open @work`, `focus @chrome`, `hide @chrome` are all valid).
    # Function-call tokens (`title("…")`, `text("…")`, etc.) are modifiers,
    # not positionals — they don't satisfy arity by themselves.
    if verb in {"OPEN", "FOCUS", "CLOSE", "HIDE"}:
        positional_count = len(body) + len(targets)
    elif verb in {"CLICK", "DRAG", "SAVE", "RUN"}:
        # CLICK / DRAG / SAVE use function-calls as their effective payload
        positional_count = len(body) + len(functions)
    else:
        positional_count = len(body)

    if positional_count < min_args:
        errors.append(
            ValidationError(
                line_no,
                f"{verb} requires at least {min_args} argument(s), got {positional_count}",
            )
        )
        return errors

    if max_args is not None and positional_count > max_args:
        errors.append(
            ValidationError(
                line_no,
                f"{verb} accepts at most {max_args} argument(s), got {positional_count}",
            )
        )
        return errors

    if len(targets) > 1:
        errors.append(
            ValidationError(line_no, "multiple @targets are not allowed")
        )
        return errors

    # Build a "primary" view for verbs that can take @target as primary.
    primary_for: List[str] = []
    if verb in {"OPEN", "FOCUS", "CLOSE", "HIDE"} and not body and targets:
        primary_for = [targets[0]]
        body = primary_for + body  # treat @target as the head positional

    # Verb-specific shape checks
    if verb == "OPEN":
        head = body[0]
        if not (
            _URL_HINT_RE.search(head)
            or _QUOTED_RE.match(head)
            or _FILE_PATH_RE.match(head)
            or _TARGET_RE.match(head)
            or head.lower() == "@" + head.lstrip("@")  # @target as primary
        ):
            errors.append(
                ValidationError(
                    line_no,
                    f"OPEN expects a URL, quoted name, file path, or @target; got {head!r}",
                )
            )

    elif verb == "FOCUS":
        # v1.1.2:
        #   focus @app | focus @app title("…") | focus @app display(N|"name")
        #   focus active                       (no-op runtime target)
        head = body[0] if body else ""
        head_lower = head.lower()
        if head_lower == "active":
            # `focus active` is a no-op runtime target — accept it; resolver
            # will short-circuit at exec time.
            pass
        else:
            has_target = _TARGET_RE.match(head) or _QUOTED_RE.match(head)
            has_title  = any(
                _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("title(")
                for fc in functions
            )
            if not (has_target or has_title or targets):
                errors.append(
                    ValidationError(
                        line_no,
                        'FOCUS expects @target, "App Name", or `active`; '
                        'got nothing useful',
                    )
                )

    elif verb == "CLOSE":
        # v1.1.2:
        #   close active | close all                   (runtime targets)
        #   close @app | close "App" | close [list]    (explicit items)
        #   close except(<arg>)                        (filter form)
        # Bare `close` (no body / @target / except) is rejected — too
        # destructive without an explicit target or filter.
        head = body[0] if body else ""
        head_lower = head.lower()
        is_runtime_kw = head_lower in _RESERVED_RUNTIME_TARGETS
        has_positional = body or targets
        has_except = any(
            _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("except(")
            for fc in functions
        )
        if not (has_positional or has_except):
            errors.append(
                ValidationError(
                    line_no,
                    "CLOSE requires an argument: `active`, `all`, a list, "
                    "@target, \"App Name\", or except(<arg>). Bare `close` "
                    "is not allowed (too destructive).",
                )
            )
        elif body and not (
            is_runtime_kw
            or _QUOTED_RE.match(head)
            or _TARGET_RE.match(head)
            or _SEQUENCE_RE.match(head)
        ):
            errors.append(
                ValidationError(
                    line_no,
                    f'CLOSE expects `active`, `all`, @target, "App Name", '
                    f'or [list]; got {head!r}',
                )
            )

    elif verb == "HIDE":
        # v1.1.2 grammar:
        #   hide active | hide all                 (runtime targets)
        #   hide @app | hide "App" | hide [list]   (explicit items)
        #   hide except(<arg>) [display(N|"name")] (filter form)
        #   hide display(N|"name")                 (display-only filter)
        #
        # Bare `hide` (no body, no @target, no except, no display) is
        # HARD-FAIL — the v1.1.1 form was removed. Old `hide all except @x`
        # also hard-fails (already rejected by `head == "all"` + extra body).
        head = body[0] if body else ""
        head_lower = head.lower()
        has_except = any(
            _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("except(")
            for fc in functions
        )
        has_display = any(
            _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("display(")
            for fc in functions
        )

        # Detect old `hide all except @x` shape: head=="all" AND extra body OR
        # head=="all" AND `except` function present.
        if head_lower == "all" and (len(body) > 1 or has_except):
            errors.append(
                ValidationError(
                    line_no,
                    '`hide all except @x` was removed in v1.1. Use '
                    '`hide except(@x)` (the `all` is implied by `except`). '
                    'For "hide every visible app including frontmost", use '
                    'bare `hide all` (no except).',
                )
            )
        elif not (body or targets or has_except or has_display):
            # Bare `hide` was removed in v1.1.2.
            errors.append(
                ValidationError(
                    line_no,
                    'Bare `hide` was removed in v1.1.2. Use one of:\n'
                    '  hide except(active)   ← keep frontmost visible\n'
                    '  hide all              ← hide every visible app\n'
                    '  hide @app             ← hide one app\n'
                    '  hide [a, b]           ← hide a list\n'
                    '  hide except(@bundle)  ← keep an alias visible',
                )
            )
        elif body and not (
            head_lower in _RESERVED_RUNTIME_TARGETS
            or _QUOTED_RE.match(head)
            or _TARGET_RE.match(head)
            or _SEQUENCE_RE.match(head)
        ):
            errors.append(
                ValidationError(
                    line_no,
                    f'HIDE expects `active`, `all`, @target, "App Name", or '
                    f'[list]; got {head!r}',
                )
            )

    elif verb == "CLICK":
        # Function-call form is the spec-preferred shape:
        #   click text("X") | click selector(".y") | click position(1,2)
        # We also accept the bare forms `click .y`, `click x,y`.
        if functions:
            # Function-call modifiers like text("…")/selector("…")/position(…)
            # are accepted; unknown modifiers are tolerated (forward-compat).
            # v1.5.4 — button()/count() carry constrained value sets;
            # a typo'd value must fail loudly, not silently left-click.
            errors.extend(_check_gesture_functions(line_no, "CLICK", functions))
        elif body:
            head = body[0]
            if not (_COORD_RE.match(head) or _looks_like_selector(head)):
                errors.append(
                    ValidationError(
                        line_no,
                        f"CLICK expects a selector, 'x,y', or text(\"…\")/selector(\"…\")/position(x,y); got {head!r}",
                    )
                )
        # else: arity check above already complained.

    elif verb == "DRAG":
        # v1.5.4 — one mouse gesture with two endpoints:
        #   drag from(x,y) to(x,y) [button(…)] [duration(t)]
        # Element-based endpoints (from(text("…"))) are deferred to the
        # v2.1 backend; only coordinate pairs are legal today.
        fn_by_name = {}
        for fc in functions:
            m = _FUNCTION_CALL_RE.match(fc)
            if m:
                name = fc.split("(", 1)[0].lower()
                inner = fc.split("(", 1)[1].rstrip(")")
                fn_by_name[name] = inner
        for endpoint in ("from", "to"):
            if endpoint not in fn_by_name:
                errors.append(
                    ValidationError(
                        line_no,
                        f"DRAG requires both endpoints: "
                        f'`drag from(x,y) to(x,y)`; missing {endpoint}(…)',
                    )
                )
            elif not _COORD_RE.match(fn_by_name[endpoint].strip()):
                errors.append(
                    ValidationError(
                        line_no,
                        f"DRAG {endpoint}(…) expects coordinates 'x,y'; "
                        f"got {fn_by_name[endpoint]!r}",
                    )
                )
        errors.extend(_check_gesture_functions(line_no, "DRAG", functions))

    elif verb == "TYPE":
        # Accept `type "hi"` (quoted positional) or `type("hi")`
        # (the verb-function-call form is normalized so the inner
        # quoted token lands in body).
        if not body:
            errors.append(
                ValidationError(
                    line_no,
                    'TYPE expects a quoted string, e.g. type("hello world")',
                )
            )
        else:
            head = body[0]
            if not _QUOTED_RE.match(head):
                errors.append(
                    ValidationError(
                        line_no,
                        'TYPE expects a quoted string, e.g. type("hello world")',
                    )
                )

    elif verb == "PRESS":
        head = body[0]
        if _KEY_TOKEN_RE.match(head) or _SEQUENCE_RE.match(head):
            pass
        else:
            errors.append(
                ValidationError(
                    line_no,
                    "PRESS expects {key}, {combo}, or [sequence]",
                )
            )

    elif verb == "WAIT":
        head = body[0]
        # Accept `wait 5`, `wait 5s`; the `wait(5s)` form was already
        # split into `wait` + `5s` by _split_verb_function.
        if not _TIME_RE.match(head):
            errors.append(
                ValidationError(
                    line_no,
                    f"WAIT expects N or Ns/Nm/Nh; got {head!r}",
                )
            )

    elif verb == "SCREENSHOT":
        # v1.1.2:
        #   screenshot                          (default sink)
        #   screenshot to("<path>")             (canonical — mirrors save)
        #   screenshot active                   (frontmost-window capture)
        #   screenshot display(N|"name") | window("…") | area(x,y,w,h)
        #
        # Positional path was REMOVED in v1.1.2 — point users at to(...).
        if body:
            head = body[0]
            head_lower = head.lower()
            if head_lower == "active":
                pass  # runtime target — accepted
            elif _QUOTED_RE.match(head) or _FILE_PATH_RE.match(head):
                errors.append(
                    ValidationError(
                        line_no,
                        f'`screenshot {head}` (positional path) was removed in '
                        f'v1.1.2 — use `screenshot to({head})` instead. '
                        f'(Mirrors `save … to(…)`.)',
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        line_no,
                        f'SCREENSHOT expects no args, `active`, `to("<path>")`, '
                        f'`display(N)`, `window("…")`, or `area(…)`; got {head!r}',
                    )
                )

    elif verb == "COPY":
        # v1.5.2 — bare `copy` (selection) or copy("text") (literal).
        # An unquoted argument is ambiguous (identifier? app? typo?) —
        # reject with the canonical quoted form.
        if body and not _QUOTED_RE.match(body[0]):
            errors.append(
                ValidationError(
                    line_no,
                    f'COPY expects a quoted string, e.g. copy("hello"); '
                    f'got {body[0]!r}. Bare `copy` copies the current '
                    f'selection.',
                )
            )

    elif verb == "SAVE":
        # SAVE expects function-style args: source(...) to("…")
        if not functions:
            errors.append(
                ValidationError(
                    line_no,
                    'SAVE expects function args, e.g. save source(clipboard) to("~/x.png")',
                )
            )

    elif verb == "RUN":
        head = body[0] if body else ""
        run_backend = _run_backend_from_functions(functions)
        if run_backend:
            errors.extend(_validate_run_handlers(args, line_no))
            if run_backend == "btt":
                if not _function_value_present(functions, "btt"):
                    errors.append(
                        ValidationError(
                            line_no,
                            'RUN btt(...) expects one trigger name',
                        )
                    )
            elif run_backend == "shortcut":
                if not _function_value_present(functions, "shortcut"):
                    errors.append(
                        ValidationError(
                            line_no,
                            'RUN shortcut(...) expects one shortcut name',
                        )
                    )
            elif run_backend == "alfred":
                alfred_value = _function_inner(functions, "alfred")
                has_split_trigger = (
                    "," in alfred_value
                    or "/" in _strip_quotes(alfred_value)
                )
                if not alfred_value or not has_split_trigger:
                    errors.append(
                        ValidationError(
                            line_no,
                            'RUN alfred(...) expects workflow bundle id and external trigger id',
                        )
                    )
            elif run_backend == "applescript":
                pass
        elif head.lower() == "applescript":
            errors.extend(_validate_run_handlers(args, line_no))
        else:
            errors.append(
                ValidationError(
                    line_no,
                    'RUN expects function-style syntax, e.g. '
                    'run btt("Trigger"), run shortcut("Name"), '
                    'run alfred("bundle", "trigger"), or run applescript',
                )
            )
        if not run_backend and head.lower() not in {"applescript"}:
            errors.extend(_validate_run_handlers(args, line_no))

    return errors


# =========================================================
# 🛠️ TOKENIZER (public — reused by the parser)
# =========================================================

def tokenize(line: str) -> List[str]:
    """
    Shell-like tokenizer that preserves:
      - single- and double-quoted runs, including the quotes
      - parenthesized groups: `text("Hi there")`, `position(1, 2)`
      - braced groups:        `{cmd+shift+tab}`
      - bracketed groups:     `[{a},({b})x5,{c}]`

    Whitespace OUTSIDE all of those separates tokens.
    """
    tokens: List[str] = []
    buf: List[str] = []
    quote: str = ""
    paren = brace = bracket = 0
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            buf.append(ch)
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = ""
        elif ch in ('"', "'"):
            buf.append(ch)
            quote = ch
        elif ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren = max(0, paren - 1)
            buf.append(ch)
        elif ch == "{":
            brace += 1
            buf.append(ch)
        elif ch == "}":
            brace = max(0, brace - 1)
            buf.append(ch)
        elif ch == "[":
            bracket += 1
            buf.append(ch)
        elif ch == "]":
            bracket = max(0, bracket - 1)
            buf.append(ch)
        elif ch.isspace() and not (paren or brace or bracket):
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
        i += 1

    if buf:
        tokens.append("".join(buf))
    return tokens


# =========================================================
# 🔧 PRIVATE HELPERS
# =========================================================

def _is_known_verb(token: str) -> bool:
    return token.upper() in KNOWN_COMMANDS


_VERB_FUNCTION_RE = re.compile(r"^([A-Za-z_][\w\-]*)\((.*)\)$")


def _split_verb_function(tokens: List[str]) -> List[str]:
    """
    If the first token is `<verb>(<inner>)` AND `<verb>` is a known verb,
    rewrite tokens to `[verb, <inner>]` so downstream code can treat
    `type("hi")` and `type "hi"` uniformly.

    The inner content is split on top-level commas so `position(1,2)`-style
    nested calls survive intact while normal arguments stay positional.
    """
    if not tokens:
        return tokens
    head = tokens[0]
    m = _VERB_FUNCTION_RE.match(head)
    if not m:
        return tokens
    verb_part = m.group(1)
    if verb_part.upper() not in KNOWN_COMMANDS:
        return tokens
    inner = m.group(2).strip()
    if inner == "":
        return [verb_part] + tokens[1:]
    inner_args = _split_top_level_commas(inner)
    return [verb_part] + inner_args + tokens[1:]


def _split_top_level_commas(s: str) -> List[str]:
    """Split `s` on top-level commas, respecting (), [], {}, "", ''."""
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
            quote = ch; buf.append(ch)
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
        elif ch == "," and not (paren or brace or bracket):
            parts.append("".join(buf).strip()); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _is_comment(line: str) -> bool:
    """Comments start with `##` (double hash). Single `#` is a tag."""
    return line.startswith("##")


def _looks_like_selector(token: str) -> bool:
    """Loose CSS-selector heuristic — supports #id, .class, tag, attr, combinators."""
    if not token:
        return False
    if any(c in token for c in "#.[]>+~ "):
        return True
    return token.replace("-", "_").isidentifier()


_VALID_BUTTONS = frozenset({"left", "right", "middle"})


def _check_gesture_functions(line_no: int, verb: str, functions) -> List[ValidationError]:
    """
    v1.5.4 — shared value checks for the mouse gesture modifiers:

        button(left|right|middle)     default left
        count(1|2|3)                  CGEvent click-state; count(2) is
                                      ONE double-click event — distinct
                                      from repeat(2) = two single clicks

    Anything outside the value set is a hard error: a typo'd
    button(rigth) silently degrading to a left-click is the exact
    class of surprise the validator exists to prevent.
    """
    errors: List[ValidationError] = []
    for fc in functions:
        name = _function_name(fc)
        if name == "button":
            inner = fc.split("(", 1)[1].rstrip(")").strip().lower()
            if inner not in _VALID_BUTTONS:
                errors.append(
                    ValidationError(
                        line_no,
                        f"{verb} button(…) expects left, right, or middle; "
                        f"got {inner!r}",
                    )
                )
        elif name == "count":
            inner = fc.split("(", 1)[1].rstrip(")").strip()
            if not inner.isdigit() or not (1 <= int(inner) <= 3):
                errors.append(
                    ValidationError(
                        line_no,
                        f"{verb} count(…) expects 1 (single), 2 (double), "
                        f"or 3 (triple); got {inner!r}. For repeating the "
                        f"whole command use repeat(n).",
                    )
                )
    return errors


def _strip_quotes(token: str) -> str:
    if _QUOTED_RE.match(token):
        return token[1:-1]
    return token


def _function_name(token: str) -> str:
    m = re.match(r"^([A-Za-z_][\w\-]*)\((.*)\)$", token)
    return m.group(1).lower() if m else ""


def _function_inner(functions: List[str], name: str) -> str:
    prefix = name.lower() + "("
    for token in reversed(functions):
        if token.lower().startswith(prefix) and token.endswith(")"):
            return token[len(prefix):-1].strip()
    return ""


def _function_value_present(functions: List[str], name: str) -> bool:
    return bool(_function_inner(functions, name))


def _run_backend_from_functions(functions: List[str]) -> str:
    for token in functions:
        name = _function_name(token)
        if name in {"btt", "shortcut", "alfred", "applescript"}:
            return name
    return ""


def _validate_run_handlers(args: List[str], line_no: int) -> List[ValidationError]:
    errors: List[ValidationError] = []
    valid_conditions = {"error", "success", "output"}
    valid_actions = {"notify", "copy", "save", "append"}
    for i, token in enumerate(args):
        if _function_name(token) != "if":
            continue
        condition = _strip_quotes(_function_inner([token], "if")).lower()
        if condition not in valid_conditions:
            errors.append(
                ValidationError(
                    line_no,
                    f"RUN if(...) supports error, success, or output; got {condition!r}",
                )
            )
            continue
        if i + 1 >= len(args):
            errors.append(
                ValidationError(line_no, "RUN if(...) must be followed by a handler")
            )
            continue
        next_token = args[i + 1]
        action = _function_name(next_token) or next_token.lower()
        if action not in valid_actions:
            errors.append(
                ValidationError(
                    line_no,
                    "RUN handlers support notify, copy, save to(...), or append to(...)",
                )
            )
            continue
        if action in {"save", "append"}:
            if i + 2 >= len(args) or _function_name(args[i + 2]) != "to":
                errors.append(
                    ValidationError(
                        line_no,
                        f"RUN if({condition}) {action} requires to(\"PATH\")",
                    )
                )
    return errors


def _split_args(
    args: List[str],
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Split tokens into (positional/body, tags, targets, functions).

    Function-call tokens like `title("Inbox")`, `text("X")`, `selector(".y")`,
    `position(1,2)`, `to("…")`, `source(…)`, `repeat(N)`, `interval(s)`,
    `speed(s)`, `timeout(s)` are NOT positionals — they're modifiers.
    """
    body: List[str] = []
    tags: List[str] = []
    targets: List[str] = []
    functions: List[str] = []
    for token in args:
        if _TAG_RE.match(token) and not token.startswith("##"):
            tags.append(token)
        elif _TARGET_RE.match(token):
            targets.append(token)
        elif _FUNCTION_CALL_RE.match(token):
            functions.append(token)
        else:
            body.append(token)
    return body, tags, targets, functions
