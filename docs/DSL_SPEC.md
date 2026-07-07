# 📘 CalFlow DSL Spec (v2.0)

This document defines how to use CalFlow in real-world scenarios.

It is the **user-facing guide** that explains:

- how to write CalFlow instructions  
- how each construct behaves  
- how Smart Mode and Plus Mode differ  

Every concept in this document is:

- **defined** (what it is)  
- **exemplified** (how to use it)  
- **constrained** (what is allowed vs not allowed)  

---

## Getting Started

- If you are new → start with **Smart Mode**  
- If you want full control → use **Plus Mode**

---

# 1. Modes Overview

CalFlow supports two execution modes:

| Mode | Purpose | Complexity |
|------|--------|-----------|
| Smart Mode | quick automation | low |
| Plus Mode | full automation | high |

---

## 🟢 Smart Mode (Default)

### Definition

Smart Mode is a **URL-driven automation mode** with minimal syntax.

---

### Designed For

- zero setup  
- meetings  
- repetitive daily workflows  

---

### 1.1 How it Works

- each line containing a URL becomes one action  
- URLs are automatically detected and normalized  
- tags (`#...`) modify behavior  

---

### 1.2 Basic Syntax

```text
<url> [@target] [#tag...]
```

---

### 1.3 Example

```text
zoom.us @chrome #left(30%)
notion.so @safari #right(70%)
```

---

### 1.4 What Happens

For each line:

1. URL is normalized  
   ```
   zoom.us → https://zoom.us
   ```

2. Target is resolved  
   ```
   @chrome → Google Chrome
   ```

3. Window is opened  

4. Layout is applied  

---

### Result

- Zoom opens in Chrome (left 30%)  
- Notion opens in Safari (right 70%)  
- windows are arranged automatically  

---

### 1.5 Mental Model

- each line = one app or website  
- Smart Mode implicitly assumes `open`  
- tags define **where and how it appears**  

---

### Constraints

- only URL lines trigger execution  
- invalid lines are ignored  
- global tags are allowed (see Section 2.2)  

---

## 🔵 Plus Mode (`+CalFlow+`)

### Definition

Plus Mode is a **command-driven automation mode**.

---

### Designed For

- deterministic workflows  
- scripting  
- multi-step automation  

---

### 1.6 How it Works

- the document MUST contain a `+CalFlow+` line (anywhere)  
- every line **after** the marker is a command  
- every line **before** the marker is treated as a comment (even URLs)  
- executed sequentially (top → bottom)  

> Plus Mode is document-wide. Once `+CalFlow+` appears, Smart Mode rules
> stop applying for the entire event — including any URL lines that
> happen to sit above the marker.

---

### 1.7 Basic Syntax

```ebnf
+CalFlow+

<command> [primary] [@target] [#tag...] [function(...)] [option(...)]
```

> This is a syntax pattern, not a runnable example. See §1.8 for one.

---

### 1.8 Example

```text
+CalFlow+

open @work #display(2)
focus @chrome #left(50%)
focus @slack #right(50%) #display(2)
click text("Export")
screenshot
save source(clipboard) to("~/Desktop/export_{now > YYYY-MM-DD_hh-mm}.png")
```

---

### 1.9 What Happens

Step-by-step:

1. `@work` expands into multiple apps  
2. apps open on display 2  
3. Chrome is focused and placed on the left  
4. Slack is focused on display 2 (right side)  
5. "Export" is clicked  
6. screenshot → clipboard  
7. file saved with timestamp  

---

### 1.10 Mental Model

- each line = one action  
- execution is sequential  
- outputs flow between steps  

---

### Constraints

- no implicit `open`  
- no global state  
- invalid commands are skipped  

---

# 2. Core Concepts

---

## 2.1 Targets vs Bundles (`@`)

`@`-prefixed identifiers fall into **two distinct categories**, and they
are NOT interchangeable in the same command:

| Category | Examples | Meaning |
|----------|----------|---------|
| **Target** | `@chrome`, `@safari`, `@figma` | **WHERE** an action runs (a single application) |
| **Bundle** | `@work`, `@comm`, `@design` | **WHAT** to execute — a list of items expanded at runtime |

