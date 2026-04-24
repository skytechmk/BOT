# CE Hybrid — Parameterize Rust Batch CE + Fix Direction Logic Bug

**Date:** 2026-04-22
**Severity:** HIGH — production CE values diverge from TradingView and from Python config
**Files touched:** `aladdin_core/src/lib.rs`, `rust_batch_processor.py`
**Requires:** Rust rebuild (`maturin develop --release`) + dashboard/main restart

---

## Problem Statement

The Rust fast path (`batch_reverse_hunt_rust`) that serves 100% of live CE computations has **two defects** vs the user's TradingView `CE Pro Hybrid` setup:

### 1. Stale hardcoded parameters in `compute_rh_indicators()`

| Layer | Param | TV & Python | Rust (current) |
|-------|-------|:---:|:---:|
| LINE | lookback | 14 | **22** ❌ |
| CLOUD | atr_len | 14 | **50** ❌ |
| CLOUD | lookback | 28 | **50** ❌ |
| CLOUD | mult | 3.2 | **5.0** ❌ |

**Impact:** Cloud reacts ~3.5× slower than intended; stops sit ~56% further from price. CE_Cloud agreement checks in `reverse_hunt.py:876-881` gate on a much lazier cloud than the operator sees on TradingView. Line lookback of 22 vs 14 also shifts extremes.

### 2. Direction-flip logic mismatch

Pine/Python compare current close against the **PREVIOUS** bar's stop. Rust compares against the **JUST-UPDATED** stop. During ratcheting, this makes Rust flip direction up to one bar earlier than Pine.

`@aladdin_core/src/lib.rs:584-589` (current):
```rust
let prev_l = l_stop;
let prev_s = s_stop;
if close[i - 1] > prev_l { l_stop = long_raw[i].max(prev_l); } else { l_stop = long_raw[i]; }
if close[i - 1] < prev_s { s_stop = short_raw[i].min(prev_s); } else { s_stop = short_raw[i]; }
if close[i] > s_stop     { d = 1; }        // ❌ post-update
else if close[i] < l_stop { d = -1; }      // ❌ post-update
```

Pine (reference):
```
lStop := close[1] > lStopPrev ? math.max(longRaw, lStopPrev) : longRaw
sStop := close[1] < sStopPrev ? math.min(shortRaw, sStopPrev) : shortRaw
if close > sStopPrev    → d := 1          // uses PREV stop
else if close < lStopPrev → d := -1
```

`reverse_hunt.py:228-229` (correct, matches Pine):
```python
if   close_vals[i] > short_stop[i - 1]: direction[i] = 1
elif close_vals[i] < long_stop[i - 1]:  direction[i] = -1
```

---

## Proposed Fix

Make `reverse_hunt.py` the single source of truth for CE parameters. Rust takes them as arguments, so any future tuning flows through one config block.

### Change 1: `aladdin_core/src/lib.rs`

#### 1a. Parameterize `compute_rh_indicators`

**Current (lines 600-617):**
```rust
fn compute_rh_indicators(high: &[f64], low: &[f64], close: &[f64]) -> RhResult {
    ...
    // CE Line layer: src_long=close, src_short=high, ATR=22, Look=22, Mult=3.0, wait=true
    let (ce_line_long, ce_line_short, ce_line_dir) =
        compute_ce(high, low, close, close, high, 22, 22, 3.0, true);

    // CE Cloud layer: src=close, ATR=50, Look=50, Mult=5.0, wait=true
    let (ce_cloud_long, ce_cloud_short, ce_cloud_dir) =
        compute_ce(high, low, close, close, close, 50, 50, 5.0, true);
    ...
}
```

**New:**
```rust
/// CE parameter bundle passed from Python (reverse_hunt config is source of truth)
#[derive(Clone, Copy)]
pub struct CeParams {
    pub line_atr_len:    usize,
    pub line_lookback:   usize,
    pub line_mult:       f64,
    pub line_wait:       bool,
    pub cloud_atr_len:   usize,
    pub cloud_lookback:  usize,
    pub cloud_mult:      f64,
    pub cloud_wait:      bool,
}

impl Default for CeParams {
    fn default() -> Self {
        // Matches reverse_hunt.py constants as of 2026-04-22
        Self {
            line_atr_len: 22, line_lookback: 14, line_mult: 3.0, line_wait: true,
            cloud_atr_len: 14, cloud_lookback: 28, cloud_mult: 3.2, cloud_wait: true,
        }
    }
}

fn compute_rh_indicators(
    high: &[f64], low: &[f64], close: &[f64], params: CeParams,
) -> RhResult {
    let tsi    = calculate_tsi(close);
    let linreg = calculate_linreg(close, 278, 69, false, 39);

    // CE Line: src_long=close, src_short=high
    let (ce_line_long, ce_line_short, ce_line_dir) = compute_ce(
        high, low, close, close, high,
        params.line_atr_len, params.line_lookback, params.line_mult, params.line_wait,
    );

    // CE Cloud: src=close for both long/short
    let (ce_cloud_long, ce_cloud_short, ce_cloud_dir) = compute_ce(
        high, low, close, close, close,
        params.cloud_atr_len, params.cloud_lookback, params.cloud_mult, params.cloud_wait,
    );

    (tsi, linreg, ce_line_long, ce_line_short, ce_line_dir,
     ce_cloud_long, ce_cloud_short, ce_cloud_dir)
}
```

