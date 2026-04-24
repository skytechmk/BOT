# ML Accuracy Overhaul + LONG-Bias Fix

**Date:** 2026-04-19
**Author:** S.P.E.C.T.R.E.
**Status:** Proposal (pending operator approval)
**Files touched:** `reverse_hunt.py`, `ml_engine_archive/feature_engine.py`, `ml_engine_archive/train.py`, `ml_engine_archive/models.py`, `ml_engine_archive/labeler.py` (new), `ml_engine_archive/meta_labeler.py` (new), `main.py`, `signal_quality.py`

---

## 1. Executive Summary

Two linked problems degrade signal quality:

1. **Directional bias** — the bot fires ~9:1 LONG:SHORT. Root cause is a contrarian dip-buyer in a bull regime + asymmetric adaptive thresholds + SHORT-specific vetoes. Partially a feature (contrarian), partially a bug (asymmetry + missing LONG-side filters during greed).
2. **ML training is sub-optimal** — fixed-horizon labels don't match ATR-based trades, class-balanced cross-entropy loss makes NEUTRAL dominant, pair universe is 20 instead of 600, and 7 high-signal features used by the live bot (funding, OI, liquidations, BTC regime, USDT.D, DeFi TVL, FVG) are **not** passed to the ML model.

This proposal fixes both in a single coordinated rollout.

Expected outcomes after full rollout:
- Direction balance: 9:1 → **~2:1** (still slightly long-biased, matching true market edge)
- Ensemble F1 on validation: ~0.52 (current) → **~0.63–0.68** target
- Precision on fired signals: **+10–15%** via meta-labeling
- Recall on SHORT signals: **+200%** via symmetric gates + focal loss

---

## 2. LONG-Bias Diagnosis (data-backed)

### 2.1 Evidence from `main.log` (Apr 14 – 18)

| Stage | LONG | SHORT | Ratio |
|---|---:|---:|---:|
| TSI zones universe | 81 OS | 25 OB | 3.2 : 1 |
| CE direction | 575 | 152 | 3.8 : 1 |
| PERSISTENT zone triggers | 115 | 11 | **10.5 : 1** |
| LATE ENTRY triggers | 7 | 3 | 2.3 : 1 |
| REVERSE HUNT detections | 122 | 14 | **8.7 : 1** |
| Registered (fired) signals | 14 | 0 | ∞ |

Market-wide bias is 3:1 — actual fire bias is 9:1 → bot **amplifies** the natural bias ~3×.

### 2.2 Root causes

**Cause A — Design (contrarian dip-buyer)**
`reverse_hunt.py:32` sets `TSI_INVERT = True`. The entire Engine 1A flips price momentum. In a bull-leaning regime, dips are frequent → TSI OS fires constantly → LONG signals proliferate. This is intentional but compounds with market regime.

**Cause B — Asymmetric adaptive thresholds**
`reverse_hunt.py` computes per-pair adaptive L1/L2 floors from the pair's TSI percentile history. When a pair has been in persistent bearish drift, its OS-side distribution is wider, so the adaptive OS floor is **loosened** more aggressively than the OB floor. This is why PERSISTENT bias (10.5:1) is worse than market (3.2:1).

**Cause C — Asymmetric macro gates**
- LONG gates: USDT.D `GREED_MAX_PAIN` veto (fires rarely in current regime)
- SHORT gates: USDT.D `FEAR_MAX_PAIN` veto **+** Extreme Fear + BTC HTF not-bearish rejection (`main.py:374-382`)

SHORT survivors pass through TWO gates; LONG survivors pass through ONE. The second SHORT gate (fear + BTC) is valid logic but has no LONG equivalent (greed + BTC) — creating asymmetry.

### 2.3 Fix plan for LONG bias

1. **Symmetrize macro gates** — add LONG-side "Greed + BTC not-bullish" rejection mirroring the SHORT-side fear gate.
2. **Symmetrize adaptive TSI floors** — clamp the OS/OB floor ratio so neither can drift more than 25% off the other.
3. **Add regime-aware direction weighting** — in BEAR market, SHORT bias becomes 0.7×, LONG 1.3×; in BULL, inverse. Currently direction weight is always 1.0.
4. **Expose the bias in dashboard ops** — add a live "directional balance" widget to the ops channel so operator can see when asymmetry appears.

