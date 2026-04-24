# Proposal: PREDATOR Composite Indicator
**Date:** 2026-04-12 (updated after RH audit)
**Author:** S.P.E.C.T.R.E.
**Status:** IMPLEMENTING — RH core preserved, PREDATOR wraps around it
**Risk:** LOW-MEDIUM — RH state machine untouched, PREDATOR adds layers around it

---

## Executive Summary

Replace the redundant 12-indicator scoring stack with a 4-layer composite
designed specifically for crypto perpetual futures. The current system stacks
RSI, MACD, BB, VWAP, ADX, pattern detection, channel, BOR on top of the core
TSI + CE system. Data analysis of 587 closed signals shows most of these add
noise, not alpha.

PREDATOR = **P**ositioning **R**egime **E**ntry **D**etection with
**A**daptive **T**hreshold **O**ptimization and **R**isk scoring.

---

## Problem Statement

### Current Architecture (signal_generator.py scoring)
```
Score components (max ~16.3 pts):
  bb_score      ×1.0   — Bollinger Band position
  vwap_score    ×1.2   — VWAP cross
  cloud_score   ×1.0   — Ichimoku cloud
  rsi_score     ×1.3   — RSI level
  pattern_score ×2.0   — Candle patterns
  ce_score      ×2.5   — Chandelier Exit
  adx_score     ×1.8   — ADX trend strength
  bor_score     ×2.0   — Breakout/rejection
  channel_score ×0.8   — Channel position
  tsi_score     ×1.5   — TSI momentum
  lr_score      ×1.2   — Linear regression
```

### Issues Identified from 587-Signal Backtest
1. **Indicator redundancy**: RSI, MACD, BB, TSI all measure momentum variations.
   Stacking them averages noise, doesn't compound alpha.
2. **96% short bias**: 560 shorts vs 20 longs — system doesn't generate long signals
   effectively. Likely caused by asymmetric scoring weights.
3. **Confidence anticorrelated with outcomes**: 80-100% confidence → 10.1% WR.
   0-40% confidence → 50.2% WR. The scoring produces the WRONG conviction.
4. **No crypto-native data**: Funding rates, OI, liquidation maps, taker volume
   are available but not used in signal generation — only as minor confidence
   adjustments post-signal.
5. **No regime adaptation**: Same indicator weights in trending, ranging, and
   volatile markets. RSI 70 is overbought in a range but normal in a trend.

---

## Proposed Architecture: PREDATOR

```
┌──────────────────────────────────────────────────────────────┐
│                    PREDATOR COMPOSITE                        │
│                                                              │
│  ┌─────────────────────────────────────────────┐             │
│  │ LAYER 1: REGIME DETECTION                   │             │
│  │  ATR Ratio (7/21) → volatility regime       │             │
│  │  Trend Clarity (EMA50 dist / ATR) → trend   │             │
│  │  Output: one of 6 regime states             │             │
│  └──────────────┬──────────────────────────────┘             │
│                 │                                            │
│                 ▼                                            │
│  ┌─────────────────────────────────────────────┐             │
│  │ LAYER 2: POSITIONING (crypto-native)        │             │
│  │  Funding Rate Momentum (trend over 3 cycles)│             │
│  │  OI Divergence (price vs open interest)     │             │
│  │  Liquidation Magnet (nearest cluster)       │             │
│  │  Taker Volume Delta (buy pressure vs sell)  │             │
│  │  Output: positioning bias + crowd direction │             │
│  └──────────────┬──────────────────────────────┘             │
│                 │                                            │
│                 ▼                                            │
│  ┌─────────────────────────────────────────────┐             │
│  │ LAYER 3: ENTRY SIGNAL                       │             │
│  │  TSI Hook (kept — proven edge)              │             │
│  │  CE Alignment (kept — trend confirmation)   │             │
│  │  Stop Hunt Detector (NEW — wick sweeps)     │             │
│  │  Regime-weighted thresholds                 │             │
│  │  Output: LONG / SHORT / NO_TRADE            │             │
│  └──────────────┬──────────────────────────────┘             │
│                 │                                            │
│                 ▼                                            │
│  ┌─────────────────────────────────────────────┐             │
│  │ LAYER 4: QUALITY + RISK (SQI v2)           │             │
│  │  R:R ratio (from institutional_risk_adjust) │             │
│  │  Volume confirmation                        │             │
│  │  Extension filter                           │             │
│  │  Positioning alignment (L2 agrees with L3?) │             │
│  │  Output: SQI score → leverage + sizing      │             │
│  └─────────────────────────────────────────────┘             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Layer Details

### Layer 1: Regime Detection

**Purpose:** Determine WHAT kind of market we're in before applying any signals.

```python
# ATR Ratio — volatility regime
atr_ratio = ATR(7) / ATR(21)
#   < 0.7  → COILING     (low vol, breakout imminent)
#   0.7-1.3 → NORMAL
#   > 1.3  → EXPANDING   (high vol, potential chop or strong move)

