---
name: commit-message-style
description: |
  Multi-paragraph commit format used in CalFlow's history. Match this
  style for every release commit.
---

# Commit message style

CalFlow's commit history uses a deliberate multi-paragraph format that
serves as the changelog. New commits MUST match this style — readers
(and future agents) rely on it for context.

## Required shape

```
v1.1.X — <one-line summary, ≤72 chars>

<2-4 sentence problem statement: what was wrong, what changed>

<Section: Symptom>          (bug fixes only)
…what the user observed…

<Section: Root cause>       (bug fixes only)
…why the bug happened, in 1-3 sentences…

<Section: Fix>              (or Implementation)
…what changed, file by file or as a numbered list…

<Section: Files touched>
  path/to/file.py        (one-line description; +/-N optional)
  path/to/other.py
  …

<Section: Tests>
…what was added; current pass count + delta from previous version…
```

## Examples in the history

```bash
# Best illustrative commits to read for style:
git show v1.1.14         # bug fix with Symptom / Root cause / Fix sections
git show v1.1.20         # feature with Implementation + user-facing examples
git show v1.1.26         # infra change with no Symptom (numbered list)
git show v1.1.25         # short, surgical (only "duplicates removed")
```

## Tone rules

- Past tense, declarative ("Removed the v1.1.1 path" not "We remove…")
- Specific over vague ("the JXA cancel-handler" not "the AppleScript bit")
- File paths in lowercase, backticks
- Code identifiers in backticks (`hide_apps_on_display`)
- User-visible behaviour shown as a code block when it's an example
- Test count in the Tests section: "Tests: 450 pass (449 → +1)" or similar

## Anti-patterns

- ❌ Single-line commits ("fix bug")
- ❌ Bullet lists where prose works
- ❌ Emojis (CalFlow uses plain text in commits, even though docs use them)
- ❌ Markdown headers inside the message (commit display strips formatting)
- ❌ Trailing references to outdated tools / phases
