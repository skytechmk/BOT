# Proposal: Critical Fixes — Feature Persistence, BTC Trend Filter, Leverage Scaling

**Date**: 2026-04-07
**Priority**: CRITICAL
**Author**: S.P.E.C.T.R.E.
**Related**: 2026-04-07_fix-feature-persistence.md, 2026-04-07_risk-parameter-tightening.md, 2026-04-07_stop-loss-failure-analysis.md

---

## Executive Summary

Three critical issues are causing sustained losses:

1. **Feature persistence broken** — `features_json` empty due to type filter rejecting numpy floats → we cannot analyze or improve the model
2. **No BTC trend filter** — SHORTs generated in bullish BTC regime → systemic directional losses
3. **Excessive leverage on moderate confidence** — 20–44× on 56–69% confidence → amplified losses

All three must be deployed immediately.

---

## Issue 1: Feature Persistence Broken (ROOT CAUSE IDENTIFIED)

**Location**: `main.py:468-472` (feature snapshot capture)

**Current Code**:
```python
# Capture features for learning
feature_snapshot = df.iloc[-1].to_dict()
# Remove massive strings/objects to keep registry clean
feature_snapshot = {k: v for k, v in feature_snapshot.items() if isinstance(v, (int, float, bool, str)) and len(str(v)) < 100}
```

**Bug**: `isinstance(v, (int, float, bool, str))` returns `False` for `numpy.float64`, `numpy.int64`, etc. All technical indicators from pandas/numpy (ATR, MACD, RSI, Senkou spans, etc.) are numpy scalar types. They get filtered out, leaving `features_json` empty.

**Fix**:
```python
import numpy as np  # add at top of main.py

# Capture features for learning
feature_snapshot = df.iloc[-1].to_dict()
# Keep numeric types (including numpy), bool, str; limit string length
def is_keepable(v):
    if isinstance(v, (int, float, bool, str)):
        return len(str(v)) < 100
    if isinstance(v, (np.integer, np.floating)):
        return True  # numpy numerics are always compact
    return False

feature_snapshot = {k: v for k, v in feature_snapshot.items() if is_keepable(v)}
```

**Alternatively**, convert numpy scalars to Python floats:
```python
feature_snapshot = {}
for k, v in df.iloc[-1].to_dict().items():
    if isinstance(v, (np.integer, np.floating)):
        v = float(v)
    if isinstance(v, (int, float, bool, str)) and len(str(v)) < 100:
        feature_snapshot[k] = v
```

**Effect**: Once fixed, `features_json` will contain full technical context (RSI, MACD, ADX, BB, Ichimoku, VWAP, etc.) for every signal, enabling all downstream analysis.

---

## Issue 2: Missing BTC Trend Filter

**Problem**: All 24 recent SHORT signals were generated without checking BTC’s higher‑timeframe trend. If BTC is bullish, alts will drift up and stop out.

**Proposed Implementation** — Add to `signal_generator.py` before accepting a SHORT:

```python
def get_btc_regime(timeframe='1h'):
    """
    Fetch BTCUSDT 1h data and determine trend regime.
    Returns: 'bullish', 'bearish', 'neutral'
    """
    try:
        # Reuse existing data fetcher or direct API
        df_btc = fetch_ohlcv('BTCUSDT', timeframe, limit=100)  # implement this helper
        if df_btc is None or len(df_btc) < 50:
            return 'neutral'  # cannot determine

        latest = df_btc.iloc[-1]
        sma20 = df_btc['close'].rolling(20).mean().iloc[-1]
        sma50 = df_btc['close'].rolling(50).mean().iloc[-1]
        price = latest['close']

        if price > sma20 and sma20 > sma50:
            return 'bullish'
        elif price < sma20 and sma20 < sma50:
            return 'bearish'
        else:
            return 'neutral'
    except Exception as e:
        log_message(f"BTC regime check failed: {e}")
        return 'neutral'

# In calculate_base_signal(df, pair=None), after computing base_signal but before returning:
if pair is not None and pair != 'BTCUSDT':
    btc_regime = get_btc_regime('1h')
    if base_signal == 'SHORT' and btc_regime == 'bullish':
        log_message(f"Rejecting SHORT on {pair}: BTC regime bullish")
        return 'NEUTRAL'
    elif base_signal == 'LONG' and btc_regime == 'bearish':
        log_message(f"Rejecting LONG on {pair}: BTC regime bearish")
        return 'NEUTRAL'
```

**Simpler alternative (lighter)**: Check only price vs SMA20 relationship; skip SMA50 if data is sparse.

**Caching**: Cache BTC regime for 5 minutes to avoid excessive API calls.

