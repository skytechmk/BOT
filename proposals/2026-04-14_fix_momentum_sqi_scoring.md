# Proposal: Fix Momentum SQI Scoring Bias

## Problem Description
In `signal_quality.py`, the Momentum Acceleration factor (Factor 6) attempts to read the `TSI` column from the provided DataFrame:
```python
if 'TSI' in df.columns and len(df) >= 5:
```
However, the `df_1h` passed from `main.py` is a raw OHLCV DataFrame from the `BATCH_PROCESSOR`. It does not contain a `TSI` column. As a result, the code always falls back to a neutral score of 5/10:
```python
factors['momentum'] = {'score': 5, 'max': 10, 'value': None}
mom_score = 5
```
This introduces a systematic bias where no signal ever benefits from strong momentum confirmation or is penalized for decelerating momentum.

## Proposed Changes

### 1. Inject TSI into DataFrame in `main.py`
**File:** `main.py`
Before calling `calculate_sqi`, we should inject the calculated TSI value into the last row of the DataFrame.

```diff
         # ── SQI v2: Signal Quality Index + PREDATOR layers ──
         ce_line_str = 'LONG' if rh_indicators.get('ce_line_dir') == 1 else 'SHORT' if rh_indicators.get('ce_line_dir') == -1 else None
         ce_cloud_str = 'LONG' if rh_indicators.get('ce_cloud_dir') == 1 else 'SHORT' if rh_indicators.get('ce_cloud_dir') == -1 else None
+        
+        # Inject TSI for Momentum SQI factor (Factor 6)
+        if 'tsi' in rh_indicators:
+            df_1h = df_1h.copy() # Avoid SettingWithCopyWarning
+            df_1h.loc[df_1h.index[-1], 'TSI'] = rh_indicators['tsi']
+
         sqi_result = calculate_sqi(
             df_1h, current_price, stop_loss, targets, final_signal,
```

## Risk Assessment
**Zero Risk.** This simply populates a missing data field that `signal_quality.py` expects. It enables the momentum scoring logic without changing any entry/exit triggers.
