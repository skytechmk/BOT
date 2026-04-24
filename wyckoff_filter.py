"""
Wyckoff Phase Classifier — Lightweight
═══════════════════════════════════════════════════════════════════════
Inspired by srlcarlg/srl-python-indicators WeisWyckoffSystem (MIT)

Classifies current market phase using the Wyckoff core principle:
  Volume (Effort) vs Price (Result)

Phases
------
  ACCUMULATION  — price flat/declining, volume contracting
                  Smart money absorbing supply quietly.
  MARKUP        — price rising, volume expanding
                  Demand exceeds supply; trend underway.
  DISTRIBUTION  — price flat/rising, volume contracting
                  Smart money selling into strength; supply > demand.
  MARKDOWN      — price declining, volume expanding
                  Panic selling; supply floods market.
  UNCERTAIN     — mixed signals, no dominant phase.

Usage
-----
    from wyckoff_filter import classify_wyckoff_phase

    result = classify_wyckoff_phase(df_1h)
    # result = {
    #   'phase':        'MARKUP',
    #   'confidence':   0.72,
    #   'effort_ratio': 1.43,    # recent vol / MA vol
    #   'price_slope':  0.0082,  # EMA20 slope normalised
    #   'efr':          0.61,    # effort-vs-result ratio
    #   'description':  '...',
    # }
"""

import numpy as np
import pandas as pd


_DESCRIPTIONS = {
    'MARKUP':       'Expanding volume + rising price — strong demand in control',
    'DISTRIBUTION': 'Rising price + contracting volume — supply absorbing bid, watch for reversal',
    'MARKDOWN':     'Expanding volume + falling price — selling pressure dominant',
    'ACCUMULATION': 'Falling price + contracting volume — smart money absorbing supply quietly',
    'UNCERTAIN':    'Mixed volume-price signals — no dominant Wyckoff phase',
}


def classify_wyckoff_phase(
    df:       pd.DataFrame,
    lookback: int = 30,
) -> dict:
    """
    Classify the current Wyckoff market phase from OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: open, high, low, close, volume.
    lookback : int
        Bars used for volume MA and EMA slope comparison (default 30).

    Returns
    -------
    dict
        phase        : str
        confidence   : float (0–1)
        effort_ratio : float   (recent 5-bar vol / lookback vol MA)
        price_slope  : float   (EMA20 slope, normalised)
        efr          : float   (Effort-vs-Result ratio)
        description  : str
    """
    result = {
        'phase':        'UNCERTAIN',
        'confidence':   0.0,
        'effort_ratio': 1.0,
        'price_slope':  0.0,
        'efr':          1.0,
        'description':  _DESCRIPTIONS['UNCERTAIN'],
    }

    needed = max(lookback, 30)
    if df is None or len(df) < needed:
        return result

    try:
        opens   = df['open'].values.astype(float)
        highs   = df['high'].values.astype(float)
        lows    = df['low'].values.astype(float)
        closes  = df['close'].values.astype(float)
        volumes = df['volume'].values.astype(float)
        n       = len(closes)

        # ── EMA-20 slope ──────────────────────────────────────────────
        ema_p  = 20
        alpha  = 2.0 / (ema_p + 1)
        ema    = np.empty(n)
        ema[0] = closes[0]
        for i in range(1, n):
            ema[i] = alpha * closes[i] + (1.0 - alpha) * ema[i - 1]

        ema_now  = ema[-1]
        ema_prev = ema[max(0, n - lookback)]
        # Normalised slope (fraction of price moved per lookback period)
        price_slope = (ema_now - ema_prev) / (ema_prev + 1e-10)

        # ── Volume effort ratio ────────────────────────────────────────
        vol_ma       = float(np.mean(volumes[-lookback:]))
        vol_recent   = float(np.mean(volumes[-5:]))      # 5-bar smoothing
        effort_ratio = vol_recent / (vol_ma + 1e-10)

        # ── True-range ATR (last 14 bars) ─────────────────────────────
        ab = min(15, n)
        h_sl = highs[-ab:]
        l_sl = lows[-ab:]
        c_sl = closes[-ab:]
        c_prev = np.roll(c_sl, 1)
        c_prev[0] = c_sl[0]
        tr = np.maximum(h_sl - l_sl,
             np.maximum(np.abs(h_sl - c_prev),
                        np.abs(l_sl - c_prev)))
        atr = float(np.mean(tr[1:]))   # skip first roll artefact

        # ── Effort-vs-Result ratio (Wyckoff core) ─────────────────────
        # Body size in last 3 bars normalised by ATR, weighted by effort
        recent_body = float(np.mean(np.abs(closes[-3:] - opens[-3:])))
        efr = (recent_body / (atr + 1e-10)) / (effort_ratio + 1e-10)
        # High EFR → price moves efficiently per unit of volume (trending)
        # Low  EFR → lots of volume, small price movement (absorption)

        # ── Phase classification ───────────────────────────────────────
        slope_thresh  = 0.005   # ~0.5% over lookback to call directional
        vol_exp_thresh = 1.15
        vol_cnt_thresh = 0.85

        price_up   = price_slope >  slope_thresh
        price_dn   = price_slope < -slope_thresh
        price_flat = not price_up and not price_dn
        vol_expand = effort_ratio > vol_exp_thresh
        vol_contct = effort_ratio < vol_cnt_thresh

        phase      = 'UNCERTAIN'
        confidence = 0.25

        if price_up and vol_expand:
            phase      = 'MARKUP'
            confidence = min(0.50 + abs(price_slope) * 25 + (effort_ratio - 1.0) * 0.40, 0.95)

        elif price_up and vol_contct:
            phase      = 'DISTRIBUTION'
            confidence = min(0.40 + abs(price_slope) * 18 + (1.0 - effort_ratio) * 0.40, 0.90)

        elif price_dn and vol_expand:
            phase      = 'MARKDOWN'
            confidence = min(0.50 + abs(price_slope) * 25 + (effort_ratio - 1.0) * 0.40, 0.95)

        elif price_dn and vol_contct:
            phase      = 'ACCUMULATION'
            confidence = min(0.40 + abs(price_slope) * 18 + (1.0 - effort_ratio) * 0.40, 0.90)

        elif price_flat and vol_expand:
            # High volume, no net price move = absorption (phase depends on context)
            phase      = 'ACCUMULATION' if closes[-1] < ema_now else 'DISTRIBUTION'
            confidence = 0.35

        elif price_flat and vol_contct:
            phase      = 'UNCERTAIN'
            confidence = 0.20

        # Low EFR (absorption) boosts confidence in accumulation/distribution
        if phase in ('ACCUMULATION', 'DISTRIBUTION') and efr < 0.50:
            confidence = min(confidence + 0.15, 0.95)

        result = {
            'phase':        phase,
            'confidence':   round(confidence, 3),
            'effort_ratio': round(effort_ratio, 3),
            'price_slope':  round(price_slope, 4),
            'efr':          round(efr, 3),
            'description':  _DESCRIPTIONS.get(phase, ''),
        }

    except Exception:
        pass

    return result


