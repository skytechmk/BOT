# Proposal: ML Ensemble Hard Gate (Option B)

**Date:** 2026-04-14  
**Status:** PENDING — do not apply until backtested  
**Priority:** Medium  
**Risk level:** Medium-High (signal volume impact ~30% reduction)

---

## Context

The stacking ensemble (BiLSTM + TFT + XGBoost + LightGBM, F1=0.586) is currently
wired as **Option A**: a soft SQI scoring bonus (−5 to +8 pts in Factor 11).
This proposal defines **Option B**: using ensemble confidence as a **hard gate**
that can outright reject signals, independently of SQI.

Option A was implemented on 2026-04-14 and is live. Option B is to be implemented
only after we have sufficient live-signal data to validate the ensemble's production
accuracy (recommended: ≥100 closed signals with ML factor logged).

---

## Proposed Change

### Gate Logic (in `main.py`, after SQI gate, before Cornix formatting)

```python
# ── ML Ensemble Hard Gate (Option B) ─────────────────────────────
# Requires: ensemble confidence ≥ ML_HARD_GATE_THRESHOLD in signal direction.
# If ensemble is confident in the OPPOSITE direction, signal is rejected.
# If ensemble is NEUTRAL or unavailable, signal passes (no blocking).
ML_HARD_GATE_THRESHOLD = 0.45   # tunable via QPSO

if sqi_result['factors'].get('ml_ensemble', {}).get('value') not in (None, 'NEUTRAL_OR_NA'):
    ml_val = sqi_result['factors']['ml_ensemble']['value']   # e.g. "SHORT@0.61"
    ml_sig, ml_conf_str = ml_val.split('@')
    ml_conf = float(ml_conf_str)
    ml_aligned = (ml_sig == 'LONG' and final_signal == 'LONG') or \
                 (ml_sig == 'SHORT' and final_signal == 'SHORT')

    if not ml_aligned and ml_conf >= ML_HARD_GATE_THRESHOLD:
        log_message(
            f"🚫 Signal Rejected [{pair}]: ML ensemble OPPOSES {final_signal} "
            f"(ensemble={ml_val}, gate={ML_HARD_GATE_THRESHOLD})"
        )
        return
```

### Placement

After the SQI gate (line ~462 in `main.py`) and before the Cornix format block.
The ML factor value is already computed inside `calculate_sqi()` and available
in `sqi_result['factors']['ml_ensemble']['value']`.

---

## Scoring Impact Analysis

Based on ensemble metadata (F1=0.586, val_samples=349,908):

| Ensemble says | Signal says | Conf | Action |
|---|---|---|---|
| LONG | LONG | ≥0.45 | Pass (already gets +5/+8 SQI bonus) |
| SHORT | LONG | ≥0.45 | **REJECT** |
| SHORT | LONG | <0.45 | Pass (soft penalty only via Option A) |
| NEUTRAL | anything | any | Pass |

Estimated rejection rate at threshold=0.45: ~25–35% of signals that pass SQI gate.

---

## Prerequisites Before Implementing

1. **≥100 closed signals** with `sqi_ml_ensemble` logged in `feature_snapshot`
   (available after Option A is live for ~2–4 weeks at current signal rate)

2. **Backtest the gate**: query `signal_registry.db` for:
   ```sql
   SELECT outcome, AVG(pnl), COUNT(*)
   FROM signals
   WHERE json_extract(features, '$.sqi_ml_ensemble') < -2   -- ML opposed with high conf
   GROUP BY outcome
   ```
   If win rate for "ML opposed" signals is ≤ 40%, the gate is validated.

3. **QPSO optimise** `ML_HARD_GATE_THRESHOLD` (range 0.38–0.60) using
   `qpso_optimizer.py` — add it to `PARAM_BOUNDS` alongside `sqi_gate`.

4. **A/B shadow mode first**: log rejections without actually blocking for 1 week,
   compare hypothetical P&L vs actual. Only activate if ≥5% expectancy improvement.

---

## Tunable Parameters

| Parameter | Default | Range | Notes |
|---|---|---|---|
| `ML_HARD_GATE_THRESHOLD` | 0.45 | 0.38 – 0.60 | Lower = more rejections |
| `ML_NEUTRAL_PASSES` | True | bool | Whether NEUTRAL ensemble passes |
| `ML_GATE_MIN_SQI` | 65 | 50 – 80 | Only apply gate if SQI already passes |

These can be added to `PARAM_BOUNDS` in `qpso_optimizer.py` for auto-tuning.

---

## Implementation Files

| File | Change |
|---|---|
| `main.py` | Add gate block after line ~462 (post SQI gate) |
| `constants.py` | Add `ML_HARD_GATE_THRESHOLD = 0.45` |
| `qpso_optimizer.py` | Add `ml_gate_threshold` to `PARAM_BOUNDS` |

---

## Rollback Plan

Set `ML_HARD_GATE_THRESHOLD = 0.0` in `constants.py` — gate becomes a no-op
since `ml_conf >= 0.0` is always True only for the aligned branch check.
Or simply comment out the gate block. No DB schema changes required.

---

## Related

- Option A implemented: `signal_quality.py` Factor 11, SQI v3 max=152
- Models: `ml_models/bilstm_attention_best.pt`, `tft_block_best.pt`, `xgboost_best.json`
- QPSO: `qpso_optimizer.py` — run `run_weekly_optimisation()` to tune threshold
