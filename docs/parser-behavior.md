# 📘 CalFlow Parser Behavior (v2.0)

This document defines how CalFlow parses and executes calendar event content.

It serves as the bridge between:

- **DSL_SPEC** — how users write CalFlow  
- **DSL_GRAMMAR** — what is syntactically valid  
- **runtime execution** — what actually happens when CalFlow runs  

This document explains not only **what** CalFlow accepts, but also **how** the parser:

- interprets  
- transforms  
- resolves  
- normalizes  
- executes  

input in a deterministic and predictable way.

---

# 1. Execution Pipeline Overview

CalFlow processes an event in the following stages:

```text
Raw Event Text
    ↓
Mode Detection
    ↓
Preprocessing (clean lines)
    ↓
Parsing (tokens → commands)
    ↓
State Resolution
    ↓
Execution
    ↓
Logging
```

Each stage has a **strictly defined responsibility** and must not overlap responsibilities of other stages.

---

## 1.1 Stage Definitions

---

### Raw Event Text

**Definition:**  
The original event description as stored in the calendar system.

---

### May Contain

- URLs  
- commands  
- comments  
- blank lines  
- aliases (`@...`)  
- modifiers (`#...`)  
- dynamic expressions (`{...}`)  

---

### Constraint

- No interpretation occurs at this stage  
- Input must be treated as raw text  

---

### Mode Detection

**Definition:**  
Determines whether the document is executed in:

- Smart Mode  
- Plus Mode  

---

### Key Rule

- Mode selection is **global and immutable** after detection  

---

### Preprocessing

**Definition:**  
Transforms raw text into normalized lines for parsing.

---

### Responsibilities

- split lines  
- trim whitespace  
- remove empty lines  
- detect comments  
- preserve order  

---

### Constraint

Preprocessing must NOT:

- reorder lines  
- execute logic  
- infer missing commands  

---

### Parsing

**Definition:**  
Converts normalized lines into structured commands.

---

### Examples

- Smart Mode:
  ```
  zoom.us → open zoom.us
  ```

- Plus Mode:
  ```
  click text("Export") → structured command
  ```

---

### State Resolution

**Definition:**  
Applies context and resolves:

- global modifiers (Smart Mode only)  
- line-level overrides  
- alias expansion  
- target resolution  
- layout normalization  

---

### Execution

**Definition:**  
Performs resolved actions sequentially.

---

### Logging

**Definition:**  
Captures execution outcomes.

---

### Includes

- success  
- skipped lines  
- warnings  
- errors  

---

# 2. Mode Detection

---

## 2.1 Smart Mode (Default)

### Trigger Conditions

Smart Mode is selected when:

1. no `+CalFlow+` marker exists  
2. at least one valid URL is present  

Both conditions MUST be satisfied.

---

## 2.2 Plus Mode

### Trigger

```text
+CalFlow+
```

---

### Behavior

- entire document switches to Plus Mode  
- Smart Mode rules are disabled  

---

## 2.3 Mode Priority

| Condition | Result |
|----------|--------|
| `+CalFlow+` present | Plus Mode |
| otherwise | Smart Mode |

---

## 2.4 Critical Constraint

Mode detection is:

- document-wide  
- not line-by-line  

---

### Implication

```text
zoom.us

+CalFlow+
open notion.so
```

→ Entire document = Plus Mode  

---

# 3. Preprocessing

---

## 3.1 Line Splitting

- split by newline  
- preserve order  
- trim whitespace  
- ignore empty lines  

---

## 3.2 Comments

`##` introduces a comment that runs to end-of-line. Both whole-line
and inline forms are supported.

```text
## whole-line comment

open zoom.us @chrome   ## inline comment
```

### Suppression

`##` is preserved literally inside:

- double-quoted strings: `"hello ## world"`
- single-quoted strings: `'hello ## world'`
- parens: `text("step ## 2")`
- brackets: `["a ## b", "c"]`
- dynamic blocks: `{now ## kept}`

### Behavior

- the comment portion is ignored during preprocessing  
- does not affect parsing of the surrounding line  
- does not affect global tag state  
- canonical helper: `core.utils.strip_inline_comment(line)`  

### Why `##` and not `#`

`#` is the tag marker (`#left(50%)`). Doubling it gives a clean,
collision-free comment marker that doesn't conflict with URL syntax
(`//`), calendar text artifacts (`--`, `;`), or escape-like sequences
(`\\`).

