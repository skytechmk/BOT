# Proposal: Strengthen Default Regime Safety

## Problem Description
In `predator.py`, the `_default_regime()` function is called when OHLCV data is insufficient or corrupt. Currently, it returns a highly permissive state:
```python
def _default_regime():
    return {
        'regime': REGIME_CLEAN_TREND,
        'atr_ratio': 1.0,
        'trend_clarity': 1.5,
        'vol_state': 'NORMAL',
        'trend_state': 'WEAK_TREND',
        'trend_dir': 'UP',
        'params': REGIME_PARAMS[REGIME_CLEAN_TREND],
    }
```
This causes the bot to default to `CLEAN_TREND` with `size_mult=1.0` (Full Size) whenever data is missing. This is unsafe for an institutional-grade system. If the bot doesn't know the market regime, it should minimize exposure or block the trade.

## Proposed Changes

### 1. Update `_default_regime` to `CHOP`
**File:** `predator.py`
We will change the default to `REGIME_CHOP`, which carries a heavy `size_mult=0.35` penalty.

```diff
 def _default_regime():
     return {
-        'regime': REGIME_CLEAN_TREND,
+        'regime': REGIME_CHOP,
         'atr_ratio': 1.0,
-        'trend_clarity': 1.5,
+        'trend_clarity': 0.5,
         'vol_state': 'NORMAL',
-        'trend_state': 'WEAK_TREND',
+        'trend_state': 'RANGE',
         'trend_dir': 'UP',
-        'params': REGIME_PARAMS[REGIME_CLEAN_TREND],
+        'params': REGIME_PARAMS[REGIME_CHOP],
     }
```

## Risk Assessment
**Low Risk.** This is a defensive change. It prevents full-size trade execution on pairs with incomplete data. In the worst case, a few trades on "just-loaded" pairs might have reduced size for the first few bars until the regime detector has enough history.
