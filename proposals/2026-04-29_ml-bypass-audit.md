# ML Bypass Audit & Integration — System-wide Structural Refactor

**Date**: 2026-04-29  
**Scope**: Full codebase sweep of ML prediction consumption across all execution modules

---

## Executive Summary

The ML ensemble (XGBoost + Isotonic Calibration + Conformal Prediction in `ml_ultra_surface.py`) generates calibrated directional probabilities (`ml_prob_short`, `ml_prob_neutral`, `ml_prob_long`) that are folded into Factor 11 of the SQI composite score. However, **six critical execution modules** bypass raw ML outputs entirely — they consume only the fully-diluted composite `sqi_score` or operate with no ML awareness at all. This creates disjointed trade execution where tactical exits override ML strategic conviction.

---

## Bypass Inventory

### 1. `trailing_engine.py` — **FIXED (this cycle)**
- **Before**: Pure ATR-based trailing SL — zero ML awareness. A low-confidence signal (ml_confidence=0.45) trails identically to a high-confidence one (ml_confidence=0.91).
- **Fix**: ML confidence extracted from `features.ml_prob_*` → ATR multiplier scaling:
  - `ml_confidence ≥ 0.85` → widen ATR by 1.5× (prevent premature exit in strong trends)
  - `ml_confidence ≤ 0.60` → tighten ATR by 0.6× (lock profits on uncertain signals)
- **Env tunables**: `TRAIL_ML_CONF_HIGH`, `TRAIL_ML_CONF_LOW`, `TRAIL_ML_WIDEN_MULT`, `TRAIL_ML_TIGHTEN_MULT`
- **Files changed**: `trailing_engine.py` (lines 55–124, 252–256, 281–305, 325–340, 390–400)

### 2. `copy_trading.py` position sizing — **FIXED (this cycle)**
- **Before**: Position size formula: `Base Size × SQI Multiplier`. A signal with identical SQI but low ML confidence gets the same allocation as a high-ML-confidence signal.
- **Fix**: `Final Position Size = Base Size × SQI Multiplier × ML Confidence`
  - ML confidence extracted from `features.ml_prob_*` via `_extract_ml_confidence_from_signal()`
  - Applied to both `fixed_usd` and percentage-of-balance modes
  - Falls back to neutral (0.5) if ML data unavailable
- **Files changed**: `dashboard/copy_trading.py` (lines 47–72, 2058–2061, 2074–2077, 2509–2513, 2521–2524)

### 3. `predator.py` regime detection — **NOT FIXED** (low-risk bypass)
- **Current state**: `detect_regime()` classifies market into 6 states using ATR ratio + trend clarity only. No ML model is consulted for regime classification.
- **Risk**: Low. Regime detection is structural (volatility + trend), not directional. A dedicated ML regime classifier would be a separate model, not the existing directional ensemble.
- **Recommendation**: Keep as-is. Regime *consumes* ML outputs downstream via `RegimeDict.ml_confidence`.

### 4. `predator.py` positioning analysis — **NOT FIXED** (medium-risk bypass)
- **Current state**: `analyze_positioning()` uses funding rate, OI divergence, and taker delta to determine crowd direction. This is an orthogonal signal — it measures positioning extremes that the ML model should already incorporate via feature engineering.
- **Risk**: Medium. If ML features already capture funding/OI/taker data (which they do — 127 features from `ml_engine_archive/feature_engine.py`), this is redundant but not harmful. However, the *combination* of ML prediction + positioning contradiction could be a powerful filter.
- **Recommendation**: Future enhancement — add ML-verification gate: if `ml_prediction == 'LONG'` but `positioning_bias == 'SHORT'`, apply a sizing penalty.

### 5. `main.py` Counter-Flow Trap Gate (lines 501–521) — **NOT FIXED**
- **Current state**: Uses `taker_delta + liq_aligned` to veto signals. No ML consumption.
- **Risk**: Medium-High. This is the most aggressive veto gate in the system and it ignores ML entirely. A high-confidence ML prediction could be killed by a counter-flow rule that the ML model already discounted in its probability estimate.
- **Recommendation**: Add a `ml_confidence > 0.85` exception to this gate — high-conviction ML predictions should not be vetoed by TA-only flow analysis.

