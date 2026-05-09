---
name: doc-drift-check
description: |
  Detect and prevent drift between documented DSL behaviour and the actual
  parser/validator behaviour.
---

# Doc drift check

## The four files that must agree

| File | Content |
|---|---|
| `docs/DSL_SPEC.md` | User-facing reference + examples |
| `docs/DSL_GRAMMAR.md` | Formal EBNF |
| `docs/parser-behavior.md` | Implementation-level rules |
| `playbooks/*.md` | Real-world usage examples |

When any of these disagrees with the parser/validator, fix the discrepancy
in the same commit.

## Detection patterns

```bash
# 1. Every code block in playbooks must parse
python -m unittest tests.test_v2_playbooks -v

# 2. Every example in DSL_SPEC must validate
python -c "
from core.parser.parser import parse
import re, pathlib
spec = pathlib.Path('docs/DSL_SPEC.md').read_text()
for m in re.finditer(r'\`\`\`text\n(.+?)\n\`\`\`', spec, re.DOTALL):
    block = m.group(1).strip()
    if '+CalFlow+' not in block and 'http' not in block:
        continue   # not a parser example
    r = parse(block)
    if r.has_errors:
        print(f'DRIFT: {block[:60]} → {r.errors}')
"

# 3. Section refs (§5.1) point at real sections
grep -E "§[0-9]+(\.[0-9]+)*" docs/*.md | head
```

## Common drift sources

1. **DSL grammar change** without updating `DSL_SPEC.md` examples.
   Caught by playbook tests if examples live in playbooks/.
2. **Renamed verb / tag** but old name lingers in `parser-behavior.md`.
3. **Deprecated form** that v1.1.X still hard-fails but docs still show.
4. **Numbered section reference** in another doc that moves out of sync.

## When you change DSL syntax

1. Search every `docs/*.md` and `playbooks/*.md` for the OLD form.
2. Update each occurrence, even if it's in a comment.
3. If the change is breaking, add a "Migration notes" section to
   `docs/DSL_SPEC.md` showing old → new.
4. Run the playbook tests to verify everything still parses.

## Scheduled audit

`qa-auditor` checks for drift every release. If you skip the audit, drift
accumulates and external readers get confused.