---

### Targets — WHERE

A target identifies a single application. It can be used:

- as the primary of `open` / `focus` / `close` / `hide`
- as a routing modifier on a Smart Mode URL line: `zoom.us @chrome`

```text
@chrome   → "Google Chrome"
@safari   → "Safari"
@figma    → "Figma"
```

Resolved via the effective `TARGETS` table: tracked defaults in
`config/settings.py`, plus any user overrides saved from Settings →
Aliases in `data/user_targets.json`.

---

### Bundles — WHAT (Execution Macros)

A bundle is a heterogeneous list of executable items. Items may be:

- application names (`"Slack"`)
- URLs (`"https://workwebsite1.com"`)
- file paths (`"~/Reports/today.pdf"`)

Resolved via `config/settings.py` under `BUNDLES` (see §2.1.4).

```text
@work → [
  "Slack",
  "https://workwebsite1.com",
  "Figma"
]
```

---

### 2.1.1 Bundle Expansion

```text
open @work
```

Expands at runtime into:

```text
open "Slack"
open "https://workwebsite1.com"
open "Figma"
```

#### Execution rules

- **order is preserved**
- **execution is sequential**
- each item is resolved independently (app vs URL vs file path)
- **`#tags` and `function(...)` modifiers on the original command apply
  to every expanded item** — i.e. `open @work #left(50%)` opens each
  bundle item and applies `#left(50%)` to each
- **bundles are flat** — items must be strings (app, URL, or file).
  A bundle MAY NOT contain another `@alias` reference (no nesting)

#### Per-verb behavior on bundle items

| Verb | Behavior on each bundle item |
|------|------------------------------|
| `open`  | open the item (app, URL, or file) — works on all types |
| `focus` | focus the item if it's an app; URL / file items → skip + `[WARN]` |
| `close` | close the item if it's an app; URL / file items → skip + `[WARN]` |
| `hide`  | hide the item if it's an app; URL / file items → skip + `[WARN]` |

> Mental model: **`open` is the primary verb for bundles.**
> `focus`/`hide`/`close` work too, but only their app-shaped items
> have any effect.

---

### 2.1.2 Bundles are arguments, not targets

A bundle behaves like an **argument** to the verb, not a routing
modifier. It cannot be combined with another argument in the same
command.

#### ✅ Valid

```text
open @work
focus @work
hide @work
close @work
```

#### ❌ Forbidden

```text
open zoom.us @work
```

> Why: ambiguous — is `@work` a target (route the URL there) or a
> bundle (expand into multiple opens)?

The validator rejects this with a clear message and skips the line.

---

### 2.1.3 Mixing rules summary

| Form | Verdict |
|------|---------|
| `open @chrome` | ✅ open the Chrome app |
| `open @work` | ✅ expand bundle → multiple opens |
| `open zoom.us` | ✅ open URL in default browser |
| `open zoom.us @chrome` | ✅ open URL in Chrome (target as routing) |
| `open zoom.us @work` | ❌ forbidden (URL + bundle) |
| `open zoom.us @chrome @safari` | ❌ forbidden (multiple targets) |

---

### 2.1.4 Where they live

```python
# config/settings.py
TARGETS = {
    "@chrome": "Google Chrome",
    "@safari": "Safari",
    "@figma":  "Figma",
}

BUNDLES = {
    "@work": ["Slack", "https://workwebsite1.com", "Figma"],
    "@comm": ["Slack", "Discord"],
}
```

A name MUST appear in exactly one of `TARGETS` or `BUNDLES`. If a
name appears in both, `BUNDLES` wins (warning logged at startup).

---

### 2.1.5 Constraints

- must start with `@`  
- must be defined in `TARGETS` or `BUNDLES`  
- undefined → command skipped + `[WARN]` logged  
- bundle and another argument in the same command → command skipped + `[WARN]`  

---

## 2.2 Tags (`#`)

### Definition

Tags modify:

- layout  
- display  
- browser session  
- behavior (Smart Mode only)  

---

### Examples

```text
#left(30%)
#right(70%)
#display(2)
#profile(1)
#area(0,0,1920,1080)
#grid(1@3x2)
#full
```

