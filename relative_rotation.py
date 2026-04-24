"""
relative_rotation.py — Relative Rotation Graph (RRG) for crypto pairs.

Based on: Julius de Kempenaer's Relative Rotation Graphs (used in RRG-Dashboard).
Tracks RS-Ratio (relative strength vs benchmark) and RS-Momentum (trend of RS-Ratio).

Used to score pairs in the screener: pairs in the "Leading" quadrant (high RS,
rising momentum) get a screener boost; "Lagging" quadrant get penalised.

Quadrants:
  Leading   (RS-Ratio > 100, RS-Momentum > 100) → strong outperformer, accelerating
  Weakening (RS-Ratio > 100, RS-Momentum < 100) → still strong but decelerating
  Lagging   (RS-Ratio < 100, RS-Momentum < 100) → underperformer, decelerating
  Improving (RS-Ratio < 100, RS-Momentum > 100) → underperformer but recovering

Both RS-Ratio and RS-Momentum are Z-score normalised and rescaled to 100 centre.
"""

import numpy as np
import pandas as pd
from typing import Optional
from utils_logger import log_message

# Normalisation window — same as RRG-Dashboard default (252 trading days = 1 year)
_NORM_PERIOD = 252

# Momentum look-forward: how many bars the trailing momentum window covers
_MOMENTUM_PERIOD_LONG  = 252   # 12-month (annual)
_MOMENTUM_PERIOD_SHORT = 21    # 1-month


def _z_normalise(series: pd.Series, period: int, min_periods: int = None) -> pd.Series:
    """Rolling Z-score normalisation, rescaled so mean=100, std=10."""
    mp = min_periods if min_periods is not None else max(5, period // 4)
    roll_mean = series.rolling(period, min_periods=mp).mean()
    roll_std  = series.rolling(period, min_periods=mp).std().replace(0, 1e-12)
    return (series - roll_mean) / roll_std * 10 + 100


def compute_rrg(closes_df: pd.DataFrame, benchmark_col: str = "BTCUSDT",
                norm_period: int = _NORM_PERIOD,
                momentum_long: int = _MOMENTUM_PERIOD_LONG,
                momentum_short: int = _MOMENTUM_PERIOD_SHORT) -> pd.DataFrame:
    """
    Compute RS-Ratio and RS-Momentum for all pairs vs a benchmark.

    Args:
        closes_df: DataFrame with columns = pair symbols, index = datetime.
                   Must include `benchmark_col`.
        benchmark_col: The reference asset (default BTCUSDT).

    Returns:
        DataFrame with columns [pair, rs_ratio, rs_momentum, quadrant, tail_direction]
        — one row per pair (excluding the benchmark itself).
    """
    if benchmark_col not in closes_df.columns:
        log_message(f"[rrg] Benchmark {benchmark_col} not in closes_df")
        return pd.DataFrame()

    bench = closes_df[benchmark_col]
    results = []

    for col in closes_df.columns:
        if col == benchmark_col:
            continue
        try:
            asset    = closes_df[col].dropna()
            b_aligned = bench.reindex(asset.index).dropna()
            asset     = asset.reindex(b_aligned.index)
            if len(asset) < norm_period // 2:
                continue

            # RS Ratio: price / benchmark, normalised
            rs_raw   = asset / b_aligned
            rs_ratio = _z_normalise(rs_raw, norm_period)

            # RS Momentum: (trailing long return - trailing short return) / benchmark,
            # captures acceleration. Use log returns for stability.
            log_rs       = np.log(rs_raw + 1e-12)
            rs_mom_raw   = log_rs - log_rs.shift(momentum_long) - (log_rs - log_rs.shift(momentum_short))
            rs_momentum  = _z_normalise(rs_mom_raw, norm_period)

            ratio_now = float(rs_ratio.iloc[-1])
            mom_now   = float(rs_momentum.iloc[-1])

            # Quadrant
            if ratio_now >= 100 and mom_now >= 100:
                quadrant = "LEADING"
            elif ratio_now >= 100 and mom_now < 100:
                quadrant = "WEAKENING"
            elif ratio_now < 100 and mom_now < 100:
                quadrant = "LAGGING"
            else:
                quadrant = "IMPROVING"

            # Tail direction: where was it 5 bars ago?
            ratio_prev = float(rs_ratio.iloc[-6]) if len(rs_ratio) >= 6 else ratio_now
            mom_prev   = float(rs_momentum.iloc[-6]) if len(rs_momentum) >= 6 else mom_now
            tail_dx    = ratio_now - ratio_prev
            tail_dy    = mom_now   - mom_prev

            results.append({
                "pair":       col,
                "rs_ratio":   round(ratio_now, 2),
                "rs_momentum": round(mom_now, 2),
                "quadrant":   quadrant,
                "tail_dx":    round(tail_dx, 2),
                "tail_dy":    round(tail_dy, 2),
            })
        except Exception as exc:
            log_message(f"[rrg] Error computing RRG for {col}: {exc}")

    return pd.DataFrame(results)


def get_rrg_signal_bonus(pair: str, rrg_df: pd.DataFrame) -> tuple[int, str]:
    """
    Return (score_delta, description) based on where pair sits in the RRG.

    Score deltas:
      LEADING   → +4  (strong outperformer vs BTC, still accelerating)
      WEAKENING → +1  (outperformer but slowing — caution)
      IMPROVING → +2  (recovering — early entry opportunity)
      LAGGING   → -3  (fundamental underperformer vs BTC)
    """
    if rrg_df.empty or pair not in rrg_df["pair"].values:
        return 0, "RRG_UNAVAILABLE"

    row = rrg_df[rrg_df["pair"] == pair].iloc[0]
    q   = row["quadrant"]

    bonus_map = {
        "LEADING":   (4,  f"RRG:LEADING RS={row['rs_ratio']:.0f} Mom={row['rs_momentum']:.0f}"),
        "WEAKENING": (1,  f"RRG:WEAKENING RS={row['rs_ratio']:.0f} Mom={row['rs_momentum']:.0f}"),
        "IMPROVING": (2,  f"RRG:IMPROVING RS={row['rs_ratio']:.0f} Mom={row['rs_momentum']:.0f}"),
        "LAGGING":   (-3, f"RRG:LAGGING RS={row['rs_ratio']:.0f} Mom={row['rs_momentum']:.0f}"),
    }
    return bonus_map.get(q, (0, f"RRG:{q}"))


def top_leading_pairs(rrg_df: pd.DataFrame, n: int = 10) -> list:
    """Return the top N pairs by RS-Ratio in the LEADING quadrant."""
    if rrg_df.empty:
        return []
    leading = rrg_df[rrg_df["quadrant"] == "LEADING"].sort_values("rs_ratio", ascending=False)
    return leading["pair"].head(n).tolist()
