# Upgrade 06 — Phase 6: Multi-Tier Chunked Training Scheduler

**Date:** 2026-04-19
**Phase:** 6 of 7
**Status:** ✅ Implemented
**Risk Level:** Low (operational change — no model architecture affected)
**Files touched:**
- `ml_engine_archive/train.py` — checkpoint save/resume, --chunk-size, --resume-checkpoint

---

## Problem

Training on 150 pairs × 6 months requires ~1–3 hours of feature engineering.
If the process is interrupted (OOM, restart, power loss), ALL work is lost and
must restart from scratch.

---

## Solution

Per-pair parquet checkpoints saved during feature engineering.

```
ml_models/feat_checkpoint/BTCUSDT.parquet
ml_models/feat_checkpoint/ETHUSDT.parquet
...
```

On restart with `--resume-checkpoint`, already-processed pairs are loaded from disk
and skipped in the feature engineering loop.

---

## Usage

### Standard training (checkpoint save enabled, no resume):
```bash
python -m ml_engine_archive.train --chunk-size 30
```
Saves each processed pair to `ml_models/feat_checkpoint/` as parquet.

### Resume interrupted training:
```bash
python -m ml_engine_archive.train --skip-download --chunk-size 30 --resume-checkpoint
```
Skips already-processed pairs, loads their parquets, continues from where it left off.

### Purge checkpoint (start fresh):
```bash
rm -rf ml_models/feat_checkpoint/
```

---

## CLI Args Added

| Arg | Default | Description |
|---|---|---|
| `--chunk-size N` | `0` (disabled) | Enable per-pair checkpointing (recommended: 30) |
| `--resume-checkpoint` | False | Load existing checkpoints and skip processed pairs |

Both can be passed to `run_training()` programmatically:
```python
run_training(..., chunk_size=30, resume_checkpoint=True)
```

---

## Performance Impact

- Checkpoint save: ~0.1s per pair (parquet write)
- Resume load: ~0.5s per pair (parquet read)
- Net benefit: 150 pairs → saves ~60–120 min of re-work on interruption

---

## Rollback
Simply don't pass `--chunk-size`. Checkpoint directory is never read unless
`--resume-checkpoint` is explicitly specified.
