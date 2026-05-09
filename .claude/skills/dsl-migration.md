---
name: dsl-migration
description: |
  The seven-file rule for DSL syntax changes. Apply when adding, changing, or
  removing any verb / tag / modifier in Smart Mode or Plus Mode.
---

# DSL migration discipline

Every DSL syntax change must update **all seven files in lockstep**:

1. `docs/DSL_GRAMMAR.md` — formal EBNF
2. `docs/DSL_SPEC.md` — user-facing reference
3. `core/parser/{plus,smart}_parser.py` — producer
4. `core/validator/validator.py` — accept / reject
5. `core/resolver/resolver.py` — only if new param shape
6. `runtime/{executor,command_executor}.py` — only if new dispatch
7. `tests/test_v2_*.py` — spec + parser + validator + regression
8. `playbooks/*.md` — every example that becomes outdated

If the change removes or changes existing syntax: also add a hard-fail
validation test that confirms the OLD form is rejected with a clear
migration message (the v1.1.1 / v1.1.2 / v1.1.19 patterns).

## Verification checklist

```
# 1. Grammar matches code
grep -n "<verb-or-tag>" docs/DSL_GRAMMAR.md
grep -n "<verb-or-tag>" core/parser/plus_parser.py

# 2. All examples still parse
python -m unittest tests.test_v2_playbooks -v

# 3. Spec class covers it
grep "<verb>" tests/test_v2_spec.py

# 4. Hard-fail message is clear
python -c "from core.parser.parser import parse; r = parse('+CalFlow+\n<old-form>'); print(r.errors)"
```

If any of these fails → migration is incomplete.
