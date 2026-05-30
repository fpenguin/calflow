# 🧪 CalFlow v2.0 QA Guide

How to verify everything that's shipped works. Three layers, each
independently runnable:

1. **Automated tests** — fast, deterministic
2. **REPL** — manual interactive checks (no calendar needed)
3. **End-to-end** — real calendar event fires the daemon

---

# 1. Automated tests (~30 seconds)

```bash
cd /Users/mba/projects/calflow
source .venv/bin/activate
python3 -m unittest \
  tests.test_v2_validator \
  tests.test_v2_parser \
  tests.test_v2_executor \
  tests.test_v2_spec \
  tests.test_v2_playbooks \
  tests.test_v2_dynamic \
  tests.test_v2_comments \
  -v
```

Expected: **`Ran 282 tests in <1s    OK`**

### Per-suite breakdown

| Suite | Count | What it covers |
|-------|------:|----------------|
| `test_v2_validator`           |  18 | Grammar enforcement (arity, quoting, numeric, selector rules) |
| `test_v2_parser`              |  16 | Mode detection, AST construction, Smart regression |
| `test_v2_executor`            |   5 | Plus dispatch table (with mocked actions) |
| `test_v2_spec`                |  72 | Every rule in `docs/DSL_GRAMMAR / DSL_SPEC / parser-behavior / validation / test-cases` |
| `test_v2_playbooks`           |  30 | Every `+CalFlow+` block in `playbooks/*.md` |
| `test_v2_dynamic`             |  29 | Dynamic expression engine (base, transforms, formats, whitespace, Smart Mode integration) |
| `test_v2_comments`            |  26 | `##` line + inline, suppression inside quotes/parens/brackets/braces |
| `test_v2_window`              |  39 | Display enumeration spec, layout rect math, `#display` regex |
| `test_v2_no_cross_contamination` |  3 | Pin: per-line tags don't leak across entries (Smart + Plus) |
| `test_v2_autofill`            |  18 | Autofill keystroke assembly + provider resolution + permission errors |
| `test_v2_app_control`         |  21 | FOCUS / CLOSE / HIDE AppleScript shape + open_target dispatch + #profile(N) |

---

# 2. REPL — manual interactive checks (~5 minutes)

```bash
python3 -m cli.repl
```

Paste each block below and verify the output matches the **Expected**
description. The REPL prints the parsed structure, executes Smart Mode
opens for real, and stubs Plus Mode UI actions with `[INFO] … (stub)`
log lines.

---

## 2.1 Smart Mode — basic

```
calflow> zoom.us @chrome #left(50%)
```

**Expected:**
- mode: `smart`
- `entries: 1`
- `[1] {'url': 'https://zoom.us', 'tags': {'@chrome', '#left(50%)'}}`
- Chrome opens to zoom.us

---

## 2.2 Smart Mode — global state + comments

```
calflow> :plus
plus> EOF
calflow> ## morning routine
calflow> #display(2)
calflow> @chrome
calflow> 
calflow> zoom.us
calflow> notion.so
```

> Type each line one at a time at the `calflow>` prompt — the REPL
> processes them line-by-line. Note: Smart Mode REPL evaluates each
> input line independently, so for **global state**, the easier way
> is the next test (full block via :plus then exit Plus mode).

For full Smart Mode global state, use the daemon path or a Python
one-liner — see §2.5.

---

## 2.3 Plus Mode — full block

```
calflow> :plus
plus> ## launch the work bundle
plus> open @work
plus> wait 2
plus> screenshot
plus> save source(clipboard) to("~/Downloads/CalFlow/run_{now > YYYY-MM-DD_hh-mm}.png")
plus> EOF
```

**Expected:**
- mode: `plus`
- 4 commands: `OPEN`, `WAIT`, `SCREENSHOT`, `SAVE`
- The screenshot is saved to `~/Downloads/CalFlow/calflow_<timestamp>.png`
  (the `to(...)` path is the v2.3 target — currently the SAVE backend
  is a stub and prints `[INFO] SAVE source='clipboard' to='~/Downloads/CalFlow/run_2026-…' (stub)`)
- The `{now > YYYY-MM-DD_hh-mm}` block IS resolved before SAVE — verify
  the printed `to=…` field shows the substituted timestamp, not the
  literal `{now > …}`.

---

## 2.4 Plus Mode — inline comment

```
calflow> :plus
plus> open zoom.us @chrome  ## the daily standup
plus> wait 2                ## let it render
plus> screenshot            ## capture state
plus> EOF
```

**Expected:**
- 3 commands: `OPEN`, `WAIT`, `SCREENSHOT`
- Zero validation errors
- Comments do not appear in any error message

---

## 2.5 One-shot smoke (Python)

For end-to-end verification without the REPL prompt:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from core.parser.parser import parse

# Smart Mode global state + comments + dynamic
text = """
## morning routine
#display(2)
@chrome
##  --
zoom.us
https://reports.com?date={now > YYYY-MM-DD}
"""
r = parse(text)
print("mode:", r.mode)
for e in r.entries:
    print(" ", e)
PY
```

**Expected:**
```
mode: smart
  {'url': 'https://zoom.us', 'tags': {'@chrome', '#display(2)'}}
  {'url': 'https://reports.com?date={now > YYYY-MM-DD}', 'tags': {'@chrome', '#display(2)'}}
