"""
SMC Market Structure — CHoCH / BOS Detector
═══════════════════════════════════════════════════════════════════════
Ported from Ahmed-GoCode/Quant-Edge-Indicators
  MSS + CHoCH + BOS.pinescript (Pine Script v5)

Fractal-based Smart Money Concepts:
  - Bull fractal (pivot high): p rising bars → peak → p falling bars
  - Bear fractal (pivot low):  p falling bars → trough → p rising bars

  BOS  (Break of Structure):   close crosses fractal in SAME direction
                                as prevailing structure → continuation
  CHoCH (Change of Character): close crosses fractal in OPPOSITE direction
                                → trend reversal signal

Default fractal length = 5 (p=2).

Usage
-----
    from smc_structure import detect_market_structure

    result = detect_market_structure(df_1h)
    # result = {
    #   'type':          'CHoCH' | 'BOS' | None,
    #   'direction':     'BULL'  | 'BEAR' | None,
    #   'fractal_price': float,
    #   'bars_ago':      int,
    #   'struct_state':  1 | -1 | 0,
    #   'bull_pct':      float,   # fraction of fractals that are bullish
    # }
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Tuple

FRACTAL_LENGTH = 5   # default window (odd number)


def _find_fractals(
    highs: np.ndarray,
    lows:  np.ndarray,
    p:     int = 2,
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    Identify bull (pivot-high) and bear (pivot-low) fractals.

    Bull fractal at bar i: h[i] is max in window [i-p .. i+p],
      preceded by p non-decreasing bars and followed by p non-increasing bars.

    Bear fractal at bar i: l[i] is min in window [i-p .. i+p],
      preceded by p non-increasing bars and followed by p non-decreasing bars.

    Returns (bull_fractals, bear_fractals) as lists of (bar_index, price).
    """
    n = len(highs)
    bull: List[Tuple[int, float]] = []
    bear: List[Tuple[int, float]] = []

    for i in range(2 * p, n):
        fi = i - p          # candidate fractal bar index

        win_h = highs[fi - p: fi + p + 1]
        win_l = lows [fi - p: fi + p + 1]

        # Bull fractal
        if highs[fi] == win_h.max():
            rising  = all(highs[fi - p + k + 1] >= highs[fi - p + k] for k in range(p))
            falling = all(highs[fi + k + 1]      <= highs[fi + k]      for k in range(p))
            if rising and falling:
                bull.append((fi, float(highs[fi])))

        # Bear fractal
        if lows[fi] == win_l.min():
            falling_b = all(lows[fi - p + k + 1] <= lows[fi - p + k] for k in range(p))
            rising_a  = all(lows[fi + k + 1]      >= lows[fi + k]      for k in range(p))
            if falling_b and rising_a:
                bear.append((fi, float(lows[fi])))

    return bull, bear


def detect_market_structure(
    df:     pd.DataFrame,
    length: int = FRACTAL_LENGTH,
) -> dict:
    """
    Detect the most recent CHoCH / BOS event in the given OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: high, low, close. Index is ignored.
    length : int
        Fractal window size (must be odd, ≥ 5).

    Returns
    -------
    dict
        type          : 'CHoCH' | 'BOS' | None
        direction     : 'BULL'  | 'BEAR' | None
        fractal_price : float or None   (price level that was broken)
        bars_ago      : int or None     (bars since event fired)
        struct_state  : 1 | -1 | 0     (1=last structure bullish, -1=bearish)
        bull_pct      : float           (fraction of fractals that are bullish)
    """
    result = {
        'type': None, 'direction': None, 'fractal_price': None,
        'bars_ago': None, 'struct_state': 0, 'bull_pct': 0.5,
    }

    if df is None or len(df) < length * 4:
        return result

    try:
        highs  = df['high'].values.astype(float)
        lows   = df['low'].values.astype(float)
        closes = df['close'].values.astype(float)
        n      = len(closes)
        p      = length // 2

        bull_fractals, bear_fractals = _find_fractals(highs, lows, p)

        if not bull_fractals and not bear_fractals:
            return result

        total_f = len(bull_fractals) + len(bear_fractals)
        result['bull_pct'] = len(bull_fractals) / total_f if total_f > 0 else 0.5

        # Merge and sort all fractals chronologically
        all_events = (
            [(idx, val, 'bull') for idx, val in bull_fractals] +
            [(idx, val, 'bear') for idx, val in bear_fractals]
        )
        all_events.sort(key=lambda x: x[0])

        struct_state      = 0
        last_event_type   = None
        last_event_dir    = None
        last_event_bar    = None
        last_event_price  = None

        # Track active (uncrossed) fractals
        active_bull: Optional[list] = None   # [bar_idx, value, crossed]
        active_bear: Optional[list] = None

        for frac_idx, frac_val, frac_kind in all_events:
            if frac_kind == 'bull':
                active_bull = [frac_idx, frac_val, False]
            else:
                active_bear = [frac_idx, frac_val, False]

            start = frac_idx + 1

            if frac_kind == 'bull' and active_bull and not active_bull[2]:
                for ci in range(start, n):
                    prev_close = closes[ci - 1] if ci > 0 else closes[ci]
                    if closes[ci] > active_bull[1] and prev_close <= active_bull[1]:
                        lbl = 'CHoCH' if struct_state == -1 else 'BOS'
                        struct_state      = 1
                        active_bull[2]    = True
                        last_event_type   = lbl
                        last_event_dir    = 'BULL'
                        last_event_bar    = ci
                        last_event_price  = active_bull[1]
                        break

            elif frac_kind == 'bear' and active_bear and not active_bear[2]:
                for ci in range(start, n):
                    prev_close = closes[ci - 1] if ci > 0 else closes[ci]
                    if closes[ci] < active_bear[1] and prev_close >= active_bear[1]:
                        lbl = 'CHoCH' if struct_state == 1 else 'BOS'
                        struct_state      = -1
                        active_bear[2]    = True
                        last_event_type   = lbl
                        last_event_dir    = 'BEAR'
                        last_event_bar    = ci
                        last_event_price  = active_bear[1]
                        break

        result['type']          = last_event_type
        result['direction']     = last_event_dir
        result['fractal_price'] = last_event_price
        result['bars_ago']      = (n - 1 - last_event_bar) if last_event_bar is not None else None
        result['struct_state']  = struct_state

    except Exception:
        pass

    return result
