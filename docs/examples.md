# CalFlow Examples

Generated from the "CalFlow Examples" sheet, tab `260707`
(spec-of-record). Regenerate this file when the sheet changes;
do not hand-edit rows here.

Legend: ❌ = must be rejected · PLANNED = approved syntax, not
yet implemented · "stub" = parses/validates/resolves, side
effect lands with the noted release.


## App Control

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| open | URL | `open <url>` | `open zoom.us` | @target, #layout | Smart & Plus |
| open | Alias | `open @alias` | `open @work` | #display(), #profile() | Expands to multiple apps |
| open | App | `open "App Name"` | `+CalFlow+ open "Messages" display(2) full` | #display() | Quoted required; bare `full` supported (v1.5.2) |
| open | File | `open "~/file.pdf"` | `+CalFlow+ open "/Users/mba/Downloads/t1134-21e.pdf"` |  | Opens via OS |
| open | New window | `open <url> new(window)` | `open zoom.us new(window)` | #window, #new-window | Forces new browser window |
| open | New tab | `open <url> new(tab)` | `open zoom.us new(tab)` | #tab, #new-tab | Default; layout/display tags imply window |
| focus | Target | `focus @target` | `+CalFlow+ focus @chrome title("Wealthsimple") display(1)` | title() | Requires window match |
| close | App | `close "App Name"` | `+CalFlow+ close "Spotify"` |  | Closes app |
| hide | App | `hide "App Name"` | `hide "Spotify"` |  | Hides app |
| hide | Active | `hide active` | `hide active` |  | Hides frontmost app |
| hide | List | `hide ["App1","App2"]` | `hide ["Spotify","Slack"]` |  | Explicit list |
| hide | List + Active | `hide [active,"App"]` | `hide [active,"Spotify"]` |  | v1.5.2 — `active` expands to frontmost at run time, deduped |
| hide | Except | `hide except(@alias)` | `hide except(@work)` |  | Inverse selection |
| hide | Except Active | `hide except(active)` | `hide except(active)` |  | Hides all except frontmost |
| hide | Except List | `hide except(["App1","App2"])` | `hide except(["Slack","Zoom"])` |  | Inverse explicit list |
| hide | Display Filter | `hide display(n)` | `hide display(2)` |  | Filter by monitor (per-window miniaturize) |
| hide | Combined | `hide except(@alias) display(n)` | `hide except(@work) display(1)` |  | Order independent (normalized internally) |
| hide | Active + Display | `hide active display(n)` | `hide active display(2)` |  | v1.5.2 — frontmost's windows on display N only (per-window) |
| hide | All + Display | `hide all display(n)` | `hide all display(2)` |  | v1.5.2 — normalized to hide display(n) |
| hide | INVALID Bare | `hide` | `hide` |  | ❌ Rejected (no implicit behavior) |

## Timing

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| wait | Time | `wait Ns` | `wait 5s` |  | Supports s,m |
| wait | Minutes | `wait Nm` | `wait 2m` |  | Blocks execution |

## Dynamic

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| now | Current | `{now}` | `open "site.com?date={now}"` |  | Runtime evaluated |
| offset | Offset | `{now-7d}` | `open "site.com?start={now-7d}"` |  | Supports s,m,h,d,w,mo,y |
| format | Format | `{now > YYYY-MM-DD}` | `save to("file_{now > YYYY-MM-DD}.png")` |  | Final stage formatting |
| combo | Combined | `{now-1mo > end_of_month > YYYY-MM-DD}` | `open "report.com?until={now-1mo > end_of_month > YYYY-MM-DD}"` |  | Full pipeline expression |
| INVALID Runtime Target | {active} | `hide {active}` |  |  | ❌ Rejected — {} is for dynamic VALUES only; use bare `active` |

## Layout (Smart)

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| position | Left | `#left` | `open zoom.us #left(50)` |  | Smart & Plus (hash-drop: left(50) — v1.5.3) |
| position | Right | `#right` | `open notion.so #right(50)` |  | Smart & Plus |
| display | Monitor | `#display(n)` | `open zoom.us #display(2)` |  | Global or per line; hash-drop display(2) works (v1.5.3) |
| profile | Browser | `#profile(n)` | `open zoom.us @chrome #profile(1)` |  | Chrome profile |
| grid | Grid legacy | `#grid(3x2@1)` | `open zoom.us #grid(3x2@1)` |  | Legacy order — warns, normalizes to 1@3x2 |
| grid | Grid | `#grid(1@3x2)` | `open zoom.us #grid(1@3x2)` |  | Canonical: cell@colsxrows |
| area | Region | `#area(x,y,w,h)` | `open zoom.us #area(0,0,1920,1080)` |  | Absolute positioning |