### 6. `main.py:759-762` AI Robustness Filter — **HARDCODED BYPASS**
- **Current state**: `deepseek_verdict = 'PROCEED'` — AI robustness filter permanently disabled.
- **Risk**: Low (by design — intentional bypass). But if re-enabled, `deepseek_verdict` must be compared against `ml_confidence` for consistency.
- **Recommendation**: No change needed. Document that re-enabling requires ML-consistency check.

### 7. `signal_generator.py` `calculate_detailed_confidence()` — **NOT FIXED**
- **Current state**: Pure TA-based confidence (RSI, volume, volatility, trend, pattern). No ML input.
- **Risk**: Low. The function is marked as "REMOVED: dead code" in main.py import. It is not in the active execution path.
- **Recommendation**: If revived, it should be augmented to factor in `ml_confidence` as a weight.

### 8. `main.py:783` `adaptive_confidence_adjustment()` — **NOT FIXED**
- **Current state**: Adjusts confidence based on VWAP distance, spread, volume tail. No ML input.
- **Risk**: Medium. The `adj_confidence` value is used for Telegram display and signal quality rating, then replaced by SQI score for actual execution decisions. This creates a semantic gap where the UI shows one confidence number but execution uses a different one.
- **Recommendation**: Future enhancement — blend `adj_confidence` with `ml_confidence` for a unified `signal_confidence` field visible in UI and stored in DB.

---

## ML Consumption Map (Post-Refactor)

```
ml_ultra_surface.py  ──►  signal_quality.py Factor 11  ──►  sqi_score
      │                                                             │
      │  ml_prob_short/neutral/long                                 │  composite
      │  ml_confidence (max calibrated prob)                        │
      │                                                             ▼
      ├─────────►  trailing_engine.py  ──►  ATR mult. scaling  ✅ NEW
      │
      ├─────────►  copy_trading.py     ──►  Position size mult  ✅ NEW
      │
      ├─────────►  feature_snapshot    ──►  persisted to DB + Redis
      │
      └─────────►  /explain command    ──►  Telegram display
```

---

## TypedDict Schema Enforcement

| Type | File | Lines | New ML Fields | Purpose |
|------|------|-------|---------------|---------|
| `RHSignalDict` | `reverse_hunt.py:47` | 47–67 | `ml_prediction: str`, `ml_confidence: float`, `sqi_score: float`, `sqi_grade: str` | Signal output contract — all consumers must handle ML data |
| `RegimeDict` | `predator.py:31` | 31–44 | `ml_confidence: float`, `ml_prediction: str` | Regime analysis — downstream modules receive ML context |
| `PositioningDict` | `predator.py:40` | 40–55 | `ml_confidence: float`, `ml_prediction: str` | Positioning analysis — ML-aware crowd direction |

All three TypedDicts use `total=False` (partial) to maintain backward compatibility — legacy callers that don't populate ML fields won't fail at runtime, but **new code that accesses `result['ml_confidence']` must handle `None`**.

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| trailing_engine ML scaling | Low | Env-gated defaults (0.85/0.60 thresholds); if ML data missing, falls back to base ATR mult |
| copy_trading ML sizing | Low | Multiplicative only — never zeroes a trade; `max(round(size * ml_conf, 2), 1.0)` floor |
| TypedDict additions | Zero | `total=False` — no callers break; new fields are optional |
| Schema compatibility | Zero | All existing DB rows have `features` column with `ml_prob_*` populated since Phase 4 |

---

## Verification

```bash
# Syntax validation (all pass)
python -c "import ast; ast.parse(open('trailing_engine.py').read())"
python -c "import ast; ast.parse(open('dashboard/copy_trading.py').read())"
python -c "import ast; ast.parse(open('reverse_hunt.py').read())"
python -c "import ast; ast.parse(open('predator.py').read())"

# Functional test: trailing_engine.py ingests ML confidence
# Set TRAILING_ENABLED=true, have an open signal with targets_hit >= 1
# Check logs for "ML=0.xx" in [PREDATOR-LOOP] trailing output

# Functional test: copy_trading position sizes with ML scaling
# Submit a copy-trade with features containing ml_prob_* fields
# Verify size_usd is multiplied by ML confidence
```