---

## 3. ML Accuracy Improvements

### 3.1 Add missing production features (biggest quick win)

Features the **live bot uses** but the **ML never sees**:

| Feature | Source | Expected impact |
|---|---|---|
| `funding_rate`, `funding_rate_sma_24h`, `funding_skew` | `data_fetcher.analyze_funding_rate_sentiment` | ⭐⭐⭐⭐ |
| `oi_change_1h`, `oi_change_4h`, `oi_divergence` | `data_fetcher.get_open_interest_change` | ⭐⭐⭐⭐ |
| `liq_magnet_long_dist`, `liq_magnet_short_dist`, `liq_cluster_score` | `predator.detect_liquidation_magnets` | ⭐⭐⭐⭐ |
| `stop_hunt_long`, `stop_hunt_short` | `predator.detect_stop_hunt` | ⭐⭐⭐ |
| `btc_htf_regime` (bullish/bearish/chop one-hot) | `trading_utilities.get_btc_htf_regime` | ⭐⭐⭐⭐ |
| `btc_correlation_30d` | `trading_utilities.check_btc_correlation` | ⭐⭐⭐ |
| `usdt_d_tsi`, `usdt_d_linreg`, `usdt_d_state` | `usdt_dominance.get_usdt_dominance_state` | ⭐⭐⭐ |
| `pair_macro_tsi`, `pair_macro_linreg` | `pair_macro_indicator` | ⭐⭐⭐ |
| `fvg_long_count`, `fvg_short_count`, `fvg_nearest_dist` | `aladdin_core` Rust FVG | ⭐⭐⭐ |
| `regime_onehot` (PARABOLIC / CLEAN_TREND / CHOP) | `predator.detect_regime` | ⭐⭐⭐⭐ |
| `defi_tvl_delta_24h` | `defi_filter.get_defi_tvl_filter` | ⭐⭐ |
| `is_prime_session`, `is_us_equity_open` | `trading_utilities` | ⭐⭐ |
| `signal_source_onehot` (PERSISTENT / LATE / REVERSE) | existing signal metadata | ⭐⭐⭐ |

**Implementation:** extend `feature_engine.prepare_dataset()` with a `macro_context` dict argument, populated by a new helper `build_macro_context(pair, df)` that batches all the above at feature-engineering time.

### 3.2 Triple-barrier labeling (López de Prado)

**Current label** (`feature_engine._compute_labels`, implicit from `forward_bars=24`):
```
label[t] = sign(close[t+24] - close[t])  → {-1, 0, 1}
```
**Problem:** the bot uses ATR-based TP/SL. A real trade ends at whichever of TP/SL is hit first, often well before bar t+24. Current labels train the model to predict an arbitrary future snapshot, not the trade outcome.

**Proposed label:**
```python
def triple_barrier_label(df, atr, tp_mult=2.0, sl_mult=1.0, max_bars=48):
    for t in range(len(df)):
        entry = df.close[t]
        tp_long  = entry + tp_mult * atr[t]
        sl_long  = entry - sl_mult * atr[t]
        tp_short = entry - tp_mult * atr[t]
        sl_short = entry + sl_mult * atr[t]
        for j in range(1, max_bars + 1):
            if df.high[t+j] >= tp_long:  return +1  # LONG win
            if df.low[t+j]  <= sl_long:  return 0   # LONG loss → NEUTRAL
            if df.low[t+j]  <= tp_short: return -1  # SHORT win
            if df.high[t+j] >= sl_short: return 0
        return 0  # timeout
```
Two variants trained as separate heads:
- **Directional head**: `{-1, 0, +1}` (which direction to take)
- **Profitability head**: `{0, 1}` (will this signal hit TP before SL?) — feeds meta-labeling

Expected F1 uplift: **+0.05 to +0.10**