#### 1b. Update `batch_reverse_hunt_rust` signature

**Current (lines 623-627):**
```rust
#[pyfunction]
fn batch_reverse_hunt_rust(
    pairs: Vec<(Vec<f64>, Vec<f64>, Vec<f64>)>,
) -> PyResult<Vec<(Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>, Vec<i32>, Vec<f64>, Vec<f64>, Vec<i32>)>> {
    if pairs.is_empty() { return Ok(vec![]); }
    ...
    let results: Vec<RhResult> = pairs.par_iter()
        .map(|(h, l, c)| compute_rh_indicators(h, l, c))
        .collect();
    ...
}
```

**New (accept optional params dict from Python — backward compatible):**
```rust
#[pyfunction]
#[pyo3(signature = (
    pairs,
    line_atr_len = 22, line_lookback = 14, line_mult = 3.0, line_wait = true,
    cloud_atr_len = 14, cloud_lookback = 28, cloud_mult = 3.2, cloud_wait = true,
))]
fn batch_reverse_hunt_rust(
    pairs: Vec<(Vec<f64>, Vec<f64>, Vec<f64>)>,
    line_atr_len:   usize, line_lookback:  usize, line_mult:  f64, line_wait:  bool,
    cloud_atr_len:  usize, cloud_lookback: usize, cloud_mult: f64, cloud_wait: bool,
) -> PyResult<Vec<RhResult>> {
    if pairs.is_empty() { return Ok(vec![]); }
    let params = CeParams {
        line_atr_len, line_lookback, line_mult, line_wait,
        cloud_atr_len, cloud_lookback, cloud_mult, cloud_wait,
    };
    let results: Vec<RhResult> = pairs.par_iter()
        .map(|(h, l, c)| compute_rh_indicators(h, l, c, params))
        .collect();
    Ok(results)
}
```

Defaults match current Python config, so callers that don't pass params still work.

#### 1c. Fix direction-flip logic in `compute_ce`

**Current (lines 579-591):**
```rust
for i in 1..n {
    if long_raw[i].is_nan() || short_raw[i].is_nan() {
        ce_long[i] = l_stop; ce_short[i] = s_stop; ce_dir[i] = d;
        continue;
    }
    let prev_l = l_stop;
    let prev_s = s_stop;
    if close[i - 1] > prev_l { l_stop = long_raw[i].max(prev_l); } else { l_stop = long_raw[i]; }
    if close[i - 1] < prev_s { s_stop = short_raw[i].min(prev_s); } else { s_stop = short_raw[i]; }
    if close[i] > s_stop     { d = 1; }
    else if close[i] < l_stop { d = -1; }
    ce_long[i] = l_stop; ce_short[i] = s_stop; ce_dir[i] = d;
}
```

**New (compare against PRE-update stops, matches Pine + reverse_hunt.py):**
```rust
for i in 1..n {
    if long_raw[i].is_nan() || short_raw[i].is_nan() {
        ce_long[i] = l_stop; ce_short[i] = s_stop; ce_dir[i] = d;
        continue;
    }
    let prev_l = l_stop;   // snapshot BEFORE update
    let prev_s = s_stop;
    if close[i - 1] > prev_l { l_stop = long_raw[i].max(prev_l); } else { l_stop = long_raw[i]; }
    if close[i - 1] < prev_s { s_stop = short_raw[i].min(prev_s); } else { s_stop = short_raw[i]; }
    // Direction flip uses the PREVIOUS bar's stop (pre-update), matching Pine's sStopPrev
    if close[i] > prev_s     { d = 1; }
    else if close[i] < prev_l { d = -1; }
    ce_long[i] = l_stop; ce_short[i] = s_stop; ce_dir[i] = d;
}
```

