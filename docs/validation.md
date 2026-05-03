# 📘 CalFlow Validation Rules (v2.0)

This document defines how CalFlow validates, interprets, and handles errors.

It serves as the **authoritative contract** for:

- parser behavior  
- QA expectations  
- runtime consistency  
- error tolerance guarantees  

All validation behavior described here MUST be deterministic and consistent across environments.

---

# 1. Validation Philosophy

CalFlow follows a **best-effort, non-blocking execution model**.

---

## 1.1 Core Principles

- Commands execute sequentially (top → bottom)  
- Errors do NOT stop execution by default  
- Invalid lines are skipped whenever possible  
- Execution continues unless explicitly configured otherwise  

---

## 1.2 Goals

- maximize successful execution  
- avoid breaking entire workflows due to single-line errors  
- maintain predictable and repeatable behavior  
- isolate failures to individual commands  

---

## 1.3 Non-Goals

CalFlow intentionally does NOT provide:

- strict compilation-style rejection  
- transactional guarantees  
- rollback or undo behavior  
- cross-command atomicity  

---

# 2. Error Categories

All validation errors MUST fall into one of the following categories:

| Type | Definition | When It Occurs | Behavior |
|------|-----------|----------------|----------|
| Syntax Error | input cannot be parsed | invalid structure | skip line |
| Semantic Error | valid syntax, invalid meaning | resolution failure | skip action |
| Runtime Error | execution failure | OS / UI / IO failure | log + continue |

---

## 2.1 Syntax Error

Occurs when DSL structure is invalid and cannot be parsed.

---

### Examples

```text
click text=Submit
#left30
press enter
```

---

### Behavior

- entire line is skipped  
- no execution attempt is made  
- MUST log as:

```text
[INFO] skipped line: invalid syntax
```

---

### Constraints

- parser MUST NOT attempt partial recovery  
- parser MUST NOT execute partially parsed commands  

---

## 2.2 Semantic Error

Occurs when syntax is valid but cannot be fulfilled.

---

### Examples

```text
open @unknown
click text("Missing")
save source(clipboard) to("file.png")   // clipboard empty
```

---

### Behavior

- command is skipped  
- execution continues  
- MUST log as `[WARN]`  

---

### Constraints

- parser MUST complete parsing  
- failure occurs at resolution stage  
- MUST NOT escalate to runtime error  

---

## 2.3 Runtime Error

Occurs during actual execution.

---

### Examples

- app fails to launch  
- permission denied (e.g. screen recording)  
- file system write failure  

---

### Behavior

- action fails  
- command skipped  
- MUST log as `[ERROR]`  
- execution continues  

---

### Constraints

- runtime MUST NOT retry automatically unless explicitly specified (e.g. repeat)  
- runtime MUST NOT terminate execution  

---

# 3. Syntax Validation

---

## 3.1 Invalid Target

```text
focus chrome
```

❌ Invalid  

✔ Valid:

```text
focus @chrome
focus "Google Chrome"
```

---

### Constraints

- unquoted identifiers MUST NOT be treated as valid targets  
- valid target forms:
  - alias (`@...`)  
  - quoted string  

---

## 3.2 Missing Quotes

```text
click text=Sign in
```

❌ Invalid  

✔ Correct:

```text
click text("Sign in")
```

---

### Constraints

- string arguments containing spaces MUST be quoted  
- function-style syntax is mandatory  

---

## 3.3 Invalid Modifier Format

```text
#left30
```

❌ Invalid  

✔ Correct:

```text
#left(30)
```

---

### Constraints

- modifiers with parameters MUST use parentheses  
- missing parentheses → syntax error  

---

## 3.4 Malformed Arguments

```text
#area(0,0,1920)
```

❌ Invalid  

✔ Correct:

```text
#area(0,0,1920,1080)
```

---

### Constraints

- argument count MUST match required signature  
- incorrect arity → syntax error  

---

## 3.5 Invalid Dynamic Expression

```text
{now-1x}
```

❌ Invalid unit  

✔ Valid units:

```text
s, m, h, d, w, mo, y
```

---

### Behavior

- invalid expression → treated as semantic error  
- affected command or argument skipped  
- MUST NOT crash execution  

---

## 3.6 Invalid Special Key Syntax

```text
press enter
```

❌ Invalid  

✔ Correct:

```text
press {enter}
```

---

### Constraints

- special keys MUST be wrapped in `{}`  
- raw identifiers are not valid key events  

---

## 3.7 Invalid Command

```text
launch @chrome
```

❌ Invalid verb  

✔ Valid:

```text
open @chrome
```

---

### Behavior

- unknown verbs → syntax error  
- line skipped  
- MUST NOT affect subsequent commands  

---

## 3.8 Invalid Function Syntax

```text
click text="Submit"
```

❌ Invalid  

✔ Correct:

```text
click text("Submit")
```

---

### Constraints

- UI interaction MUST use function-call syntax  
- key-value form is NOT valid unless explicitly supported  

---

# 4. Target Resolution Validation

---

## 4.1 Alias Target

```text
@chrome
@work
```

---

### Validation Rules

- MUST exist in `config/settings.py` (under `TARGETS`)  
- MAY expand to:
  - single app  
  - multiple apps  

---

### Failure Case

```text
open @unknown
```

→ semantic error  
→ skip + warn  

---

## 4.2 Direct App Name

```text
"Google Chrome"
```

---

### Rules

- MUST match system application name  
- MUST be quoted  

---

### Failure

```text
open "Unknown App"
```

→ skip + warn  

---

## 4.3 URI Handling

```text
open https://zoom.us
```

---

### Rules

- MUST contain `://`  
- ALWAYS treated as URI  

---

### Constraint

- URI resolution overrides all other resolution paths  

---

