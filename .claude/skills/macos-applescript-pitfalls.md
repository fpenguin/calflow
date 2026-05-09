---
name: macos-applescript-pitfalls
description: |
  Common osascript / JXA / System Events traps in CalFlow. Read before
  touching `runtime/actions/*` or writing new osascript.
---

# macOS AppleScript / JXA pitfalls

## Reserved property names — NEVER use as local variables

`hidden`, `position`, `size`, `frontmost`, `name`, `bounds`, `visible`,
`minimized`, `closed`. Using any of these as a local variable in System
Events causes `-10003 (Access not allowed)`.

```applescript
# ❌ WRONG — `hidden` is a System Events property
set hidden to {}

# ✅ RIGHT
set hid to {}
```

(v1.1.7 was exactly this bug.)

## Coordinate systems

| API | Origin | Y direction |
|---|---|---|
| `NSScreen.visibleFrame` | bottom-left of primary | up |
| AppleScript `set bounds` | top-left of primary | down |

Conversion:

```javascript
y_top_left = primary_h - cocoa_y - height
```

Canonical implementation in `_JXA_ENUM` (runtime/actions/window.py).

## AXSheet enumeration

`process.windows()` returns top-level NSWindows only. Settings panes,
save dialogs, etc. are AXSheets attached to a parent. Enumerate with
`win.sheets()`.

(v1.1.11 added this.)

## TCC permission buckets

| Operation | Bucket |
|---|---|
| `tell application X to activate` | Apple Events / Automation |
| `set visible of process X to false` | Apple Events / Automation |
| `windows[w].position()` (AX read) | **Accessibility** (separate grant) |
| `keystroke "x"` | **Accessibility** |

User can grant one without the other. Detect AX denial early (the
`AX_DENIED` sentinel pattern in v1.1.8).

## Error code reference

| Code | Meaning |
|---|---|
| -10003 | "Access not allowed" — usually reserved-name collision OR Accessibility missing |
| -1719 | "Invalid object" |
| -25204 | "errAEEventNotPermitted" |
| -1728 | "Can't get application X" — app not running or wrong name |

## Subprocess timeouts

Every osascript subprocess MUST have `timeout=N` (4–10 seconds standard).
osascript can hang indefinitely on apps that won't respond.