---

### Core Rule

> Tags are applied **only after a command resolves a window**

---

### Supported Commands

Layout tags apply ONLY to commands that produce a window:

```text
open @chrome #left(50%)
focus @chrome #right(50%)
```

---

### Invalid Use

```text
click text("Submit") #left(50%)
```

Behavior:

- click executes  
- layout tag ignored  

---

### Resolution Order

For each command:

1. execute command  
2. resolve window  
3. apply tags  

---

### Unit Rules

- `#left(30)` → treated as `30%`  
- `#left(30%)` → explicit  
- `#area(...)` defaults to pixels unless `%` used  

---

### `#display` — picking which monitor

| Form | Meaning | Fallback |
|------|---------|----------|
| *no `#display` tag* | primary monitor | n/a |
| `#display` | first external monitor | → primary if no external (warns) |
| `#display()` | same as `#display` | → primary if no external (warns) |
| `#display(ext)` | same as `#display` (recommended hint) | → primary if no external (warns) |
| `#display(N)` | Nth display, 1-based (1 = primary) | **none** — skips layout if N is out of range |
| `#display("Samsung S90D")` | case-insensitive substring match on the display's name | **none** — skips layout if no match |

Run `python3 -m cli.main display` to see your connected monitors and
the exact strings you can paste into `#display("…")`.

> **Portability tip.** `#display(N)` depends on your current macOS
> primary-display setting and the order in which OS sees displays —
> brittle if you move between locations. `#display` (bare) and
> `#display("…")` are robust across home/work/laptop-only setups.

---

### Global Tags (Smart Mode Only)

Standalone tags apply to all subsequent lines.

---

#### Example

```text
#display(2)
@chrome
#profile(1)

zoom.us
notion.so
```

---

#### Result

- both open on display 2  
- both use Chrome  
- both use profile 1  

---

### Constraint

- global tags DO NOT work in Plus Mode  

---

## 2.3 Parameters (`=`)

### Definition

Named configuration values.

---

### Examples

```text
to="~/file.png"
source=clipboard
```

---

### Constraints

- used for configuration only  
- NOT used for UI interaction  

---

## 2.4 Function Arguments (`()`)

### Definition

Structured input for commands.

---

### Examples

```text
text("Submit")
selector(".btn")
position(100,200)
```

---

### Constraints

- positional  
- must match expected signature  
- order matters  

---

## 2.5 Collections (`[]`)

### Definition

Grouping of multiple values.

---

### Examples

```text
hide ["Google Chrome","Safari"]
hide except([@work,"Spotify"])
hide except(@work)
```

---

### Rules

- comma-separated  
- order preserved  
- single item may omit brackets  

---

## 2.6 Dynamic Expressions (`{}`)

### Definition

Runtime-evaluated values, expanded at execution time as a left-to-right
**pipeline** of base → transforms → format.

---

### Examples

```text
{now}
{now-7d}
{now-2h > HH:mm}
{now-1mo > start_of_month > YYYY-MM-DD}
{now-1mo > end_of_month > format("YYYY-MM-DD")}
```

---

### 🔁 Pipeline Semantics

Execution order:

1. Resolve base (`now`)
2. Apply offsets (`-1mo`, `-7d`, `+2h`, …)
3. Apply transforms (`start_of_month`, `end_of_month`, …)
4. Apply format (`YYYY-MM-DD` or `format("…")`)

Format is applied AFTER all transformations in the pipeline.

---

### 🧾 Format Stage Rules

Format is always the FINAL stage in a pipeline.

Supported forms:

```text
> YYYY-MM-DD
> HH:mm
> format("YYYY-MM-DD")
```

#### Token table

| Token | Meaning |
|-------|---------|
| `YYYY` | year (4 digit) |
| `YY`   | year (2 digit) |
| `MM`   | month |
| `DD`   | day |
| `HH`   | 24-hour |
| `hh`   | 12-hour |
| `mm`   | minute |
| `ss`   | second |

---

### ⚠️ Format vs Transform Disambiguation

A pipeline stage is interpreted as a FORMAT if:

- it matches known datetime tokens (`YYYY`, `MM`, `DD`, `HH`, `mm`, …)
- OR it is explicitly wrapped in `format(...)`

Otherwise it is treated as a transform.

```text
end_of_month     → transform
YYYY-MM-DD       → format (token detection)
format("…")      → format (explicit)
```

---

### 🧠 Default Format

If no format stage is provided, the default is:

```text
YYYY-MM-DD
```

Resolver always returns string output.

---

### 🔒 Design Constraint

The DSL uses a single pipeline operator:

```text
>
```

There is NO use of `:` for formatting. This ensures:

- consistent parsing  
- composability  
- extensibility  

---

### Behavior

- evaluated at execution time  
- replaced before command runs  

---

### Constraint

- invalid expressions → logged as `[WARN]` and returned unchanged  
  (so the surrounding text is not destroyed)  

---

## 2.7 Special Keys (`{}`)

### Definition

Keyboard input tokens.

---

### Examples

```text
press {enter}
press {cmd+c}
press {shift+left}
press {f1}
press {f19}
press {left_cmd}
```

---

### Rules

- must be wrapped in `{}`  
- supports combinations  
- supports left/right modifiers  

---

## 2.8 Target Resolution

### Priority Order

1. `@alias`  
2. URI (`scheme://`)  
3. file path  
4. quoted string → app → fallback to URL  
5. bare URL  
6. invalid  

---

### Examples

```text
open @chrome
open https://zoom.us
open spotify://track/123
open "Google Chrome"
open "zoom.us"
open "~/file.pdf"
open zoom.us
open zoom   ❌
```

---

## 2.9 Interaction Functions

### Definition

Functions used for UI targeting.

---

### Supported

```text
text(...)
selector(...)
position(...)
```

---

### Examples

```text
click text("Sign in")
click selector(".submit-button")
click selector("[data-testid='submit']")
click position(100,200)
```

---

### Matching Rules

- multiple matches → first match  
- AND logic supported  

```text
click text("Submit") selector(".btn")
```

---

### Constraint

Conflicting selectors invalidate command:

```text
click text("Submit") position(100,200) ❌
```

---

# 3. Commands (Plus Mode)

---

## 3.1 App Control (v1.1.2)

```text
## OPEN
open @chrome
open @work                          ## bundle expansion
open https://x.com @chrome
open "Notion"
open zoom.us new(window)            ## force a new browser WINDOW
open zoom.us new(tab)               ## force a tab (also: #tab / #window)

## FOCUS
focus @chrome                       ## activate
focus @chrome title("Inbox")        ## raise matching window
focus @chrome display(2)            ## activate + move to display
focus active                        ## no-op (frontmost is focused)

## CLOSE
close @chrome
close [a, b]
close "Spotify"
close active                        ## quit frontmost
close all                           ## quit every visible app
close except(@work)                 ## quit everything except @work

## HIDE
hide @chrome
hide [a, b]
hide active                         ## hide frontmost
hide all                            ## hide every visible app
hide except(@work)                  ## hide all except @work
hide except(active)                 ## hide all except frontmost
hide display(2)                     ## hide all on display 2
hide except(@work) display(2)       ## combine
hide active display(2)              ## v1.5.2 — frontmost's windows on display 2 only
hide [active,"Spotify"]             ## v1.5.2 — `active` expands at run time
```

> Bare `hide` (no args) was REMOVED in v1.1.2. Use `hide except(active)`
> to keep the frontmost visible, `hide all` to hide everything, or
> `hide @app` to hide a specific app.

> v1.5.2 — `hide active display(N)` miniaturizes the frontmost app's
> windows on display N ONLY (per-window; the app's windows on other
> displays stay visible). If the frontmost has no window on that
> display, it's a logged no-op. `hide all display(N)` is normalized to
> `hide display(N)`. Inside a list, `active` expands to the frontmost
> app name at execution time and is deduped against the static items.

### Tab vs window (URL opens)

Whether a URL opens in a new TAB or a new WINDOW is decided by
`wants_new_window` with this precedence:

1. explicit `new(window)` / `new(tab)` function call — wins
2. explicit `#window` / `#new-window` / `#tab` / `#new-tab` tag
3. any layout or display tag implies WINDOW (a tab can't be
   positioned independently of the window it lives in)
4. default: TAB

`#profile(N)` does NOT imply a window — profile routing is
window-mode-agnostic.

---

## 3.2 Mouse & Keyboard

```text
click text("Sign in")
click selector(".btn")
click position(100,200)

type("hello")
type("abc") repeat(3) interval(0.5s) speed(0.1s)

press {enter}
press {cmd+shift+tab}
press [{shift_down},({left})x5,{shift_up}]
```

---

### Timing Options

```text
repeat(n)
interval(1s)
speed(0.1s)
timeout(3s)
```

---

### Defaults

- speed = 0.0s  
- interval = 0.0s  

---

### Limits

- max speed/interval = 60s  
- repeat capped (implementation-defined, recommended ≤100)  

---

## 3.3 Screenshot

```text
screenshot                           ## → clipboard (v1.5.2 default)
screenshot to(clipboard)             ## → clipboard (explicit spelling)
screenshot to("~/x.png")             ## → file (canonical path form — v1.1.2)
screenshot active                    ## frontmost-window capture
screenshot display(2)
screenshot display("Samsung S90D")
screenshot window("Google Chrome")
screenshot area(0,0,1920,1080)
```

---

### Behavior

- v1.5.2 — the DEFAULT sink is the CLIPBOARD (`screencapture -c`).
  Bare `screenshot` and `screenshot to(clipboard)` are equivalent.
  (Pre-v1.5.2 the bare form wrote a file to `PLUS_SCREENSHOT_DIR`.)
- a PNG FILE is written only when `to("path")` is supplied
- file filename pattern is `PLUS_SCREENSHOT_FILENAME_FORMAT`  
  (default `CalFlow_{YYYY-MM-DD_HHMMSS}.png`) when the path is a folder
- destination directory is created automatically if it doesn't exist; falls
  back to `~/Library/Application Support/CalFlow/screenshots/` if read-only
- both folder and filename pattern are configurable in `config/settings.py`
- positional path (`screenshot "~/x.png"`) was REMOVED in v1.1.2 — use
  `to("…")` for parity with `save … to(…)`

---

## 3.4 Clipboard

```text
copy                                 ## copy current selection (⌘C)
copy("hello")                        ## v1.5.2 — place literal text on clipboard
paste
save source(clipboard) to("~/file.png")
```

> v1.5.2 — `copy("text")` writes the literal straight to the clipboard
> via `pbcopy` (no keystroke synthesis, no Accessibility permission).
> The argument must be quoted; `copy(hello)` is rejected. Bare `copy`
> (selection copy) remains keystroke-based.

---

## 3.5 Run Backends

```text
run btt("BTT-ClaudeCoworkTryAgain")
run shortcut("Start Focus") input("deep work")
run alfred("com.example.workflow", "try-again") input("meeting prep")
run alfred("com.example.workflow/try-again") input("meeting prep")
run applescript if(error) notify(result)
+++
display dialog "hello"
+++
```

Run backends are gated by event trust and backend allowlists in
`config/settings.py`. `btt`, `shortcut`, `alfred`, and `applescript`
are real backends. Arbitrary file/script execution remains disabled by
default.

Run-result handlers are local to one run command:

```text
if(error) notify(result)
if(error) copy(result)
if(error) save to("~/Logs/calflow-last-error.txt")
if(success) notify("Done")
if(output) copy(result)
```

Run backend timeouts are configured in `config/settings.py`:

```python
RUN_APPLESCRIPT_TIMEOUT = 10
RUN_BTT_TIMEOUT = 5
RUN_SHORTCUT_TIMEOUT = 30
RUN_ALFRED_TIMEOUT = 5
```

Inline `timeout(...)` currently overrides AppleScript only. BTT,
Shortcuts, and Alfred use their settings-level timeout values.

# 4. Layout & Display

---

### Supported Layouts

```text
#left(30%)
#middle(40%)
#right(30%)
#full
#grid(1@3x2)
#area(0,0,1920,1080)
#display(2)
```