# Trend Clarity — directional strength
trend_clarity = abs(close - EMA(50)) / ATR(14)
#   > 3.0  → STRONG_TREND
#   1.0-3.0 → WEAK_TREND
#   < 1.0  → RANGE

# Combined Regime Matrix (6 states):
#   COILING + RANGE       → COMPRESSION     (best for breakout entries)
#   COILING + TREND       → TREND_PAUSE     (continuation expected)
#   NORMAL  + RANGE       → CHOP            (avoid or scalp only)
#   NORMAL  + TREND       → CLEAN_TREND     (bread and butter)
#   EXPANDING + RANGE     → VOLATILE_CHOP   (avoid — noise)
#   EXPANDING + TREND     → PARABOLIC       (ride or fade, high risk)
```

**Impact:** Each regime gets different entry thresholds, different indicator
weights, and different risk parameters. No more one-size-fits-all.

| Regime | Entry Aggression | Stop Width | Target Width | Position Size |
|--------|-----------------|------------|-------------|---------------|
| COMPRESSION | High — breakout imminent | Tight (1.5×ATR) | Wide (3-5×ATR) | Full |
| TREND_PAUSE | Medium — wait for confirmation | Medium (2×ATR) | Medium (2-3×ATR) | 75% |
| CHOP | Low — high bar to enter | Very tight (1×ATR) | Tight (1.5×ATR) | 25% |
| CLEAN_TREND | High — primary setup | Standard (2.5×ATR) | Standard (2.5×ATR) | Full |
| VOLATILE_CHOP | Skip — no edge | N/A | N/A | 0% |
| PARABOLIC | Fade only — countertrend | Tight (1.5×ATR) | Wide (3×ATR) | 50% |

### Layer 2: Positioning (Crypto-Native)

**Purpose:** See WHERE the crowd is positioned BEFORE the move happens.

#### 2a. Funding Rate Momentum
```python
# Not just current funding — the TREND over 3 funding cycles (24h)
funding_sma3 = SMA(funding_rate, 3)  # 3 cycles = 24h on Binance
funding_delta = funding_rate[-1] - funding_sma3

# Interpretation:
#   funding < 0 AND falling  → shorts aggressively crowding → squeeze LONG setup
#   funding > 0 AND rising   → longs aggressively crowding → dump SHORT setup
#   funding near 0, flat     → neutral — no positioning edge
```

#### 2b. OI Divergence (HIGHEST ALPHA crypto signal)
```python
# Compare price direction with Open Interest direction
price_change_5h = (close[-1] / close[-5]) - 1
oi_change_5h = (OI[-1] / OI[-5]) - 1

# The divergence matrix:
#   Price ↑ + OI ↑  → ACCUMULATION (genuine bullish — new longs entering)
#   Price ↑ + OI ↓  → SHORT_SQUEEZE (shorts closing — will exhaust)
#   Price ↓ + OI ↑  → DISTRIBUTION (genuine bearish — new shorts entering)
#   Price ↓ + OI ↓  → LONG_SQUEEZE (longs closing — will exhaust)

