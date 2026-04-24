# Proposal: Fix Feature Persistence in Signal Registry

**Date**: 2026-04-07
**Priority**: HIGH
**Files affected**: `signal_generator.py`, `signal_registry_db.py`, possibly `main.py` or `trading_utilities.py`

## Problem

The `features_json` field in `signal_registry.db` is empty for all recent signals, despite `signal_generator.py` computing extensive technical indicators (RSI, MACD, ADX, BB, Ichimoku, VWAP, etc.). This prevents:
- Post-hoc performance analysis of which indicators distinguish winners from losers
- Statistical validation of confidence factor weights
- ML training on recent labeled data
- Systematic debugging of false signals

## Root Cause Analysis

1. **`signal_generator.py`** likely computes a `features_dict` or similar structure but does not include it when calling `SignalRegistryDB.set_signal()` or `update_signal()`.
2. The `set_signal()` method in `SignalRegistryDB` accepts a `features_json` key in the data dict, but the caller may be passing `None` or `{}`.
3. Historical migration from `signal_registry.json` may have also omitted features.

## Proposed Changes

### 1. Modify `signal_generator.py` — Ensure features dict is populated and passed

Find the function that assembles signal data before saving (likely near `set_signal` or `update_signal` calls). Add explicit `features_json` population.

Example patch:

```python
# In signal_generator.py, where signal_data or similar dict is created:

# Before saving, compile all technical features into a features_dict
features_dict = {
    'RSI_14': latest.get('RSI_14'),
    'RSI_21': latest.get('RSI_21'),
    'STOCH_K': latest.get('STOCH_K'),
    'STOCH_D': latest.get('STOCH_D'),
    'STOCHRSI_K': latest.get('STOCHRSI_K'),
    'MACD': latest.get('MACD'),
    'MACD_signal': latest.get('MACD_signal'),
    'MACD_histogram': latest.get('MACD_Histogram'),
    'ADX': latest.get('ADX'),
    'PLUS_DI': latest.get('PLUS_DI'),
    'MINUS_DI': latest.get('MINUS_DI'),
    'BB_upper': latest.get('Upper Band'),
    'BB_lower': latest.get('Lower Band'),
    'BB_middle': latest.get('Middle Band'),
    'ATR': latest.get('ATR'),
    'ATR_percent': (latest.get('ATR', 0) / latest['close'] * 100) if latest['close'] > 0 else None,
    'Volume': latest.get('volume'),
    'Volume_MA': df['volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else None,
    'Ichimoku_Tenkansen': latest.get('tenkan_sen'),
    'Ichimoku_Kijunsen': latest.get('kijun_sen'),
    'Ichimoku_SenkouA': latest.get('senkou_span_a'),
    'Ichimoku_SenkouB': latest.get('senkou_span_b'),
    'VWAP': latest.get('VWAP'),
    'Chandelier_Exit_Long': latest.get('CE_Long_Stop'),
    'Chandelier_Exit_Short': latest.get('CE_Short_Stop'),
    'SMA_20': latest.get('SMA_20'),
    'SMA_50': latest.get('SMA_50'),
    'EMA_10': latest.get('EMA_10'),
    'Pattern': latest.get('Pattern'),
    'Pattern_Strength': latest.get('Pattern_Strength'),
    'Pattern_Type': latest.get('Pattern_Type'),
    'Smart_Money_Confirmation': latest.get('Smart_Money_Confirmation'),
    'Smart_Money_Confidence': latest.get('Smart_Money_Confidence'),
    'ML_Confirmation': latest.get('ML_Confirmation'),
    'ML_Confidence': latest.get('ML_Confidence'),
    'Signal_Score': total_score,  # from calculate_base_signal
}

# Filter out None values to keep JSON clean
features_dict = {k: v for k, v in features_dict.items() if pd.notna(v)}

# Then, in signal_data:
signal_data = {
    'signal_id': signal_id,
    'pair': pair,
    'signal': signal,
    'price': entry_price,
    'confidence': confidence,
    'targets': targets,
    'stop_loss': stop_loss,
    'leverage': leverage,
    'features_json': json.dumps(features_dict, default=str),  # <-- ADD THIS
    'timestamp': time.time(),
    'status': 'SENT',
    'telegram_message_id': msg_id,
    'cornix_response_json': None,
    'pnl': 0.0
}
```

### 2. Verify `SignalRegistryDB.set_signal()` correctly stores JSON

The existing method already handles `features_json`. No change needed, but verify the field type is `TEXT` (it is).

### 3. Add missing indicator calculations (if needed)

Check `technical_indicators.py` or Rust batch processor to ensure all the above indicators are actually computed for each pair before signal generation. If any are missing, add them.

### 4. Add test validation

After deploying, run a quick check:

```python
from signal_registry_db import SignalRegistryDB
db = SignalRegistryDB()
all_signals = db.get_all()
sample = list(all_signals.values())[0]
assert sample.get('features_json') not in (None, '{}', {})
features = json.loads(sample['features_json'])
print(f"Stored {len(features)} features for {sample['pair']}")
```

## Risk Assessment

- **Low risk**: We're only adding data to existing `features_json` column; no schema changes.
- **Performance impact**: Negligible (JSON serialization of ~30 float values per signal).
- **Storage**: ~500 bytes per signal × 30 signals/hour ≈ 15KB/hour, manageable.
- **Migration**: Not required — new signals will have features immediately. Old signals can be backfilled if needed (separate task).

## Verification

1. Generate 1–2 new signals after code change.
2. Query `signal_registry.db` and confirm `features_json` contains non-empty JSON with expected keys.
3. Compare a winner and loser: extract indicator values and confirm they differ as expected.
4. Document success and close any prior tickets about missing features.

## Implementation Notes

- Ensure all NaN/NaT values are either converted to `None` (JSON null) or finite numbers before JSON dump to avoid serialization errors.
- Keep field names consistent with `signal_generator.py` variable names.
- Do not block signal generation if JSON serialization fails — log error and continue with empty features to maintain uptime.

---

**Bottom line:** With this fix, we will finally have the full technical context for every signal, enabling data-driven refinement of the confidence algorithm and systematic root-cause analysis of losing trades.