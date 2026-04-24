# Proposal: Stop‑Loss Failure Analysis & Hypothesis Testing

**Date**: 2026-04-07
**Priority**: HIGH
**Related**: `2026-04-07_fix-feature-persistence.md` (prerequisite)

---

## Problem

Recent stop‑loss hits reveal a severe misalignment between signal confidence and actual outcomes. Notably:

- 15 of 20 recent losers were **SHORT** positions
- Many losers had **high confidence (70–89%)** yet stopped out for small losses (-0.67% to -3.57%)
- Leverage on these losers ranged from 5× to 44×, magnifying the effective loss on margin
- The overall directional clustering (24/33 recent signals are SHORT) suggests the system is generating counter‑trend shorts in a bullish/neutral market

Without persisted feature data, we cannot determine *which* technical condition(s) failed for each losing trade. We need to test specific hypotheses about what distinguishes winners from losers.

---

## Hypothesis: Conditions That Should Separate Winners from Losers

Once `features_json` is populated, we can test these statistically:

### H1: Trend Alignment
- **Winners** have price below SMA20 AND SMA20 < SMA50 (bearish trend confirmed)
- **Losers** have price below SMA20 but SMA20 > SMA50 (no trend confirmation)
- Test: For SHORT signals, compare SMA20 vs SMA50 relationship

### H2: Cloud Position
- **Winners** have close < both `senkou_span_a` and `senkou_span_b` (true bearish cloud)
- **Losers** have close inside or above cloud (mixed/weak signal)
- Test: Cloud breakout strength

### H3: MACD Histogram Confluence
- **Winners** have MACD histogram < -0.0001 (strong bearish momentum)
- **Losers** have MACD histogram near zero or positive (weak/bullish momentum)
- Test: Absolute MACD histogram value and sign

### H4: Volume Confirmation
- **Winners** have volume > 120% of 20‑period average on signal candle
- **Losers** have volume < 105% (lack of institutional confirmation)
- Test: Volume ratio distribution

### H5: ADX Strength
- **Winners** have ADX > 25 (strong trend)
- **Losers** have ADX < 18 (weak/choppy market)
- Test: ADX value separation

### H6: RSI Extremes
- **Winners** have RSI > 70 for SHORT (deeply overbought)
- **Losers** have RSI 55–65 (only mildly overbought, not enough fuel)
- Test: RSI distribution at entry

### H7: ATR‑Based Stop Proximity
- **Losers** have stop loss set too tightly (< 1.0× ATR from entry) → whipsaw
- **Winners** have stop loss > 1.5× ATR → room for noise
- Test: Stop‑loss distance in ATR units

---

## Proposed Analysis Workflow

1. **Extract dataset** of all closed signals with non‑zero PnL (both winners and losers) after feature persistence is deployed.
2. **For each signal**, load `features_json` and compute derived metrics:
   - `trend_aligned` = (SMA20 < SMA50) for SHORT, (SMA20 > SMA50) for LONG
   - `cloud_below` = close < senkou_span_a AND close < senkou_span_b
   - `macd_strength` = abs(MACD_histogram)
   - `volume_spike` = volume / volume_MA(20)
   - `adx_strong` = ADX > 25
   - `rsi_extreme` = (RSI > 70 for SHORT) OR (RSI < 30 for LONG)
   - `stop_atr_ratio` = (stop_loss - entry_price) / ATR (absolute value)
3. **Run statistical tests**:
   - Chi‑square for binary features (trend_aligned, cloud_below, adx_strong, rsi_extreme)
   - T‑tests for continuous features (macd_strength, volume_spike, stop_atr_ratio)
   - Compute effect sizes (Cohen’s d) to prioritize which factors matter most
4. **Build a simple decision tree** to visualize the split between winners and losers.
5. **Report**:
   - Which indicator(s) show the largest significant difference?
   - What threshold optimizes the separation (e.g., ADX > 23)?
   - How many losers would have been avoided if that threshold were enforced?

---

## Implementation Plan

1. **Deploy feature persistence fix** (`2026-04-07_fix-feature-persistence.md`) — wait for ~50–100 closed signals with features.
2. **Write analysis script** (Python) that queries `signal_registry.db`, extracts features, runs stats, outputs a report.
3. **Run analysis** and generate visualization plots (optional: boxplots, histograms).
4. **Translate findings** into concrete code changes:
   - Adjust confidence weighting to favor high‑ADX, strong trend alignment
   - Add a pre‑signal filter that rejects if trend_aligned = False OR adx < 20
   - Tweak leverage schedule based on feature strengths (e.g., higher leverage only if ADX > 25 AND volume_spike > 1.5)

---

## Risk Mitigation While Waiting for Data

In the meantime, we should:
- **Cap leverage** per the risk‑tightening proposal (≤10× for confidence <70%)
- **Enable BTC trend filter** to avoid SHORTs in bullish regime
- **Increase stop‑loss distance** to ≥2× ATR if currently tighter

---

## Success Criteria

- Identify at least one feature with p < 0.01 separating winners from losers
- Achieve >70% accuracy in a simple logistic regression using only the top 2 features
- Reduce loser rate by at least 30% after applying the discovered thresholds

---

## Bottom Line

We suspect the current signal generator is firing on superficial overbought conditions without confirming *sustained* bearish momentum. The stop‑loss failures are likely not due to bad luck but to **missing confluence filters**. This analysis will provide the data‑driven backing needed to tighten the rules and restore profitability.

Once features are persisted, this analysis can be run automatically on a weekly basis to recalibrate thresholds. Recommend approval and scheduling post‑fix deployment.