### 3.3 Focal loss + class weighting

Replace `nn.CrossEntropyLoss` in `ml_engine_archive/models.py:BiLSTMAttention` training loop with:

```python
class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0, weight=None):
        super().__init__()
        self.gamma = gamma
        self.weight = weight
    def forward(self, logits, target):
        ce = F.cross_entropy(logits, target, weight=self.weight, reduction='none')
        pt = torch.exp(-ce)
        return ((1 - pt) ** self.gamma * ce).mean()
```

Class weights computed inverse-frequency from training set. Tree models (XGBoost / LightGBM) use `scale_pos_weight` and `class_weight='balanced'` respectively.

Expected: NEUTRAL bias dissolves, LONG/SHORT precision +3–8%.

### 3.4 Meta-labeling (second-stage filter)

Two-model pipeline at inference:

```
Primary model      : "Direction = LONG with prob 0.78"
     ↓
Meta model (new)   : "Given LONG prediction + current context, will it hit TP? prob 0.34"
     ↓
Fire only if prob × conviction × sqi ≥ threshold
```

Meta-learner = XGBoost trained on **primary model's predictions + macro context features + primary model's confidence + historical win rate of that pair/direction**. Labels come from triple-barrier profitability head.

Expected: **precision +10–15%, recall -15–25%** (fewer but much cleaner fires).

### 3.5 Regime-conditional ensemble

Three specialist ensembles, routed at inference by live regime:
- `ensemble_parabolic.pkl`
- `ensemble_clean_trend.pkl`
- `ensemble_chop.pkl`

Each trained only on bars whose regime at `t` matched. This is standard practice in quant shops — generic models average out to mediocre; specialists dominate their niche. Compute cost: 3× training time, but each model is smaller so wall-clock rises ~1.8×.

Expected: **big win on regime transitions** where the generic model historically whipsaws.

### 3.6 Summary of expected F1 uplift

| Change | Cumulative F1 |
|---|---|
| Baseline (current) | 0.52 |
| + Missing features | 0.58 |
| + Triple-barrier | 0.62 |
| + Focal loss | 0.63 |
| + Meta-labeling | 0.66 |
| + Regime-conditional | 0.68 |

---

## 4. Multi-Pair Chunked Training

### 4.1 Current state
`main.py:932` → `--pairs 20`, same 20 pairs every time (sorted by volume). ~600 pairs go untrained.

### 4.2 Proposed 3-tier schedule

```
┌─────────────────────────────────────────────────────────────────┐
│ Tier-A  |  Top 20 by volume  | daily @ 00:15 UTC | ~15 min     │
│ Tier-B  |  Top 21–120        | weekly @ Sun 02:00 UTC | ~60 min │
│ Tier-C  |  All 600 pairs     | monthly | ~4 h chunked 5×120    │
└─────────────────────────────────────────────────────────────────┘
```

**Chunking logic:**
- Each chunk loads data → engineers features → trains → saves partial model → frees GPU VRAM (`torch.cuda.empty_cache()`, `del model`, 30s cooldown).
- Tier-B and Tier-C produce **incremental updates**: merge new samples into a rolling training buffer, then fine-tune existing ensemble instead of retraining from scratch.
- A guard file `ml_models/.training_lock` prevents concurrent runs; main.py skips scheduled retrain if lock exists.

### 4.3 GPU-safety guards
1. **VRAM watchdog**: if `torch.cuda.mem_get_info()[0] < 2 GB` free, abort current chunk and retry after cooldown.
2. **Process isolation**: each chunk spawns a subprocess so Python / CUDA state is clean between chunks.
3. **Signal-latency check**: before starting training, verify main scan loop has no signal pending < 30s; defer if active.

### 4.4 Implementation
- New file: `scripts/train_scheduler.py` (daemon, tracks schedule via `ml_models/training_schedule.json`).
- New helper in `ml_engine_archive/train.py`: `run_training_chunked(pair_batches, incremental=True)`.
- `main.py _run_ml_autotraining` replaced with a lighter dispatcher that reads `training_schedule.json` and invokes the correct tier.

