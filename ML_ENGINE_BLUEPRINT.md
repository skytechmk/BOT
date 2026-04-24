# Aladdin ML Engine — Blueprint

## 1. Overview

Ensemble ML system trained on 6 months of Binance Vision historical data for 30 top futures pairs.  
Replaces the broken `multi_timeframe_ml_system.py` + `institutional_ml_system.py` stubs.

**Goal**: Predict LONG / SHORT / NEUTRAL with calibrated confidence [0–1] for each pair on 15m timeframe.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LIVE SIGNAL FLOW                      │
│                                                         │
│  main.py → fetch 15m OHLCV → feature_engine.py (67 ft) │
│         → predictor.py → StackingEnsemble.predict()     │
│         → {signal, confidence, probabilities}           │
│         → replaces get_multi_timeframe_prediction()     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   TRAINING PIPELINE                      │
│                                                         │
│  data_downloader.py                                     │
│    └─ Binance Vision (data.binance.vision)              │
│    └─ 30 pairs × 6 months × 15m = ~500K candles        │
│    └─ Parquet cache (ml_data/)                          │
│                     ↓                                   │
│  feature_engine.py                                      │
│    └─ 67 numeric features (see §4)                      │
│    └─ ATR-based forward labels (TP/SL race, 12 bars)    │
│                     ↓                                   │
│  models.py                                              │
│    ├─ BiLSTM + Attention    (sequential patterns)       │
│    ├─ TFT                   (temporal fusion + attn)    │
│    ├─ XGBoost GPU           (feature interactions)      │
│    ├─ LightGBM              (diversity / regularized)   │
│    └─ Meta-Learner          (logistic stacking)         │
│                     ↓                                   │
│  ml_models/  (saved artifacts)                          │
│    ├─ bilstm_attention_best.pt                          │
│    ├─ tft_block_best.pt                                 │
│    ├─ xgboost_best.json                                 │
│    ├─ lightgbm_best.pkl                                 │
│    ├─ scaler.pkl                                        │
│    ├─ meta_learner.pkl                                  │
│    ├─ feature_cols.pkl                                  │
│    └─ metadata.json                                     │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Data Pipeline

### Source
- **Binance Vision** (`data.binance.vision/data/futures/um/`)
- Free, no auth, no rate limits
- Monthly ZIP archives + daily ZIPs for recent data

### Pairs (top 30 by 24h volume)
```
BTCUSDT  ETHUSDT  BNBUSDT  SOLUSDT  XRPUSDT
DOGEUSDT ADAUSDT  AVAXUSDT LINKUSDT DOTUSDT
MATICUSDT UNIUSDT LTCUSDT  ATOMUSDT NEARUSDT
APTUSDT  ARBUSDT  OPUSDT   FILUSDT  SUIUSDT
SEIUSDT  INJUSDT  FETUSDT  WIFUSDT  PEPEUSDT
ONDOUSDT RENDERUSDT AAVEUSDT MKRUSDT TIAUSDT
```

### Storage
- Raw: `ml_data/raw/{PAIR}/{TF}/{YYYY-MM}.parquet`
- Combined: `ml_data/combined/{PAIR}_{TF}.parquet`
- ~500K candles total (~150MB parquet)

