---
name: tier-gate
description: |
  Per-verb / per-modifier tier gating for a future Free / Pro / Pro+ split.
  Status: design-locked, not implemented. Apply if and when the user
  decides to ship paid tiers.
---

# Tier gate

## Status

**Design only.** No code today gates by tier. CalFlow is currently free /
not-yet-released. This skill describes the agreed-on tier table so any
future implementation matches the design.

## Tier table

| Tier | Goal | Verbs | Modifiers |
|---|---|---|---|
| **Free (Lite)** | Demo + habit formation | OPEN, FOCUS @app, CLOSE @app, HIDE @app, HIDE all, WAIT, COPY, PASTE, SAVE, basic SCREENSHOT | `#left`, `#right`, `#full` (primary display only); `#fill`; `{now}` (basic); `#profile(N)` |
| **Pro** (one-time IAP, ~$25) | Multi-display + report automation | + per-window HIDE display(N), FOCUS @app display(N), FOCUS @app title("…"), HIDE except(active), advanced SCREENSHOT, SAVE source(clipboard) to(...) | + `#display(N)`, `#display("name")`, `#area`, `#grid`, full dynamic-expression pipelines |
| **Pro+** (subscription, ~$4/mo) | RPA + GUI + cross-machine | + CLICK, TYPE, PRESS, RUN, missed-events recovery, menubar app, cloud-sync of TARGETS/BUNDLES | (all) |

## Implementation hook (when ready)

Validator-layer gate, similar to the v1.1.2 reserved-keyword check:

```python
# config/settings.py
LICENSE_TIER = "lite"   # 'lite' | 'pro' | 'pro_plus'

VERB_TIERS = {
    "OPEN": "lite", "FOCUS": "lite", "CLOSE": "lite", "WAIT": "lite",
    "COPY": "lite", "PASTE": "lite", "SAVE": "lite",
    "HIDE": "lite",          # bare hide / hide @app are free; display(N) is pro
    "SCREENSHOT": "lite",    # bare screenshot is free; to() etc. are pro
    "CLICK": "pro_plus", "TYPE": "pro_plus", "PRESS": "pro_plus",
    "RUN": "pro_plus",
}

MODIFIER_TIERS = {
    "display": "pro",   # any display(N) usage
    "title": "pro",
    "area": "pro", "grid": "pro",
    "to": "pro",
    "except": "pro",
}
```

Validator reads these and rejects out-of-tier syntax with a clean
"Upgrade to Pro to use…" message.

## Design rationale

1. Free tier is genuinely useful (single-monitor calendar-as-launcher).
2. Pro tier targets the 5–10% of users who'll actually pay (multi-monitor,
   report automation).
3. Pro+ is recurring because the value is recurring (RPA workflow lock-in
   compounds).
4. Don't cripple the CLI — paid features unlock real capability, not
   artificial limits.

## Out of scope for this skill

- Stripe / IAP integration
- License key validation
- Trial-period implementation

Those are infrastructure concerns; this skill is purely the verb-by-verb
gating decision.