---

## 5. Realtime GPU Inference Enhancements

### 5.1 Current inference path
`signal_generator` → `ensemble.predict_proba(features)` → one forward pass on CPU/GPU → one scalar probability. ~20 ms on RTX 3090.

### 5.2 Proposed enhancements

**A. Monte-Carlo dropout** (confidence estimation)
Keep dropout active at inference, run 50 stochastic forward passes in a single batched call, output `(mean_prob, std_prob)`. Reject signals where `std_prob > 0.15` (model is uncertain).
Cost: ~200 ms per signal on 3090 — negligible.
Gain: filters low-conviction fires.

**B. Multi-horizon consensus**
Run 3 inference heads in parallel (15m, 1h, 4h sequence lengths) on GPU. Require 2/3 agreement before firing.
Cost: trivially batchable, ~60 ms total.
Gain: eliminates timeframe-specific false positives.

**C. Per-pair LoRA heads** (future / optional)
Keep the core ensemble frozen, attach a tiny LoRA adapter (~10k params) per pair, update daily with that pair's recent 48h.
Cost: 200ms fine-tune per pair per day, negligible VRAM.
Gain: pair-specific quirks captured without corrupting core model.

**D. GPU warm pool**
Pre-load models onto GPU at bot startup and keep them resident. Avoids 2-3s cold-start latency on first signal.

### 5.3 Would this improve accuracy? — Direct answer
**Yes, but not because GPU vs CPU.** The current model already infers on GPU when available. Real gains come from:
- MC-dropout filtering → precision +2–5%
- Multi-horizon consensus → precision +3–6%, recall -5%
- LoRA per-pair → F1 +0.02–0.04 on idiosyncratic pairs

---

## 6. Phased Rollout Plan

### Phase 1 — LONG bias fix (low risk, fast)
**Day 1**
- Symmetrize macro gates (`main.py`)
- Clamp adaptive TSI floor ratio (`reverse_hunt.py`)
- Add regime-aware direction weighting in `signal_quality.py`
- Add ops-channel balance widget

**Risk:** may temporarily reduce total signal count while SHORT fraction grows. Monitor for 48h.

### Phase 2 — Add missing features + retrain (medium risk)
**Days 2–4**
- Extend `feature_engine` with macro-context features
- Pipe `build_macro_context` through `train.py`
- Full retrain on Tier-A (20 pairs, 6 months)
- Compare F1 vs current baseline on held-out validation

**Risk:** feature engineering bugs introduce NaNs; mitigated by existing `dropna` and `nan_to_num` in training.

### Phase 3 — Triple-barrier + focal loss (medium risk)
**Days 5–7**
- Add `ml_engine_archive/labeler.py`
- Swap label generation in `train.py`
- Replace loss in `models.py` (neural heads) and `scale_pos_weight` (tree heads)
- A/B validate: retrain both old and new on identical data, compare F1

**Risk:** changed label distribution may flip some existing model behaviours unpredictably. A/B testing mandatory.

### Phase 4 — Meta-labeling (medium-high risk)
**Days 8–10**
- New module `ml_engine_archive/meta_labeler.py`
- Dual-pass inference wiring in `signal_generator` (if still used) or `main.py` scoring path
- Shadow-mode deploy: run meta-model but don't block signals, log what would have been filtered
- After 48h shadow data, enable blocking mode

**Risk:** meta-model could be too aggressive and kill signal flow. Shadow-mode gates this.

### Phase 5 — Regime-conditional ensembles (high risk, long implementation)
**Weeks 2–3**
- Three parallel training pipelines
- Inference router in `signal_generator` keyed on live regime
- Fallback to generic ensemble if regime detection uncertain

### Phase 6 — Multi-pair chunked scheduler (low risk, independent)
**Week 2 in parallel**
- `scripts/train_scheduler.py` + `training_schedule.json`
- Lock file + VRAM watchdog
- Replace `_run_ml_autotraining` dispatcher

