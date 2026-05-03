# 📘 CalFlow DSL Grammar (v2.0)

This document defines the formal grammar, parsing rules, normalization rules, and resolution logic for CalFlow.

This is the **authoritative specification** for how CalFlow interprets input.

All syntax rules, resolution priorities, normalization behaviors, and execution assumptions defined here MUST be treated as:

- deterministic  
- consistent  
- binding across all implementations  

This document explains:

- what inputs are valid  
- how inputs are interpreted  
- how ambiguity is resolved  
- how invalid input is handled  

---

# 1. Top-Level Structure

```ebnf
document ::= plus_block | smart_block
```

---

## Definition

A CalFlow document MUST be interpreted entirely as either:

- a Smart Mode block  
- OR a Plus Mode block  

---

## Constraint: Mode Exclusivity

- Mode detection is **document-wide**, not line-by-line  
- Mixed-mode execution is NOT allowed  
- Once `+CalFlow+` appears, the entire document becomes Plus Mode  

---

## 1.1 Smart Mode

```ebnf
smart_block ::= line+
line        ::= url_line
              | tag_line
              | comment
              | empty_line
```

---

### Activation Conditions

Smart Mode is activated when:

1. no `+CalFlow+` marker exists  
2. at least one valid URL line exists  

Both MUST be satisfied.

---

### Behavior

- implicit `open` conversion  
- global tag state enabled  
- URL-driven execution  

---

## 1.2 Plus Mode

```ebnf
plus_block ::= "+CalFlow+" newline command_line*
```

---

### Activation Rule

- first occurrence of `+CalFlow+` switches mode  
- applies to entire document  

---

### Behavior

- every line is a command  
- no implicit actions  
- no global state  

---

### Constraints

- Smart Mode rules MUST NOT apply  
- parsing continues until end-of-document  

---

## 1.3 Comments

```ebnf
comment ::= "##" any-char* (newline | end-of-line)
```

A comment starts at the first **top-level** `##` and runs to the end
of the line.

### Forms

- **Whole-line comment** — line starts with `##`:

  ```text
  ## this whole line is a comment
  ```

- **Inline comment** — `##` after a command, target, or URL:

  ```text
  open zoom.us @chrome    ## the daily standup
  wait 2                  ## let the page settle
  ```

### Suppression rules

`##` is **only** treated as a comment marker when it sits at the top
level of the line. It is preserved literally when it appears inside:

| Container | Example |
|-----------|---------|
| double-quoted string | `type("hello ## world")` |
| single-quoted string | `type('hello ## world')` |
| function-call args   | `click text("step ## 2")` |
| collection           | `hide ["A ## B", "C"]` |
| dynamic block        | `{now ## not_a_comment}` |

This means a `##` inside a quoted string, parens, brackets, or braces
is **not** a comment — it's data.

### Behavior

- the comment portion is ignored during parsing  
- ignored during execution  
- does NOT affect mode detection  
- does NOT affect global tag state  
- a whole-line comment collapses to an empty line  
- an inline comment leaves the rest of the line intact for parsing  

### Choice rationale

- `#` (single hash) is reserved for tags (`#left(50%)`, `#display(2)`).
- `##` is unambiguous, doesn't collide with URL syntax, and reads well
  in calendar event descriptions.

### What is NOT a comment