## 4.4 File Path

```text
open "~/file.pdf"
```

---

### Rules

- MUST exist  
- MUST be accessible  

---

### Failure

→ skip + `[ERROR]`  

---

## 4.5 Bare URL

```text
open google.com
```

---

### Behavior

- normalized to `https://google.com`  

---

### Invalid Case

```text
open google
```

→ invalid → skipped  

---

## 4.6 Multiple Targets (Invalid)

```text
open zoom.us @chrome @safari
```

---

### Behavior

- syntax/semantic invalid  
- entire command skipped  
- warning logged  

---

## 4.7 Bundle Exclusivity (Invalid)

A bundle (`@bundle` defined in `BUNDLES`) cannot be combined with any
other argument in the same command. This prevents the routing-vs-
expansion ambiguity.

❌ Invalid:

```text
open zoom.us @work
focus "Slack" @work
```

✔ Valid:

```text
open @work               # bundle expansion
focus @work              # bundle expansion
open zoom.us @chrome     # url + target routing (target, not bundle)
```

---

### Behavior

- semantic invalid  
- entire command skipped  
- warning logged: `[WARN] @work is a bundle and cannot share a command with other arguments`  

---

# 5. Semantic Validation

---

## 5.1 App Not Found

```text
open @unknown
```

→ skip + warn  

---

## 5.2 Window Not Found

```text
focus @chrome title("Inbox")
```

→ skip + continue  

---

## 5.3 Click Target Not Found

```text
click text("Export")
```

→ skip + continue  

---

## 5.4 Selector Not Found

```text
click selector(".missing")
```

→ skip + continue  

---

## 5.5 Clipboard Empty

```text
save source(clipboard) to("file.png")
```

→ skip + warn  

---

# 6. Runtime Validation

---

## 6.1 App Launch Failure

→ skip + continue  

---

## 6.2 Permission Issues

Examples:

- screenshot blocked  
- automation denied  

→ skip + `[ERROR]`  

---

## 6.3 File Write Failure

```text
save source(clipboard) to("/restricted/path/file.png")
```

→ skip + `[ERROR]`  

---

# 7. Modifier Conflict Resolution

---

## 7.1 Sequential Modifiers

```text
#left(30) #right(70)
```

→ evaluated left → right  
→ last wins  

---

## 7.2 Unit Fallback

```text
#left(55)
```

→ normalized to `#left(55%)`  

---

## 7.3 Display Override

```text
#display(1) #display(2)
```

→ last wins  

---

## 7.4 Mixed Layout Systems

```text
#left(50) #area(0,0,1920,1080)
```

→ last wins  

---

## 7.5 Global Modifiers (Smart Mode Only)

Same category:

```text
#display(1)
#display(2)
```

→ last wins  

Different categories:

```text
@chrome
#profile(1)
#display(2)
```

→ merged  

---

# 8. Execution Rules

---

## 8.1 Sequential Execution

- commands execute top-to-bottom  
- execution order MUST be preserved  

---

## 8.2 Failure Handling

- failure MUST NOT stop execution  
- next command MUST execute  

---

## 8.3 Context Dependency

```text
click text("Submit")
```

Requires:

- active window  
- valid UI context  

If missing → skip  

---

## 8.4 Repeat Limits

```text
repeat(200)
```

---

### Behavior

- capped to system max (recommended: 100)  
- MUST NOT error  
- execution continues  

---

## 8.5 Timing Defaults

If not specified:

- `speed()` = 0.0s  
- `interval()` = 0.0s  

---

### Constraints

- max = 60s  
- unitless values → seconds  

---

## 8.6 Wait Limits

```text
wait 120m
```

---

### Behavior

- capped to max (recommended: 60m)  
- blocking  

---

# 9. Smart Mode Validation

---

## 9.1 URL Requirement

- MUST contain at least one valid URL  
- otherwise → document ignored  

---

## 9.2 Invalid Lines

```text
hello world
```

→ ignored  

---

## 9.3 Global Modifiers

```text
#display(2)
zoom.us
```

→ applied to subsequent lines  

---

# 10. Plus Mode Validation

---

## 10.1 Mode Trigger

```text
+CalFlow+
```

→ entire document is Plus Mode  

---

## 10.2 Invalid Lines

```text
random text
```

→ ignored  

---

## 10.3 Missing Command

```text
@chrome
```

→ ignored  

---

## 10.4 Modifier Compatibility

```text
open zoom.us @chrome #left(50)
```

---

### Behavior

- modifiers applied per-line  
- no global state  
- unit fallback applies  

---

# 11. Normalization Rules

---

## 11.1 URL Normalization

```text
google.com → https://google.com
```

---

## 11.2 Whitespace Handling

Allowed inside:

- `()`  
- `{}`  
- `[]`  

Ignored during parsing.

---

## 11.3 Case Sensitivity

| Element | Behavior |
|--------|----------|
| commands | case-insensitive |
| targets | case-insensitive |
| strings | case-sensitive |

---

# 12. Logging

---

## 12.1 Log Types

```text
[INFO]
[WARN]
[ERROR]
```

---

## 12.2 Examples

```text
[WARN] click failed: text("Export")
[INFO] skipped line: invalid syntax
[ERROR] permission denied: screenshot
```

---

## 12.3 Required Logging Events

- mode detection  
- skipped lines  
- command failures  
- alias expansion  
- dynamic expression failures  
- clipboard errors  

---

## 12.4 Constraints

Logging MUST be:

- deterministic  
- non-blocking  
- consistent  
- privacy-aware  

---

# 💡 Summary

- CalFlow is forgiving by default  
- failures are isolated  
- execution continues whenever possible  
- predictability is prioritized over strictness  

---

# 🚀 Design Principle

**"Fail small, continue fast."**