---

## Issue 3: Dynamic Leverage Scaling

**Current leverage** (from open signals): 20–44× on 56–69% confidence. Too aggressive.

**Proposed Leverage Schedule** (implement in `trading_utilities.py` or where leverage is assigned):

```python
def assign_leverage(confidence: float, signal_type: str, pair: str = None) -> int:
    """
    Confidence is 0.0–1.0.
    Returns max allowed leverage.
    """
    # Base tiers
    if confidence >= 0.70:
        base_lev = 20
    elif confidence >= 0.60:
        base_lev = 10
    elif confidence >= 0.50:
        base_lev = 5
    else:
        return 1  # spot only

    # SHORTs in bullish BTC regime get further reduced (if BTC filter not yet blocking)
    # if signal_type == 'SHORT' and get_btc_regime('1h') == 'bullish':
    #     base_lev = max(2, base_lev // 2)

    # Pair‑specific caps for ultra‑volatile micro‑caps
    high_risk_pairs = {'PUMPUSDT', 'XANUSDT', 'COSUSDT', 'LEVERUSDT', 'TROYUSDT', '1000SATSUSDT'}
    if pair in high_risk_pairs:
        base_lev = min(base_lev, 5)

    return base_lev
```

**Wire‑up**: Call `assign_leverage()` in `main.py` after computing `adj_confidence`, before sending signal.

---

## Implementation Checklist

### Phase 1: Feature Persistence Fix
- [ ] Import `numpy as np` at top of `main.py`
- [ ] Replace the `feature_snapshot` filter with one that accepts `np.integer` and `np.floating`
- [ ] Test: Generate 1 signal, query DB, ensure `features_json` contains keys like 'ATR', 'RSI_14', 'MACD Histogram'
- [ ] Verify with: `SELECT features_json FROM signals LIMIT 1;`

### Phase 2: BTC Trend Filter
- [ ] Implement `fetch_ohlcv(pair, timeframe, limit)` helper (or use existing Binance client)
- [ ] Implement `get_btc_regime(timeframe)` as above
- [ ] Integrate into `signal_generator.py` (or `main.py` after `final_signal` determined but before `register_signal`)
- [ ] Add caching (store last regime and timestamp in module global, refresh if > 5 min old)
- [ ] Log every rejection with reason

### Phase 3: Leverage Scaling
- [ ] Add `assign_leverage(confidence, signal_type, pair)` function in `trading_utilities.py`
- [ ] Replace current leverage assignment in `main.py` with call to this function
- [ ] Ensure `high_risk_pairs` list covers the most volatile tokens (based on ATR% > 5%)
- [ ] Optionally: reduce leverage if ADX < 25 (weak trend)

### Testing & Validation
1. **Feature Test**:
   ```python
   db = SignalRegistryDB()
   sig = db.get_all()
   sample = list(sig.values())[0]
   assert 'ATR' in json.loads(sample['features_json'])
   ```
2. **BTC Filter Test**: Mock BTC downtrend → ensure SHORT signals still pass; mock BTC uptrend → ensure SHORTs rejected.
3. **Leverage Test**: Log leverage assignments for 10 signals, verify they match confidence tiers.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| BTC regime check adds latency | Slower signal generation | Cache BTC data for 5 min; use async fetch |
| Filter too strict, miss good trades | Reduced signal count | Acceptable trade‑off; monitor win rate improvement |
| Leverage reduction cuts PnL | Smaller gains on winners | Better risk‑adjusted returns; survive drawdowns |
| Feature filter change breaks other logic | Unexpected errors | Test on staging first; keep old filter as fallback |

---

## Rollback

All changes are localized:
- Feature filter: revert to original `isinstance(v, (int, float, bool, str))`
- BTC filter: comment out the rejection block
- Leverage: restore hard‑coded mapping

Keep original code in comments for quick rollback.

---

## Success Metrics (After 7 Days)

- **Feature persistence**: 100% of signals have non‑empty `features_json`
- **BTC filter rejections**: ~30% of SHORTs rejected in bullish regime (verify log)
- **Leverage distribution**: ≤5× for <60% confidence; max 20× for ≥70%
- **Performance**: Win rate >55%, average win > average loss, net PnL positive

---

## Bottom Line

These fixes address the **immediate root causes** of the recent losses:
- Empty features → blind analysis
- No BTC filter → SHORTs against macro trend
- Over‑leverage → amplified bleeding

Deploy in order: Feature fix first (enables everything else), then BTC filter, then leverage scaling. Monitor logs for rejections and feature population. Expect initial signal count drop; quality should rise.