```text
# tag                    not a comment — `#` introduces a tag
// comment               not supported — would collide with URL '//'
-- comment               not supported — calendar text uses '--' as em-dash
; comment                not supported — calendar text uses ';' literally
```

---

# 2. Smart Mode Grammar

---

## 2.1 URL Line

```ebnf
url_line ::= url target? tag*
```

---

### Definition

Represents a **single implicit action**.

---

### Examples

```text
zoom.us
zoom.us @chrome
zoom.us @chrome #left(30)
zoom.us @chrome #left(30%)
```

---

### Behavior

Internally normalized to:

```text
open <url> [@target] [#tags...]
```

---

### Constraints

- URL MUST be valid (Section 6)  
- target optional  
- tags optional  
- order preserved  

---

## 2.2 Global Tag Line

```ebnf
tag_line ::= (tag | target)+
```

---

### Definition

Defines **persistent context** for subsequent lines.

---

### Examples

```text
#display(2)
@chrome
#profile(1)
#submit
```

---

### Behavior

- applies to all following URL lines  
- persists until overridden  
- does NOT execute  

---

### Constraints

- Smart Mode only  
- ignored in Plus Mode  

---

### Conflict Resolution

- same category → last wins  
- different categories → merged  

---

## 2.3 Comment

Ignored.

---

## 2.4 Empty Line

Ignored.

---

# 3. Plus Mode Grammar

---

## 3.1 Command Line

```ebnf
command_line ::= command comment?
command      ::= verb argument*
```

---

### Definition

Represents one executable instruction.

---

### Examples

```text
open @chrome
focus @chrome title("Inbox")
click text("Export")
type("hello") speed(0.1s)
press {cmd+shift+tab}
save source(clipboard) to("~/file.png")
```

---

## 3.2 Standalone Tags

```text
#display(2)
@chrome
```

---

### Behavior

- ignored  
- do NOT create state  
- must attach to command  

---

### Compatibility Rule

Attached tags remain valid:

```text
open zoom.us @chrome #left(50%)
screenshot #display(2)
```

---

# 4. Core Elements

---

## 4.1 Verb

```ebnf
verb ::= "open" | "focus" | "close" | "hide"
       | "click" | "type" | "press" | "wait"
       | "screenshot" | "copy" | "paste"
       | "save" | "run"
```

---

### Constraint

- case-insensitive  
- unknown → skipped  

---

## 4.2 Target / Bundle (`@`)

`@`-prefixed identifiers fall into two distinct categories:

```ebnf
target ::= "@" identifier        ; a single application (resolved from TARGETS)
bundle ::= "@" identifier        ; a list of executable items (resolved from BUNDLES)
```

The same surface syntax (`@name`) is disambiguated at runtime via the
two settings tables. A name MUST appear in exactly one of them.

---

### Behavior

- **target** → resolved to an application name; routes the command's
  primary argument
- **bundle** → expanded at runtime into N independent commands;
  preserves order, executes sequentially

---

### Constraints

- must start with `@`  
- must exist in `TARGETS` or `BUNDLES`  
- a bundle is **never** combined with another argument (see §5)  
- otherwise skipped + `[WARN]` logged  

---

## 4.2.1 Alias as Argument

Aliases may also appear as positional arguments:

```ebnf
arg   ::= string
        | url
        | file_path
        | dynamic_block
        | alias

alias ::= "@" identifier
```

Aliases used as arguments are **always bundles** (because targets
appear in their own grammar slot for routing). Bundles are expanded
at runtime into multiple execution steps.

---

## 4.3 Tags (`#`)

```ebnf
tag ::= "#" identifier ( "(" args? ")" )?
```

---

### Behavior

Modify:

- layout  
- display  
- session  
- behavior  

---

### Evaluation

- left → right  
- last conflict wins  

---

### Categories

| Category | Examples |
|----------|----------|
| Display | #display |
| Layout | #left, #area, #grid |
| Session | #profile |
| Behavior | #fill, #submit, #slow |

---

### Relative Fallback

```text
#left(55) == #left(55%)
```

---

### Exception

Does NOT apply to `#area(...)`

---

## 4.4 Arguments

```ebnf
args ::= value ( "," value )*
```

---

### Rules

- positional  
- ordered  
- whitespace ignored  

---

## 4.5 Collections

```ebnf
collection ::= "[" value ( "," value )* "]"
```

---

### Behavior

- grouped values  
- ordered  

---

### Constraint

Single item allowed without brackets.

---

## 4.6 Function Calls

```ebnf
function_call ::= identifier "(" args? ")"
```

---

### Purpose

- UI targeting  
- execution control  
- IO routing  

---

## 4.7 Values

```ebnf
value ::= number | percentage | string | identifier
        | dynamic_expr | special_key | collection
```

---

## 4.8 Percentages

Relative to context.

---

## 4.9 Strings

Must be quoted if spaced.

---

# 5. Command Structure

---

## Pattern

A command takes EITHER a primary (with optional target) OR a bundle:

```text
<command> <primary> [@target] [#tags...] [function(...)]*
<command> @bundle             [#tags...] [function(...)]*
```

---

## Primary

Main object of command (URL, app name, file path, dynamic block).

---

## Multiple Target Rule

Multiple `@target` → invalid.

---

## Bundle Exclusivity Rule

`<command> <primary> @bundle` → **invalid** (ambiguous between routing
and expansion). The validator skips the line and logs `[WARN]`.

---

# 6. Resolution Pipeline

Per-command resolution order:

1. **bundle expansion** — if the lone argument is `@bundle`, expand to
   N commands and re-enter the pipeline for each item
2. **target resolution** for each (now non-bundle) command:
   1. alias (`@target`)  
   2. URI (`scheme://`)  
   3. file path  
   4. quoted → app → URL  
   5. bare URL  
   6. invalid  

---

## URI Override

`://` always wins.

---

## URL Normalization

```text
zoom.us → https://zoom.us
```

---

## URI Override

`://` always wins.

---

## URL Normalization

```text
zoom.us → https://zoom.us
```

---

# 7. Dynamic Expressions

Evaluated at execution time, AFTER parsing and BEFORE dispatch.

---

## 7.1 Pipeline Grammar

```ebnf
<dynamic>     ::= "{" <pipeline> "}"
<pipeline>    ::= <base>
                  { ">" <transform> }
                  [ ">" <format_stage> ]

<base>        ::= "now" [ ("+" | "-") <int> <unit> ]
<unit>        ::= "s"   // seconds
                | "m"   // minutes
                | "h"   // hours
                | "d"   // days
                | "w"   // weeks
                | "mo"  // months
                | "y"   // years

<transform>   ::= "start_of_day" | "end_of_day"
                | "start_of_week" | "end_of_week"
                | "start_of_month" | "end_of_month"
                | "start_of_year" | "end_of_year"

<format_stage> ::= <token-string>
                 | "format(" <string> ")"
```

> Whitespace around `>` is optional. Both `{now-1mo>end_of_month}` and
> `{now-1mo > end_of_month}` are accepted. The spaced form is preferred
> for readability and is what every example in this doc uses.

---

## 7.2 Examples

```text
{now}
{now-7d}
{now-2h > HH:mm}
{now-1mo > end_of_month > YYYY-MM-DD}
{now-1mo > end_of_month > format("YYYY-MM-DD")}
```

---

## 7.3 Notes

- The final pipeline stage is interpreted as a format stage.
- Format may be provided as:
  - shorthand: `YYYY-MM-DD`
  - explicit: `format("YYYY-MM-DD")`
- `format()` is preferred for unambiguous parsing.
- `>` is the only pipeline operator (no `:` usage).

---

# 8. Special Keys

Supports:

- modifiers  
- navigation  
- function keys (F1–F19)  
- left/right variants  

---

## Press Sequences

```text
press [{shift_down},({left})x5,{shift_up}]
```

---

## Repetition

`x` is canonical operator.

---

# 9. Layout Grammar

---

## Relative

```text
#left #right #middle #top #bottom #full
```

---

## Grid

```text
#grid(3x2@1)
```

---

## Area

```text
#area(x,y,w,h)
```

---

### Rules

- pixel default  
- % allowed  
- mixed units allowed  
- overflow allowed  
- negative normalized  

---

## Display

```text
no tag                         primary display
#display                       first external monitor
#display()                     first external monitor
#display(ext)                  first external monitor (recommended hint)
#display(2)                    Nth display by index (1-based; no fallback)
#display("Samsung S90D")       case-insensitive substring match (no fallback)
```

Run `python3 -m cli.main display` to see your connected monitors and
the exact strings you can use in `#display("…")`.

---

# 10. Execution Control

---

## Functions

```text
repeat(n)
interval(t)
speed(t)
timeout(t)
```

---

## Wait

```text
wait 5s
wait(5s)
```

---

### Rules

- default seconds  
- max = 60m  

---

# 11. Execution Model

- sequential  
- best-effort  
- non-blocking  
- deterministic  

---

## Selector Rules

- first match  
- AND logic supported  

---

## Conflict Exception

Conflicting selectors invalidate command.

---

# 12. Symbol Roles

| Symbol | Meaning |
|--------|--------|
| @ | target |
| # | context |
| () | parameters |
| [] | collection |
| {} | dynamic/input |
| x | repetition |

---

## 12.1 Mental Model

- `@` = WHAT  
- `#` = WHERE / CONTEXT / BEHAVIOR  
- `()` = STRUCTURED ARGUMENTS  
- `[]` = COLLECTION OR TIMELINE  
- `{}` = DYNAMIC / KEY TOKEN  
- `x` = REPEAT THIS ITEM  

---

# 13. Design Principles

- explicit > implicit  
- deterministic resolution  
- human-readable  
- flexible for beginners, precise for power users  

---

## 13.1 Separation of Concerns

| Component | Role |
|----------|------|
| verb | action |
| @target | object |
| #tag | context / layout / behavior |
| () | structured parameters |
| [] | collections or press timelines |
| {} | dynamic/input token |
| xN | repetition inside press sequence |

---

## 13.2 Why This Matters

- prevents ambiguity  
- ensures parser consistency  
- enables safe extensibility  
- keeps Smart Mode simple and Plus Mode powerful  

---

# 💡 One-liner

**"Explicit input → deterministic execution."**