# CLAUDE.md

Project-level instructions for Claude (and other AI agents) working in CalFlow.

This file is the **single source of truth** for how AI assistants should behave
in this repo. Read it first. Specialised behaviours (DSL changes, macOS quirks,
release management) live in `.claude/agents/` and `.claude/skills/` — but the
rules below apply unconditionally.

Last reviewed against repo state: **v1.1.29**.

---

## 1. Project context

**CalFlow** is a macOS calendar-driven automation engine. Calendar events trigger
workflows: open URLs in specific browsers / profiles, arrange windows across
displays, hide apps, autofill passwords, capture screenshots. Two execution
modes:

- **Smart Mode** — URL-line shorthand (`zoom.us @chrome #left(50%)`)
- **Plus Mode** — `+CalFlow+` block + 13-verb DSL with full grammar

Architecture: `parser → validator → resolver → executor → actions/backends`,
strict layer separation enforced.

Tech: Python 3.10+, Google Calendar API, optional pyobjc/AppKit. macOS-specific
runtime (launchd + osascript + JXA + screencapture).

The `docs/DSL_SPEC.md`, `docs/DSL_GRAMMAR.md`, and `docs/parser-behavior.md`
files are **authoritative for DSL behaviour**. If code disagrees with them,
either the docs lie (fix docs) or the code is buggy (fix code) — never silently
accept the discrepancy.

---

## 2. Hard rules — non-negotiable

### Privacy & secrets

- **Never read `secrets/credentials.json`, `data/oauth_token.*`, or any file
  under `secrets/`.** Abort and ask the user if you find yourself needing to.
- **Never log calendar event content** — titles, URLs, descriptions are PII.
  In tests / logs use generic placeholders (`https://example.com`, `Standup`).
- **Never commit anything from `data/`, `secrets/`, `.venv/`, `__pycache__/`.**
  `.gitignore` covers this; don't override it.

### Git discipline

- **Never `git push` without explicit user approval.** Default = local commits
  + local tags. The user controls publication.
- **Never `git push --force`, `git reset --hard`, or `git clean -fd` without
  the user explicitly typing the literal command.** Refuse to compose them.
- **Never delete a tag once pushed.** v1.1.x tags are historical record.
- **Never force-edit a commit that was previously pushed.**

### Destructive operations

- **Never delete files in `tests/`, `docs/`, `playbooks/`** without approval +
  explicit reason logged in the commit message.
- **Never modify `data/state.json` schema** without backup + approval.
- **Never run the daemon against the user's real Google account** in any
  automated way. `python -m cli.main test` (interactive) is the only sanctioned
  path; everything else uses mocked IO (see `tests/test_v2_daemon_smoke.py`).
- **Never auto-modify launchd plist or run `launchctl` commands** without
  user approval.

### User configuration

- **Never modify** `TARGETS`, `BUNDLES`, `AUTOFILL_PROVIDER`, or any other
  user-customisable section of `config/settings.py`. Onboarding writes there;
  agents don't.
- **Never change `BLACKLIST_REGEX`, `IGNORED_PROTOCOLS`, `MAP_DOMAINS`** without
  treating it as a security review (these are user-protection lists).

---

## 3. Code style & conventions

### Python

- **Python 3.10+.** All new files start with `from __future__ import annotations`.
- **PEP 8.** 100-column soft limit (`pyproject.toml` ruff config).
- **snake_case** for functions, **PascalCase** for classes.
- **No bare `except:`** — always name the exception.
- **No `print()` in `core/` or `runtime/`** — use `core.utils.log()`. CLI entry
  points (`cli/main.py`, `cli/onboarding.py`, `cli/repl.py`) MAY use `print()`
  for user-facing prompts and banners.
- **Type hints required on public functions.** Private (`_` prefix) helpers may
  omit them when the type is obvious from context.

### File organisation

