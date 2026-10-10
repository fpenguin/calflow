# Approved reliability follow-up

User approval: 2026-10-10, after the six-item recommendation. User confirmed
the icon has returned, approved necessary reliability changes, and requested
committing/pushing to GitHub. Item 2 requires no further choice: failures are
recorded, not retried automatically; explicit retry remains available.

## Dry-run / implementation order

1. Commit the already-verified audit fixes and mark version 1.5.6-dev. Keep
   outputs, secrets, local data and ignored audit evidence out of Git.
2. Add pure structured action/workflow results. Change both executors from
   no return value to outcomes; retain best-effort per-command continuation.
   Unsupported actions fail explicitly. Keep backend details out of general
   logs. Store result details only in the private local job history for the
   requested menu diagnostics; prune details after seven days on job creation.
3. Add a separate job store without changing data/state.json. A file lock
   serializes native desktop work; durable job attempts prevent scheduled
   retries and duplicate event occurrences. Completion state means success,
   not merely an attempt. Shared execution is used by daemon and manual runs.
4. Add detached local CLI workers with restrictive per-job storage, opaque
   identifiers, polling/status/cancel endpoints and menu/playbook run status.
   Closing a popup must not stop a worker. Worker death means interrupted,
   never silent replay. Cancellation terminates the worker process group.
5. Persist login preferences separately from pause state. Preserve pause
   during settings restarts. Break configuration/logger import cycles.
6. Repair parser edge cases: quoted/spaced hash arguments, deterministic
   modifier precedence, fenced script validation, uppercase URLs, date overflow.
   Keep v1.0 hashtag support. Sync grammar/spec/help with accepted behavior.
7. Redact remaining event-content logs; replace destructive reinstall with
   staged upgrade and backup/rollback preserving credentials, state and playbooks.
8. Add focused regression tests, run full Python/Node checks, review staged
   diffs and push logical commits. No release tag or GitHub release requested.

## Verified safety additions

The concurrent dated audit identified adjacent launch blockers. The same
approved safety pass also rejects ambiguous CLOSE scopes and relative-file
permission bypasses, validates CLI arguments before imports/dispatch, and
preserves invitation trust in the interactive calendar runner. Lower-priority
items from that audit remain documented, not implicitly accepted as fixed.

## Ownership and safety

Main owns implementation and integration. Regression-locker supplies independent
tests. macOS-backend may update action return contracts in a disjoint scope.
Tests must use temporary persistence and mocked desktop/calendar actions.
Do not invoke real calendar automation or read secrets during verification.
No settings preferences will be changed on this machine without explicit need.

## Acceptance

- Failed/blocked/unsupported/handed-off results are distinguishable.
- Manual and scheduled attempts cannot execute the same occurrence together.
- Interrupted/failed jobs require explicit retry; repeat polls cannot replay.
- Long waits survive popup closure and are cancellable.
- Login choices persist; restart does not silently resume paused automation.
- Upgrades retain private files and allow recovery of the old installation.
- Parser repairs have synthetic regressions and preserve legacy hashtags.
