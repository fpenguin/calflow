from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from core.dynamic import resolve_dynamic, resolve_dynamic_expr
from core.parser.parser import extract_url_entries, parse
from core.resolver import resolve_command, resolve_display, resolve_layout

# Contracts: DSL_GRAMMAR sections 3.3/7/9; DSL_SPEC sections 2.3/2.6/3.5/9.1;
# parser-behavior sections 4.2/6.2/6.4; approved reliability-followup-2026-10-10.
# AppleScript arguments are NOT an alternate payload syntax: only +++ fences
# are documented. Legacy # modifiers remain supported in both parser modes.
NOW = datetime(2026, 10, 10, 12, 30)
MODES = ("plus", "smart-inline", "smart-global")
INVALID_SCRIPTS = (
    pytest.param('run applescript("return 1")', id="quoted-inline-payload"),
    pytest.param("run applescript(return 1)", id="bare-inline-payload"),
    pytest.param("run applescript()", id="empty-inline-call"),
    pytest.param("run applescript\n+++\nreturn 1", id="unclosed-fence"),
    pytest.param("run applescript\n+++\n", id="unclosed-empty-fence"),
)


@pytest.fixture(autouse=True)
def isolated_parser_io(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    guards = []
    for target in (
        "subprocess.Popen",
        "subprocess.run",
        "os.system",
        "webbrowser.open",
        "socket.socket",
        "socket.create_connection",
    ):
        guard = Mock(side_effect=AssertionError(f"unexpected IO: {target}"))
        monkeypatch.setattr(target, guard)
        guards.append(guard)
    monkeypatch.setattr("runtime.actions.browser.MAC_AVAILABLE", False)
    for module in (
        "core.dynamic",
        "core.parser.parser",
        "core.parser.plus_parser",
        "core.parser.smart_parser",
        "core.resolver.resolver",
        "runtime.actions.browser",
    ):
        monkeypatch.setattr(f"{module}.log", Mock())
    monkeypatch.setattr("core.parser.plus_parser.PLUS_STRICT_VALIDATION", False)
    yield
    # Detect IO even if the public parser caught the guard's exception.
    for guard in guards:
        guard.assert_not_called()


def _parse_modifiers(mode: str, modifiers: str):
    if mode == "plus":
        return parse(f"+CalFlow+\nopen https://example.com {modifiers}")
    if mode == "smart-inline":
        return parse(f"https://example.com {modifiers}")
    return parse(f"{modifiers}\nhttps://example.com")


def _tags(mode: str, modifiers: str):
    result = _parse_modifiers(mode, modifiers)
    return result.commands[0].tags if mode == "plus" else result.entries[0]["tags"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", ("DELL", "Desk Panel"))
def test_legacy_quoted_display_reaches_resolver(mode: str, name: str) -> None:
    display = resolve_display(_tags(mode, f'#display("{name}")'))
    normalized = (display[0], display[1].casefold()) if display else None
    # v1.5.6 - regression: quoted legacy #display arguments disappeared in Plus.
    assert normalized == ("name", name.casefold())


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("percent", (False, True), ids=("pixels", "mixed-units"))
def test_legacy_spaced_area_reaches_resolver(mode: str, percent: bool) -> None:
    modifier = "#area(0, 0, 100, 50%)" if percent else "#area(0, 0, 100, 100)"
    # v1.5.6 - regression: spaces in #area must not silently discard the layout.
    assert resolve_layout(_tags(mode, modifier)) == {
        "type": "area",
        "x": {"value": 0.0, "unit": "pixel"},
        "y": {"value": 0.0, "unit": "pixel"},
        "w": {"value": 100.0, "unit": "pixel"},
        "h": {"value": 50.0 if percent else 100.0, "unit": "percent" if percent else "pixel"},
    }


@pytest.mark.parametrize("mode", MODES)
def test_layout_conflicts_follow_source_order_not_hash_order(mode: str) -> None:
    layouts = []
    # Checking BOTH orders in one test guarantees a failure for an unordered
    # tag set on every hash seed; repetition also catches first-seen deduping.
    for modifiers in (
        "#left(30) #right(70)",
        "#right(70) #left(30)",
        "#left(30) #right(70) #left(30)",
    ):
        result = _parse_modifiers(mode, modifiers)
        layout = (
            resolve_command(result.commands[0])["layout"]
            if mode == "plus"
            else resolve_layout(result.entries[0]["tags"])
        )
        layouts.append(layout)
    # v1.5.6 - regression: parser-behavior 6.4 says the LAST layout wins.
    assert layouts == [
        {"type": "right", "value": 0.7},
        {"type": "left", "value": 0.3},
        {"type": "left", "value": 0.3},
    ]


@pytest.mark.parametrize("mode", MODES)
def test_legacy_hashtags_keep_independent_categories(mode: str) -> None:
    modifiers = "#display(2) #left(30) #profile(2) #no-autofill #slow"
    # v1.5.6 - compatibility: repairs must not require hash-drop sugar.
    assert set(_tags(mode, modifiers)) == set(modifiers.split())


def test_v1_entry_api_keeps_legacy_hashtags() -> None:
    # v1.5.6 - compatibility: preserve the v1 callable and hashtag entry shape.
    assert extract_url_entries("https://example.com #display(2) #left(30)") == [
        {"url": "https://example.com", "tags": {"#display(2)", "#left(30)"}}
    ]


@pytest.mark.parametrize("source", INVALID_SCRIPTS)
def test_malformed_applescript_emits_line_diagnostic(source: str) -> None:
    result = parse("+CalFlow+\n" + source)
    # v1.5.6 - regression: invalid inline payloads/fences validated silently.
    assert any(error.line_no == 1 and error.message.strip() for error in result.errors)


@pytest.mark.parametrize("source", INVALID_SCRIPTS)
def test_malformed_applescript_is_not_executable(source: str) -> None:
    result = parse("+CalFlow+\n" + source)
    # v1.5.6 - regression: no empty or unterminated RUN may reach execution.
    assert result.commands == []


def test_rejected_inline_applescript_keeps_valid_neighbors() -> None:
    result = parse('+CalFlow+\nwait 1\nrun applescript("return 1")\nwait 2')
    # v1.5.6 - regression: rejecting a malformed RUN must remain line-local.
    assert [(command.name, getattr(command, "seconds", None)) for command in result.commands] == [
        ("WAIT", 1.0),
        ("WAIT", 2.0),
    ]


def test_closed_applescript_fence_preserves_payload() -> None:
    result = parse("+CalFlow+\nrun applescript\n+++\nset value to 1\nreturn value\n+++")
    # v1.5.6 - compatibility: documented fenced multiline scripts remain valid.
    assert [(command.backend, command.script) for command in result.commands] == [
        ("applescript", "set value to 1\nreturn value")
    ]


def test_closed_applescript_fence_keeps_following_command() -> None:
    result = parse("+CalFlow+\nrun applescript\n+++\nreturn 1\n+++\nwait 2")
    # v1.5.6 - compatibility: consuming the fence must not consume the next verb.
    assert [(command.name, getattr(command, "seconds", None)) for command in result.commands] == [
        ("RUN", None),
        ("WAIT", 2.0),
    ]


@pytest.mark.parametrize("scheme", ("HTTP", "HTTPS", "hTtP", "hTtPs"))
@pytest.mark.parametrize("location", ("body", "title"))
def test_smart_http_scheme_is_case_insensitive(scheme: str, location: str) -> None:
    suffix = "example.com/Report?Key=Value#Section"
    raw = f"{scheme}://{suffix}"
    result = parse(raw) if location == "body" else parse("", title=raw)
    # v1.5.6 - regression: uppercase schemes acquired a second https:// prefix.
    # URL semantics, not cosmetic scheme casing; path/query/fragment stay exact.
    assert [urlsplit(entry["url"]) for entry in result.entries] == [
        urlsplit(f"{scheme.lower()}://{suffix}")
    ]


@pytest.mark.parametrize(
    "expression",
    (
        "now+999999999d",
        "now-999999999d",
        "now+999999999w",
        "now+999999999mo",
        "now-999999999mo",
        "now+999999999y",
    ),
)
def test_large_dynamic_date_returns_literal(expression: str) -> None:
    # v1.5.6 - regression: datetime/timedelta/relativedelta overflow must not escape.
    assert resolve_dynamic_expr(expression, _now=NOW) == "{" + expression + "}"


def test_dynamic_overflow_preserves_literal_and_resolves_neighbors() -> None:
    source = "https://example.com?from={now-1d}&bad={now+999999999d}&to={now}"
    # v1.5.6 - regression: one invalid expression cannot abort valid substitutions.
    assert resolve_dynamic(source, _now=NOW) == (
        "https://example.com?from=2026-10-09&bad={now+999999999d}&to=2026-10-10"
    )