- **Layered:** `core/` is pure (no IO), `runtime/` does side effects, `infra/`
  talks to external services (Google Calendar), `cli/` is entry points,
  `state/` is file-backed state, `config/` is settings.
- **New IO goes in `runtime/actions/` or `infra/`**, never in `core/`.
- **`__all__` per public module.** Anything not in `__all__` is private.
- **One commit per logical change.** Don't bundle unrelated edits.

### Naming

- **DSL verbs** are lowercase (`open`, `hide`, `focus`).
- **Tags** are `#kebab-case` (`#new-window`, `#no-autofill`, `#display(2)`).
- **Functions** read as `verb_object`: `resolve_target`, `parse_layout_tag`,
  `wants_new_window`.
- **Reserved keywords** (`active`, `all`, `display`, `except`) are enforced
  by `core/reserved.py` — never add to user `TARGETS` / `BUNDLES`.

### Logging

- Three prefixes only:
  - `[INFO]` — normal operation.
  - `[WARN]` — recovered or skipped (caller should keep going).
  - `[ERROR]` — failed but caught (caller should keep going; pipeline never
    aborts on a single failure).
- **Every reject path emits a hint.** Never `return None` silently when an
  input was clearly intended to do something. The user must be able to
  read the log and know what to fix.

### Error handling

- **Best-effort discipline.** A single bad command never aborts the rest.
  Catch + log + continue.
- **Validation errors are returned, not raised.** `core/validator/` returns
  `List[ValidationError]`; the caller decides what to do.
- **Subprocess timeouts.** Every `subprocess.run` call must have a `timeout=N`.
  No exceptions.

---

## 4. Testing expectations

- **Tests must pass before every commit.** Run `python -m unittest discover
  tests/` (or `pytest tests/`) and verify "OK" before staging.
- **New code path → at least one test.** No exceptions for "trivial" changes.
- **Bug fix workflow:** write the failing regression test FIRST, in the same
  commit or an immediately-prior commit. Tag it with `# v1.1.X — regression
  for <symptom>` so future readers know why it exists.
- **Never modify a test to make it pass** without a documented reason. The
  test was written to lock a behaviour; if you change the test, you're
  changing the contract.
- **Smoke tests for new pipeline paths.** If a feature crosses parser →
  resolver → executor → action, add a smoke case in
  `tests/test_v2_daemon_smoke.py`. The v1.1.23 bug exists because we didn't
  do this.
- **Test layer hygiene.** A test should fail for one reason. If parser tests
  break when you change the validator, your tests are coupled across layers.

See `docs/TESTING.md` for the full guide.

---

## 5. DSL change discipline (the seven-file rule)

When you change Plus Mode or Smart Mode syntax — **every commit MUST update
all of the following** in lockstep, or the change is incomplete:

1. `docs/DSL_GRAMMAR.md` (formal grammar)
2. `docs/DSL_SPEC.md` (user-facing reference)
3. `core/parser/plus_parser.py` or `core/parser/smart_parser.py`
4. `core/validator/validator.py` (accept / reject decision)
5. `core/resolver/resolver.py` (if the change produces new params)
6. `runtime/{executor,command_executor}.py` (if the change is dispatched differently)
7. `tests/test_v2_*.py` (parser test + validator test + spec test + regression)
8. `playbooks/*.md` (any user-facing example that becomes out-of-date)

Migration script template lives in `_workspace/specs/dsl-migration-template.md`
once specs are populated.

If you can only update some of these in one session, use `_workspace/tasks/`
to track the remainder. Don't ship a partial migration as "done."

---

## 6. AI-agent behaviour rules

### Agent dispatch

- **Default agent handles ~80% of work.** Subagents are narrow specialists
  invoked only when their lane fits. See `.claude/agents/` for the five
  subagent definitions.
- **Subagents do not invoke other subagents.** Orchestration is human-driven.
- **Each subagent stays in its lane** — defined by its `description` field.
  When in doubt, default agent.

