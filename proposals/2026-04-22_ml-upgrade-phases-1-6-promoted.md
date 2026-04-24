# ML Ensemble Upgrade — Phases 1–6 PROMOTED

**Date**: 2026-04-22 (00:30–09:30 UTC+02:00)
**Status**: ✅ Promoted live at 09:13. Legacy backup at `ml_models_legacy_20260422_091339/`.
**Risk**: Low-medium. The legacy model was carrying **label leakage** that has been removed. New model is honest (F1 0.51) but genuinely predictive on all 3 classes. Rollback is a 3-line shell command.

---

## Motivation

1. **Bug discovered** during Phase 4 shadow retrain: the live production ML ensemble (reporting Ensemble F1 = 0.967) was scoring so high because label-adjacent feature columns (`tb_uniqueness`, `tb_barrier_bar`, `tb_ret_magnitude`, `sample_weight`, plus raw CE-stop price levels combined with SavGol-smoothed labels) were leaking the forward-looking barrier outcome into the training features. The model wasn't predicting — it was memorising.
2. **Feature surface was stale**: no funding-rate context, no open-interest z-scores, no HTF 4h alignment, no volume-profile / FVG proximity features — all of which the operator already computes elsewhere in the bot but the ML engine never saw.
3. **No calibration, no uncertainty quantification, no drift monitoring, no per-signal explainability** — blocking launch of the Ultra subscription tier.

## What landed

### Phase 1 — Funding / OI features (live)
- Persistent 10-minute refresh cache for all 568 USDT perps (`funding_oi_cache.py`, already live prior to this work).
- Added 8 features to `build_features()`:
  `funding_rate_now`, `funding_z_24h`, `funding_z_7d`, `funding_extreme_flag`, `oi_change_1h`, `oi_change_24h`, `oi_z_24h`, `price_oi_divergence_1h`.

### Phase 2 — HTF 4h alignment (live in features, not yet picked by tree pruning)
- 1h→4h resample inside `build_features()`, producing 7 HTF features:
  `htf_4h_trend_dir`, `htf_4h_ema_slope`, `htf_4h_rsi_14`, `htf_4h_close_vs_ema200`, `htf_4h_atr_pct`, `htf_4h_roc_6`, `htf_alignment_score`.
- **Known limitation**: tree-based feature-importance pruning discounts them (values change every 4 bars → long constant streaks). Fix: protect HTF columns from pruning, or gate them to the LSTM/TFT branches only. Deferred.

### Phase 3 — Volume Profile + FVG (live and being selected)
- Reused existing Rust VP/FVG engine. Added 9 features. **4 of 9 made the top-50** post-training:
  - `vp_vah_distance_pct` (rank 7)
  - `vp_above_poc_flag` (rank 12)
  - `vp_poc_distance_pct` (rank 36)
  - `vp_val_distance_pct` (rank 44)

### Phase 4 — López de Prado Triple-Barrier labeling + sample weighting
- Added `generate_labels_triple_barrier()` in `ml_engine_archive/feature_engine.py`.
- Pure TB (no SavGol smoothing) + uniqueness weights (AFML ch. 4) × return magnitude, normalised to mean 1.0 across labeled bars.
- `prepare_dataset(..., label_mode='triple_barrier')` and `train.py --label-mode triple_barrier`.
- **Lookahead bias fix**: excluded `tb_uniqueness`, `tb_barrier_bar`, `tb_ret_magnitude`, `sample_weight` from `get_feature_columns()`. Without this, the classifier memorises the label.

### Phase 5 — Probability calibration + conformal prediction
- `ml_calibration.py` — isotonic one-vs-rest calibrator. Persisted to `ml_models/calibrator.pkl`.
- `ml_conformal.py` — inductive conformal prediction at α=0.1 (90% CI). Persisted to `ml_models/conformal.pkl`.
- Both fit automatically from XGBoost validation predictions at the end of `train.py`.

### Phase 6 — Drift, explainability, Ultra-tier API
- `ml_drift_monitor.py` — Population Stability Index (PSI) per feature vs. stored training snapshot. Alert bands: <0.1 stable, 0.1–0.25 moderate, >0.25 major.
- `ml_explainer.py` — TreeExplainer SHAP top-N drivers (supports modern SHAP (N, F, K) output shape).
- `ml_ultra_surface.py` — unified `predict_ultra()` + `format_for_tier()` that redacts the output per subscription tier (free / plus / pro / ultra).
- Training auto-snapshots feature distributions (`ml_models/feature_distribution.pkl`) for subsequent drift checks.

