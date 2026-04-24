# Signal Quality Analysis & Fix Proposal
**Date:** 2026-04-14  
**Trigger:** Excessive negative PnL observed on live signals  
**Status:** ANALYSIS COMPLETE — awaiting operator approval to implement fixes

---

## Executive Summary

After full audit of `signal_cache.json`, `self_learning_data.json`, `main.py`, `trading_utilities.py`, and live logs, **6 distinct root causes** were identified. The single biggest driver of losses is a **SL=entry price bug** affecting 39% of signals — those trades are stopped out on the first tick against them. Compounding this are a broken ML confidence layer, universally terrible R:R ratios, extreme direction bias, and micro-cap pair selection.

---

## Root Cause Analysis

### 🔴 Bug #1 — SL = Entry Price (39% of signals)
**Severity: CRITICAL**

```
LEVERUSDT     SL_dist=0.00%   R:R=0.0   ← SL triggers immediately
TROYUSDT      SL_dist=0.00%   R:R=0.0
LINAUSDT      SL_dist=0.00%   R:R=0.0
AMBUSDT       SL_dist=0.00%   R:R=0.0
REEFUSDT      SL_dist=0.00%   R:R=0.0
KEYUSDT       SL_dist=0.00%   R:R=0.0
NEIROETHUSDT  SL_dist=0.00%   R:R=0.0
```

**Root cause:** `institutional_risk_adjust()` computes `capped_risk = min(raw_risk, atr_cap, hard_cap)` then calls `round(stop_loss, precision)`. On micro-cap tokens (price ~0.0001125), `precision` is high (7+ decimals) and `min_risk = 0.5 * ATR` rounds to the same integer as entry. The result: SL equals entry price exactly. Cornix (and the dashboard) display this SL, and any price move immediately hits stop.

**Fix:** Enforce a minimum SL distance of 0.3% from entry AFTER rounding.

```python
# In institutional_risk_adjust(), after rounding:
min_sl_dist = entry * 0.003  # 0.3% floor
if abs(stop_loss - entry) < min_sl_dist:
    stop_loss = entry - sign * min_sl_dist
    stop_loss = round(stop_loss, precision)
```

---

### 🔴 Bug #2 — R:R < 1.0 on 16/18 Signals (89%)
**Severity: CRITICAL**

```
COSUSDT        SL=27.25%  TP1=4.50%   R:R=0.17   ← lose 27% to gain 4.5%
1000SATSUSDT   SL=18.08%  TP1=4.50%   R:R=0.25
PIXELUSDT      SL=34.62%  TP1=4.50%   R:R=0.13
BANANAS31USDT  SL=23.51%  TP1=4.50%   R:R=0.19
```

Only 2/18 signals pass R:R > 1.0 (EPTUSDT=2.8, COMMONUSDT=1.6).

**Root cause (two parts):**

1. **`institutional_risk_adjust()` R:R check uses TP3, not TP1.** The function returns `rr = reward(TP3) / risk`. So a signal passes the `rr < 1.0` rejection gate even when TP1 is 0.17:1. In practice, Cornix closes partial at TP1 — which is a guaranteed loss.

2. **TP targets are all exactly 4.50%** — the ATR-based fallback path (`1.0 × ATR × tp_scale_mult`) is being hit for most pairs. The VP/FVG liquidity targets are not replacing them, likely because the VP is computed on 1h data with insufficient candles for micro-caps.

**Fix:** Reject if TP1 R:R < 0.8. Use ATR×1.5 minimum for TP1 and enforce it:

```python
# In institutional_risk_adjust(), add after building adj_targets:
tp1_reward = abs(adj_targets[0] - entry)
tp1_rr = tp1_reward / capped_risk if capped_risk > 0 else 0
if tp1_rr < 0.8:
    return None  # TP1 doesn't justify the risk
```

---

### 🔴 Bug #3 — CE Stop Too Wide → Reject, Not Cap
**Severity: HIGH**

From live logs, 38/38 processed pairs had SL Capped events:

```
ONUSDT:       CE=43.2% → capped to 6.0%
MYXUSDT:      CE=56.4% → capped to 6.0%
BROCCOLI714:  CE=25.4% → capped to 6.0%
WETUSDT:      CE=41.8% → capped to 6.0%
```

A CE stop at 43% means price can move 43% without the signal being technically invalidated. By capping to 6%, we're placing an artificial stop that gets hit constantly by normal volatility — the signal was valid, but our artificially tight SL causes a loss.

**Fix:** Hard-reject if `raw_risk_pct > 15%`. These signals are not tradeable:

```python
# In institutional_risk_adjust(), after computing raw_risk_pct:
if raw_risk_pct > 0.15:  # CE SL wider than 15% from entry
    return None  # Signal untradeable — too volatile for any safe SL
```

---

### 🟡 Issue #4 — ML Confidence is Non-Functional
**Severity: HIGH**

The ML layer produces only **3 unique confidence values** across all signals:
- `0.56` — SELL signals (10 instances)
- `0.28` — Short signals (7 instances)  
- `0.34` — 1 instance

The `self_learning_data.json` confirms: **all 1,740 recorded outcomes have `accuracy=0` and `prediction_confidence=0.5`**. The ML is outputting a constant — it is not predicting anything.

**Root cause:** The `performance_summary.json` shows accuracy=0.909 on 1h timeframe during training, but the production `predict_signal()` is likely returning a default/fallback value. The ML ensemble models may not be loaded in memory, causing the fallback `confidence=0.5` to propagate, which then gets split into the two buckets via the `assign_leverage()` mapping.

**Fix (immediate):** Raise minimum confidence gate to 0.60 until ML is verified working. All current sub-0.60 confidence signals (100% of the cache) would be suppressed.

