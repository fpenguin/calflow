"""
Plus Mode DSL Validator (v2.0).

Grammar (line-based, one command per line, case-insensitive verbs):

    open <url|app|file> [@target] [#tag ...]
    focus <app|@target> [title("…")] [#tag ...]
    close <app|"name"> | close [list] | close except(<…>)
    hide | hide <app|@target> | hide [list] | hide except(<…>) [display(N)] | hide display(N)
    click <selector> | click x,y |
        click text("…") [selector("…") | position(x,y)] [#tag ...]
    type "<text>"  |  type("<text>") [speed(s)] [interval(s)] [repeat(N)] [timeout(s)]
    press {key} | press {a+b+c} | press [{a},({b})xN,{c}]
    wait <seconds>  |  wait <Ns|Nm|Nh>  |  wait(<…>)
    screenshot [<path>] | screenshot display(N) | screenshot window("…") |
        screenshot area(x,y,w,h)
    copy
    paste
    save source(<…>) to("<path>")
    run "<path>"

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
    "TYPE":       (1, None),
    "PRESS":      (1, None),
    "WAIT":       (1, 1),
    "SCREENSHOT": (0, None),
    "COPY":       (0, 0),
    "PASTE":      (0, 0),
    "SAVE":       (0, None),
    "RUN":        (1, 1),
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
    elif verb in {"CLICK", "SAVE"}:
        # CLICK / SAVE can use function-calls as their effective payload
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
        # focus needs a window-targeting argument: @target, "App Name",
        # or title("…") via functions. display() is HIDE-only (per spec
        # decision Q3 — focus is window-level, not display-level).
        head = body[0] if body else ""
        has_target = _TARGET_RE.match(head) or _QUOTED_RE.match(head)
        has_title  = any(
            _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("title(")
            for fc in functions
        )
        # Reject focus display(...) explicitly with a clear hint
        if any(_FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("display(")
               for fc in functions):
            errors.append(
                ValidationError(
                    line_no,
                    "FOCUS does not accept display(N) — focus needs a window "
                    "target (@app, \"App Name\", or title(\"…\")). The "
                    "display() filter is HIDE-only.",
                )
            )
        elif not (has_target or has_title or targets):
            errors.append(
                ValidationError(
                    line_no,
                    'FOCUS expects @target or "App Name"; got nothing useful',
                )
            )

    elif verb == "CLOSE":
        # close [list] | close @app | close "App" | close except(<arg>)
        # Bare `close` is rejected — too destructive without an explicit
        # target or filter.
        head = body[0] if body else ""
        has_positional = body or targets  # @target shorthand allowed
        has_except = any(
            _FUNCTION_CALL_RE.match(fc) and fc.lower().startswith("except(")
            for fc in functions
        )
        if not (has_positional or has_except):
            errors.append(
                ValidationError(
                    line_no,
                    "CLOSE requires an argument: a list, @target, "
                    "\"App Name\", or except(<arg>). Bare `close` is not "
                    "allowed (too destructive).",
                )
            )
        elif body and not (
            _QUOTED_RE.match(head) or _TARGET_RE.match(head) or _SEQUENCE_RE.match(head)
        ):
            errors.append(
                ValidationError(
                    line_no,
                    f'CLOSE expects @target, "App Name", or [list]; got {head!r}',
                )
            )

    elif verb == "HIDE":
        # New (v1.1+) syntax:
        #   hide                          ← bare = hide all (except frontmost)
        #   hide @app | hide "App" | hide [list]
        #   hide except(<arg>) [display(N)]
        # Old (v1.0) syntax `hide all` / `hide all except @x` is HARD-FAIL.
        head = body[0] if body else ""
        if head.lower() == "all":
            errors.append(
                ValidationError(
                    line_no,
                    '`hide all` and `hide all except @x` were removed in v1.1. '
                    'Use bare `hide` to hide everything except the frontmost, '
                    'or `hide except(@bundle)` / `hide except([list])` to '
                    'keep specific apps visible.',
                )
            )
        elif body and not (
            _QUOTED_RE.match(head)
            or _TARGET_RE.match(head)
            or _SEQUENCE_RE.match(head)
        ):
            errors.append(
                ValidationError(
                    line_no,
                    f'HIDE expects @target, "App Name", [list], or no '
                    f'argument (bare hide); got {head!r}',
                )
            )

    elif verb == "CLICK":
        # Function-call form is the spec-preferred shape:
        #   click text("X") | click selector(".y") | click position(1,2)
        # We also accept the bare forms `click .y`, `click x,y`.
        if functions:
            # Function-call modifiers like text("…")/selector("…")/position(…)
            # are accepted; unknown modifiers are tolerated (forward-compat).
            pass
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
        # Optional path / display(N) / window("…") / area(…) — all OK
        pass

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
        head = body[0]
        if not (_QUOTED_RE.match(head) or _FILE_PATH_RE.match(head)):
            errors.append(
                ValidationError(
                    line_no,
                    'RUN expects a quoted path, e.g. run "~/scripts/x.sh"',
                )
            )

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