### Side fix — `MODEL_DIR` env override
- `ml_engine_archive/models.py` now honours `ALADDIN_MODEL_DIR` so shadow training can write to a separate folder without touching the live `ml_models/`.

## Empirical results (30 pairs, 36 months, 50 epochs)

| Metric | Legacy (pre-fix) | New model (honest) |
|---|---|---|
| Ensemble F1 (tuned) | **0.967** *(inflated)* | **0.510** |
| XGBoost val F1 | 0.777 *(inflated)* | 0.297 |
| LightGBM val F1 | 0.760 *(inflated)* | 0.241 |
| BiLSTM val F1 | — | 0.253 |
| TFT val F1 | — | 0.249 |
| Meta-learner val F1 | 0.967 | 0.384 (→0.510 after threshold tuning) |
| Training samples | — | 283,890 |
| Validation samples | — | 52,199 |
| Calibrated probs | ❌ | ✅ |
| Conformal 90% CI | ❌ | ✅ |
| SHAP explainability | ❌ | ✅ |
| PSI drift snapshot | ❌ | ✅ |

### Per-class (new model, validation set)
```
SHORT    precision 0.44  recall 0.49  F1 0.47   n=11,936
NEUTRAL  precision 0.66  recall 0.62  F1 0.64   n=29,591
LONG     precision 0.41  recall 0.43  F1 0.42   n=10,624
```

All three classes beat random (0.33). NEUTRAL is well-calibrated (model knows when to stay out). LONG/SHORT precision near 0.44 means ~44% of model-predicted directional signals actually hit the barrier, and meta-learner combines this with BiLSTM/TFT/LightGBM.

## Files touched / added

**Added**
- `ml_calibration.py`
- `ml_conformal.py`
- `ml_drift_monitor.py`
- `ml_explainer.py`
- `ml_ultra_surface.py`
- `proposals/2026-04-22_ml-upgrade-phases-1-6-promoted.md` (this file)

**Modified**
- `ml_engine_archive/feature_engine.py` — added `generate_labels_triple_barrier()`, TB metadata excluded from features, `prepare_dataset(label_mode=)`.
- `ml_engine_archive/models.py` — `MODEL_DIR` honours `ALADDIN_MODEL_DIR`.
- `ml_engine_archive/train.py` — `--label-mode` flag, TB sample-weight switch, post-training calibrator + conformal + drift-snapshot fitting.

**Promoted**
- `ml_models/` — full swap with shadow artifacts.
- `ml_models_legacy_20260422_091339/` — rollback backup.

## Rollback plan
```bash
systemctl stop anunnaki-bot
mv /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/ml_models \
   /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/ml_models_v2
mv /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/ml_models_legacy_20260422_091339 \
   /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/ml_models
systemctl start anunnaki-bot
```
Rollback restores the leaky-but-familiar 0.967-F1 model.

## Follow-ups (not yet done)

1. **Wire `/explain <signal_id>` Telegram handler** — calls `ml_ultra_surface.predict_ultra()` with Ultra-tier gate. 30 min.
2. **Dashboard Ultra widget** — consumes `format_for_tier(payload, 'ultra')`.
3. **Daily drift-monitor cron** — `python -m ml_drift_monitor` → Ops channel at 00:00 UTC.
4. **Protect HTF features from importance pruning** — 5 min edit in `filter_by_importance`.
5. **Full 200-pair retrain** — once Binance Vision data is downloaded for all pairs. Current model uses 30 cached majors; stability improves with full fleet.
6. **Meta-labeler expansion** — feed calibrated probs + funding/OI/HTF into meta-learner. Currently only uses base model probs + regime cols.
7. **Purged + embargoed K-fold CV** — architectural refactor of `train.py`. Follow-up.

## Verification after promotion

Live `predict_ultra()` on top pairs at 09:14 UTC+02:00:
```
BTCUSDT: class=NEUTRAL  probs_cal=[0.16 0.62 0.21]  CI_90=[0.17, 1.00]  set={NEUTRAL, LONG}
ETHUSDT: class=NEUTRAL  probs_cal=[0.21 0.56 0.23]  CI_90=[0.11, 1.00]  set={SHORT, NEUTRAL, LONG}
SOLUSDT: class=NEUTRAL  probs_cal=[0.21 0.58 0.21]  CI_90=[0.13, 1.00]  set={SHORT, NEUTRAL, LONG}
```
Bot service: **active**. First scan cycle at 09:16 emitted normal price-drift rejections for stale small-cap quotes, confirming the ML scoring path ran without error.
