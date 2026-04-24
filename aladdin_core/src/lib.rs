use pyo3::prelude::*;
use rand::prelude::*;
use rand_distr::{Normal, Distribution};
use rayon::prelude::*;

#[pyfunction]
fn get_rust_version() -> PyResult<String> {
    Ok(env!("CARGO_PKG_VERSION").to_string())
}

#[pyfunction]
fn calculate_atr_rust(high: Vec<f64>, low: Vec<f64>, close: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    if high.len() != low.len() || high.len() != close.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "High, low, and close arrays must have the same length"
        ));
    }
    
    if high.len() < period {
        return Ok(vec![]);
    }
    
    let mut true_ranges = Vec::with_capacity(high.len());
    
    // Calculate True Range for each candle
    for i in 0..high.len() {
        if i == 0 {
            // First candle: TR = High - Low
            true_ranges.push(high[i] - low[i]);
        } else {
            let prev_close = close[i - 1];
            let tr1 = high[i] - low[i];
            let tr2 = (high[i] - prev_close).abs();
            let tr3 = (low[i] - prev_close).abs();
            true_ranges.push(tr1.max(tr2).max(tr3));
        }
    }
    
    // Calculate ATR using Wilder's smoothing (matches TA-Lib ATR)
    let mut atr = Vec::with_capacity(high.len());
    
    // Initialize with zeros for first period-1 values
    for i in 0..period-1 {
        atr.push(0.0);
    }
    
    // First ATR value: simple average of true ranges
    let mut sum = 0.0;
    for i in 0..period {
        sum += true_ranges[i];
    }
    let first_atr = sum / period as f64;
    atr.push(first_atr);
    
    // Continue with Wilder's smoothing
    let multiplier = 1.0 / period as f64;
    
    for i in period..high.len() {
        let prev_atr = atr[i - 1];
        let new_atr = (true_ranges[i] - prev_atr) * multiplier + prev_atr;
        atr.push(new_atr);
    }
    
    Ok(atr)
}

// ── helpers ──────────────────────────────────────────────────────────────────

/// Wilder's RSI — matches TA-Lib RSI exactly.
fn calculate_rsi_wilder(close: &[f64], period: usize) -> Vec<f64> {
    let n = close.len();
    if n <= period {
        return vec![f64::NAN; n];
    }
    let mut rsi = vec![f64::NAN; n];
    // Price deltas
    let deltas: Vec<f64> = (1..n).map(|i| close[i] - close[i - 1]).collect();
    // Seed average gain/loss with SMA of first `period` deltas
    let mut avg_gain: f64 = deltas[..period].iter().map(|&d| if d > 0.0 { d } else { 0.0 }).sum::<f64>() / period as f64;
    let mut avg_loss: f64 = deltas[..period].iter().map(|&d| if d < 0.0 { -d } else { 0.0 }).sum::<f64>() / period as f64;
    let rs = if avg_loss > 0.0 { avg_gain / avg_loss } else { f64::INFINITY };
    rsi[period] = 100.0 - 100.0 / (1.0 + rs);
    // Wilder's EMA smoothing
    for i in (period + 1)..n {
        let d = deltas[i - 1];
        let gain = if d > 0.0 { d } else { 0.0 };
        let loss = if d < 0.0 { -d } else { 0.0 };
        avg_gain = (avg_gain * (period - 1) as f64 + gain) / period as f64;
        avg_loss = (avg_loss * (period - 1) as f64 + loss) / period as f64;
        let rs = if avg_loss > 0.0 { avg_gain / avg_loss } else { f64::INFINITY };
        rsi[i] = 100.0 - 100.0 / (1.0 + rs);
    }
    rsi
}

/// VWAP: cumulative(close × volume) / cumulative(volume).
fn calculate_vwap_series(close: &[f64], volume: &[f64]) -> Vec<f64> {
    let n = close.len();
    let mut cum_pv = 0.0f64;
    let mut cum_vol = 0.0f64;
    (0..n).map(|i| {
        cum_pv  += close[i] * volume[i];
        cum_vol += volume[i];
        if cum_vol > 0.0 { cum_pv / cum_vol } else { close[i] }
    }).collect()
}

fn rolling_max(data: &[f64], period: usize) -> Vec<f64> {
    let n = data.len();
    let mut out = vec![f64::NAN; n];
    if period == 0 || n < period { return out; }
    for i in (period - 1)..n {
        let mut m = data[i + 1 - period];
        for j in (i + 2 - period)..=i {
            if data[j] > m { m = data[j]; }
        }
        out[i] = m;
    }
    out
}

fn rolling_min(data: &[f64], period: usize) -> Vec<f64> {
    let n = data.len();
    let mut out = vec![f64::NAN; n];
    if period == 0 || n < period { return out; }
    for i in (period - 1)..n {
        let mut m = data[i + 1 - period];
        for j in (i + 2 - period)..=i {
            if data[j] < m { m = data[j]; }
        }
        out[i] = m;
    }
    out
}

// ── Phase 1a: Chandelier Exit ─────────────────────────────────────────────────