Only the two `prev_s` / `prev_l` references change.

---

### Change 2: `rust_batch_processor.py`

Pass CE params from `reverse_hunt.py` when calling Rust batch.

**Current `prefetch()` call (line 88):**
```python
results = aladdin_core.batch_reverse_hunt_rust(batch_input)
```

**New:**
```python
from reverse_hunt import (
    CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_WAIT,
    CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, CE_CLOUD_MULT, CE_CLOUD_WAIT,
)
results = aladdin_core.batch_reverse_hunt_rust(
    batch_input,
    CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_WAIT,
    CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, CE_CLOUD_MULT, CE_CLOUD_WAIT,
)
```

Apply the same to `update_single()` call at line 152.

Put the `from reverse_hunt import ...` at module top to avoid import-on-every-call overhead (or keep it local if circular-import concerns apply — `reverse_hunt` imports from `technical_indicators` not `rust_batch_processor`, so top-level should be safe).

---

## Numerical Parity Test Plan

After rebuild, run a side-by-side check on a handful of pairs to confirm Rust output == Python output. Suggested script (for your review — don't commit):

```python
from reverse_hunt import calculate_chandelier_exit, CE_LINE_*, CE_CLOUD_*
import aladdin_core, pandas as pd
from data_fetcher import fetch_data

for pair in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']:
    df = fetch_data(pair, '1h')
    # Python
    py_line = calculate_chandelier_exit(df, CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT,
        CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT)
    # Rust
    results = aladdin_core.batch_reverse_hunt_rust(
        [(df.high.tolist(), df.low.tolist(), df.close.tolist())],
        CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_WAIT,
        CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, CE_CLOUD_MULT, CE_CLOUD_WAIT,
    )
    _, _, ce_ll, _, ce_ld, _, _, _ = results[0]
    # Compare last 200 bars
    diff_stop = (py_line['long_stop'].values[-200:] - ce_ll[-200:])
    diff_dir  = (py_line['direction'].values[-200:] - ce_ld[-200:])
    print(f"{pair}: max_stop_diff={abs(diff_stop).max():.6f}, dir_mismatches={int((diff_dir!=0).sum())}")
```

Expected: `max_stop_diff` ≈ 1e-10 (float noise), `dir_mismatches == 0`.

---

## Apply Steps

1. Apply Change 1 to `aladdin_core/src/lib.rs`
2. Apply Change 2 to `rust_batch_processor.py`
3. Rebuild Rust:
   ```
   cd /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/aladdin_core
   maturin develop --release
   ```
4. Run parity test above
5. Restart main bot + dashboard:
   ```
   systemctl restart anunnaki-bot anunnaki-dashboard
   ```

## Risk Assessment

| Risk | Severity | Mitigation |
|------|:---:|------|
| Existing open signals built on wrong CE → new CE may close them or invalidate | MEDIUM | The fix affects FUTURE decisions only; open signals' SL/TP are frozen. They'll simply be monitored with more accurate context. No forced re-evaluation. |
| Rust build fails (new function signature) | LOW | `maturin develop --release` will catch this immediately before deploy. |
| Python caller passes wrong order of params | LOW | `#[pyo3(signature = ...)]` enforces kwargs-compatible calling; if wrong order, PyO3 rejects at call time. |
| Performance regression from passing 8 extra scalar args | NEGLIGIBLE | Scalars are cheap; batch is still dominated by Rayon parallel OHLCV crunch. |
| Increased flip-rate on signals from tighter cloud (14/28/3.2 vs 50/50/5.0) | MEDIUM | This is the INTENDED behavior — cloud now matches your TV tuning. May see more ce_cloud_agree ✅ on actually-aligned signals and more ❌ rejections on poorly-aligned ones. |

## Expected Observable Changes

- `CE Cloud: ✅` / `❌` frequency in signal logs will shift (cloud is now faster, more responsive)
- Signals that used to pass ce_cloud check with 50/50/5.0 CE may now fail with 14/28/3.2
- Reverse Hunt `PERSISTENT_*` fallback may trigger less often (ce_line_dir flips more in line with Pine)
- Chop filter (`_ce_flip_count >= 3` in last 24 bars) may trigger marginally more often on line=14 vs line=22 — monitor first 24h

## Rollback

If things go sideways:
1. `git diff HEAD~1 -- aladdin_core/src/lib.rs rust_batch_processor.py` to review what changed
2. `git revert` the commit
3. Rebuild: `cd aladdin_core && maturin develop --release`
4. Restart services

No DB migrations. No schema changes. Pure compute-path fix.
