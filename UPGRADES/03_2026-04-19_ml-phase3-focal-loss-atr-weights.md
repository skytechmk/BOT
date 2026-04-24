# Upgrade 03 — Phase 3: Focal Loss γ=2.0 + ATR Sample Weights

**Date:** 2026-04-19
**Phase:** 3 of 7
**Status:** ✅ Implemented (active on next retrain)
**Risk Level:** Low (training-only)
**Files touched:**
- `ml_engine_archive/models.py` — gamma bump, sample_weight params
- `ml_engine_archive/train.py` — ATR weight computation + propagation

---

## Problem

1. **NEUTRAL class dominance** — cross-entropy (and low-gamma focal loss) allows the model to
   achieve low loss by predicting NEUTRAL for ambiguous bars. Result: LONG/SHORT recall is poor.
2. **Flat sample weighting** — all bars in training had equal weight regardless of volatility.
   A 0.1% ATR bar teaches the model nothing useful about signal quality. A 3% ATR bar is where
   real TP/SL distances live.

---

## Changes

### `models.py` — FocalLoss gamma 1.5 → 2.0
```python
# Before
criterion = FocalLoss(alpha=class_weights, gamma=1.5)

# After
criterion = FocalLoss(alpha=class_weights, gamma=2.0)
```
`gamma=2.0` is the standard value from the original RetinaNet paper. Easy-to-classify bars
(high confidence NEUTRAL) have their loss down-weighted more aggressively, forcing the model
to focus on hard LONG/SHORT examples.

### `models.py` — `train_xgboost` + `train_lightgbm`
Added `sample_weight=None` parameter, passed directly to `model.fit()`.

### `train.py` — ATR weight computation
```python
# Scale 0.5–2.0 so high-ATR bars get 4× the weight of low-ATR bars
atr_weight_raw = (0.5 + 1.5 * atr_rank).astype(np.float32)
```
- Computed from `atr_pct_rank` column (percentile rank of ATR, 0→1)
- Stored as `atr_weights_train` in the `shared` dict
- Used in `_train_neural_worker`: multiplies the class-frequency sampler weights
- Passed to `_train_tree_worker`: used as `sample_weight` in XGBoost and LightGBM

---

## Expected Impact

| Metric | Before | Expected |
|---|---|---|
| NEUTRAL precision | Very high (easy to predict) | Lower (harder to cheat) |
| LONG/SHORT recall | Low | Higher |
| Macro F1 | 0.54 | 0.57–0.62 |

---

## Rollback
- `gamma=2.0` → revert to `gamma=1.5` in `train_neural_model`
- Remove `sample_weight=...` from XGBoost/LightGBM fit calls
- Remove `atr_weights_train` from `shared` dict
- Retrain required