# Squeeze states = reversal imminent
# Accumulation/Distribution = trend continuation
```

#### 2c. Liquidation Magnet
```python
# Estimate where liquidation clusters sit:
# - Recent swing highs = short stop cluster
# - Recent swing lows = long stop cluster
# - Distance to nearest cluster = liquidation magnet strength

# Price tends to gravitate toward the nearest large liquidity pool
# BEFORE reversing. This tells you the likely next move.
liq_long_cluster = recent_swing_low * 0.97   # ~3% below recent low
liq_short_cluster = recent_swing_high * 1.03  # ~3% above recent high

# Magnet direction: which cluster is closer?
# If short cluster is closer → price likely sweeps UP first → then reverses
```

#### 2d. Taker Volume Delta
```python
# Binance provides taker_buy_base_asset_volume per candle
# Delta = taker_buy - taker_sell (where taker_sell = total_vol - taker_buy)
# Accumulated delta over 12h shows real buying/selling pressure

taker_delta_12h = sum(taker_buy[-12:]) - sum(taker_sell[-12:])
taker_delta_ratio = taker_delta_12h / sum(total_volume[-12:])
#   > +0.1 → Strong buy pressure (bullish)
#   < -0.1 → Strong sell pressure (bearish)
#   Between → Neutral
```

### Layer 3: Entry Signal

**Purpose:** Generate the actual LONG/SHORT/NO_TRADE decision.

**Keep what works:**
- TSI hook in extreme zones (OS/OB) — proven edge from Reverse Hunt
- CE Line + Cloud alignment — directional confirmation

**Add: Stop Hunt Detector**
```python
def detect_stop_hunt(df, lookback=20):
    """
    Detect when price swept a key level and immediately rejected.
    This is the institutional entry — retail stops get taken out,
    then smart money enters in the opposite direction.

    Criteria (all must be true):
    1. Current candle has wick > 3× body
    2. Wick pierced a swing high/low from last N bars
    3. Volume on this candle > 2× average
    4. Close is back INSIDE the range (didn't break out)

    Returns:
      'LONG_HUNT'  — downside stop hunt → enter long
      'SHORT_HUNT' — upside stop hunt → enter short
      None         — no hunt detected
    """
    candle = df.iloc[-1]
    body = abs(candle['close'] - candle['open'])
    upper_wick = candle['high'] - max(candle['open'], candle['close'])
    lower_wick = min(candle['open'], candle['close']) - candle['low']
    avg_vol = df['volume'].iloc[-lookback:-1].mean()

    # Downside hunt: long lower wick, swept recent low
    recent_low = df['low'].iloc[-lookback:-1].min()
    if (lower_wick > 3 * max(body, 0.0001) and
        candle['low'] < recent_low and
        candle['close'] > recent_low and
        candle['volume'] > 2 * avg_vol):
        return 'LONG_HUNT'

    # Upside hunt: long upper wick, swept recent high
    recent_high = df['high'].iloc[-lookback:-1].max()
    if (upper_wick > 3 * max(body, 0.0001) and
        candle['high'] > recent_high and
        candle['close'] < recent_high and
        candle['volume'] > 2 * avg_vol):
        return 'SHORT_HUNT'

    return None
```

**Regime-weighted entry thresholds:**

In CLEAN_TREND regime, TSI hook threshold is relaxed (enter earlier).
In CHOP regime, TSI must be in deep L2 zone (higher bar).
In VOLATILE_CHOP, no entries at all.

### Layer 4: Quality + Risk (SQI v2)

Extends the existing SQI with positioning alignment:

```
SQI v2 = SQI v1 + Positioning Score (0-20 pts)

Positioning Score:
  Funding momentum aligns with direction → +5
  OI divergence confirms              → +10 (highest weight)
  Taker delta aligns                  → +5
