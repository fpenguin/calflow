---
name: fallback-chain-pattern
description: |
  The three-step graceful-degradation pattern for backend operations.
  Apply to any verb that interacts with arbitrary apps.
---

# Fallback chain pattern

When automating arbitrary apps, no single API works for all of them.
Use a three-step chain, ordered from least disruptive to most:

```
try canonical action     # e.g., `set miniaturized = true`
catch:
    try adjacent action  # e.g., `el.close()`
    catch:
        try off-screen   # `el.position = [-32000, -32000]`
        catch:
            log [ERROR] with all three failure reasons
```

Each step preserves user data better than the next. Move-off-screen is the
last resort because the window stays alive but invisible — recoverable but
counterintuitive.

## Established applications

- `runtime/actions/window.py::hide_apps_on_display` — miniaturize → close → off-screen
- `runtime/actions/app_control.py::hide_app` — `set visible to false` only (no chain needed; works for whole apps)

## Tracking outcome

Always emit a per-app summary so the user sees what worked:

```
[INFO] HIDE display(1) [...]: hidden = [cmux (1 off-screen of 1), Preview (1 min of 1)]
```

The `<count> <action>` format is canonical. Don't invent new prefixes.

## Anti-pattern

Single-try with silent failure → no diagnostic emitted → user can't tell
what happened. Every chain MUST log failure reasons of ALL attempts in
the final `errored` entry:

```
errored = [cmux win (mini: <reason>; close: <reason>; move: <reason>)]
```

(v1.1.13–v1.1.15 evolved this pattern through real bug feedback.)
