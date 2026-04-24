# Upgrade 01 — LONG-Bias Fix (Symmetric Adaptive TSI + Greed Gate)

**Date:** 2026-04-19
**Phase:** 1 of 7 (master proposal: `/proposals/2026-04-19_ml-accuracy-and-long-bias-fix.md`)
**Status:** ✅ Implemented (awaiting main.py restart to take effect)
**Risk Level:** Low (logic-only change, no retrain required)

---

## Problem Statement

The bot was firing signals at a **9:1 LONG:SHORT ratio** — drastically more
skewed than the underlying market bias of ~3:1. Data from `main.log`
(Apr 14 – 18):

| Stage | LONG | SHORT | Ratio |
|---|---:|---:|---:|
| TSI zones (market) | 81 OS | 25 OB | 3.2 : 1 |
| CE direction | 575 | 152 | 3.8 : 1 |
| PERSISTENT zone triggers | 115 | 11 | **10.5 : 1** |
| REVERSE HUNT detections | 122 | 14 | **8.7 : 1** |
| Registered signals | 14 | 0 | ∞ |

The bot was **amplifying** natural market bias 3×, and filtering out the
surviving SHORT detections entirely.

---

## Root Causes

### Cause A: Asymmetric adaptive TSI thresholds

`reverse_hunt.calculate_adaptive_tsi_thresholds()` computed thresholds from
the 92nd percentile of `|TSI|` (absolute value). When the TSI distribution
is skewed — as it is in bull-leaning regimes (TSI is inverted, so bull pumps
produce a long NEGATIVE tail) — the magnitude percentile reflects the bigger
tail:

- Pair's TSI range: [-3.0, +1.5]
- Old symmetric threshold: `L2 = percentile(|tsi|, 92) ≈ 2.7`
- OS trigger (`tsi < -2.7`): reachable (negative tail hits -3.0 regularly)
- OB trigger (`tsi > +2.7`): **unreachable** (positive tail only hits +1.5)

This is the dominant driver of the 10.5:1 PERSISTENT zone skew vs 3.2:1
market-level bias.

### Cause B: Asymmetric macro gates

- **SHORT gates**: TWO (`main.py:367-382` Extreme Fear + BTC-bearish,
  plus USDT.D `FEAR_MAX_PAIN` veto)
- **LONG gates**: ONE (USDT.D `GREED_MAX_PAIN` veto only)

SHORT signals had to pass through two filters; LONG signals through one.
Asymmetric by omission.

---

## Changes Made

### Change 1 — `reverse_hunt.py`

**Added** `calculate_adaptive_tsi_thresholds_split()` (`reverse_hunt.py:474-544`)
— computes OB and OS thresholds from **separate tails** of the TSI
distribution, with a cross-side symmetry clamp (max 30% ratio) preventing
either side from drifting unreachable.

```python
def calculate_adaptive_tsi_thresholds_split(tsi_vals) -> (l1_ob, l2_ob, l1_os, l2_os):
    pos_tsi = tsi_clean[tsi_clean > 0]
    neg_tsi = -tsi_clean[tsi_clean < 0]
    # ... percentile per side ...
    # Cross-side clamp: MAX_RATIO = 1.30
    # Returns (l1_ob, l2_ob, l1_os, l2_os) — OS values are NEGATIVE
```

**Modified** `_simulate_state_machine()` (`reverse_hunt.py:260-288`) — now
accepts `adapt_l1_os` and `adapt_l2_os` kwargs. Legacy calls still work
(falls back to symmetric negation).

**Modified** the main runner (`reverse_hunt.py:706-732`) — now calls the
split version and passes all 4 thresholds through to the state machine and
the PERSISTENT extreme fallback.

**Kept** the legacy `calculate_adaptive_tsi_thresholds()` function unchanged
— dashboard and other callers still use it (backward-compat).

### Change 2 — `main.py`

**Added** an Extreme Greed LONG Gate (`main.py:384-400`) mirroring the
existing Extreme Fear SHORT Gate:

```python
if final_signal.upper() == 'LONG':
    fear_greed = MACRO_RISK_ENGINE.state.get('fear_greed', 50)
    if fear_greed > 75:
        btc_htf = get_btc_htf_regime(client)
        if btc_htf != 'bullish':
            log_message("🚫 Signal Rejected: LONG suppressed — Extreme Greed ...")
            return
```

Now LONG signals must also pass a macro-risk filter when F&G > 75 without
independent BTC HTF confirmation.

---

## Validation

### Unit test — synthetic bull-biased TSI

```
Simulated TSI: [-0.5±1.2 (400 bars), +0.3±0.6 (100 bars)]

OLD symmetric:  L1=1.470  L2=2.000   ← same for both OB and OS
NEW split OB:   L1=1.231  L2=1.736   ← SHORT trigger now reachable
NEW split OS:   L1=-1.500 L2=-2.000  ← LONG trigger unchanged
```

The fix successfully lowers the OB trigger threshold in bull-biased
distributions, restoring SHORT-trigger reachability.

### Syntax check

```
$ /root/miniconda3/bin/python3 -c "import ast; ast.parse(open('reverse_hunt.py').read()); ast.parse(open('main.py').read())"
OK: both files parse cleanly
```

### Production activation

The main bot (`main.py` PID 473530) was started April 18 and has not yet
loaded these changes. **Operator must restart `main.py`** to activate.
Dashboard (`app.py`) and MCP server do not need restart — they use the
unchanged symmetric function.

---

## Expected Impact

After restart:

| Metric | Before | Expected After |
|---|---|---|
| Fire ratio LONG:SHORT | 9 : 1 | ~2–3 : 1 |
| SHORT detections surviving gates | ~0% | ~40% |
| Total signal volume | baseline | -15% to -25% (filtering Extreme Greed LONGs) |
| Signal precision | baseline | likely +3-5% (better balanced) |

Monitor for 48 hours post-restart. If SHORT count overshoots (>1:1 ratio
in a bull regime), the cross-side symmetry clamp can be tightened from 1.30
to 1.20 in `calculate_adaptive_tsi_thresholds_split`.

---

## Rollback Procedure

### Option 1: Git revert
```bash
cd /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA
git diff reverse_hunt.py main.py  # review
git checkout HEAD -- reverse_hunt.py main.py  # rollback
```

### Option 2: Manual disable (keeps the new function but unused)
In `reverse_hunt.py:717`, replace:
```python
adapt_l1, adapt_l2, adapt_l1_os, adapt_l2_os = calculate_adaptive_tsi_thresholds_split(tsi_vals)
```
with:
```python
adapt_l1, adapt_l2 = calculate_adaptive_tsi_thresholds(tsi_vals)
adapt_l1_os, adapt_l2_os = -adapt_l1, -adapt_l2  # legacy symmetric
```

And comment out the Extreme Greed LONG Gate block in `main.py:384-400`.

Restart main.py.

---

## Files Touched

| File | Lines | Change |
|---|---|---|
| `reverse_hunt.py` | 260-288 | State machine now accepts split OS thresholds |
| `reverse_hunt.py` | 474-544 | New `calculate_adaptive_tsi_thresholds_split()` |
| `reverse_hunt.py` | 706-732 | Runner uses split thresholds |
| `reverse_hunt.py` | 743 | PERSISTENT fallback uses split OS threshold |
| `main.py` | 384-400 | Extreme Greed LONG Gate |

---

## References

- Master proposal: `/proposals/2026-04-19_ml-accuracy-and-long-bias-fix.md`
- Prior analysis: this session's diagnostic grep output from `main.log`
- Related upgrade (inspiration): Extreme Fear SHORT gate at `main.py:367-382`