#[pyfunction]
fn calculate_chandelier_exit_rust(
    high:   Vec<f64>,
    low:    Vec<f64>,
    close:  Vec<f64>,
    atr:    Vec<f64>,
    period: usize,
    mult:   f64,
) -> PyResult<(Vec<f64>, Vec<f64>, Vec<i32>)> {
    let n = high.len();
    if n == 0 || n != low.len() || n != close.len() || n != atr.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "All arrays must be non-empty and equal length",
        ));
    }

    let hh = rolling_max(&high, period);
    let ll = rolling_min(&low,  period);

    // Raw stops
    let long_raw: Vec<f64>  = (0..n).map(|i| if atr[i].is_nan() || ll[i].is_nan()  { f64::NAN } else { ll[i]  - atr[i] * mult }).collect();
    let short_raw: Vec<f64> = (0..n).map(|i| if atr[i].is_nan() || hh[i].is_nan()  { f64::NAN } else { hh[i]  + atr[i] * mult }).collect();

    let mut long_stop  = vec![0.0f64; n];
    let mut short_stop = vec![0.0f64; n];
    let mut direction  = vec![1i32;   n];

    let mut l_stop = 0.0f64;
    let mut s_stop = 0.0f64;
    let mut d      = 1i32;

    for i in 1..n {
        if long_raw[i].is_nan() || short_raw[i].is_nan() {
            long_stop[i]  = l_stop;
            short_stop[i] = s_stop;
            direction[i]  = d;
            continue;
        }

        let prev_close = close[i - 1];

        // Save pre-update values for direction logic (matches Python exactly)
        let prev_l = l_stop;
        let prev_s = s_stop;

        // Update long stop (ratchets up, never down while trend intact)
        if prev_close > prev_l {
            l_stop = long_raw[i].max(prev_l);
        } else {
            l_stop = long_raw[i];
        }

        // Update short stop (ratchets down, never up while trend intact)
        if prev_close < prev_s {
            s_stop = short_raw[i].min(prev_s);
        } else {
            s_stop = short_raw[i];
        }

        // Direction based on prev_close vs PRE-UPDATE stops (no repaint)
        if close[i - 1] > prev_s {
            d = 1;
        } else if close[i - 1] < prev_l {
            d = -1;
        }

        long_stop[i]  = l_stop;
        short_stop[i] = s_stop;
        direction[i]  = d;
    }

    Ok((long_stop, short_stop, direction))
}

// ── Phase 1b: Fair Value Gap scanner ─────────────────────────────────────────

#[pyfunction]
fn detect_fair_value_gaps_rust(
    high:            Vec<f64>,
    low:             Vec<f64>,
    lookback:        usize,
    current_price:   f64,
    max_dist_pct:    f64,
) -> PyResult<Vec<(f64, f64, bool, f64)>> {
    // Returns sorted Vec of (top, bottom, is_bullish, strength) for unfilled FVGs
    let n = high.len();
    if n < 3 { return Ok(vec![]); }

    let start = if n > lookback { n - lookback } else { 0 };
    let mut gaps: Vec<(f64, f64, bool, f64)> = Vec::new();

    for i in (start + 2)..n {
        let h1 = high[i - 2]; let l1 = low[i - 2];
        let h2 = high[i - 1]; let l2 = low[i - 1];
        let h3 = high[i];     let l3 = low[i];

        // Bullish FVG: candle1.high < candle3.low, candle2 bridging but not filling
        if h1 < l3 && l2 > h1 && h2 < l3 {
            let top    = l3;
            let bottom = h1;
            let strength = (top - bottom) / h1;
            // Check if filled by any subsequent candle
            let filled = (i + 1..n).any(|j| low[j] <= top && high[j] >= bottom);
            if !filled {
                let mid = (top + bottom) / 2.0;
                if (mid - current_price).abs() / current_price <= max_dist_pct {
                    gaps.push((top, bottom, true, strength));
                }
            }
        }
        // Bearish FVG: candle1.low > candle3.high, candle2 bridging but not filling
        else if l1 > h3 && h2 < l1 && l2 > h3 {
            let top    = l1;
            let bottom = h3;
            let strength = (top - bottom) / h3;
            let filled = (i + 1..n).any(|j| high[j] >= bottom && low[j] <= top);
            if !filled {
                let mid = (top + bottom) / 2.0;
                if (mid - current_price).abs() / current_price <= max_dist_pct {
                    gaps.push((top, bottom, false, strength));
                }
            }
        }
    }

    // Sort by proximity to current price
    gaps.sort_by(|a, b| {
        let da = ((a.0 + a.1) / 2.0 - current_price).abs();
        let db = ((b.0 + b.1) / 2.0 - current_price).abs();
        da.partial_cmp(&db).unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok(gaps)
}

// ── Phase 2a: Ichimoku Cloud ──────────────────────────────────────────────────

#[pyfunction]
fn calculate_ichimoku_rust(
    high: Vec<f64>,
    low:  Vec<f64>,
) -> PyResult<(Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>)> {
    let n = high.len();
    if n == 0 || n != low.len() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "high and low must be equal-length non-empty arrays",
        ));
    }

    let hh9  = rolling_max(&high, 9);
    let ll9  = rolling_min(&low,  9);
    let hh26 = rolling_max(&high, 26);
    let ll26 = rolling_min(&low,  26);
    let hh52 = rolling_max(&high, 52);
    let ll52 = rolling_min(&low,  52);

    let tenkan: Vec<f64> = (0..n).map(|i| {
        if hh9[i].is_nan() || ll9[i].is_nan() { f64::NAN } else { (hh9[i] + ll9[i]) / 2.0 }
    }).collect();

    let kijun: Vec<f64> = (0..n).map(|i| {
        if hh26[i].is_nan() || ll26[i].is_nan() { f64::NAN } else { (hh26[i] + ll26[i]) / 2.0 }
    }).collect();

    // Senkou Span A: average of tenkan+kijun, shifted FORWARD 26 → span_a[i] = avg(i-26)
    let mut span_a = vec![f64::NAN; n];
    for i in 26..n {
        if !tenkan[i - 26].is_nan() && !kijun[i - 26].is_nan() {
            span_a[i] = (tenkan[i - 26] + kijun[i - 26]) / 2.0;
        }
    }

    // Senkou Span B: (52-period mid), shifted FORWARD 26 → span_b[i] = mid(i-26)
    let mut span_b = vec![f64::NAN; n];
    for i in 26..n {
        if !hh52[i - 26].is_nan() && !ll52[i - 26].is_nan() {
            span_b[i] = (hh52[i - 26] + ll52[i - 26]) / 2.0;
        }
    }

    Ok((tenkan, kijun, span_a, span_b))
}