### Timeframe
- Primary: **15m** (matches bot's ENTRY_TIMEFRAMES)
- Sequence length: **48 bars** (12 hours of context for LSTM/TFT)
- Forward label window: **12 bars** (3 hours)

---

## 4. Feature Engineering (67 features)

### Price & Momentum (12)
| Feature | Description |
|---------|-------------|
| `ret_1, ret_3, ret_5, ret_10, ret_20` | Period returns |
| `log_ret_1, log_ret_5` | Log returns |
| `body` | Candle body / open |
| `upper_wick, lower_wick` | Wick ratios |
| `candle_range` | (High - Low) / Close |
| `ema_200_slope` | 200 EMA slope (regime) |

### Trend (8)
| Feature | Description |
|---------|-------------|
| `close_vs_ema_9/21/50/100/200` | Price distance from EMAs |
| `sma_cross_20_50` | SMA 20/50 crossover ratio |
| `regime_bull` | Binary: close > EMA200 |
| `pair_encoded` | Pair hash (multi-pair model) |

### RSI & Stochastic (7)
| Feature | Description |
|---------|-------------|
| `rsi_7, rsi_14, rsi_21` | Multi-period RSI |
| `rsi_slope_5, rsi_divergence` | RSI momentum + divergence |
| `stoch_rsi_k, stoch_rsi_d` | Stochastic RSI |

### MACD (4)
| Feature | Description |
|---------|-------------|
| `macd, macd_signal, macd_hist` | MACD components |
| `macd_hist_slope` | Histogram momentum |

### Bollinger Bands (2)
| Feature | Description |
|---------|-------------|
| `bb_width` | Band width (volatility) |
| `bb_pct` | %B (position within bands) |

### ATR & Volatility (5)
| Feature | Description |
|---------|-------------|
| `atr_pct` | ATR as % of price |
| `atr_ratio_7_14` | Short/long ATR ratio |
| `volatility_10, volatility_20` | Realized volatility |
| `price_slope_5` | 5-bar price slope |

### ADX (4)
| Feature | Description |
|---------|-------------|
| `adx` | Average Directional Index |
| `plus_di, minus_di` | Directional Indicators |
| `di_diff` | DI+ minus DI- |

### Ichimoku (4)
| Feature | Description |
|---------|-------------|
| `close_vs_cloud` | Above/below/inside cloud |
| `cloud_width` | Span A - Span B normalized |
| `tk_cross` | Tenkan-Kijun cross distance |

### VWAP & TSI (4)
| Feature | Description |
|---------|-------------|
| `close_vs_vwap` | Distance from VWAP |
| `tsi, tsi_signal, tsi_hist` | True Strength Index |

### Volume (4)
| Feature | Description |
|---------|-------------|
| `volume_ratio` | Current / 20-bar avg volume |
| `volume_change` | Volume % change |
| `taker_buy_ratio` | Buy pressure ratio |
| `avg_trade_size` | Quote volume / trades |

### Structure (3)
| Feature | Description |
|---------|-------------|
| `dist_to_high_20, dist_to_low_20` | Distance to 20-bar extremes |
| `range_position_20` | Position within 20-bar range |

### Patterns (4)
| Feature | Description |
|---------|-------------|
| `doji` | Doji candle detection |
| `hammer` | Hammer pattern |
| `engulfing_bull, engulfing_bear` | Engulfing patterns |

### Time (6)
| Feature | Description |
|---------|-------------|
| `hour, day_of_week` | Raw time features |
| `hour_sin, hour_cos` | Cyclical hour encoding |
| `dow_sin, dow_cos` | Cyclical day encoding |

---

## 5. Label Generation

**ATR-based TP/SL Race** — realistic simulation of trade outcomes.

For each candle, simulate forward `12 bars` (3 hours on 15m):
- **LONG (+1)**: Price hits `entry + 2×ATR` before hitting `entry - 1.5×ATR`
- **SHORT (-1)**: Price hits `entry - 2×ATR` before hitting `entry + 1.5×ATR`
- **NEUTRAL (0)**: Neither TP nor SL hit within window

This produces a naturally imbalanced dataset (~30% LONG, 40% NEUTRAL, 30% SHORT).

---

## 6. Models

### 6.1 BiLSTM with Attention
- **Architecture**: 3-layer bidirectional LSTM (128 hidden) + scaled dot-product self-attention + BatchNorm + GELU
- **Input**: (batch, 48, 67) → sliding window of 48 bars × 67 features
- **Output**: 3-class logits (SHORT, NEUTRAL, LONG)
- **Strength**: Captures sequential dependencies, order flow patterns
- **Training**: AdamW + CosineAnnealingWarmRestarts, Focal Loss

### 6.2 Temporal Fusion Transformer (TFT)
- **Architecture**: GRN variable selection → 2-layer LSTM → 4-head self-attention → GRN output
- **Input**: Same as BiLSTM
- **Output**: 3-class logits
- **Strength**: Attention identifies which timesteps and features matter most
- **Training**: Same as BiLSTM, lower LR (5e-4)

### 6.3 XGBoost (GPU)
- **Architecture**: 1000 trees, max_depth=8, GPU-accelerated
- **Input**: Single feature vector (67 features) — no sequence context
- **Output**: 3-class probabilities
- **Strength**: Non-linear feature interactions, robust to noise
- **Training**: Early stopping on validation set

### 6.4 LightGBM
- **Architecture**: 1000 trees, max_depth=7, CPU
- **Input**: Same as XGBoost
- **Output**: 3-class probabilities
- **Strength**: Diversity (different tree algorithm), better regularization
- **Training**: Early stopping

### 6.5 Meta-Learner (Stacking Ensemble)
- **Architecture**: Logistic Regression on 12 meta-features (4 models × 3 class probabilities)
- **Input**: Concatenated probability outputs from all 4 base models
- **Output**: Final 3-class prediction + calibrated confidence
- **Strength**: Learns optimal weighting of each model's strengths

```
BiLSTM    → [P(short), P(neutral), P(long)]  ─┐
TFT       → [P(short), P(neutral), P(long)]  ─┤
XGBoost   → [P(short), P(neutral), P(long)]  ─┼→ Meta-Learner → Final Signal + Confidence
LightGBM  → [P(short), P(neutral), P(long)]  ─┘
```

---

## 7. Training Protocol

### Data Split
- **80% train / 20% validation** — strict time-series split (no future leakage)
- No shuffle — preserves temporal ordering

### Loss Function
- **Focal Loss** (γ=2.0) with inverse-frequency class weights
- Handles NEUTRAL class dominance without undersampling

### Optimization
- AdamW with weight decay 1e-4
- Cosine Annealing with Warm Restarts (T₀=10, T_mult=2)
- Gradient clipping at 1.0
- Early stopping (patience=8 epochs on macro F1)

### Metrics
- **Primary**: Macro F1-score (treats all classes equally)
- **Secondary**: Per-class precision/recall, accuracy

### Expected Performance
| Model | Val F1 (mini test) | Expected F1 (full) |
|-------|-------------------|-------------------|
| BiLSTM | 0.42 | 0.50–0.55 |
| TFT | 0.42 | 0.50–0.55 |
| XGBoost | 0.54 | 0.55–0.62 |
| LightGBM | 0.49 | 0.52–0.58 |
| **Ensemble** | **0.53** | **0.58–0.65** |

---

## 8. Integration with Main Bot

### Current Flow (broken)
```python
# main.py line 270
if MULTI_TF_ML_AVAILABLE:
    ml_pred = get_multi_timeframe_prediction(pair)  # ← feature mismatch, always fails
    if ml_pred and 'consensus' in ml_pred:
        ...
```

### New Flow (after training completes)
```python
# main.py — replace the broken MULTI_TF_ML section
from ml_engine.predictor import predict_signal, is_available as ML_ENGINE_AVAILABLE

if ML_ENGINE_AVAILABLE():
    ml_pred = predict_signal(df, pair)
    if ml_pred and 'consensus' in ml_pred:
        consensus = ml_pred['consensus']
        ml_signal_normalized = 'LONG' if consensus['signal'] == 'BUY' else 'SHORT'
        if ml_signal_normalized == final_signal.upper():
            ml_confidence = (ml_confidence + consensus['confidence']) / 2
        elif consensus['confidence'] > 0.75:
            ml_confidence *= 0.80
```

### No changes needed to:
- `signal_generator.py` (still generates base scores)
- `technical_indicators.py` (features are recalculated independently)
- `telegram_handler.py` (signal format unchanged)

---

## 9. Retraining Schedule

- **Auto-retrain**: Weekly (Sunday 03:00 UTC)
- **Incremental**: Download latest week of data, append to dataset, retrain
- **Fallback**: If training fails, keep previous model weights
- **Trigger**: Can also be triggered manually via `python3 -m ml_engine.train`

---

## 10. File Structure

```
ml_engine/
├── __init__.py           # Package marker
├── data_downloader.py    # Binance Vision downloader + parquet cache
├── feature_engine.py     # 67-feature builder + ATR label generator
├── models.py             # BiLSTM, TFT, XGBoost, LightGBM, StackingEnsemble
├── train.py              # CLI training script
└── predictor.py          # Live prediction API

ml_data/                  # Downloaded data (gitignored)
├── raw/{PAIR}/{TF}/      # Per-pair parquet cache
└── combined/             # Merged parquets

ml_models/                # Trained artifacts (gitignored)
├── bilstm_attention_best.pt
├── tft_block_best.pt
├── xgboost_best.json
├── lightgbm_best.pkl
├── scaler.pkl
├── meta_learner.pkl
├── feature_cols.pkl
└── metadata.json
```

---

## 11. Risk & Limitations

- **No forward-looking bias**: Time-series split, no shuffle, labels use future bars only for training
- **NEUTRAL dominance**: Handled by Focal Loss + class weights
- **Regime change**: Model trained on 6 months may not adapt to sudden regime shifts — weekly retrain mitigates
- **Feature drift**: Scaler fitted on historical data may mismatch live data — periodic re-standardization needed
- **Single timeframe**: 15m only — multi-timeframe fusion is a future enhancement
- **No order flow data**: Only OHLCV + taker buy ratio — no L2/L3 order book data

---

## 12. Current Status

| Step | Status |
|------|--------|
| Data download (30 pairs × 6 months) | ✅ Complete |
| Feature engineering (484K samples) | ✅ Complete |
| BiLSTM training | 🔄 In progress (epoch 5/50) |
| TFT training | ⏳ Pending |
| XGBoost training | ⏳ Pending |
| LightGBM training | ⏳ Pending |
| Meta-learner | ⏳ Pending |
| Wire into main.py | ⏳ After training |

**Monitor progress**: `tail -f ml_training.log`
