# Proposal: Tighten Risk Parameters — Leverage Scaling & HTF Trend Filter

**Date**: 2026-04-07
**Priority**: HIGH
**Files affected**: `signal_generator.py`, `trading_utilities.py` (or wherever leverage/confidence logic resides), possibly `config.py` or `constants.py`

## Problem

Current open signals exhibit extreme risk:
- 23 open signals with **average confidence ~62%** but **leverage up to 44×**
- Directional clustering: 24/35 recent signals are SHORT, creating concentrated exposure
- Several positions already underwater before they’re even filled (e.g., BANANAS31 +2.3%, JCT +3.8% against SHORT entries)
- GALA SHORT just stopped out (~‑10% leveraged loss)

The system is generating many moderately‑confident signals with dangerously high leverage, and there’s no higher‑timeframe trend filter to avoid counter‑trend entries.

## Proposed Changes

### 1. Dynamic Leverage Scaling by Confidence Tier

Replace static leverage assignments with a tiered schedule:

| Confidence Range | Max Leverage | Rationale |
|------------------|--------------|-----------|
| 70% – 100% | 20× | High conviction, can afford larger position |
| 60% – 69.9% | 10× | Moderate conviction, controlled risk |
| 50% – 59.9% | 5× | Low‑moderate conviction, minimal risk |
| < 50% | 1× (spot) or reject | Not confident enough for leverage |

**Implementation** (in `signal_generator.py` or leverage‑assignment function):

```python
def assign_leverage(confidence: float, signal_type: str, pair: str = None) -> int:
    """Assign leverage based on confidence tiers and signal direction."""
    if confidence >= 70.0:
        base_leverage = 20
    elif confidence >= 60.0:
        base_leverage = 10
    elif confidence >= 50.0:
        base_leverage = 5
    else:
        return 1  # Spot only
    
    # Optional: Reduce leverage for SHORTs in bullish BTC regime (see below)
    # if signal_type == 'SHORT' and is_bullish_btc_regime():
    #     base_leverage = max(2, base_leverage // 2)  # at least 2×, but halved
    
    # Optional: Pair‑specific caps (e.g., avoid >10× on ultra‑volatile micro‑caps)
    volatile_pairs = {'PUMPUSDT', 'XANUSDT', 'COSUSDT'}  # example; extend as needed
    if pair in volatile_pairs:
        base_leverage = min(base_leverage, 5)
    
    return base_leverage
```

**Where to call**: Immediately after confidence is calculated and before targets/stop‑loss are set.

---

### 2. Higher‑Timeframe Trend Filter (BTC‑Aware)

**Goal**: Avoid SHORT signals when the broader market is bullish; avoid LONG signals when bearish.

**Logic**:
- Fetch 1h BTCUSDT data (or use cached) and compute:
  - `btc_sma20` = 1h SMA(20)
  - `btc_sma50` = 1h SMA(50)
  - `btc_price` = current 1h close
- Define **bullish regime**: `btc_price > btc_sma20` AND `btc_sma20 > btc_sma50`
- Define **bearish regime**: `btc_price < btc_sma20` AND `btc_sma20 < btc_sma50`
- Neutral otherwise

**Signal gating**:

```python
def passes_trend_filter(signal_type: str, btc_regime: str) -> bool:
    """
    btc_regime: 'bullish', 'bearish', 'neutral'
    Returns True if signal is allowed under current BTC regime.
    """
    if btc_regime == 'bullish':
        return signal_type == 'LONG'  # only allow LONGs
    elif btc_regime == 'bearish':
        return signal_type == 'SHORT'  # only allow SHORTs
    else:
        return True  # neutral allows both
```

**Integration**: In `signal_generator.py`, for each pair, call `passes_trend_filter()` after determining `signal_type`. If `False`, set `signal = 'NEUTRAL'` and confidence = 0 (reject).

**Note**: We could also apply the same regime filter on the *pair’s own* 1h trend to avoid counter‑trend trades, but starting with BTC filter is simpler and reduces systemic correlation risk.

---

### 3. Volatility‑Based Stop‑Loss Tightening (Optional Enhancement)

Current stop‑loss distances look reasonable (0.5‑2%), but we can make them adaptive:

```python
def calculate_stop_loss(signal_type: str, entry_price: float, atr: float, volatility_ratio: float) -> float:
    """
    Tighten stops in high‑volatility regimes, widen in low‑volatility.
    volatility_ratio = current ATR / 14‑period avg ATR
    """
    base_distance = 1.5 * atr  # 1.5× ATR from entry
    
    if volatility_ratio > 1.5:  # elevated volatility
        base_distance *= 0.75  # tighter to avoid whipsaw
    elif volatility_ratio < 0.7:  # low volatility
        base_distance *= 1.25  # wider to avoid noise
    
    if signal_type == 'LONG':
        return entry_price - base_distance
    else:  # SHORT
        return entry_price + base_distance
```

---

### 4. Minimum Confidence Threshold

Reject any signal with confidence < 50% outright. This is likely already done via `calculate_base_signal` returning NEUTRAL, but verify.

---

## Implementation Checklist

- [ ] Locate where leverage is currently assigned (in `signal_generator.py` or `trading_utilities.py`)
- [ ] Replace static leverage logic with `assign_leverage()` function
- [ ] Add BTC trend filter function and ensure 1h BTC data is fetched (reuse existing `get_market_context` if available)
- [ ] Gate signal generation: if trend filter fails, set `signal = 'NEUTRAL'` and confidence = 0
- [ ] (Optional) Implement adaptive stop‑loss function
- [ ] Add unit tests for:
  - Leverage assignment across confidence tiers
  - Trend filter logic with mocked BTC regimes
  - Stop‑loss calculation for various volatility regimes
- [ ] Update any configuration constants (e.g., `MIN_CONFIDENCE = 50.0`)
- [ ] Deploy with monitoring: log every rejection reason (leverage cap, trend filter) to a `signal_rejections.log` for analysis

---

## Risk Assessment

- **Low‑to‑moderate risk**: Changes are defensive; they reduce risk, not increase it.
- **Potential missed opportunities**: Some good signals may be rejected due to trend filter; acceptable trade‑off for survival.
- **Performance impact**: May reduce number of signals, but improve win rate and risk‑adjusted returns.
- **Leverage reduction**: Directly reduces maximum possible loss per trade, which is always beneficial in volatile altcoin markets.

---

## Verification

1. **Log review** after 24‑48h:
   - Count of signals rejected by trend filter
   - Distribution of assigned leverage vs confidence
   - Any errors in BTC data fetching
2. **Compare realized performance** before vs after:
   - Win rate should increase
   - Average loss should decrease
   - Net PnL should improve or at least become less volatile
3. **Check open positions**: Ensure no new open signals have leverage >20× (except possibly BTC‑related with >70% confidence).

---

## Rollback Plan

If we see adverse effects (e.g., too many rejections, missing strong trends), we can:
- Temporarily raise confidence tiers (e.g., 10× for 55%+)
- Remove BTC filter but keep leverage scaling
- Adjust stop‑loss multiplier back to static 1.5× ATR

All changes are contained in a few functions; rollback is straightforward.

---

## Bottom Line

These adjustments are prudent given the current open‑loss exposure and the evident over‑leverage on moderate‑confidence signals. Implementing them **before** the feature‑persistence fix is acceptable because they are independent risk controls. The feature fix will then allow us to further refine the model with data.

---

**Recommendation**: Approve and deploy immediately. Monitor rejections and performance metrics daily for one week, then iterate.