// ── Phase 2b: Volume Profile ──────────────────────────────────────────────────

#[pyfunction]
fn calculate_volume_profile_rust(
    high:     Vec<f64>,
    low:      Vec<f64>,
    close:    Vec<f64>,
    volume:   Vec<f64>,
    num_bins: usize,
) -> PyResult<(Vec<f64>, Vec<f64>, f64, f64, f64)> {
    // Returns (bin_prices, bin_volumes, poc_price, vah, val)
    let n = high.len();
    if n == 0 || num_bins == 0 {
        return Ok((vec![], vec![], 0.0, 0.0, 0.0));
    }

    let price_min = low.iter().cloned().fold(f64::INFINITY,     f64::min);
    let price_max = high.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let range     = price_max - price_min;

    if range == 0.0 || !range.is_finite() {
        let p = *close.last().unwrap_or(&0.0);
        return Ok((vec![p], vec![0.0], p, p, p));
    }

    let bin_size = range / num_bins as f64;
    let bin_prices: Vec<f64> = (0..num_bins)
        .map(|i| price_min + (i as f64 + 0.5) * bin_size)
        .collect();

    // Rayon-parallel bin volume accumulation
    let bin_volumes: Vec<f64> = (0..num_bins)
        .into_par_iter()
        .map(|b| {
            let bin_lo = price_min + b as f64 * bin_size;
            let bin_hi = bin_lo + bin_size;
            let mut vol = 0.0f64;
            for i in 0..n {
                let h = high[i]; let l = low[i];
                let candle_range = h - l;
                let overlap_lo = l.max(bin_lo);
                let overlap_hi = h.min(bin_hi);
                if overlap_hi > overlap_lo {
                    let ratio = if candle_range > 0.0 {
                        (overlap_hi - overlap_lo) / candle_range
                    } else if l >= bin_lo && l <= bin_hi {
                        1.0
                    } else {
                        0.0
                    };
                    vol += volume[i] * ratio;
                }
            }
            vol
        })
        .collect();

    // Point of Control
    let (poc_idx, _) = bin_volumes.iter().enumerate()
        .fold((0, f64::NEG_INFINITY), |(mi, mv), (i, &v)| {
            if v > mv { (i, v) } else { (mi, mv) }
        });
    let poc = bin_prices[poc_idx];

    // Value Area (70% of total volume)
    let total: f64 = bin_volumes.iter().sum();
    let target = total * 0.7;
    let mut sorted: Vec<(f64, f64)> = bin_volumes.iter().cloned()
        .zip(bin_prices.iter().cloned())
        .collect();
    sorted.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut cum = 0.0f64;
    let mut va_prices: Vec<f64> = Vec::new();
    for (v, p) in &sorted {
        cum += v;
        va_prices.push(*p);
        if cum >= target { break; }
    }
    let vah = va_prices.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let val = va_prices.iter().cloned().fold(f64::INFINITY,     f64::min);

    Ok((bin_prices, bin_volumes, poc, vah, val))
}

// ══════════════════════════════════════════════════════════════════════════════
//  REVERSE HUNT — Rust-accelerated indicators for 150+ pairs via Rayon
// ══════════════════════════════════════════════════════════════════════════════

/// EWM (Exponential Weighted Mean) — alpha = 2/(span+1)  (pandas ewm(span=s))
fn ewm(data: &[f64], span: usize) -> Vec<f64> {
    let alpha = 2.0 / (span as f64 + 1.0);
    let n = data.len();
    let mut out = vec![f64::NAN; n];
    let mut prev = f64::NAN;
    for i in 0..n {
        if data[i].is_nan() { out[i] = prev; continue; }
        if prev.is_nan() {
            prev = data[i];
        } else {
            prev = alpha * data[i] + (1.0 - alpha) * prev;
        }
        out[i] = prev;
    }
    out
}