```

New max: 120 instead of 100. Grades adjusted accordingly.

---

## What Gets Removed

| Component | Status | Reason |
|-----------|--------|--------|
| RSI scoring | REMOVE from signal gen | Redundant with TSI. Keep in SQI for quality only |
| MACD scoring | REMOVE from signal gen | Lagging, low alpha. Redundant with TSI |
| BB scoring | REMOVE from signal gen | Redundant with CE for volatility-based entries |
| Pattern scoring | REMOVE | Candle patterns on 1h crypto = noise |
| Channel scoring | REMOVE | Subsumed by regime detection |
| BOR scoring | REMOVE | Replaced by stop hunt detector |
| VWAP scoring | KEEP as quality filter | Useful for extension measurement |
| Ichimoku cloud | KEEP | Used in CE Cloud layer |

**Net effect:** Scoring goes from 11 components to 4 layers. Fewer inputs, each
with a clear purpose and data-backed edge.

---

## Implementation Plan

### Phase 1: Regime Detection + Stop Hunt ✅ COMPLETE
- [x] Build `predator.py` with regime detection (6 regimes, ATR ratio + trend clarity)
- [x] Implement stop hunt detector (wick sweep + volume + level reclaim)
- [x] Add regime logging (`🌍 REGIME` + `🎯 STOP HUNT` log lines in main.py)
- [x] ~~Observation mode~~ → Went live: regime actively filters (VOLATILE_CHOP=skip) + sizes

### Phase 2: Positioning Layer ✅ COMPLETE
- [x] Funding rate momentum (contrarian: negative funding → shorts crowded)
- [x] OI divergence scoring (ACCUMULATION/SHORT_SQUEEZE/DISTRIBUTION/LONG_SQUEEZE/NEUTRAL)
- [x] Taker volume delta (12-bar buy/sell ratio from `taker_buy_base_asset_volume`)
- [x] Liquidation magnet from swing points (7 leverage tiers, density clustering, gravity scoring)
- [x] Log positioning scores (`📡 POSITIONING` + `🧲 LIQ MAGNETS` log lines)

### Phase 3: Integration ✅ COMPLETE
- [x] Replace `calculate_detailed_confidence()` scoring — dead import removed, chain stripped
- [x] Regime → entry threshold mapping (`REGIME_PARAMS` with `allow_entry`, `size_mult`)
- [x] SQI v2 with positioning factor (0-20pts) + stop hunt bonus (0-5pts) + liq magnet boost
- [x] Update Telegram message with regime + OI divergence + SQI/125

### Phase 4: Validation ⏳ LIVE MONITORING
- [x] Dashboard analytics extended with regime + positioning breakdown tables
- [ ] Accumulate 50+ signals with PREDATOR data → compare win rates by regime
- [ ] Analyze which positioning states produce highest alpha
- [ ] Tune regime size multipliers based on real performance data
- [ ] If not → analyze which layer is underperforming and adjust

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Regime detection misclassifies | MEDIUM | Log regimes for 1 week before using for decisions |
| Stop hunt false positives | LOW | Strict criteria (3× wick + volume + level sweep) |
| OI data latency | LOW | Use 1h OI snapshots, not real-time |
| Reduced signal count | MEDIUM | PREDATOR filters more aggressively — fewer but higher quality |
| Short bias persists | LOW | Regime + positioning is direction-agnostic by design |

---

## Expected Impact

Based on backtest analysis of 587 signals:

| Metric | Current | Expected with PREDATOR |
|--------|---------|----------------------|
| Signals/day | ~20 | ~8-12 (fewer, better filtered) |
| Win rate | 36.6% | 50-60% (regime filtering + positioning) |
| Avg win | +3.10% | +3.5-4.0% (better entries from stop hunts) |
| Avg loss | -1.02% | -0.8% (tighter regime-adaptive stops) |
| Profit factor | 1.76 | 2.5-3.0 |
| Max leverage on D-grade | 25x | 3x (SQI-controlled) |
| Short bias | 96% | ~55-60% (balanced by positioning data) |

---

## Decision Required

**Proceed with Phase 1 (observation mode)?** Regime detection + stop hunt
detector built and logging alongside current system. Zero risk to live signals.

Once validated, Phase 2-3 integrate progressively.
