# Aladdin Trading Bot — Upgrades Log

This folder tracks all upgrades, implementations, and integrations made to the
Aladdin Trading Bot as part of the **April 2026 ML Accuracy & Signal Quality**
improvement cycle.

Each upgrade has its own dated Markdown file with:
- **What** was changed
- **Why** (root cause + data)
- **Where** (exact files and line ranges)
- **How** to verify / rollback
- **Status** (implemented / shadow-mode / disabled)

## Master Index

| # | Date | Title | Status | File |
|---|---|---|---|---|
| 01 | 2026-04-19 | LONG-Bias Fix — Symmetric Adaptive TSI + Greed Gate | ✅ Implemented | `01_2026-04-19_long-bias-fix.md` |
| 02 | 2026-04-19 | Phase 2: Missing Production Features in ML (85→98 features) | ✅ Implemented | `02_2026-04-19_ml-phase2-missing-features.md` |
| 03 | 2026-04-19 | Phase 3: Focal Loss γ=2.0 + ATR Sample Weights | ✅ Implemented | `03_2026-04-19_ml-phase3-focal-loss-atr-weights.md` |
| 04 | 2026-04-19 | Phase 4: Meta-Labeler Shadow Mode (meta_labeler.py) | ✅ Implemented | `04_2026-04-19_ml-phase4-meta-labeler.md` |
| 05 | 2026-04-19 | Phase 5: Regime-Conditional Ensemble Routing | ✅ Implemented | `05_2026-04-19_ml-phase5-regime-routing.md` |
| 06 | 2026-04-19 | Phase 6: Chunked Training Scheduler + Checkpoint | ✅ Implemented | `06_2026-04-19_ml-phase6-chunked-training.md` |
| 07 | 2026-04-19 | Phase 7: MC-Dropout Realtime GPU Inference | ✅ Implemented | `07_2026-04-19_ml-phase7-mc-dropout.md` |

## Related Proposals

- `/proposals/2026-04-19_ml-accuracy-and-long-bias-fix.md` — the master roadmap (7 phases)

## Phase Tracker (from master proposal)

| Phase | Title | Status |
|---|---|---|
| 1 | LONG-Bias Fix | ✅ Done |
| 2 | Missing ML Features | ✅ Done |
| 3 | Focal Loss γ=2.0 + ATR Sample Weights | ✅ Done |
| 4 | Meta-Labeling (shadow → active) | ✅ Done (shadow) |
| 5 | Regime-Conditional Ensembles | ✅ Done |
| 6 | Multi-Tier Chunked Training Scheduler | ✅ Done |
| 7 | Realtime GPU Enhancements (MC-dropout) | ✅ Done |

## Environment Flags

All upgrades can be rolled back via `.env` flags once implemented:

```
# Currently no feature flags — Phase 1 is an always-on fix.
# ML_USE_MACRO_FEATURES=true        # Phase 2
# ML_USE_TRIPLE_BARRIER=true        # Phase 3
# ML_USE_FOCAL_LOSS=true            # Phase 3
# ML_USE_META_LABELER=true          # Phase 4
# ML_USE_REGIME_ROUTER=true         # Phase 5
# ML_USE_MC_DROPOUT=true            # Phase 7
```