/// RMA (Wilder's Moving Average) — alpha = 1/length
fn rma_smooth(data: &[f64], length: usize) -> Vec<f64> {
    let alpha = 1.0 / length as f64;
    let n = data.len();
    let mut out = vec![f64::NAN; n];
    let mut prev = f64::NAN;
    for i in 0..n {
        if data[i].is_nan() { out[i] = prev; continue; }
        if prev.is_nan() {
            prev = data[i];
        } else {
            prev = alpha * data[i] + (1.0 - alpha) * prev;
        }
        out[i] = prev;
    }
    out
}

/// TSI: True Strength Index = 100 * EWM(EWM(pc, long), short) / EWM(EWM(|pc|, long), short)
/// Then inverted and scaled by /scale_factor (matching PineScript)
fn calculate_tsi(close: &[f64], long_len: usize, short_len: usize, scale: f64, invert: bool) -> Vec<f64> {
    let n = close.len();
    let mut pc = vec![f64::NAN; n];
    let mut pc_abs = vec![f64::NAN; n];
    for i in 1..n {
        pc[i] = close[i] - close[i - 1];
        pc_abs[i] = (close[i] - close[i - 1]).abs();
    }
    let ds  = ewm(&ewm(&pc, long_len), short_len);
    let dsa = ewm(&ewm(&pc_abs, long_len), short_len);

    let mut tsi = vec![f64::NAN; n];
    for i in 0..n {
        if dsa[i].is_nan() || dsa[i] == 0.0 { continue; }
        let mut v = 100.0 * ds[i] / dsa[i];
        if invert { v = -v; }
        tsi[i] = v / scale;
    }
    tsi
}

/// LinReg oscillator: normalized linear regression slope with optional EMA smoothing
/// smooth_len = 1 means no smoothing (pass-through)
fn calculate_linreg(close: &[f64], length: usize, norm_len: usize, invert: bool, smooth_len: usize) -> Vec<f64> {
    let n = close.len();
    let mut raw = vec![f64::NAN; n];

    for i in (length - 1)..n {
        let mut sum_x = 0.0f64;
        let mut sum_y = 0.0f64;
        let mut sum_xy = 0.0f64;
        let mut sum_x2 = 0.0f64;
        for j in 0..length {
            let x = j as f64;
            let y = close[i - length + 1 + j];
            sum_x  += x;
            sum_y  += y;
            sum_xy += x * y;
            sum_x2 += x * x;
        }
        let denom = length as f64 * sum_x2 - sum_x * sum_x;
        if denom == 0.0 { continue; }
        let m = (length as f64 * sum_xy - sum_x * sum_y) / denom;
        let c = (sum_y - m * sum_x) / length as f64;
        let mut v = m * i as f64 + c;
        if invert { v = -v; }
        raw[i] = v;
    }

    // Normalize: (value - SMA) / StdDev
    let mut normalized = vec![f64::NAN; n];
    for i in (norm_len - 1)..n {
        let mut sum = 0.0f64;
        let mut cnt = 0usize;
        for j in (i + 1 - norm_len)..=i {
            if !raw[j].is_nan() { sum += raw[j]; cnt += 1; }
        }
        if cnt == 0 || raw[i].is_nan() { continue; }
        let mean = sum / cnt as f64;
        let mut var_sum = 0.0f64;
        for j in (i + 1 - norm_len)..=i {
            if !raw[j].is_nan() { var_sum += (raw[j] - mean).powi(2); }
        }
        let std = (var_sum / cnt as f64).sqrt();
        if std > 0.0 {
            normalized[i] = (raw[i] - mean) / std;
        }
    }

    // EMA smoothing pass (matches PineScript 'Smoothing Factor' param)
    if smooth_len <= 1 {
        return normalized;
    }
    let alpha = 2.0 / (smooth_len as f64 + 1.0);
    let mut result = vec![f64::NAN; n];
    let mut ema = f64::NAN;
    for i in 0..n {
        if normalized[i].is_nan() { continue; }
        if ema.is_nan() {
            ema = normalized[i];
        } else {
            ema = alpha * normalized[i] + (1.0 - alpha) * ema;
        }
        result[i] = ema;
    }
    result
}

/// Chandelier Exit — configurable sources, ATR via RMA, wait-for-close (no repaint)
fn compute_ce(
    high: &[f64], low: &[f64], close: &[f64],
    src_long: &[f64], src_short: &[f64],
    atr_len: usize, lookback: usize, mult: f64, wait: bool,
) -> (Vec<f64>, Vec<f64>, Vec<i32>) {
    let n = high.len();

    // True Range
    let mut tr = vec![0.0f64; n];
    for i in 0..n {
        if i == 0 { tr[i] = high[i] - low[i]; }
        else {
            let pc = close[i - 1];
            tr[i] = (high[i] - low[i]).max((high[i] - pc).abs()).max((low[i] - pc).abs());
        }
    }
    let atr_raw = rma_smooth(&tr, atr_len);

    let hh = rolling_max(src_short, lookback);
    let ll = rolling_min(src_long, lookback);

    let shift = if wait { 1usize } else { 0 };

    let mut long_raw  = vec![f64::NAN; n];
    let mut short_raw = vec![f64::NAN; n];
    for i in shift..n {
        let ai = if shift > 0 && i >= shift { i - shift } else { i };
        let a = atr_raw[ai];
        let h = hh[ai];
        let l = ll[ai];
        if a.is_nan() || h.is_nan() || l.is_nan() { continue; }
        long_raw[i]  = l - a * mult;
        short_raw[i] = h + a * mult;
    }

    let mut ce_long  = vec![0.0f64; n];
    let mut ce_short = vec![0.0f64; n];
    let mut ce_dir   = vec![1i32; n];
    let mut l_stop = 0.0f64;
    let mut s_stop = 0.0f64;
    let mut d = 1i32;

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

    (ce_long, ce_short, ce_dir)
}

