# Upgrade 02 — Phase 2: Missing Production Features in ML

**Date:** 2026-04-19
**Phase:** 2 of 7 (master proposal: `/proposals/2026-04-19_ml-accuracy-and-long-bias-fix.md`)
**Status:** ✅ Implemented (active on next retrain)
**Risk Level:** Low (training-only change; no live logic modified)
**Files touched:**
- `ml_engine_archive/macro_context.py` ← NEW
- `ml_engine_archive/feature_engine.py` ← integrate macro_context
- `ml_engine_archive/train.py` ← inject BTC correlation per pair

---

## Problem Statement

The ML ensemble (BiLSTM, TFT, XGBoost, LightGBM) was trained on 85 features derived
purely from OHLCV candles. However, the live bot makes signal decisions using additional
context that was **never passed to the ML model**:

| Live Signal Context | Was in ML Training? |
|---|---|
| Market regime (PARABOLIC / CHOP / COMPRESSION) | ❌ |
| Fair Value Gaps (count + distance) | ❌ |
| Stop-hunt detection (wick+volume pattern) | ❌ |
| Liquidity magnet distances (swing high/low) | ❌ |
| Trading session (prime / US equity open) | ❌ |
| BTC rolling correlation | ❌ |
| Funding rate, OI change | ❌ (Phase 2b — needs historical API) |

Training on a different feature distribution than inference = **train/serve skew**.
The model was blind to the context that shapes the live signal quality.

---

## Root Cause

Feature engineering was OHLCV-only. The production context features existed in
`predator.py`, `reverse_hunt.py`, `trading_utilities.py`, and `main.py` but were
never ported to `ml_engine_archive/feature_engine.py`.

---

## Changes Made

### New File: `ml_engine_archive/macro_context.py`

New module adding 20 production-context features computable from OHLCV + timestamps:

| Group | Features | Derivation |
|---|---|---|
| Regime | `regime_parabolic`, `regime_clean_trend`, `regime_chop`, `regime_compress`, `regime_atr_ratio`, `regime_clarity` | ATR(7)/ATR(21) ratio + EMA9/EMA21 clarity |
| FVG | `fvg_long_count`, `fvg_short_count`, `fvg_nearest_dist_pct` | OHLCV 3-bar gap pattern |
| Stop Hunt | `stop_hunt_long_proxy`, `stop_hunt_short_proxy` | Wick>3×body + swing sweep + vol surge |
| Swing Liquidity | `liq_dist_above_pct`, `liq_dist_below_pct`, `liq_cluster_score`, `liq_asymmetry` | Rolling swing high/low |
| Session | `is_prime_session`, `is_us_equity_open`, `hour_sin`, `hour_cos` | UTC timestamp |
| Correlation | `btc_corr_30d` | 720-bar rolling Pearson corr vs BTCUSDT |

### `ml_engine_archive/feature_engine.py`

- Added import of `add_macro_context_features` from `macro_context` (with fallback)
- Called at end of `build_features()` — all 20 features added per bar
- Feature count: **85 → 98** (after `get_important_features` pruning: top 50 selected)

### `ml_engine_archive/train.py`

- Pre-computes BTC returns from `BTCUSDT` in `raw_data` if present
- Injects real `btc_corr_30d` values per pair BEFORE `prepare_dataset()` is called
- Falls back to placeholder `0.5` if BTC is not in the training universe

---

## What Phase 2b Defers

Historical funding rate and OI require Binance Futures history API:
- `GET /fapi/v1/fundingRate` (funding, 8h granularity, 1000 rows/call)
- `GET /futures/data/openInterestHist` (OI, various intervals)

These will be added to `data_downloader.py` in a future upgrade.

---

## Validation

```bash
cd /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA
python3 -c "
import sys; sys.path.insert(0, '.')
from ml_engine_archive.feature_engine import build_features, get_feature_columns
import pandas as pd, numpy as np
idx = pd.date_range('2025-01-01', periods=600, freq='1h', tz='UTC')
rng = np.random.default_rng(42); c = rng.standard_normal(600).cumsum() + 100
df = pd.DataFrame({'open':c,'high':c+0.5,'low':c-0.5,'close':c,'volume':rng.uniform(500,2000,600)},index=idx)
result = build_features(df)
print(len(get_feature_columns(result)), 'features — expect 98')
"
```

Expected output: `98 features — expect 98`

---

## Expected Impact

- **Train/serve skew eliminated** — model now sees regime + FVG + stop-hunt + session at train time
- **Better SHORT signal accuracy** — regime_chop and stop_hunt features are correlated with mean-reversion setups
- **Session-aware predictions** — US equity open correlates with vol spikes; off-session = more noise
- **BTC correlation** — high-beta pairs vs low-beta pairs treated differently by the model

Impact will be visible after the next retrain. Target: F1 0.54 → 0.60+.

---

## Rollback

Remove the `add_macro_context_features` call from `feature_engine.py:321`:
```python
# Comment out these 3 lines:
# if _MACRO_CONTEXT_AVAILABLE:
#     df = add_macro_context_features(df, pair=pair)
```
Retrain is required either way; the running bot is not affected.
