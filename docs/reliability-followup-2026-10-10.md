# Reliability Follow-Up

Version: **1.5.6-dev**, 2026-10-10. Development push, not a tagged release.
The user confirmed the restored menu icon. No real calendar or
desktop workflow was intentionally run during automated verification.

## Implemented

- Both executors return per-step results. Failed opens/layouts/autofill and
  unsupported actions no longer imply success. Valid neighboring commands still
  run. BTT and Alfred report handoff, not external workflow completion.
- Scheduled and manual event execution share atomic occurrence claims. A
  desktop file lock serializes workflows without an age-based expiry. Overlapping
  requests cannot turn into sequential retries. Failed/interrupted attempts
  require explicit retry; a retry repeats all steps, not only failed steps.
- Menu and Playbooks runs use detached workers, private request files, status
  polling and process-group cancellation. They survive popup/companion closure.
  Recent Runs retains errors. Already handed-off work cannot be cancelled.
- Job metadata lives in `data/jobs/`, separate from unchanged `data/state.json`.
  Request payloads are removed when consumed. Result details are private and
  pruned after seven days when a new job starts. Occurrence claims are retained
  for replay protection. Errors may contain script output; review before sharing.
- Login preferences and pause state are independent and persistent. Restart
  preserves paused/stopped state. The daemon installer uses escaped plist data
  and checked, bounded launch calls. Settings/logger imports no longer cycle.
- Reinstall stages code, preserves `data/` and `secrets/`, retains the previous
  installation and rolls back setup failures. It refuses active services or
  tracked local edits. Nothing deletes the previous installation automatically.
- Legacy quoted/spaced hash modifiers and last-wins layouts work in both modes.
  Incomplete AppleScript blocks/inline calls are rejected; uppercase URL schemes
  and date overflow are handled; malformed numeric arguments stay line-local.
- Ambiguous/empty CLOSE exclusions are rejected. Invitation permissions cover
  relative filesystem paths and the interactive calendar runner. Help/unknown
  arguments cannot fall through to scheduled execution. Smart previews show URLs.
- Ordinary parser/action diagnostics omit calendar payloads. Test storage and
  native-action guards are strengthened. One stale lifecycle mock exercised
  login enable/disable; final services were verified enabled. A synthetic state
  record was surgically removed; all other records were retained.

## Verification

Local verification: **1,010 Python tests and 6 Node UI tests passed** with
`.venv/bin/python -m pytest tests/` and
`node --test tests/menubar_ui.test.cjs`. Targeted Ruff, `pip check`, installer
shell syntax and diff whitespace checks also passed. Coverage includes
two-process occurrence contention, overlapping manual requests, cancellation
authorization, private-file cleanup, failure persistence, fresh-interpreter
settings imports, legacy hashtags and synthetic installer rollback.

Cancellation signalling and native desktop actions are mocked. This is not a
live reboot, permissions, OAuth, process-descendant shutdown or multi-display acceptance
run. The existing broader Ruff/mypy backlog remains advisory; this pass is not
a whole-repository formatting rewrite.

## Still Open

The [baseline audit](codebase-audit-2026-10-10.md) remains the source for further
work. In particular: concurrent settings/alias transactions, finite numeric
settings validation, corrupt optional statistics, stale cached controls,
managed-versus-unmanaged menu ownership, native confirmation/picker behavior,
blank-playbook draft preservation, autofill preference precedence, HTML/script
normalization, and onboarding calendar selection/pagination are not claimed
fixed here. Resolve these and complete native acceptance before a public launch.