// ── RH Result struct for batch output ────────────────────────────────────────
// (tsi, linreg, ce_line_long, ce_line_short, ce_line_dir, ce_cloud_long, ce_cloud_short, ce_cloud_dir)
type RhResult = (Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>, Vec<i32>, Vec<f64>, Vec<f64>, Vec<i32>);

/// CE parameter bundle passed from Python (reverse_hunt.py is source of truth)
#[derive(Clone, Copy)]
struct CeParams {
    line_atr_len:    usize,
    line_lookback:   usize,
    line_mult:       f64,
    line_wait:       bool,
    cloud_atr_len:   usize,
    cloud_lookback:  usize,
    cloud_mult:      f64,
    cloud_wait:      bool,
}

fn compute_rh_indicators(high: &[f64], low: &[f64], close: &[f64], p: CeParams) -> RhResult {
    // TSI: Match TV config — long=69, short=9, scale=14, NOT inverted
    let tsi = calculate_tsi(close, 69, 9, 14.0, false);

    // LinReg: Match TV config — len=278, norm=69, smooth=39, NOT inverted
    let linreg = calculate_linreg(close, 278, 69, false, 39);

    // CE Line layer: src_long=close, src_short=high
    let (ce_line_long, ce_line_short, ce_line_dir) = compute_ce(
        high, low, close, close, high,
        p.line_atr_len, p.line_lookback, p.line_mult, p.line_wait,
    );

    // CE Cloud layer: src=close for both
    let (ce_cloud_long, ce_cloud_short, ce_cloud_dir) = compute_ce(
        high, low, close, close, close,
        p.cloud_atr_len, p.cloud_lookback, p.cloud_mult, p.cloud_wait,
    );

    (tsi, linreg, ce_line_long, ce_line_short, ce_line_dir, ce_cloud_long, ce_cloud_short, ce_cloud_dir)
}

/// Batch compute Reverse Hunt indicators for ALL pairs in parallel via Rayon.
/// CE params are accepted from Python so `reverse_hunt.py` constants remain the
/// single source of truth. Defaults match reverse_hunt.py as of 2026-04-22.
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
) -> PyResult<Vec<(Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>, Vec<i32>, Vec<f64>, Vec<f64>, Vec<i32>)>> {
    if pairs.is_empty() { return Ok(vec![]); }

    let params = CeParams {
        line_atr_len, line_lookback, line_mult, line_wait,
        cloud_atr_len, cloud_lookback, cloud_mult, cloud_wait,
    };

    let results: Vec<RhResult> = pairs
        .into_par_iter()
        .map(|(high, low, close)| {
            if high.is_empty() || high.len() != low.len() || high.len() != close.len() {
                let z = vec![0.0f64; 0];
                return (z.clone(), z.clone(), z.clone(), z.clone(), vec![], z.clone(), z.clone(), vec![]);
            }
            compute_rh_indicators(&high, &low, &close, params)
        })
        .collect();

    Ok(results)
}

// ── Efficiency Ratio (ER) ─────────────────────────────────────────────────────
// ER = |close[n] - close[0]| / sum(|close[i] - close[i-1]|)
// Range [0, 1]: 1.0 = perfect trend, 0.0 = pure noise/chop.
#[pyfunction]
fn calculate_efficiency_ratio_rust(close: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    let n = close.len();
    if n < period + 1 {
        return Ok(vec![0.0f64; n]);
    }
    let mut er = vec![0.0f64; n];
    for i in period..n {
        let net_change = (close[i] - close[i - period]).abs();
        let path: f64 = (i - period + 1..=i)
            .map(|j| (close[j] - close[j - 1]).abs())
            .sum();
        er[i] = if path > 1e-12 { net_change / path } else { 0.0 };
    }
    Ok(er)
}

// ── Money Flow Index (MFI) ────────────────────────────────────────────────────
// MFI = 100 - 100 / (1 + PMF / NMF)  where PMF/NMF = positive/negative money flow sums.
#[pyfunction]
fn calculate_mfi_rust(
    high: Vec<f64>,
    low: Vec<f64>,
    close: Vec<f64>,
    volume: Vec<f64>,
    period: usize,
) -> PyResult<Vec<f64>> {
    let n = close.len();
    if n != high.len() || n != low.len() || n != volume.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("Array length mismatch"));
    }
    if n < period + 1 {
        return Ok(vec![50.0f64; n]);
    }

    let tp: Vec<f64> = (0..n).map(|i| (high[i] + low[i] + close[i]) / 3.0).collect();
    let mf: Vec<f64> = (0..n).map(|i| tp[i] * volume[i]).collect();

    let mut mfi = vec![50.0f64; n];
    for i in period..n {
        let mut pos = 0.0f64;
        let mut neg = 0.0f64;
        for j in (i - period + 1)..=i {
            if tp[j] > tp[j - 1] {
                pos += mf[j];
            } else if tp[j] < tp[j - 1] {
                neg += mf[j];
            }
        }
        mfi[i] = if neg < 1e-12 {
            100.0
        } else {
            100.0 - 100.0 / (1.0 + pos / neg)
        };
    }
    Ok(mfi)
}