---

### Behavior Rules

- apply ONLY to window-producing commands  
- applied AFTER command execution  
- last layout tag wins  

---

### Examples

```text
open site1.com #left(33%)
focus @chrome #middle(34%)
focus @slack #right(33%)
```

---

# 5. Argument Order (Recommended)

Two valid forms:

```text
<command> <primary> [@target] [#tags...] [function(...)] [option(...)]
<command> @bundle           [#tags...] [function(...)] [option(...)]
```

A command takes EITHER a `<primary>` (with optional `@target` routing)
OR an `@bundle` — never both. See §2.1.2.

---

# 6. Execution Rules

- commands run sequentially  
- failures do NOT stop execution  
- context determines behavior  
- Plus Mode has NO global state  
- bundle expansion runs BEFORE per-command resolution (see §2.1.1)  

---

# 7. Best Practices

---

## Prefer readable targeting

```text
click text("Sign in")
```

---

## Avoid ambiguity

```text
❌ focus chrome
✔ focus @chrome
```

---

## Use timing when needed

```text
click text("Submit") timeout(3s)
```

---

## Keep scripts simple

- avoid unnecessary complexity  
- break flows into steps  

---

# 8. Notes

- Smart Mode assumes `open`  
- Plus Mode requires explicit commands  
- `#` supported in Plus Mode (compatibility only — see §9)  
- global tags apply ONLY in Smart Mode  

---

# 9. Type System (v1.1.2)

CalFlow's DSL distinguishes between **values** (data the engine
generates), **runtime targets** (system entities the engine resolves at
execution time), **aliases** (predefined sets), and **filters**
(modifiers that narrow a selection). Mixing these types is rejected at
parse time.

| Type            | Syntax    | Examples                           | Meaning                          |
|-----------------|-----------|------------------------------------|----------------------------------|
| Dynamic value   | `{ … }`   | `{now}`, `{now-7d > YYYY-MM-DD}`   | produces data                    |
| Runtime target  | bare ident | `active`, `all`                   | selects a system entity at exec  |
| Alias           | `@…`      | `@chrome`, `@work`                 | predefined set from settings     |
| Filter          | `name(…)` | `except(@x)`, `display(2)`         | modifies the verb's selection    |

## Reserved Keywords

```text
active   ← frontmost app (resolved at exec time)
all      ← every visible non-background app
display  ← filter function name
except   ← filter function name
```

User configuration (`TARGETS`, `BUNDLES`) MUST NOT shadow these. CalFlow
refuses to start with a clear error and a rename suggestion if it does.

## Invalid Usage

```text
hide {active}            ## ❌ {} is for VALUES only — use bare `active`
hide except({@work})     ## ❌ same — use `except(@work)`
hide {display(2)}        ## ❌ same — use `display(2)`
TARGETS = {"@active": …} ## ❌ shadows reserved keyword — refuses to start
```

## Rationale

- prevents mixing value and execution semantics
- keeps the parser + resolver simple (no precedence rules)
- guarantees portability — same script behaves identically on every machine

---

## 9.1 `#` Drop Sugar

In Plus Mode, attached function-shaped tags MAY drop the `#` prefix:

```text
open zoom.us @chrome display(2)     ≡  open zoom.us @chrome #display(2)
open zoom.us @chrome left(50%)      ≡  open zoom.us @chrome #left(50%)
open zoom.us @chrome area(0,0,1,1)  ≡  open zoom.us @chrome #area(0,0,1,1)
open zoom.us @chrome grid(1@3x2)    ≡  open zoom.us @chrome #grid(1@3x2)
open zoom.us @chrome profile(2)     ≡  open zoom.us @chrome #profile(2)
```

Smart Mode URL lines accept the same function-shaped layout/session
modifiers, so this also works without a `+CalFlow+` block:

```text
zoom.us @chrome display(2) grid(1@2x2) profile(3)
```

Bare-relative tags (`#left`, `#full`) keep the `#` because they're not
function-shaped. Standalone modifier lines remain Smart-Mode-only.

---

# 💡 One-liner

**"If it’s on your calendar, it should just happen."**