---

## 3.3 Normalization

---

### URL Normalization

```text
google.com → https://google.com
```

---

### Whitespace Rules

Allowed inside:

- `()`  
- `{}`  
- `[]`  

---

### Time Unit Normalization

If unit is omitted:

```text
speed(1) → speed(1s)
wait 5   → wait 5s
```

---

### Relative Layout Fallback

Applies only to:

- `#left`
- `#right`
- `#middle`
- `#top`
- `#bottom`

---

### Example

```text
#left(50) → #left(50%)
```

---

### Area Normalization

```text
#area(0,0,1920,1080) → pixels
#area(0,0,50%,50%)   → percentage
```

---

### Constraints

- order preserved  
- no implicit behavior added  

---

## 3.4 Forbidden Actions

Preprocessing must NOT:

- execute commands  
- merge lines  
- infer missing syntax  

---

# 4. Smart Mode Parsing

---

## 4.1 Line Classification

| Type | Example |
|------|--------|
| URL line | `zoom.us @chrome #left(30)` |
| Global modifier | `#display(2)` |
| Alias | `@chrome` |
| Comment | `## note` |
| Invalid | ignored |

---

## 4.2 Global State

Smart Mode maintains global modifier state.

---

### Example

```text
#display(2)
@chrome
#profile(1)

zoom.us
```

---

### Result

```text
browser = chrome
display = 2
profile = 1
```

---

### Conflict Rules

- same category → last wins  
- different → merged  

---

## 4.3 URL Execution

---

### Resolution Order

1. apply global state  
2. apply line overrides  
3. resolve conflicts  
4. normalize URL  
5. normalize layout  
6. convert → command  
7. execute  

---

### Example

```text
#display(2)
zoom.us @chrome
```

→ Chrome opens Zoom on display 2  

---

## 4.4 Internal Conversion

```text
zoom.us → open zoom.us
```

---

## 4.5 Alias Line

```text
@chrome
```

---

### Behavior

- updates global state  
- does NOT execute  

---

## 4.6 Invalid Lines

```text
hello world
```

---

### Behavior

- ignored  
- does not block execution  

---

# 5. Plus Mode Parsing

---

## 5.1 Line Types

| Type | Behavior |
|------|----------|
| Command | execute |
| Standalone modifier | ignored |
| Comment | ignored |
| Invalid | skipped |

---

## 5.2 No Global State

```text
#display(2) → ignored
```

---

## 5.3 Command Structure

```text
<command> [primary] [@target] [#modifiers...] [function(...)]
```

---

## 5.4 Primary

Represents main input:

- URL  
- file  
- app  
- collection  

---

## 5.5 Function Arguments

```text
click text("Export")
save source(clipboard)
```

---

## 5.6 Function-call Syntax (mandatory)

UI interaction arguments MUST use function-call form:

```text
click text("Export")
click selector(".btn")
click position(100,200)
```

The legacy `text="Export"` (key-value) form is **not supported**.
Lines using it are rejected by the validator (see `validation.md` §3.8).

---

## 5.7 Resolution Pipeline

Per-command order:

1. **bundle expansion** — if the lone argument is an `@bundle` (defined
   in `BUNDLES`), the command is replaced by N independent commands —
   one per bundle item — preserving order
2. **target resolution** (per resulting command):
   1. alias / target (`@chrome`)  
   2. URI (`scheme://`)  
   3. file path  
   4. quoted → app → URL  
   5. bare URL  

Bundle expansion runs first so subsequent steps see only "leaf"
commands.

---

### Multiple Target Rule

```text
open zoom.us @chrome @safari → invalid
```

(Two `@target` tokens on the same command is always invalid.)

---

### Bundle Exclusivity Rule

```text
open zoom.us @work → invalid
```

A bundle (`@work`) cannot share a command with another argument.
The validator skips the line and logs `[WARN]`.

---

## 5.8 Alias Expansion

`@alias` resolution depends on which settings table the name is in:

| Table | Effect |
|-------|--------|
| `TARGETS` (string) | resolved to a single app name; routes the primary |
| `TARGETS` (list) — *legacy* | treated as a bundle (warning logged); migrate to `BUNDLES` |
| `BUNDLES` | expanded into N commands at runtime |

