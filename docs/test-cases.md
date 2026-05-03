# 📘 CalFlow Test Cases (v2.0)

This document defines test cases for validating CalFlow behavior.

This file serves as:

- a QA reference  
- a parser validation checklist  
- a regression testing baseline  

---

## Coverage

This test suite explicitly covers:

- Smart Mode parsing and execution  
- Plus Mode command execution  
- Syntax validation  
- Target resolution  
- Dynamic expression handling  
- Modifier precedence and conflict resolution  
- Error handling and failure isolation  
- Edge cases and tolerance behavior  
- Real-world workflow scenarios  

---

# 1. Unit Tests

---

## 1.1 Smart Mode

---

### 1.1.1 Basic URL

**Input:**
```text
zoom.us
```

**Expected:**

- interpreted as implicit command: `open zoom.us`  
- normalized to: `https://zoom.us`  
- opened in default browser  
- no modifiers applied  

---

### 1.1.2 URL with target

**Input:**
```text
zoom.us @chrome
```

**Expected:**

- `@chrome` resolved via alias mapping  
- resolved application = `Google Chrome`  
- URL opened in Chrome  
- no layout or display modifiers applied  

---

### 1.1.3 URL with layout (unit fallback)

**Input:**
```text
zoom.us @chrome #left(30)
```

**Expected:**

- `#left(30)` normalized to `#left(30%)`  
- layout applied AFTER window creation  
- window positioned on left  
- occupies 30% of available display width  

---

### 1.1.4 Multiple URLs

**Input:**
```text
zoom.us @chrome #left(50%)
notion.so @chrome #right(50%)
```

**Expected:**

- both URLs opened  
- both resolved to Chrome  
- layout applied independently per line  
- windows split horizontally  
- deterministic left/right placement  

---

### 1.1.5 Global modifiers

**Input:**
```text
#display(2)
@chrome

zoom.us
notion.so
```

**Expected:**

- global state applied to both lines  
- both open in Chrome  
- both open on display 2  
- no layout applied  

---

### 1.1.6 Global modifier conflict

**Input:**
```text
#display(1)
#display(2)

zoom.us
```

**Expected:**

- same-category conflict resolved → last wins  
- final display = 2  
- zoom opens on display 2  

---

### 1.1.6a `#display` symbolic forms

**Input:**
```text
zoom.us @chrome #display
```

**Expected:**

- Chrome opens zoom.us on **first external monitor**  
- if no external connected → opens on primary; logs `[WARN] #display: no external monitor connected; using primary`  

---

### 1.1.6b `#display("name")` substring match

**Input:**
```text
zoom.us @chrome #display("Samsung")
```

**Expected:**

- if any connected display's `localizedName` contains "samsung" (case-insensitive) → opens there  
- if no match → layout is **skipped** (no fallback); logs `[WARN]`  

---

### 1.1.6c `#display(N)` out of range

**Input:**
```text
zoom.us @chrome #display(9)
```

**Expected:**

- only 2 displays connected → layout **skipped entirely** (no fallback)  
- Chrome opens zoom.us at default position  
- logs `[WARN] #display(9): only 2 display(s) connected; layout skipped`  

---

### 1.1.7 Invalid line ignored

**Input:**
```text
hello world
zoom.us
```

**Expected:**

- first line ignored (invalid URL)  
- second line executed normally  
- no error blocks execution  

---

---

## 1.2 Plus Mode

---

### 1.2.1 Basic command

**Input:**
```text
+CalFlow+

open zoom.us
```

**Expected:**

- Plus Mode activated  
- `zoom.us` normalized to HTTPS  
- opened in default browser  

---

### 1.2.2 Multiple commands

**Input:**
```text
+CalFlow+

open zoom.us
open notion.so
```

**Expected:**

- executed sequentially (top → bottom)  
- both URLs opened  
- no reordering  

---

### 1.2.3 Focus command

**Input:**
```text
+CalFlow+

open zoom.us @chrome
focus @chrome
```

**Expected:**

- Chrome launched  
- Zoom opened in Chrome  
- Chrome brought to foreground  

---

### 1.2.4 Click command (function-style)

**Input:**
```text
+CalFlow+

click text("Sign in")
```

**Expected:**

- locate element by visible text  
- if found → click  
- if not found → skipped  
- execution continues  

---

### 1.2.5 Click with selector

**Input:**
```text
+CalFlow+

click selector(".submit-button")
```

**Expected:**

- selector evaluated  
- first matching element clicked  
- if none → skipped  

---

### 1.2.6 Click with AND condition

**Input:**
```text
+CalFlow+

click text("Submit") selector(".btn")
```

**Expected:**

- BOTH conditions must match  
- AND semantics enforced  
- if mismatch → skip  

---

### 1.2.7 Click with timing controls

**Input:**
```text
+CalFlow+

click text("Submit") repeat(2) interval(1s) timeout(3s)
```

**Expected:**

- max 2 attempts  
- 1s delay between attempts  
- each attempt capped at 3s  
- success stops retry loop  

---

### 1.2.8 Type command (basic)

**Input:**
```text
+CalFlow+

type("hello")
```

**Expected:**

- text entered into active element  
- no delay between characters  

---

### 1.2.9 Type with speed

**Input:**
```text
+CalFlow+

type("abc") speed(0.1s)
```