def wyckoff_sqi_score(phase_result: dict, is_long: bool) -> tuple:
    """
    Convert a classify_wyckoff_phase() result to an SQI score contribution.

    Scoring logic
    -------------
    Signal LONG:
      MARKUP (high conf)        → +7 pts  (demand in control, go with it)
      ACCUMULATION (high conf)  → +5 pts  (smart money loading)
      DISTRIBUTION              → -4 pts  (supply building, likely to reverse)
      MARKDOWN                  → -4 pts  (selling pressure, wrong side)

    Signal SHORT: mirror of above.
    Moderate confidence halves the score. UNCERTAIN → 0.

    Returns (score: int, flag: str | None)
    """
    if not phase_result or phase_result['phase'] == 'UNCERTAIN':
        return 0, None

    phase = phase_result['phase']
    conf  = phase_result['confidence']

    bull_phases  = ('MARKUP', 'ACCUMULATION')
    bear_phases  = ('MARKDOWN', 'DISTRIBUTION')
    top_phases   = ('MARKUP', 'MARKDOWN')      # highest score
    base_phases  = ('ACCUMULATION', 'DISTRIBUTION')

    aligned = (is_long and phase in bull_phases) or (not is_long and phase in bear_phases)
    opposed = (is_long and phase in bear_phases) or (not is_long and phase in bull_phases)

    score = 0
    flag  = None

    if aligned:
        if phase in top_phases:
            base = 7 if conf >= 0.60 else 4 if conf >= 0.40 else 2
        else:
            base = 5 if conf >= 0.60 else 3 if conf >= 0.40 else 1
        score = base
        flag  = f'WYCKOFF:{phase}({conf:.2f})'

    elif opposed:
        base  = -4 if conf >= 0.55 else -2
        score = base
        flag  = f'WYCKOFF_AGAINST:{phase}({conf:.2f})'

    return score, flag