// ── Stochastic Oscillator (%K, %D) ───────────────────────────────────────────
// %K = 100 * (close - lowest_low) / (highest_high - lowest_low)  over k_period
// %D = SMA(%K, d_period)
#[pyfunction]
fn calculate_stochastic_rust(
    high: Vec<f64>,
    low: Vec<f64>,
    close: Vec<f64>,
    k_period: usize,
    d_period: usize,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let n = close.len();
    if n < k_period {
        return Ok((vec![50.0f64; n], vec![50.0f64; n]));
    }

    let mut k = vec![50.0f64; n];
    for i in (k_period - 1)..n {
        let lo = low[i - k_period + 1..=i].iter().cloned().fold(f64::INFINITY, f64::min);
        let hi = high[i - k_period + 1..=i].iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        k[i] = if (hi - lo).abs() < 1e-12 {
            50.0
        } else {
            100.0 * (close[i] - lo) / (hi - lo)
        };
    }

    // %D = simple moving average of %K
    let mut d = k.clone();
    for i in (d_period - 1)..n {
        let sum: f64 = k[i - d_period + 1..=i].iter().sum();
        d[i] = sum / d_period as f64;
    }

    Ok((k, d))
}

// ── ADX — Average Directional Index ──────────────────────────────────────────
#[pyfunction]
fn calculate_adx_rust(
    high:   Vec<f64>,
    low:    Vec<f64>,
    close:  Vec<f64>,
    period: usize,
) -> PyResult<Vec<f64>> {
    let n = close.len();
    if n < period + 1 {
        return Ok(vec![0.0f64; n]);
    }

    // True Range + DM buffers
    let mut tr  = vec![0.0f64; n];
    let mut pdm = vec![0.0f64; n];   // +DM
    let mut ndm = vec![0.0f64; n];   // -DM

    for i in 1..n {
        let hl  = high[i]  - low[i];
        let hpc = (high[i]  - close[i - 1]).abs();
        let lpc = (low[i]   - close[i - 1]).abs();
        tr[i]  = hl.max(hpc).max(lpc);

        let up   = high[i]  - high[i - 1];
        let down = low[i - 1] - low[i];
        pdm[i] = if up > down && up > 0.0 { up   } else { 0.0 };
        ndm[i] = if down > up && down > 0.0 { down } else { 0.0 };
    }

    // Wilder smoothing (period-bar initial sum, then EMA-style)
    let alpha = 1.0 / period as f64;
    let mut atr_w  = tr[1..=period].iter().sum::<f64>();
    let mut pdm_w  = pdm[1..=period].iter().sum::<f64>();
    let mut ndm_w  = ndm[1..=period].iter().sum::<f64>();

    let mut adx_arr = vec![0.0f64; n];
    let mut dx_sum  = 0.0f64;
    let mut dx_cnt  = 0usize;

    for i in (period + 1)..n {
        atr_w = atr_w - atr_w * alpha + tr[i];
        pdm_w = pdm_w - pdm_w * alpha + pdm[i];
        ndm_w = ndm_w - ndm_w * alpha + ndm[i];

        let pdi = if atr_w > 0.0 { 100.0 * pdm_w / atr_w } else { 0.0 };
        let ndi = if atr_w > 0.0 { 100.0 * ndm_w / atr_w } else { 0.0 };
        let dx  = if pdi + ndi > 0.0 { 100.0 * (pdi - ndi).abs() / (pdi + ndi) } else { 0.0 };

        dx_sum += dx;
        dx_cnt += 1;
        if dx_cnt >= period {
            adx_arr[i] = if dx_cnt == period {
                dx_sum / period as f64
            } else {
                adx_arr[i - 1] * (1.0 - alpha) + dx * alpha
            };
        }
    }
    Ok(adx_arr)
}