## Layout (Plus)

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| sugar | Bare word | `full \| left \| right \| middle \| top \| bottom` | `+CalFlow+ open "Messages" display(2) full` |  | v1.5.2 — parenless drop-sugar for #tag forms |

## Browser

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| new | Tab | `new(tab) \| #tab` | `open zoom.us new(tab)` |  | Default open mode |
| new | Window | `new(window) \| #window` | `open zoom.us new(window)` |  | Layout/display tags imply window automatically |

## Resolution

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| priority | Order | N/A | `open "zoom.us"` |  | Alias > URI > file > app > URL |
| URL | Normalize | N/A | `open zoom.us` |  | → https://zoom.us |
| error | Invalid | N/A | `open zoom` |  | ❌ Rejected — not a URL/app/file/@target |

## Rules

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| syntax | Primary | N/A | `<command> <args> <modifiers>` |  | Order flexible (normalized internally) |
| model | Separation | N/A | `type vs press` |  | type=text, press=keys |
| hash | Drop-sugar | N/A | `display(2) ≡ #display(2)` |  | v1.5.3 — Smart URL lines & Plus verb lines both accept hash-drop |
| reserved-keywords | Protection | N/A | `TARGETS={"active": "..."}` |  | ❌ Rejected at config load (ReservedKeywordError) |

## Screenshot

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| screenshot | Default | `screenshot` | `screenshot` |  | v1.5.2 — copies to clipboard |
| screenshot | Clipboard | `screenshot to(clipboard)` | `screenshot to(clipboard)` |  | Explicit spelling of the default |
| screenshot | File | `screenshot to("path")` | `screenshot to("~/x.png")` |  | Writes PNG file |
| screenshot | Window | `screenshot window("...")` | `screenshot window("Google Chrome")` |  | Parses; capture stub until v2.5 (falls back to full screen) |
| screenshot | Display | `screenshot display(n)` | `screenshot display(2)` |  | Parses; capture stub until v2.5 |
| screenshot | Area | `screenshot area(x,y,w,h)` | `screenshot area(0,0,1920,1080)` |  | Parses; capture stub until v2.5 |

## Clipboard

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| copy | Text | `copy("...")` | `copy("hello")` |  | v1.5.2 — literal → clipboard via pbcopy (real) |
| copy | Default | `copy` | `copy` |  | Copies selection (⌘C synth — stub until v2.3) |
| copy | INVALID Unquoted | `copy(text)` | `copy(hello)` |  | ❌ Rejected — argument must be quoted |
| paste | Paste | `paste` | `paste` |  | Stub until v2.3 |
| save | Clipboard | `save source(clipboard) to("...")` | `save source(clipboard) to("~/file.png")` |  | Stub until v2.3 |

## Modifiers

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| repeat | Command | `repeat(n)` | `click text("Submit") repeat(3)` | interval() | Whole command |
| interval | Between repeats | `interval(t)` | `click text("Submit") repeat(3) interval(1s)` |  | Between executions |
| speed | Execution | `speed(t)` | `type("abc") speed(0.1s)` |  | Per action/key |
| timeout | Action | `timeout(t)` | `click text("Submit") timeout(3s)` |  | Fail limit |
| button | Mouse button | `button(left\|right\|middle)` | `click text("row") button(right)` |  | v1.5.4 — default left |
| count | Click-state | `count(1\|2\|3)` | `click text("file.pdf") count(2)` |  | v1.5.4 — ONE double-click event; ≠ repeat(2) |
| duration | Drag length | `duration(t)` | `drag from(0,0) to(50,50) duration(0.5s)` |  | v1.5.4 — drag only; default 0.3s |

