---
name: type-system-contract
description: |
  The CalFlow DSL type system (v1.1.2). The four-way classification of
  identifiers and how the parser / validator enforce it.
---

# Type system contract

## The four types

| Type | Syntax | Examples | Meaning |
|---|---|---|---|
| **Dynamic value** | `{ … }` | `{now}`, `{now-7d > YYYY-MM-DD}` | produces data |
| **Runtime target** | bare identifier | `active`, `all` | selects system entity at exec |
| **Alias** | `@…` | `@chrome`, `@work` | predefined set |
| **Filter** | `name(…)` | `except(…)`, `display(…)` | modifies the verb's selection |

## Reserved keywords (DSL contract)

```python
# core/reserved.py
RESERVED_KEYWORDS = frozenset({"active", "all", "display", "except"})
```

User configuration (`TARGETS`, `BUNDLES`) MUST NOT shadow these.
`config/settings.py` calls `enforce_or_exit(TARGETS)` at module load.

## Invalid combinations (validator rejects)

```text
{active}           # ❌ {} is for dynamic VALUES only
{@work}            # ❌ same
{display(2)}       # ❌ same
TARGETS["active"]  # ❌ shadows reserved (config-load fails)
```

The fix is to use the bare form: `active`, `@work`, `display(2)`.

## When you add a new construct

Decide which of the four types it is BEFORE writing the parser. The choice
informs how the validator should accept it and how the resolver populates
params.

If you find yourself wanting a fifth type, you've probably misclassified
an existing one. Ask before adding.

## Where this rule applies

- `core/parser/{plus,smart}_parser.py` — produces typed AST nodes
- `core/validator/validator.py` — rejects type mismatches
- `core/resolver/resolver.py` — resolves runtime targets at exec time
- `runtime/{executor,command_executor}.py` — handles the resolved params
- All future DSL syntax additions
