# Upgrade 05 — Phase 5: Regime-Conditional Ensemble Routing

**Date:** 2026-04-19
**Phase:** 5 of 7
**Status:** ✅ Implemented (active on next retrain)
**Risk Level:** Low (training-only architecture change)
**Files touched:**
- `ml_engine_archive/models.py` — regime cols injected into meta-learner, predict()

---

## Problem

The stacking meta-learner combined 4 sub-model outputs (12 probability features)
without knowing what market regime the signal occurred in. The same weights were
applied during PARABOLIC trending moves as in CHOP consolidation — two regimes
where entirely different sub-models are likely to dominate.

---

## Solution

Append the regime one-hot columns directly to the meta-learner's input features.
The XGBoost meta-learner then learns: "in CHOP regime, trust XGBoost more; in
PARABOLIC, trust TFT more." This is regime-conditional stacking.

```
Meta-features before: 12 cols (4 models × 3 classes)
Meta-features after:  12 + 4 = 16 cols (+ regime_parabolic/clean_trend/chop/compress)
```

---

## Changes

### `_build_meta_learner()` — regime feature extraction
```python
_regime_cols = ['regime_parabolic', 'regime_clean_trend', 'regime_chop', 'regime_compress']
_regime_idxs = [feature_cols.index(c) for c in _regime_cols if c in feature_cols]
if _regime_idxs:
    regime_feats_val = X_val_scaled[-n_neural:][:, _regime_idxs]
    meta_features = np.hstack([lstm_probs_val, tft_probs_val, xgb_raw, lgb_raw, regime_feats_val])
```
`_regime_idxs` stored in `metadata['regime_feature_indices']` for use at inference.

### `predict()` and `predict_with_uncertainty()` — regime injection
```python
_regime_idxs = self.metadata.get('regime_feature_indices', [])
if _regime_idxs:
    _regime_feats = features_scaled[-1, _regime_idxs]
    meta_input = np.hstack([lstm_probs, tft_probs, xgb_probs, lgb_probs, _regime_feats]).reshape(1, -1)
```
Graceful degradation: if feature_cols don't include regime (e.g., first training run),
falls back to 12-feature meta input silently.

---

## Expected Impact

- Meta-learner learns regime-specific sub-model trust
- CHOP regime: XGBoost/LGB (tree models better at mean-reversion) gets higher weight
- PARABOLIC/CLEAN_TREND: BiLSTM/TFT (sequential models) get higher weight
- Estimated F1 lift: +0.02–0.04 vs flat stacking

---

## Rollback
Remove regime feature extraction from `_build_meta_learner` and `predict()`.
Set `metadata['regime_feature_indices'] = []`. Retrain required.
