# Proposal: Fix Reverse Hunt Logic Issues

## Problem 1: Adaptive Threshold Cache Stagnation
**File:** `reverse_hunt.py` (lines ~605-613)

The adaptive TSI thresholds (`adapt_l1`, `adapt_l2`) are meant to track pair-specific distributions. A cache is implemented here (`_adaptive_threshold_cache`), and the comment states "refresh every 100 bars". However, the invalidation logic is entirely missing. Once a pair's thresholds are cached on the first calculation, they are never updated for the lifetime of the bot process.

## Problem 2: Volume Gate SMA Self-Inflation
**File:** `reverse_hunt.py` (lines ~382)

The new Extreme Mode "Volume Gate" correctly requires `v_now > 1.5 * v_sma` to confirm a reversal breakout. However, the calculation of `v_sma` includes the current bar's volume (`v_now`). During an extreme capitulation event, a massive outlier volume spike will exponentially inflate the 20-period SMA itself, pushing the 1.5x threshold much higher and actively suppressing the intended breakout signal. The baseline SMA must exclude the current outlier candle.

## Proposed Changes

### 1. Fix Cache Invalidation
**File:** `reverse_hunt.py`
```diff
-    if cache_key in _adaptive_threshold_cache:
+    if cache_key in _adaptive_threshold_cache and (bar_idx - _adaptive_threshold_cache[cache_key]['bar'] < 100):
         cached = _adaptive_threshold_cache[cache_key]
         adapt_l1, adapt_l2 = cached['l1'], cached['l2']
     else:
```

### 2. Fix Volume Gate SMA Indexing
**File:** `reverse_hunt.py`
```diff
-        v_sma = vol_sma[current_bar]
+        # Use previous bar's SMA to prevent the current volume surge from inflating the baseline
+        v_sma = vol_sma[current_bar - 1] if current_bar > 0 else vol_sma[current_bar]
```

## Risk Assessment
**Low Risk.** These changes fix mathematical validation oversights to restore the originally intended behavior of the system. The cache fix properly tracks shifting market dynamics, while the SMA index shift repairs a math error that could cause genuine capitulation trades to be filtered out as noise.