// ── Supertrend ────────────────────────────────────────────────────────────────
#[pyfunction]
fn calculate_supertrend_rust(
    high:       Vec<f64>,
    low:        Vec<f64>,
    close:      Vec<f64>,
    period:     usize,
    multiplier: f64,
) -> PyResult<(Vec<f64>, Vec<i64>)> {
    let n = close.len();
    if n < period {
        return Ok((close.clone(), vec![1i64; n]));
    }

    // RMA-smoothed ATR (same alpha as CE)
    let alpha = 1.0 / period as f64;
    let mut atr_rma = {
        let mut init = 0.0f64;
        for i in 1..=period.min(n - 1) {
            let hl  = high[i]  - low[i];
            let hpc = (high[i]  - close[i - 1]).abs();
            let lpc = (low[i]   - close[i - 1]).abs();
            init += hl.max(hpc).max(lpc);
        }
        init / period as f64
    };

    let hl2 = |i: usize| (high[i] + low[i]) / 2.0;

    let mut upper = vec![0.0f64; n];
    let mut lower = vec![0.0f64; n];
    let mut st    = vec![0.0f64; n];
    let mut dir   = vec![1i64;   n];   // 1 = uptrend, -1 = downtrend

    for i in 1..n {
        // Update RMA ATR
        let tr_i = {
            let hl  = high[i]  - low[i];
            let hpc = (high[i]  - close[i - 1]).abs();
            let lpc = (low[i]   - close[i - 1]).abs();
            hl.max(hpc).max(lpc)
        };
        atr_rma = atr_rma * (1.0 - alpha) + tr_i * alpha;

        let basic_upper = hl2(i) + multiplier * atr_rma;
        let basic_lower = hl2(i) - multiplier * atr_rma;

        upper[i] = if i > 0 && basic_upper < upper[i - 1] || close[i - 1] > upper[i - 1] {
            basic_upper
        } else {
            upper[i - 1]
        };
        lower[i] = if i > 0 && basic_lower > lower[i - 1] || close[i - 1] < lower[i - 1] {
            basic_lower
        } else {
            lower[i - 1]
        };

        dir[i] = if dir[i - 1] == -1 && close[i] > upper[i - 1] {
            1
        } else if dir[i - 1] == 1 && close[i] < lower[i - 1] {
            -1
        } else {
            dir[i - 1]
        };

        st[i] = if dir[i] == 1 { lower[i] } else { upper[i] };
    }

    Ok((st, dir))
}

// ── Laguerre RSI (Ehlers) ─────────────────────────────────────────────────────
// Reference: John Ehlers "Time Warp – Without Space Travel" (TASC, July 2004)
// Lag-reduced RSI using Laguerre polynomials. gamma controls smoothness (0=no
// smoothing → standard RSI, 1=max smoothing). Typical value: 0.5–0.8.
#[pyfunction]
fn calculate_laguerre_rsi_rust(
    close:  Vec<f64>,
    gamma:  f64,       // smoothing factor 0-1, typically 0.5
) -> PyResult<Vec<f64>> {
    let n = close.len();
    let g = gamma.clamp(0.0, 0.9999);

    let mut lrsi = vec![0.0f64; n];
    let mut l0_prev = 0.0f64;
    let mut l1_prev = 0.0f64;
    let mut l2_prev = 0.0f64;
    let mut l3_prev = 0.0f64;

    for i in 0..n {
        let p  = close[i];
        let l0 = (1.0 - g) / 2.0 * p + g * l0_prev;
        let l1 = -g * l0 + l0_prev + g * l1_prev;
        let l2 = -g * l1 + l1_prev + g * l2_prev;
        let l3 = -g * l2 + l2_prev + g * l3_prev;

        let mut cu = 0.0f64;
        let mut cd = 0.0f64;
        if l0 >= l1 { cu += l0 - l1; } else { cd += l1 - l0; }
        if l1 >= l2 { cu += l1 - l2; } else { cd += l2 - l1; }
        if l2 >= l3 { cu += l2 - l3; } else { cd += l3 - l2; }

        lrsi[i] = if (cu + cd).abs() < 1e-12 { 0.5 } else { cu / (cu + cd) };

        l0_prev = l0;
        l1_prev = l1;
        l2_prev = l2;
        l3_prev = l3;
    }
    Ok(lrsi)
}

// ── Fisher Transform (Ehlers) ─────────────────────────────────────────────────
// Reference: John Ehlers "Using The Fisher Transform" (TASC, November 2002)
// Converts price into a Gaussian normal distribution. Extreme values (>±2.0)
// signal genuine reversals with high probability. Returns (fisher, trigger).
#[pyfunction]
fn calculate_fisher_transform_rust(
    high:   Vec<f64>,
    low:    Vec<f64>,
    period: usize,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let n = high.len();
    if n < period {
        return Ok((vec![0.0f64; n], vec![0.0f64; n]));
    }

    let mut fisher  = vec![0.0f64; n];
    let mut trigger = vec![0.0f64; n];
    let mut prev_fish = 0.0f64;
    let mut prev_value = 0.0f64;

    for i in (period - 1)..n {
        let lo = low[i - period + 1..=i].iter().cloned().fold(f64::INFINITY, f64::min);
        let hi = high[i - period + 1..=i].iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let range = hi - lo;

        let raw = if range < 1e-12 {
            0.0
        } else {
            2.0 * ((high[i] + low[i]) / 2.0 - lo) / range - 1.0
        };
        // Smooth with previous value, clamp to avoid log infinity
        let value = (0.66 * raw + 0.67 * prev_value).clamp(-0.999, 0.999);
        let f = 0.5 * ((1.0 + value) / (1.0 - value)).ln() + 0.5 * prev_fish;

        trigger[i] = prev_fish;
        fisher[i]  = f;
        prev_fish  = f;
        prev_value = value;
    }
    Ok((fisher, trigger))
}

