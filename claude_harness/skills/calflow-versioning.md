---
name: calflow-versioning
description: |
  How to bump version, write changelog, tag, and push. Apply at every
  release boundary.
---

# CalFlow versioning

## Source of truth

`core/version.py`:

```python
__version__ = "1.1.X"
__is_release__ = True   # always True for tagged releases
```

When in mid-cycle development, keep `__is_release__ = True` and just bump
patch. The `version_string()` function returns `1.1.X-dev` only if you
explicitly toggle `__is_release__ = False`.

## Version scheme

| Change type | Version bump |
|---|---|
| Bug fix in v1.1.x | patch (1.1.29 → 1.1.30) |
| Additive feature, no DSL change | patch |
| New verb / tag (DSL change, backward-compat) | patch |
| Breaking DSL change (rejects previously-valid syntax) | minor (1.1.x → 1.2.0) |
| Public release on GitHub | the user explicitly says "v2.0.0" |

`v2.0.0` is **reserved**. Don't tag it without explicit user instruction.

## Tag locally, never push

```bash
git tag v1.1.X
git tag -l | tail -5    # confirm in context
```

Default = local tag only. The user pushes when they're ready.

## Commit message style (multi-paragraph)

```
v1.1.X — <one-line summary>

<2–3 sentence problem statement>

<Section: Symptom>      (for bug fixes)
<Section: Root cause>   (for bug fixes)
<Section: Fix>          (or Implementation)
<Section: Files touched>
<Section: Tests>        (current count + delta)
```

Match historical commits: `git log --oneline | head -20`.

## Common operations

```bash
# Look up the last tagged version
git describe --tags --abbrev=0

# Show what changed since last tag
git log --oneline $(git describe --tags --abbrev=0)..HEAD

# Tag and verify
git tag v1.1.X
git log --oneline -3
git tag -l | tail -5
```

## What never to do

- Never delete a pushed tag
- Never force-edit a pushed commit
- Never tag a red test suite
- Never bundle multiple unrelated changes in one release commit
