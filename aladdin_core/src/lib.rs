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
    
    // Calculate ATR using exponential moving average
    let mut atr = Vec::with_capacity(high.len());
    let mut sum = 0.0;
    
    // Initialize with simple average for first period
    for i in 0..period {
        sum += true_ranges[i];
        atr.push(if i == period - 1 { sum / period as f64 } else { 0.0 });
    }
    
    // Continue with EMA
    let multiplier = 2.0 / (period as f64 + 1.0);
    let prev_atr = sum / period as f64;
    
    for i in period..high.len() {
        let current_atr = if i == period {
            prev_atr
        } else {
            atr[i - 1]
        };
        let new_atr = (true_ranges[i] - current_atr) * multiplier + current_atr;
        atr.push(new_atr);
    }
    
    Ok(atr)
}

#[pyfunction]
fn simulate_monte_carlo(
    current_price: f64,
    stop_loss: f64,
    targets: Vec<(f64, f64)>, // (price, weight)
    volatility: f64,
    num_simulations: usize,
    time_steps: usize,
    drift: f64, // NEW: Directional drift from ML confidence
) -> PyResult<(f64, f64, f64)> {
    let results: Vec<(bool, f64)> = (0..num_simulations)
        .into_par_iter()
        .map(|_| {
            let mut rng = thread_rng();
            let mut price = current_price;
            let normal = Normal::new(0.0, volatility / (time_steps as f64).sqrt()).unwrap();
            let mut hit_sl = false;
            let mut targets_hit = vec![false; targets.len()];
            let mut sim_pnl = 0.0;
            let is_long = targets[0].0 > current_price;

            // Apply drift per step (total drift distributed over steps)
            let step_drift = drift / (time_steps as f64);

            for _ in 0..time_steps {
                let change = normal.sample(&mut rng);
                price *= 1.0 + change + step_drift; // Informed Brownian Motion

                // Check SL
                if (is_long && price <= stop_loss) || (!is_long && price >= stop_loss) {
                    let mut pnl = (stop_loss - current_price) / current_price;
                    if !is_long { pnl = -pnl; }
                    sim_pnl = pnl;
                    hit_sl = true;
                    break;
                }

                // Check Targets
                let mut all_hit = true;
                for (i, (target_price, weight)) in targets.iter().enumerate() {
                    if !targets_hit[i] {
                        if (is_long && price >= *target_price) || (!is_long && price <= *target_price) {
                            targets_hit[i] = true;
                            let mut pnl = (*target_price - current_price) / current_price;
                            if !is_long { pnl = -pnl; }
                            sim_pnl += pnl * weight;
                        } else {
                            all_hit = false;
                        }
                    }
                }
                if all_hit { break; }
            }

            if !hit_sl {
                for (i, (_, weight)) in targets.iter().enumerate() {
                    if !targets_hit[i] {
                        let mut pnl = (price - current_price) / current_price;
                        if !is_long { pnl = -pnl; }
                        sim_pnl += pnl * weight;
                    }
                }
            }

            let success = targets_hit[0] && !hit_sl; 
            (success, sim_pnl)
        })
        .collect();

    let success_count = results.iter().filter(|(s, _)| *s).count();
    let total_pnl: f64 = results.iter().map(|(_, p)| p).sum();
    
    let pos = success_count as f64 / num_simulations as f64;
    let avg_pnl = total_pnl / num_simulations as f64;
    
    // Normalize EV to ratio scale: 1.0 = breakeven, 1.02 = +2% avg PnL
    // This matches the Python fallback convention where main.py checks ev < 1.0
    Ok((pos, 1.0 + avg_pnl, 0.0))
}

#[pymodule]
fn aladdin_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_rust_version, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_atr_rust, m)?)?;
    m.add_function(wrap_pyfunction!(simulate_monte_carlo, m)?)?;
    Ok(())
}
