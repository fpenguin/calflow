"""Shared modifier categories; resolve precedence before converting tags to sets."""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = ["TAG_TOKEN", "tag_category", "collapse_tags"]

TAG_TOKEN = re.compile(r"^#\w[\w\-=%.,@/]*(?:\(.*\))?$", re.DOTALL)


def tag_category(tag: str) -> str:
    name = tag.lstrip("#").split("(", 1)[0].split("=", 1)[0].lower()
    if name in {"left", "right", "middle", "top", "bottom", "full", "area", "grid"}:
        return "layout"
    if name in {"fill", "submit", "no-autofill"}:
        return "behavior"
    if name in {"window", "new-window", "tab", "new-tab"}:
        return "open-mode"
    return f"tag:{name}"


def collapse_tags(tags: Iterable[str]) -> set[str]:
    by_category = {tag_category(tag): tag for tag in tags}
    return set(by_category.values())