```text
open @work    →    open "Slack"
                   open "https://workwebsite1.com"
                   open "Figma"
```

Items in a bundle may be:

- application names (`"Slack"`)
- URLs (`"https://workwebsite1.com"`)
- file paths (`"~/Reports/today.pdf"`)

Bundles are **flat** — an item may not be another `@alias` reference.

### Tag propagation

Modifiers on the original command flow into every expanded child:

```text
open @work #left(50%)
```

Becomes:

```text
open "Slack"                    #left(50%)
open "https://workwebsite1.com" #left(50%)
open "Figma"                    #left(50%)
```

### Verb compatibility per item

When a non-`open` verb expands a bundle, items that don't fit the verb
are skipped with a `[WARN]`. URLs and file paths cannot be focused,
hidden, or closed — only app items can.

| Verb | App item | URL item | File item |
|------|----------|----------|-----------|
| `open`  | open the app | open the URL in the default browser | open the file with its default app |
| `focus` | focus the app window | skip + `[WARN]` | skip + `[WARN]` |
| `close` | quit the app | skip + `[WARN]` | skip + `[WARN]` |
| `hide`  | hide the app | skip + `[WARN]` | skip + `[WARN]` |

---

## 5.9 Execution Order

- strictly top → bottom  
- no reordering  

---

## 5.10 Standalone Modifiers

Ignored.

---

## 5.11 Attached Modifiers

Valid:

```text
open zoom.us #left(50%)
```

---

# 6. Modifier Handling

---

## 6.1 Categories

| Category | Examples |
|----------|----------|
| Display | #display |
| Layout | #left, #area |
| Session | #profile |
| Behavior | #fill, #submit |

---

## 6.2 Precedence

- same → last wins  
- different → merged  

---

## 6.3 Layout Rules

- applied AFTER window resolves  
- ignored if no window  

---

## 6.4 Layout Conflict

```text
#left(30) #right(70) → right wins
```

---

## 6.5 Relative Layout

Independent per command:

```text
open a #left(50%)
open b #right(50%)
```

---

## 6.6 `#area`

Supports:

- pixels  
- %  
- mixed  

---

### Normalization

| Case | Behavior |
|------|----------|
| x < 0 | → 0 |
| width <= 0 | → MIN |
| overflow | allowed |

---

---

# 7. Dynamic Expressions

---

## 7.1 Timing

Evaluated:

- after parsing  
- before execution  

---

## 7.2 Pipeline

```text
parse → offset → conversion → format
```

---

## 7.3 Error Handling

- skip  
- log warning  

---

# 8. Execution

---

## 8.1 Model

- sequential  
- best-effort  
- non-blocking  

---

## 8.2 Failures

| Case | Behavior |
|------|----------|
| click not found | skip |
| focus fail | skip |

---

# 9. Timing & Repeat

---

## 9.1 repeat()

- applies to click/type/press  
- capped (recommended ≤100)

---

## 9.2 speed()

- per character/key  
- default 0s  

---

## 9.3 interval()

- between repeats  

---

## 9.4 timeout()

- max execution time  

---

## 9.5 wait

```text
wait 5s
wait(5s)
```

---

### Limits

- max = 60 minutes  

---

# 10. Keyboard Model

---

## 10.1 type vs press

| Command | Purpose |
|--------|--------|
| type | text |
| press | key events |

---

## 10.2 press sequence

```text
press [{shift_down},({left})x5,{shift_up}]
```

---

### Rules

- local scope only  
- no cross-command state  

---

# 11. Clipboard

---

## Example

```text
screenshot
save source(clipboard)
```

---

## Failure

- empty clipboard → skip  

---

# 12. Logging

---

## Types

```text
[INFO]
[WARN]
[ERROR]
```

---

## Must Log

- invalid lines  
- failures  
- expansions  

---

# 13. Determinism

---

CalFlow guarantees:

- same input → same behavior  
- no hidden state (Plus Mode)  
- predictable overrides  

---

# 14. Design Principles

---

## Explicit > Implicit

---

## Fail Small

---

## State Isolation

- Smart Mode → global allowed  
- Plus Mode → none  

---

## Predictability

No hidden magic.

---

# 🚀 Summary

CalFlow parsing is:

- deterministic  
- layered  
- predictable  

---

# 💡 One-line Mental Model

**Parse → Resolve → Execute**