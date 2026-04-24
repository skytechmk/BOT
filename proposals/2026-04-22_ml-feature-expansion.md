# ML Feature Expansion & Accuracy Roadmap

**Date:** 2026-04-22
**Author:** SPECTRE
**Status:** In progress (Phase 1 being applied)
**Scope:** Adds ~40 features across 6 phases, introduces triple-barrier labeling,
meta-labeling, probability calibration, conformal prediction, and drift monitoring.
Expected cumulative AUC uplift: ~0.05–0.09 (from current 0.67 → ~0.72–0.76).

## Design principle: tier-gating

The trading signal itself is identical across tiers (fair model). Ultra adds:
- Raw ML probability (vs bucketed for lower tiers)
- Conformal confidence interval
- SHAP per-signal top-5 reasons
- Funding / OI / liquidation live context panel
- Meta-labeler verdict (fire / skip)
- HTF alignment numeric score + regime classifier state

Paid data (liquidation heatmaps from CoinGlass tier, L2 depth) may become Ultra-only
inputs if subscription is added later. Free Binance data feeds the shared model.

## Phase plan

### Phase 1 — Funding rate + Open Interest ingestion ✅ (this session)
**Files:**
- `data_fetcher.py` — add `fetch_funding_rate(pair, limit)`, `fetch_open_interest(pair, period, limit)`, `batch_fetch_funding_oi(pairs)`.
- New `funding_oi_cache.db` SQLite store (`funding_{pair}` and `oi_{pair}` tables).
- `ml_engine_archive/feature_engine.py` — add 8 new features:
  - `funding_rate_now`, `funding_z_24h`, `funding_z_7d`
  - `oi_change_1h`, `oi_change_24h`, `oi_z_24h`
  - `price_oi_divergence_1h` (sign mismatch)
  - `funding_extreme_flag` (|z|>2)
- Periodic fetcher task in `main.py` (every 10 min).
- **No retrain yet** — features land dormant until Phase 4 retrain. Zero risk to live signals.

### Phase 2 — HTF alignment features
Project 4h and 15m state onto 1h row:
- `htf_4h_ce_line_dir`, `htf_4h_ce_cloud_dir`, `htf_4h_tsi_zone`
- `htf_15m_ce_line_dir`, `htf_15m_momentum`
- `htf_alignment_score` (aggregate)

Reuses existing `rust_batch_processor` multi-TF cache. Pure-compute, no new data fetch.

### Phase 3 — Volume Profile + FVG features (Rust already computes them)
Wire into `build_features`:
- `vp_poc_distance_pct`, `vp_vah_distance_pct`, `vp_val_distance_pct`, `vp_above_poc_flag`
- `fvg_nearest_above_distance`, `fvg_nearest_below_distance`, `fvg_count_above`, `fvg_count_below`, `inside_fvg_flag`

### Phase 4 — Triple-barrier labels + sample weighting (FULL RETRAIN)
Replace current `generate_labels`:
- Label by whichever barrier is hit first: TP (≈2×ATR) / SL (≈1×ATR) / time (24 bars)
- Classes: `TP_HIT`, `SL_HIT`, `TIME_OUT_POSITIVE`, `TIME_OUT_NEGATIVE`
- Sample weights = `abs(forward_return) * uniqueness_weight` (overlap-adjusted)

Biggest single AUC lift historically. Triggers full model retrain.

### Phase 5 — Meta-labeler + probability calibration + conformal prediction
- Expand `meta_learner.pkl` with funding z, OI z, HTF alignment, CE conviction as inputs.
- Wrap XGBoost with `CalibratedClassifierCV(method='isotonic')` — probabilities become trustworthy.
- Implement inductive conformal prediction for per-signal edge CIs.
- Ultra-tier dashboard surface: CI + meta-verdict + SHAP top-5.

### Phase 6 — Drift monitor + SHAP in Telegram + purged K-fold CV
- Weekly PSI job on every feature vs training distribution.
- On-demand `/explain <signal_id>` Telegram command (Ultra-only) returning SHAP waterfall.
- Replace naive time-series split with purged+embargoed K-fold in `train.py`.