### Tool use

- **Read full files only on first encounter.** Subsequent inspections use `Grep`.
- **Don't dump full test output into prompts.** Pipe `tail -10` or `grep -E
  "^(FAIL|ERROR|OK)"`.
- **Don't re-read a file you just edited.** The Edit tool's success message
  is the verification.
- **Use `Edit` for diffs, `Write` only for new files.** Edit shows the user
  exactly what changed.

### Safety gates

- **Every "spec" is a `_workspace/specs/<feature>.md` file with user
  approval before code is written.** Specs that touch ≥3 files OR change
  the DSL require this gate.
- **Refactors require a `_workspace/diffs/<refactor>.md` dry-run plan.**
  Show before/after per file. Wait for approval. Then execute in
  layer-by-layer commits.
- **Mass-edit operations** (touching ≥10 files) ALWAYS require a dry-run.
- **Bug fixes** under one file with an obvious cause may skip the spec gate
  and go straight to the regression-test-first workflow.

### Prompt conventions

- When the user reports a bug → reproduce as a failing test FIRST.
- When the user describes a feature → write the spec, await approval.
- When the user says "ship" / "tag" / "release" → invoke `release-manager`.
- When the user asks "audit" → invoke `qa-auditor`.
- When in doubt about a destructive op → ask, don't act.

---

## 7. Versioning & releases

- **`core/version.py` is the single source of truth.** Bump `__version__` on
  every shipped change.
- **`v1.1.x` are internal iterations.** Tag locally; push only on user
  approval.
- **`v2.0.0` is reserved for the public GitHub release.** Don't tag it
  until the user says "ship publicly."
- **Commit messages are multi-paragraph.** First line: `vX.Y.Z — <one-line
  summary>`. Then a blank line, then sections (Symptom / Root cause / Fix /
  Files touched / Tests). Match the established history.

---

## 8. Token & cost optimisation

- Prefer `Grep` over `Read` for follow-up searches.
- Don't paste full file contents into agent prompts when a path + line range
  works.
- Don't recompose the test suite for every commit — pipe `tail -3`.
- When a subagent finishes, return only the report (under 500 words is the
  default ceiling).

---

## 9. When the rules conflict

- **User explicit override > CLAUDE.md.** If the user says "do X anyway,"
  obey but log the exception in the commit message.
- **Safety rules > convenience.** If a rule slows down a task but prevents
  data loss, it stays.
- **CLAUDE.md > skill files > agent prompts.** Skills can refine, never
  override.

If a rule feels wrong in practice, propose an edit to CLAUDE.md in the next
session. Don't violate silently.

---

## 10. Cowork vs Code coordination

When both sessions are available:

- Cowork is for visual design, research, and quick exploration.
- Code is the source of truth for specs, implementation, and commits.
- Cowork MUST NOT modify tracked source files (`cli/`, `core/`,
  `runtime/`, `state/`, `tests/`, `infra/`, `config/`) — if it does, the
  next Code session must commit immediately or the work is lost.
- Cowork MAY write to `_workspace/scratchpads/` (gitignored) for handoff
  notes, and to `_workspace/specs/` for spec drafts (but the spec must
  be committed by Code before implementation begins).
- Mockup HTML rendered in Cowork is for review only, not for editing
  the real `runtime/menubar/*.html` files.

If forced to choose only one tool: use Code. Cowork is the sketchpad.

---

## 11. Pointers

- `docs/DSL_SPEC.md` — DSL reference
- `docs/DSL_GRAMMAR.md` — formal grammar
- `docs/TESTING.md` — testing guide
- `docs/menubar_readiness.md` — future GUI architecture
- `docs/roadmap.md` — what's deferred and why
- `_workspace/specs/` — accepted feature specs (committed)
- `_workspace/scratchpads/` — agent thinking notes (gitignored)
- `.claude/agents/` — subagent definitions
- `.claude/skills/` — reusable patterns
