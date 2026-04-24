# Upgrade 04 — Phase 4: Meta-Labeler (Shadow Mode)

**Date:** 2026-04-19
**Phase:** 4 of 7
**Status:** ✅ Implemented — Shadow Mode Active
**Risk Level:** Low (shadow mode only — does not modify signals)
**Files touched:**
- `ml_engine_archive/meta_labeler.py` ← NEW

---

## What Is Meta-Labeling?

Technique from López de Prado's "Advances in Financial Machine Learning" (Chapter 3).

```
Primary Model  →  direction (LONG / SHORT)
Meta-Labeler   →  P(this specific signal wins)
```

The meta-labeler does NOT predict direction — it learns to filter bad signals from the
primary model. The same signal that "looks like a LONG" could be a winner 70% of the time
in CHOP regimes and only 40% in PARABOLIC regimes. The meta-labeler learns this.

---

## Architecture

- **Model**: LightGBM binary classifier (log-loss, AUC metric)
- **Class balance**: `scale_pos_weight = n_neg / n_pos` (auto-handles WIN/LOSS imbalance)
- **Input features per signal**:
  - All 98 production features at signal time
  - `primary_confidence` (ensemble probability)
  - `signal_is_long` (1/0 binary)
  - `p_win_prior` (previous meta-labeler estimate if available)
- **Output**: `p_win ∈ [0, 1]`

---

## Shadow Mode (Current)

The meta-labeler is in **shadow mode** until 200+ signal outcomes are recorded.

In shadow mode:
- Every fired signal is logged to `ml_models/meta_predictions.jsonl`
- `p_win = 0.5` (neutral) returned — does NOT block any signals
- After 200+ outcomes, call `train_from_shadow_log()` to train the binary classifier

```python
from ml_engine_archive.meta_labeler import get_meta_labeler, train_from_shadow_log

# At signal fire time:
ml = get_meta_labeler()
p_win = ml.predict_proba(features_at_signal_time)
ml.log_prediction(pair, signal, p_win, confidence, feature_snapshot)

# When signal closes:
ml.log_outcome(pair, signal, outcome="TP")  # or "SL" / "EXPIRED"

# After 200+ outcomes, retrain:
train_from_shadow_log(min_samples=200)
```

---

## Activation Path (Future)

Once trained:
1. Set `ml._is_shadow = False` to enable gating
2. Signals with `p_win < ml.threshold` (default 0.55) are rejected
3. Use `p_win` to scale position size: `size_mult = max(0.5, p_win / 0.6)`

---

## Monitoring

```python
from ml_engine_archive.meta_labeler import get_meta_labeler
stats = get_meta_labeler().get_shadow_stats()
# {'logged': 45, 'with_outcome': 32, 'win_rate': 0.59, 'avg_p_win': 0.50, 'shadow_mode': True}
```

Log path: `ml_models/meta_predictions.jsonl`

---

## Rollback
Not needed — shadow mode is purely additive and does not affect any signal flow.
