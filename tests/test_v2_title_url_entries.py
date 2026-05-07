"""
Title URL → entry tests (v1.1.17 — Option B).

Old behaviour (v2.0.x): a calendar event with a join link in the
TITLE and empty body would silently open nothing — title URLs were
captured into a whitelist set but never became entries on their own.

New behaviour (v1.1.17 / Option B):
    - Title URLs ARE entries.
    - Body URLs are entries (unchanged).
    - Body URL identical to a title URL: dedupe via the existing
      `seen` set — each URL opens at most once.
    - Title URLs still get the title-whitelist exemption from
      blacklist / map-filter (they're declared by the user in the
      title, so the user clearly wants them).
    - Title URLs inherit GLOBAL tags only (no per-line tags, because
      the title isn't a body line).

Run:
    python -m unittest tests.test_v2_title_url_entries -v
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.parser.smart_parser import extract_url_entries


def _urls(entries):
    return [e["url"] for e in entries]


class TitleUrlOnly(unittest.TestCase):
    """Title has a URL, body is empty / has no URL."""

    def test_title_url_alone_becomes_entry(self) -> None:
        entries = extract_url_entries(
            "",
            title="Standup — https://zoom.us/j/12345",
        )
        self.assertEqual(_urls(entries), ["https://zoom.us/j/12345"])

    def test_title_url_with_only_comments_in_body(self) -> None:
        entries = extract_url_entries(
            "## a note\n## another note",
            title="https://example.com",
        )
        self.assertEqual(_urls(entries), ["https://example.com"])


class TitleUrlPlusBodyUrls(unittest.TestCase):
    """Title URL + 1+ different body URLs → both kinds present."""

    def test_distinct_urls_all_open(self) -> None:
        entries = extract_url_entries(
            "https://other.com",
            title="Meeting — https://zoom.us/j/12345",
        )
        urls = _urls(entries)
        self.assertIn("https://zoom.us/j/12345", urls)
        self.assertIn("https://other.com", urls)
        self.assertEqual(len(urls), 2)


class TitleAndBodyDedupe(unittest.TestCase):
    """Same URL in title AND body → opens exactly once."""

    def test_identical_url_deduped_to_one(self) -> None:
        entries = extract_url_entries(
            "https://zoom.us/j/12345",
            title="Standup — https://zoom.us/j/12345",
        )
        self.assertEqual(_urls(entries), ["https://zoom.us/j/12345"])

    def test_dedupe_keeps_body_targets_and_tags(self) -> None:
        # The body URL, when seen first, picks up its line's tags.
        # Title URL is a duplicate → skipped, so body version wins.
        entries = extract_url_entries(
            "https://x.com @safari #left(50%)",
            title="Standup — https://x.com",
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], "https://x.com")
        self.assertIn("@safari", entries[0]["tags"])


class TitleUrlGlobalTagsInheritance(unittest.TestCase):
    """Title URLs pick up the GLOBAL Smart Mode tag/target state."""

    def test_global_target_applied_to_title_url(self) -> None:
        body = "@safari\n## body has no URL"  # standalone @target line
        entries = extract_url_entries(
            body, title="Meeting — https://zoom.us/j/123"
        )
        self.assertEqual(len(entries), 1)
        self.assertIn("@safari", entries[0]["tags"])

    def test_global_layout_tag_applied(self) -> None:
        body = "#left(50%)"
        entries = extract_url_entries(
            body, title="Meeting — https://zoom.us/j/123"
        )
        self.assertEqual(len(entries), 1)
        self.assertIn("#left(50%)", entries[0]["tags"])


class NoTitleUrlNoChange(unittest.TestCase):
    """Regression: existing body-only behaviour is untouched."""

    def test_body_only(self) -> None:
        entries = extract_url_entries(
            "https://a.com\nhttps://b.com",
            title="Plain title with no link",
        )
        self.assertEqual(_urls(entries), ["https://a.com", "https://b.com"])

    def test_no_title_argument(self) -> None:
        entries = extract_url_entries("https://a.com")
        self.assertEqual(_urls(entries), ["https://a.com"])

    def test_parse_with_empty_body_and_title_url(self) -> None:
        """v1.1.21 — parse() must NOT short-circuit on empty body when
        the title still carries a URL. Earlier the dispatcher returned
        MODE_NONE before smart_parser ever saw the title."""
        from core.parser.parser import parse
        result = parse(
            "",
            title="https://zone.fizz.ca/dce/customer-ui-prod/loyalty;preserveFragment=true#badges",
        )
        self.assertEqual(result.mode, "smart")
        self.assertFalse(result.is_empty)
        self.assertEqual(len(result.entries), 1)
        self.assertIn("zone.fizz.ca", result.entries[0]["url"])

    def test_parse_with_no_text_and_no_title(self) -> None:
        from core.parser.parser import parse
        self.assertEqual(parse("").mode, "none")
        self.assertEqual(parse("", title=None).mode, "none")
        self.assertEqual(parse("", title="").mode, "none")

    def test_no_title_no_body(self) -> None:
        entries = extract_url_entries("")
        self.assertEqual(entries, [])


class TitleUrlDefaultsV1_1_22(unittest.TestCase):
    """v1.1.22 — TITLE_URL_AUTOFILL_DEFAULT and TITLE_URL_OPEN_DEFAULT
    apply to title URLs unless overridden by explicit body tags."""

    def setUp(self) -> None:
        # Snapshot + reset for each test so ordering doesn't leak.
        from config import settings
        self._snap = (
            settings.TITLE_URL_AUTOFILL_DEFAULT,
            settings.TITLE_URL_OPEN_DEFAULT,
        )

    def tearDown(self) -> None:
        from config import settings
        settings.TITLE_URL_AUTOFILL_DEFAULT, settings.TITLE_URL_OPEN_DEFAULT = self._snap
        # Re-import smart_parser to refresh module-level binding from settings.
        # smart_parser reads them at call time via the imported names, so we
        # also need to refresh those.
        import core.parser.smart_parser as sp
        sp.TITLE_URL_AUTOFILL_DEFAULT = settings.TITLE_URL_AUTOFILL_DEFAULT
        sp.TITLE_URL_OPEN_DEFAULT = settings.TITLE_URL_OPEN_DEFAULT

    def _set(self, autofill=None, open_mode=None):
        from config import settings
        import core.parser.smart_parser as sp
        if autofill is not None:
            settings.TITLE_URL_AUTOFILL_DEFAULT = autofill
            sp.TITLE_URL_AUTOFILL_DEFAULT = autofill
        if open_mode is not None:
            settings.TITLE_URL_OPEN_DEFAULT = open_mode
            sp.TITLE_URL_OPEN_DEFAULT = open_mode

    # ── Autofill default ─────────────────────────────────────────
    def test_default_submit(self) -> None:
        self._set(autofill="submit", open_mode="tab")
        e = extract_url_entries("", title="https://example.com")[0]
        self.assertIn("#submit", e["tags"])
        self.assertNotIn("#fill", e["tags"])
        self.assertNotIn("#no-autofill", e["tags"])

    def test_default_fill(self) -> None:
        self._set(autofill="fill", open_mode="tab")
        e = extract_url_entries("", title="https://example.com")[0]
        self.assertIn("#fill", e["tags"])
        self.assertNotIn("#submit", e["tags"])

    def test_default_none(self) -> None:
        self._set(autofill="none", open_mode="tab")
        e = extract_url_entries("", title="https://example.com")[0]
        self.assertIn("#no-autofill", e["tags"])
        self.assertNotIn("#submit", e["tags"])
        self.assertNotIn("#fill", e["tags"])

    def test_global_body_autofill_tag_wins(self) -> None:
        # Body's standalone `#fill` line should win over the
        # title-URL default (which would otherwise add #submit).
        self._set(autofill="submit", open_mode="tab")
        e = extract_url_entries("#fill", title="https://example.com")[0]
        self.assertIn("#fill", e["tags"])
        self.assertNotIn("#submit", e["tags"])

    # ── Open-mode default ────────────────────────────────────────
    def test_default_open_tab(self) -> None:
        self._set(autofill="submit", open_mode="tab")
        e = extract_url_entries("", title="https://example.com")[0]
        self.assertIn("#tab", e["tags"])
        self.assertNotIn("#window", e["tags"])

    def test_default_open_window(self) -> None:
        self._set(autofill="submit", open_mode="window")
        e = extract_url_entries("", title="https://example.com")[0]
        self.assertIn("#window", e["tags"])
        self.assertNotIn("#tab", e["tags"])

    def test_layout_overrides_open_default(self) -> None:
        # User has TITLE_URL_OPEN_DEFAULT=tab, but global #left layout
        # is set in body — layout always implies window, so we should
        # NOT add #tab.
        self._set(autofill="submit", open_mode="tab")
        e = extract_url_entries("#left(50%)", title="https://example.com")[0]
        self.assertNotIn("#tab", e["tags"])
        # The layout tag itself is what flips the window decision in
        # wants_new_window — no #window tag injected here.

    def test_explicit_window_tag_in_body_preserved(self) -> None:
        # If user already added #window globally, don't double-write.
        self._set(autofill="submit", open_mode="tab")
        e = extract_url_entries("#window", title="https://example.com")[0]
        self.assertIn("#window", e["tags"])
        self.assertNotIn("#tab", e["tags"])


# v1.1.22 — wants_new_window honours #window / #tab tags
class WindowTabTagOverride(unittest.TestCase):
    def test_window_tag(self) -> None:
        from runtime.actions.browser import wants_new_window
        self.assertTrue(wants_new_window(tags={"#window"}))
        self.assertTrue(wants_new_window(tags={"#new-window"}))

    def test_tab_tag(self) -> None:
        from runtime.actions.browser import wants_new_window
        self.assertFalse(wants_new_window(tags={"#tab"}))
        self.assertFalse(wants_new_window(tags={"#new-tab"}))

    def test_tab_overrides_layout(self) -> None:
        # Layout would normally imply window; explicit #tag wins.
        from runtime.actions.browser import wants_new_window
        self.assertFalse(wants_new_window(tags={"#left(50%)", "#tab"}))

    def test_window_with_layout_still_window(self) -> None:
        from runtime.actions.browser import wants_new_window
        self.assertTrue(wants_new_window(tags={"#grid(1@3x2)", "#window"}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