## Rollout safety

- Each phase gated by a feature flag in `constants.py` (`ML_FUNDING_OI_ENABLED`, etc.).
- Features added dormant — model keeps running on current feature set until a planned retrain reads the new columns.
- Parity test after each retrain: shadow-mode A/B for 48h before promoting.
- Rollback: disable feature flag + reload previous `xgboost_best.json` snapshot.

## Tier exposure matrix

| Surface | Free | Plus | Pro | Ultra |
|---|---|---|---|---|
| Signal direction | ✅ | ✅ | ✅ | ✅ |
| Probability (bucketed) | ✅ | ✅ | ✅ | ✅ |
| Probability (exact numeric) | ❌ | ❌ | ✅ | ✅ |
| Conformal CI | ❌ | ❌ | ❌ | ✅ |
| SHAP explanation | ❌ | ❌ | ❌ | ✅ |
| Funding/OI live context | ❌ | ❌ | partial | ✅ full |
| Meta-verdict (fire/skip) | ❌ | ❌ | ❌ | ✅ |
| HTF alignment numeric | badge | badge | ✅ | ✅ |
| Regime classifier state | ❌ | ❌ | ❌ | ✅ |
| Drift health banner | ❌ | ❌ | ❌ | ✅ |

## Status (2026-04-22 02:20)

- **Phase 1–3**: ✅ Live — 24 new features feeding `build_features`
- **Phase 4**: ✅ Code landed; first shadow retrain exposed **lookahead-bias bug**
  (TB metadata `tb_uniqueness`, `tb_barrier_bar`, `tb_ret_magnitude`,
  `sample_weight` were leaking into features). Fixed by excluding them in
  `get_feature_columns`. Second clean shadow retrain produced:
  - Ensemble F1 **0.544** (vs legacy 0.967 which was inflated by the same bug)
  - SHORT precision 0.49 / recall 0.48
  - LONG precision 0.50 / recall 0.41
  - NEUTRAL precision 0.67 / recall 0.73
- **Phase 5**: ✅ Code landed + applied
  - `ml_calibration.py` — isotonic calibrator fitted from val predictions
  - `ml_conformal.py`   — inductive conformal thresholds at α=0.1 (90% CI)
  - Artifacts: `ml_models_v2/calibrator.pkl`, `ml_models_v2/conformal.pkl`
- **Phase 6**: ✅ Code landed + applied
  - `ml_drift_monitor.py` — PSI against training snapshot
  - `ml_explainer.py`     — SHAP top-N (fixed for modern (N,F,K) shape)
  - `ml_ultra_surface.py` — unified Ultra-tier API with tier redaction
  - Snapshot: `ml_models_v2/feature_distribution.pkl`
- **Deferred**: Purged+embargoed K-fold CV (architectural refactor, follow-up)
  + `/explain` Telegram handler wiring (one-line add to `telegram_handler.py`)
  + Dashboard Ultra widget (consumes `predict_ultra` → `format_for_tier`)

### Legacy model status
Live ensemble at `ml_models/` was almost certainly carrying the same
label-leakage bug because features like `rh_ce_long_stop` (raw price
levels) are partially label-predictive when paired with SavGol smoothing
on labels. The shadow retrain after the leakage fix will be the honest
baseline. Operator must decide whether to:
  (a) Promote `ml_models_v2/` to `ml_models/` (honest 0.54 F1 replaces
      inflated 0.97 — live win rate may actually **improve** because the
      overconfident legacy model was producing bad high-probability signals)
  (b) Stay on legacy until a larger-scale retrain runs (200 pairs, 36 months)
      to confirm the honest score stabilizes.

Promotion command:
    systemctl stop anunnaki-bot
    mv ml_models ml_models_legacy_backup
    mv ml_models_v2 ml_models
    systemctl start anunnaki-bot