```

The dynamic block is preserved in `entries` — substitution happens at
**execute time** (so the timestamp reflects the actual run, not the
parse), via `runtime.executor`. To see the resolved URL, run the
executor with patched action layer (or just run the daemon — see §3).

---

# 3. End-to-end (real calendar event)

## 3.1 Setup (one time)

```bash
cd /Users/mba/projects/calflow
source .venv/bin/activate
# place credentials.json at secrets/credentials.json
python3 -m cli.main setup
```

Walk through:
1. Paste OAuth client JSON
2. Pick which calendars to monitor
3. Pick polling interval (default 60s)
4. Optionally generate the test event

## 3.2 Verify the daemon is loaded

```bash
python3 -m cli.main status
```

**Expected:** `✅ CalFlow is loaded` + a `com.calflow` line from launchctl.

## 3.3 Smart Mode test event

In Google Calendar, create an event ~5 minutes from now with description:

```
## smoke test — Smart Mode
zoom.us @chrome #left(50%)  ## meeting
notion.so @chrome #right(50%)
```

**Expected at the trigger time:**
- Chrome opens both URLs
- One on left half, one on right half
- The `## meeting` annotation is invisible to the runtime
- `data/launchd.out.log` shows:
  ```
  [INFO] Mode: SMART
  [INFO] Forced URL or [INFO] Opened URL in Google Chrome: https://zoom.us
  ```

## 3.4 Plus Mode test event

```
## smoke test — Plus Mode + dynamic
+CalFlow+

open zoom.us @chrome   ## the daily standup
wait 2                 ## let page render
screenshot             ## capture
save source(clipboard) to("~/Downloads/CalFlow/standup_{now > YYYY-MM-DD_hh-mm}.png")
```

**Expected at the trigger time:**
- Chrome opens zoom.us
- After 2s, `screencapture` writes `~/Downloads/CalFlow/calflow_<timestamp>.png`
  (note: the `to("…")` path is currently a stub — see `docs/roadmap.md` v2.3)
- `data/launchd.out.log` shows:
  ```
  [INFO] Mode: PLUS
  [INFO] Opened URL in Google Chrome: https://zoom.us
  [INFO] WAIT 2.0s
  [INFO] Screenshot saved: /Users/<you>/Downloads/CalFlow/calflow_…png
  [INFO] SAVE source='clipboard' to='/Users/<you>/Downloads/CalFlow/standup_2026-…' (stub)
  ```

## 3.5 Dynamic-only smoke

```
+CalFlow+

open "https://example.com/report?from={now-7d}&to={now}"
open "https://example.com/monthly?range={now-1mo > start_of_month}_{now-1mo > end_of_month}"
```

**Expected:**
- The first opens with two ISO dates (today minus 7d, and today)
- The second opens with the previous month's first and last dates
- Both substitutions happen at **execute time**, not parse time

---

# 4. What's stubbed (logged, not done)

Per `docs/roadmap.md`, these print `(stub)` instead of acting:

| Verb | Stub log | Will land in |
|------|----------|--------------|
| FOCUS | `[INFO] FOCUS apps=[…] title=…` | v2.1 |
| CLOSE | `[INFO] CLOSE items=[…]` | v2.1 |
| HIDE  | `[INFO] HIDE items=[…]` | v2.1 |
| CLICK | `[INFO] CLICK selector=…` | v2.1 |
| TYPE  | `[INFO] TYPE 'hello' …`  | v2.1 |
| PRESS | `[INFO] PRESS keys=…`    | v2.1 |
| COPY / PASTE / SAVE | `[INFO] SAVE source=… to=…` | v2.3 |
| RUN arbitrary script/path | `[INFO] RUN '…' (stub — refusing)` | deferred; disabled by default |
| Layout window-move (after `parse_layout_tag`) | `[INFO] Applying layout …` | v2.2 |

The pipeline still runs each line and the next command still executes.
Failures in real backends are best-effort (`[ERROR]` + continue).
Real `RUN` backends now include `-btt`, `-shortcut`, `-alfred`, and
`-applescript`, gated by event trust and backend allowlists in
`config/settings.py`. Failures from those backends are logged and can
show macOS notifications.

---

# 5. Quick troubleshooting

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| `python3 -m cli.main` → ModuleNotFoundError 'google.auth' | venv not active | `source .venv/bin/activate` |
| Daemon doesn't fire on event | event time outside execution window | check `EARLY_TOLERANCE` / `GRACE_SECONDS` in `config/settings.py`; logs in `data/launchd.err.log` |
| `{now > YYYY-MM-DD}` opens literally | URL contains the brace but parsing failed | run the §2.5 smoke and confirm it resolves there; if not, file an issue with the exact URL |
| Plus block runs in Smart Mode | header missing or misspelled | must contain `+CalFlow+` (case-insensitive) on its own line, anywhere in the description |
| Comment text appears in URL | `##` was inside a quoted string / brace / paren — that's intended (see DSL_GRAMMAR §1.3 Suppression) | use a true top-level `##` |

---

# 💡 One-line check

If everything works:

```bash
python3 -m unittest discover tests -p "test_v2_*.py" 2>&1 | tail -1
```

Should print: **`OK (skipped=5)`**.