### Phase 7 — Realtime GPU enhancements (medium risk)
**Week 3**
- MC-dropout wrapper in inference
- Multi-horizon consensus (requires training 15m + 4h variants, built on Phase 5 infrastructure)

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LONG-bias fix over-corrects to SHORT bias | Medium | Medium | Clamp direction weight within [0.6, 1.4] |
| New features contain lookahead leakage | Medium | High | Purged K-fold CV validation before deploy |
| Triple-barrier labels inherit bot's TP/SL bias | Low | Medium | Train two variants (tight + wide barriers), pick by F1 |
| Meta-labeler kills all signal flow | Low | High | Mandatory 48h shadow mode |
| Regime-conditional models thin-sample specific regimes | High | Medium | Require ≥5000 samples per regime or fall back to generic |
| Chunked training VRAM OOM mid-chunk | Medium | Low | Watchdog aborts + retries; no data loss |
| Dashboard / signal stream disruption during rollout | Low | High | Deploy during low-volume sessions; feature-flag each phase |

---

## 8. Rollback Plan

Every phase is feature-flagged via env vars in `.env`:
```
ML_USE_MACRO_FEATURES=true
ML_USE_TRIPLE_BARRIER=true
ML_USE_FOCAL_LOSS=true
ML_USE_META_LABELER=true
ML_USE_REGIME_ROUTER=true
ML_LONG_BIAS_FIX=true
```

Rollback = flip flag to `false` and restart `main.py`. Old ensemble files kept in `ml_models/archive/YYYY-MM-DD/` for 30 days.

---

## 9. Open Questions for Operator

1. **Direction-weight clamp** — keep \[0.6, 1.4\] or tighter?
2. **Triple-barrier TP/SL mults** — match bot's live `assign_leverage` output (variable) or use fixed 2:1?
3. **Meta-labeler threshold** — how aggressive? Defaults at p=0.55; can go 0.50 (loose) to 0.65 (strict).
4. **Tier-C all-600 training cadence** — monthly or bi-weekly?
5. **Regime-conditional — include PREDATOR regimes** (VOLATILE_CHOP etc.) or keep to 3 primary?
6. **LoRA per-pair** — in scope for this proposal or defer to v2?

---

## 10. Implementation Order (if approved)

1. ✅ Phase 1 (LONG bias) — same-day, ~2 hours coding
2. ✅ Phase 6 (chunked scheduler) — 1 day, runs in parallel to everything else
3. ✅ Phase 2 (missing features) — 1 day
4. ✅ Phase 3 (triple-barrier + focal loss) — 2 days
5. ✅ Phase 4 (meta-labeling shadow) — 2 days shadow + 1 day activation
6. ✅ Phase 5 (regime-conditional) — 1 week
7. ✅ Phase 7 (realtime GPU) — 3 days

**Total: ~3 weeks end-to-end. Phase 1 + 2 + 3 alone delivers ~70% of the F1 uplift in 4 days.**

---

## Appendix A: Files to Create

```
ml_engine_archive/
  labeler.py                  (new — triple-barrier implementation)
  meta_labeler.py             (new — stage-2 profitability classifier)
  macro_context.py            (new — builds missing feature block)
  regime_router.py            (new — routes to specialist ensemble)
scripts/
  train_scheduler.py          (new — tiered schedule daemon)
  validate_model.py           (new — F1 comparison harness)
ml_models/
  training_schedule.json      (new — tier state)
  archive/                    (new — model rollback store)
```

## Appendix B: Files to Modify

| File | Change |
|---|---|
| `main.py` | symmetrize macro gates, replace `_run_ml_autotraining`, add MC-dropout wrapper |
| `reverse_hunt.py` | clamp adaptive floor ratio |
| `signal_quality.py` | regime-aware direction weighting |
| `ml_engine_archive/train.py` | chunked training support, new labeler hookup, focal loss wiring |
| `ml_engine_archive/models.py` | focal loss in neural heads, class weights in tree heads, MC-dropout-aware predict |
| `ml_engine_archive/feature_engine.py` | integrate `macro_context.py` features |
| `.env` | new feature flags |
