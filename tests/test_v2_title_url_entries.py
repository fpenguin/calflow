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


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