```python
# In DynamicConfidenceThreshold.tiers:
self.tiers = [
    (0.67, 0.60),   # Was 0.45 — raise floor significantly
    (0.89, 0.70),   # Was 0.60
    (1.00, 0.80),   # Was 0.75
]
```

---

### 🟡 Issue #5 — 100% SHORT Direction Bias
**Severity: HIGH**

All 18 cached signals are SHORT/SELL. Live cycle logs show:
```
CE: 463L / 142S  (76% of pairs have CE pointing LONG)
TSI zones: 92 pairs in extreme zones (OB2/OB1/OS1/OS2)
```

The bot is generating only SHORT signals while the CE indicator on **76% of pairs is pointing LONG**. This is a mismatch. The market is in Extreme Fear (F&G=21) — historically a mean-reversion zone. Sending 100% SHORT signals into this context has a poor base rate.

**Root cause:** The TSI-based signal requires TSI to exit an **oversold** zone for a LONG, but TSI is currently in oversold zones (34 OS1 + 40 OS2 = 74 oversold pairs), meaning a LONG trigger requires *exiting* oversold — which hasn't happened yet. Meanwhile, SHORT triggers (exiting overbought: 6 OB2 + 12 OB1 = 18 pairs) are firing on the few overbought pairs.

This is correct behavior technically — but the 100% SHORT bias is a red flag in an extreme fear environment where bounces are likely.

**Fix:** Add a macro regime gate: if F&G < 25 (Extreme Fear), suppress SHORT signals unless BTC HTF is also in confirmed downtrend. Or reduce leverage on all SHORT signals to maximum 3x when F&G < 25.

---

### 🟡 Issue #6 — Micro-Cap Pair Selection
**Severity: MEDIUM**

Pairs currently generating signals: LEVERUSDT, TROYUSDT, COSUSDT, 1000SATSUSDT, LINAUSDT, XANUSDT, AMBUSDT, PUMPUSDT, PIXELUSDT, REEFUSDT, KEYUSDT, NEIROETHUSDT, BANANAS31USDT, HMSTRUSDT.

These are low-liquidity micro-caps where:
- Spreads are wide relative to ATR targets
- Whale manipulation invalidates TA
- CE on these pairs fires on noise, not trend changes
- ATR-based targets are proportionally smaller than spreads

**Fix:** Require minimum 24h volume of $5M USDT before a pair is eligible for signals.

---

## Impact Summary

| Bug/Issue | Signals Affected | Impact |
|---|---|---|
| SL = entry price | 39% (7/18) | Immediate stop-out on open |
| R:R < 1 at TP1 | 89% (16/18) | Guaranteed loss if TP1 hit |
| CE SL > 15% → fake cap | ~80% of processed pairs | Artificial SL hit constantly |
| ML confidence broken | 100% | No ML quality gate working |
| 100% SHORT in extreme fear | 100% | Poor directional base rate |
| Micro-cap pairs | ~70% of signals | TA noise > signal |

---

## Proposed Fixes (Priority Order)

### Fix 1 — `trading_utilities.py` → `institutional_risk_adjust()`
```python
# After Layer 5 (existing code), add:

# ── Layer 6: Minimum SL distance guard ───────────────────────
min_sl_pct = 0.003  # 0.3% minimum
if abs(stop_loss - entry) / entry < min_sl_pct:
    stop_loss = entry - sign * entry * min_sl_pct
    stop_loss = round(stop_loss, precision)

# ── Layer 7: TP1 R:R gate ─────────────────────────────────────
tp1_reward = abs(adj_targets[0] - entry) if adj_targets else 0
tp1_rr = tp1_reward / capped_risk if capped_risk > 0 else 0
if tp1_rr < 0.8:
    return None  # TP1 doesn't justify risk — reject

# ── Layer 8: Reject if CE SL > 15% (untradeable) ─────────────
if raw_risk_pct > 0.15:
    return None  # CE stop too wide — signal untradeable
```

### Fix 2 — `trading_utilities.py` → `DynamicConfidenceThreshold`
```python
self.tiers = [
    (0.67, 0.60),   # First 60 signals: min 60% confidence
    (0.89, 0.70),   # Signals 61-80: min 70% confidence
    (1.00, 0.80),   # Signals 81-90: min 80% confidence
]
```

### Fix 3 — `main.py` → extreme fear SHORT gate
After the macro risk check, add:
```python
fear_greed = MACRO_RISK_ENGINE.state.get('fear_greed', 50)
if fear_greed < 25 and final_signal == 'SHORT':
    btc_htf = get_btc_htf_regime(client)
    if btc_htf != 'BEARISH':
        log_message(f"🚫 Signal Rejected for {pair}: SHORT suppressed in Extreme Fear (F&G={fear_greed}) without BTC HTF confirmation")
        return
```

### Fix 4 — `data_fetcher.py` → minimum volume filter
In `fetch_trading_pairs()`, add minimum 24h volume filter:
```python
MIN_VOLUME_USDT = 5_000_000  # $5M minimum 24h volume
pairs = [p for p in pairs if float(p.get('quoteVolume', 0)) >= MIN_VOLUME_USDT]
```

---

## Expected Outcome After Fixes

| Metric | Current | After Fixes |
|---|---|---|
| Signals per day | ~20-40 | ~5-15 (quality over quantity) |
| Signals with valid SL | ~61% | ~100% |
| Signals with TP1 R:R > 0.8 | ~11% | ~80%+ |
| CE SL > 15% passing through | ~80% | 0% |
| SHORT signals in extreme fear | 100% | Gated by BTC HTF |
| Micro-cap signals | ~70% | <20% |

Fewer signals, but each signal will have a mathematically defensible SL and R:R. This is the correct trade-off for a paid service.

---

## Decision Required

Approve all 4 fixes, or specify which to proceed with.