## Keyboard

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| type | Text | `type("...")` | `type("hello")` | speed(), repeat(), interval() | Text only; exec stub until v2.1 |
| type | Repeat | `type("...") repeat(n)` | `type("abc") repeat(3)` | interval() | Repeats string |
| type | Speed | `type("...") speed(t)` | `type("abc") speed(0.1s)` |  | Per character delay |
| type | Combined | `type(...) speed() repeat()` | `type("abc") speed(0.1s) repeat(2) interval(0.5s)` |  | Order-independent |
| press | Key | `press {key}` | `press {enter}` | repeat(), interval() | Single key; exec stub until v2.1 |
| press | Combo | `press {mod+key}` | `press {cmd+c}` | repeat() | Modifier combo |
| press | Navigation | `press {shift+left}` | `press {shift+left} repeat(5)` | interval() | Selection |
| press | Function | `press {f12}` | `press {f15}` |  | Supports F1–F19 |
| press | Special | `press {tab}` | `press {escape}` |  | Alias supported |
| press | List | `press [...]` | `press [{left},{left},{up}]` | speed() | Sequential execution |
| press | List + Repeat | `press [{left}x5]` | `press [{left}x5]` | speed() | Inline repetition |
| press | Grouped Repeat | `press [({left})x5]` | `press [({left})x5]` | speed() | Grouping supported |
| press | Modifier Block | `press [{shift_down},{left}x5,{shift_up}]` | `press [{shift_down},{left}x5,{shift_up}]` | speed() | Scoped modifier |
| press | Repeat Command | `press ... repeat(n)` | `press {left} repeat(5)` | interval() | Repeats full command |

## Mouse

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| click | Text | `click text("...")` | `click text("Submit")` | repeat(), timeout() | Text match; exec stub until v2.1 |
| click | Selector | `click selector("...")` | `click selector(".btn")` | repeat(), timeout() | CSS-like selector |
| click | Position | `click position(x,y)` | `click position(100,200)` | repeat() | Absolute position |
| click | Combined | `click text() selector()` | `click text("Submit") selector(".btn")` | timeout() | AND logic |
| click | Repeat | `click ... repeat(n)` | `click text("Submit") repeat(3)` | interval() | Repeats action |
| click | Timeout | `click ... timeout(t)` | `click text("Submit") timeout(3s)` |  | Fail-safe |
| click | Right | `click ... button(right)` | `click text("row") button(right)` | count(), repeat(), timeout() | v1.5.4 — context-menu click |
| click | Double | `click ... count(2)` | `click text("report.pdf") count(2)` | button(), repeat() | v1.5.4 — one double-click event |
| click | Triple | `click ... count(3)` | `click text("word") count(3)` |  | v1.5.4 — select paragraph/line |
| click | Combined | `click ... button() count()` | `click text("cell") button(right) count(2) repeat(3)` |  | v1.5.4 — three double-right-clicks |
| click | INVALID Button | `click ... button(back)` | `click text("x") button(back)` |  | ❌ Rejected — left\|right\|middle only |
| click | INVALID Count | `click ... count(4)` | `click text("x") count(4)` |  | ❌ Rejected — 1..3; use repeat(n) for repetition |
| drag | Basic | `drag from(x,y) to(x,y)` | `drag from(100,200) to(300,400)` | button(), duration() | v1.5.4 — one gesture; exec stub until v2.1 |
| drag | Right | `drag ... button(right)` | `drag from(0,0) to(50,50) button(right)` |  | v1.5.4 |
| drag | Duration | `drag ... duration(t)` | `drag from(0,0) to(500,500) duration(0.5s)` |  | v1.5.4 — default 0.3s; instant drags trip DnD thresholds |
| drag | PLANNED Elements | `drag from(text("...")) to(text("..."))` | `drag from(text("report.pdf")) to(text("Trash"))` |  | Deferred to v2.1 AX backend |
| drag | INVALID Missing endpoint | `drag from(x,y)` | `drag from(100,200)` |  | ❌ Rejected — both from() and to() required |

## Rules

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| repeat | Inline | N/A | `{left}x5` |  | Inside list only |
| group | Optional | N/A | `({left})x5` |  | Grouping support |

## Script

| Command | Variant | Syntax | Example | Modifiers | Notes |
|---|---|---|---|---|---|
| run | BTT | `run btt("trigger")` | `run btt("BTT-ClaudeCoworkTryAgain")` | if(error/success/output) handlers | Trusted backend; trust-gated |
| run | Shortcut | `run shortcut("name")` | `run shortcut("Start Focus") input("deep work")` | input() | Trusted backend |
| run | Alfred | `run alfred(bundle, trigger)` | `run alfred("com.example.workflow", "try-again") input("prep")` | input() | Trusted backend |
| run | AppleScript | `run applescript` | `run applescript if(error) notify(result)` | +++ block form | Trusted backend |
| run | PLANNED Script | `run script(PATH)` | `run script("~/script.py")` |  | Approved syntax; ships with v2.4 whitelist model |
| run | INVALID Bare path | `run "path"` | `run "~/script.py"` |  | ❌ Rejected — use run script(PATH) when it ships |