// ── Inverse Fisher Transform ──────────────────────────────────────────────────
// Applied to RSI to make it more decisive at extremes. Output in [-1, +1].
// Values near ±1 indicate high-probability reversals.
#[pyfunction]
fn calculate_inverse_fisher_rsi_rust(
    close:      Vec<f64>,
    rsi_period: usize,
) -> PyResult<Vec<f64>> {
    let n = close.len();
    if n < rsi_period + 1 {
        return Ok(vec![0.0f64; n]);
    }

    // Standard Wilder RSI
    let alpha = 1.0 / rsi_period as f64;
    let mut avg_gain = 0.0f64;
    let mut avg_loss = 0.0f64;

    // Seed with first period
    for i in 1..=rsi_period.min(n - 1) {
        let chg = close[i] - close[i - 1];
        if chg > 0.0 { avg_gain += chg; } else { avg_loss += -chg; }
    }
    avg_gain /= rsi_period as f64;
    avg_loss /= rsi_period as f64;

    let mut ifisher = vec![0.0f64; n];

    for i in (rsi_period + 1)..n {
        let chg = close[i] - close[i - 1];
        if chg > 0.0 {
            avg_gain = avg_gain * (1.0 - alpha) + chg * alpha;
            avg_loss *= 1.0 - alpha;
        } else {
            avg_loss = avg_loss * (1.0 - alpha) + (-chg) * alpha;
            avg_gain *= 1.0 - alpha;
        }
        let rs  = if avg_loss.abs() < 1e-12 { 100.0 } else { avg_gain / avg_loss };
        let rsi = 100.0 - 100.0 / (1.0 + rs);

        // Normalize RSI [0,100] → [-1,1], then apply inverse Fisher transform
        let x = 0.1 * (rsi - 50.0);
        let e2 = (2.0 * x).exp();
        ifisher[i] = (e2 - 1.0) / (e2 + 1.0);
    }
    Ok(ifisher)
}

// ── Internal Bar Strength (IBS) ───────────────────────────────────────────────
// IBS = (close - low) / (high - low). Range [0,1].
// <0.2 = close near lows (buyer exhaustion / reversal signal for LONG)
// >0.8 = close near highs (seller exhaustion / reversal for SHORT)
#[pyfunction]
fn calculate_ibs_rust(
    high:  Vec<f64>,
    low:   Vec<f64>,
    close: Vec<f64>,
) -> PyResult<Vec<f64>> {
    let n = high.len().min(low.len()).min(close.len());
    let ibs: Vec<f64> = (0..n).map(|i| {
        let range = high[i] - low[i];
        if range.abs() < 1e-12 { 0.5 } else { (close[i] - low[i]) / range }
    }).collect();
    Ok(ibs)
}

// ── Positive / Negative Volume Index ─────────────────────────────────────────
// PVI rises on above-average-volume bars; NVI rises on below-average-volume bars.
// NVI tracks "smart money": significant moves on quiet days reveal institutional intent.
// Returns (pvi, nvi) — both start at 1000.0.
#[pyfunction]
fn calculate_pvi_nvi_rust(
    close:  Vec<f64>,
    volume: Vec<f64>,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let n = close.len().min(volume.len());
    if n < 2 {
        return Ok((vec![1000.0f64; n], vec![1000.0f64; n]));
    }
    let mut pvi = vec![1000.0f64; n];
    let mut nvi = vec![1000.0f64; n];

    for i in 1..n {
        let pct_chg = (close[i] - close[i - 1]) / close[i - 1];
        if volume[i] > volume[i - 1] {
            pvi[i] = pvi[i - 1] * (1.0 + pct_chg);
            nvi[i] = nvi[i - 1];
        } else {
            pvi[i] = pvi[i - 1];
            nvi[i] = nvi[i - 1] * (1.0 + pct_chg);
        }
    }
    Ok((pvi, nvi))
}

// ── Ulcer Index ───────────────────────────────────────────────────────────────
// Measures depth and duration of drawdowns vs peak — a downside-risk metric.
// UI = sqrt(mean(((close - max_close_over_period) / max_close_over_period * 100)^2))
// Used to normalise position size: larger UI → smaller size.
#[pyfunction]
fn calculate_ulcer_index_rust(
    close:  Vec<f64>,
    period: usize,
) -> PyResult<Vec<f64>> {
    let n = close.len();
    let mut ui = vec![0.0f64; n];
    for i in (period - 1)..n {
        let window = &close[i + 1 - period..=i];
        let peak   = window.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let sum_sq: f64 = window.iter().map(|&c| {
            let dd = (c - peak) / peak * 100.0;
            dd * dd
        }).sum();
        ui[i] = (sum_sq / period as f64).sqrt();
    }
    Ok(ui)
}

// ── module registration ───────────────────────────────────────────────────────

#[pymodule]
fn aladdin_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_rust_version, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_atr_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_chandelier_exit_rust, m)?)?;
    m.add_function(wrap_pyfunction!(detect_fair_value_gaps_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_ichimoku_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_volume_profile_rust, m)?)?;
    m.add_function(wrap_pyfunction!(batch_reverse_hunt_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_efficiency_ratio_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_mfi_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_stochastic_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_adx_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_supertrend_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_laguerre_rsi_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_fisher_transform_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_inverse_fisher_rsi_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_ibs_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_pvi_nvi_rust, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_ulcer_index_rust, m)?)?;
    Ok(())
}