**Expected:**

- per-character delay = 0.1s  
- execution order preserved  

---

### 1.2.10 Type with repeat + interval

**Input:**
```text
+CalFlow+

type("abc") repeat(3) interval(0.5s)
```

**Expected:**

- full string repeated  
- 0.5s delay between repeats  

---

### 1.2.11 Press command (single)

**Input:**
```text
+CalFlow+

press {enter}
```

**Expected:**

- Enter key event triggered  

---

### 1.2.12 Combined keys

**Input:**
```text
+CalFlow+

press {cmd+shift+tab}
```

**Expected:**

- modifier keys applied correctly  
- sequence executed atomically  

---

### 1.2.13 Press sequence

**Input:**
```text
+CalFlow+

press [{left},{left},{up}]
```

**Expected:**

- executed sequentially  
- left → left → up  

---

### 1.2.14 Press with repetition

**Input:**
```text
+CalFlow+

press [{left}x5]
```

**Expected:**

- left key repeated 5 times  

---

### 1.2.15 Press with modifier scope

**Input:**
```text
+CalFlow+

press [{shift_down}, ({left})x5, {shift_up}]
```

**Expected:**

- shift held only within block  
- selects text leftwards  
- modifier state does NOT persist  

---

### 1.2.16 Wait command

**Input:**
```text
+CalFlow+

wait 5
```

**Expected:**

- normalized to `5s`  
- execution pauses  
- blocking behavior  

---

### 1.2.17 Screenshot + save

**Input:**
```text
+CalFlow+

screenshot
save source(clipboard) to("~/Desktop/test.png")
```

**Expected:**

- screenshot → clipboard  
- saved to file  
- path expanded correctly  

---

### 1.2.18 Modifier support in Plus Mode

**Input:**
```text
+CalFlow+

open zoom.us @chrome #left(50)
```

**Expected:**

- layout applied  
- `#left(50)` → `#left(50%)`  
- applies ONLY to this command  

---

### 1.2.19 Standalone modifier ignored

**Input:**
```text
+CalFlow+

#display(2)
open zoom.us
```

**Expected:**

- standalone modifier ignored  
- no global state created  

---

### 1.2.20 Implicit open (Plus Mode)

**Input:**
```text
+CalFlow+

zoom.us
```

**Expected:**

- interpreted as `open zoom.us`  
- consistent with Smart Mode behavior  

---

---

## 1.3 Target Resolution

---

### 1.3.1 Alias target

```text
open @chrome
```

→ resolves via settings  
→ opens Chrome  

---

### 1.3.2 Direct app name

```text
open "Google Chrome"
```

→ opens application  

---

### 1.3.3 URI

```text
open spotify://track/123
```

→ passed to OS handler  

---

### 1.3.4 File path

```text
open "~/Downloads/file.pdf"
```

→ opened with default app  

---

### 1.3.5 Quoted fallback

```text
open "zoom.us"
```

→ fallback to URL  

---

### 1.3.6 Invalid target

```text
open zoom
```

→ skipped  

---

### 1.3.7 Multiple targets

```text
open zoom.us @chrome @work
```

→ invalid  
→ skipped  
→ warning logged  

---

### 1.3.8 Alias expansion

```text
open @work
```

→ expands into multiple commands  

---

---

## 1.4 Dynamic Expressions

---

### Expected Behavior

- evaluated BEFORE execution  
- order: offset → conversion → format  

---

### Invalid Case

```text
{now-1x}
```

→ skipped or fallback  
→ must NOT crash execution  

---

---

## 1.5 Modifier Handling

---

### Rules

- same category → last wins  
- different categories → merged  

---

### Layout Constraints

- applied ONLY to window-producing commands  
- ignored otherwise  

---

---

## 1.6 Error Handling

---

### Core Rule

Errors must NOT stop execution.

---

### Examples

| Case | Behavior |
|------|----------|
| syntax error | skip |
| invalid command | skip |
| missing target | skip |
| runtime failure | log + continue |

---

---

## 1.7 Edge Cases

---

### Includes

- repeat caps  
- whitespace tolerance  
- case insensitivity  
- mixed valid + invalid input  

---

---

## 1.8 Mode Detection

---

### Rules

- `+CalFlow+` → Plus Mode  
- otherwise → Smart Mode  

---

---

## 1.9 Logging

---

### Expected Logs

```text
[WARN] click failed: text("Missing")
[INFO] skipped line: invalid syntax
```

---

---

# 2. Scenarios (Workflow Tests)

---

## 2.1 Meeting Setup

Validates:

- layout correctness  
- deterministic placement  

---

## 2.2 Workspace Launch

Validates:

- alias expansion  
- multi-display  

---

## 2.3 Export Flow

Validates:

- sequential execution  
- UI automation  
- clipboard pipeline  

---

## 2.4 Global Override

Validates:

- Smart Mode inheritance  

---

## 2.5 Failure Isolation

Validates:

- failure does NOT block execution  

---

## 2.6 Dynamic Reporting

Validates:

- expressions resolved at runtime  

---

# 🚀 Summary

This test suite ensures:

- correctness  
- stability  
- resilience  
- deterministic execution  
- real-world usability  

---

# 💡 Design Principle

**"Test behavior, not just syntax."**