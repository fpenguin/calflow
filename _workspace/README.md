# `_workspace/` — AI scratchpad and spec storage

This directory is the **working memory** of AI agents operating in CalFlow.
It holds three kinds of artefacts with different lifecycles:

| Subdirectory | Lifecycle | Tracked in git? |
|---|---|---|
| `specs/` | **Long-lived.** Accepted feature specs that drove implementation. | ✅ committed |
| `tasks/` | Active work, one file per in-progress feature. | ❌ gitignored |
| `scratchpads/` | Agent thinking notes during a session. | ❌ gitignored |
| `architecture/` | Design exploration before a spec is accepted. | ❌ gitignored |
| `prompts/` | Reusable prompt templates per workflow. | ❌ gitignored |
| `diffs/` | Dry-run refactor proposals waiting for approval. | ❌ gitignored |
| `outputs/` | Temporary script output. | ❌ gitignored |
| `reviews/` | `qa-auditor` reports keyed by date. | ❌ gitignored |

## Why specs are committed

Future readers (including future agents and external contributors) need to
understand WHY a feature exists and WHICH constraints shaped it. Specs are
short, high-signal, and rarely change once accepted. Treat them as
documentation, not scratch.

## Lifecycle

A typical feature goes:

1. **Idea** — user describes intent.
2. **Architecture exploration** — agent writes a draft in
   `_workspace/architecture/<topic>.md` if the design is non-obvious. *(Skip
   for simple changes.)*
3. **Spec** — agent commits `_workspace/specs/<feature>.md` with: scope,
   file-by-file diff plan, test plan, doc plan, risk list. **User approval
   gate.**
4. **Task tracking** — agent creates `_workspace/tasks/<feature>.md` with
   checkboxes, updates as work proceeds.
5. **Implementation** — code + tests + doc updates per the spec.
6. **Archival** — once the version ships, the spec stays in `specs/` (it's
   the historical record). The `tasks/` file can be deleted or moved to
   `tasks/done/<feature>.md`.

## Cleanup conventions

- `scratchpads/`, `prompts/`, `outputs/` may be cleaned anytime; nothing
  there is canonical.
- `tasks/` files older than 60 days without commits should be reviewed —
  either the work is forgotten, or it should become a spec.
- `diffs/` files outlive their commit; once the refactor lands they can
  be deleted.
- `reviews/` accumulates one file per audit; archive (move to
  `reviews/archive/`) yearly to keep the listing readable.

## What does NOT go here

- Production code (`core/`, `runtime/`, `infra/`, etc.)
- User documentation (`docs/`)
- Test code (`tests/`)
- Configuration (`config/`)
- Data files (`data/`, `secrets/` — also gitignored, but for security)

If you find yourself wanting to put something here that another consumer
needs at runtime, it belongs elsewhere.
