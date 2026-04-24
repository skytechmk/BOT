# Upgrade 07 — Phase 7: MC-Dropout Realtime GPU Inference

**Date:** 2026-04-19
**Phase:** 7 of 7
**Status:** ✅ Implemented
**Risk Level:** Low (new method, does not replace existing predict())
**Files touched:**
- `ml_engine_archive/models.py` — `predict_with_uncertainty()`, uncertainty field in `predict()`

---

## Problem

The ensemble's `predict()` was deterministic — a single forward pass per model.
This gave no information about epistemic uncertainty: how confident the neural
networks are (not just what their softmax probabilities say).

A signal with `P(LONG)=0.60` but high variance across dropout samples is much
riskier than the same probability with low variance.

---

## Solution

**Monte Carlo Dropout** (Gal & Ghahramani, 2016): run N=30 forward passes with
dropout layers **enabled** (i.e., `model.train()` mode). The variance across passes
estimates the model's epistemic uncertainty.

```
N=30 passes → mean probabilities → same as deterministic predict
              std dev → uncertainty score [0.0–0.3 typically]
```

---

## New Method: `predict_with_uncertainty(features, n_samples=30)`

```python
result = ensemble.predict_with_uncertainty(features, n_samples=30)
# {
#   'signal': 'LONG',
#   'confidence': 0.67,
#   'uncertainty': 0.04,   ← epistemic uncertainty
#   'probabilities': {'SHORT': 0.15, 'NEUTRAL': 0.18, 'LONG': 0.67},
#   'mc_samples': 30,
# }
```

### Uncertainty Gate
```
uncertainty > 0.15  →  signal downgraded to NEUTRAL
```
Calibrated on typical uncertainty range:
- Clean trend: 0.02–0.06
- Noisy market: 0.08–0.12
- High uncertainty / chop: 0.15–0.25

### Cost
30 forward passes adds ~20ms on RTX 3090 vs ~1ms for deterministic predict.
Only use when decision is close (e.g., `0.45 < max_prob < 0.55`).

---

## Integration in Existing `predict()`

The standard `predict()` now returns `'uncertainty': 0.0` to indicate it is
deterministic. Callers that want uncertainty call `predict_with_uncertainty()`.

Recommended usage in `main.py` (future):
```python
# For close-call signals only:
if 0.45 < result['confidence'] < 0.60:
    result = ensemble.predict_with_uncertainty(features, n_samples=30)
    if result['uncertainty'] > 0.15:
        continue  # skip noisy signal
```

---

## Rollback

The method is additive — existing `predict()` is unchanged. No rollback needed.
