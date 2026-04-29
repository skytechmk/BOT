"""
PREDATOR — Positioning Regime Entry Detection with Adaptive Threshold Optimization and Risk
═══════════════════════════════════════════════════════════════════════════════════════════

Enhancement layer that wraps around the Reverse Hunt state machine.
RH core (TSI + CE) is UNTOUCHED — PREDATOR adds:

  Layer 1: Regime Detection    — ATR ratio + trend clarity → 6 market states
  Layer 2: Positioning         — Funding momentum, OI divergence, taker delta
  Layer 3: Stop Hunt Detector  — Wick sweep + volume + level reclaim
  Layer 4: SQI v2 integration  — Positioning score added to signal quality

Usage in main.py:
  regime  = detect_regime(df_1h)
  pos     = analyze_positioning(funding_data, oi_data, df_1h)
  hunt    = detect_stop_hunt(df_1h)
  # Feed regime + positioning into SQI v2 and sizing decisions
"""

import numpy as np
import pandas as pd
from typing import TypedDict, Optional, Dict, Tuple, Any
from utils_logger import log_message

class RegimeParams(TypedDict):
    allow_entry: bool
    sqi_modifier: int
    size_multiplier: float
    tp_mode: str

class RegimeDict(TypedDict):
    regime: str
    atr_ratio: float
    trend_clarity: float
    vol_state: str
    trend_state: str
    trend_dir: str
    params: RegimeParams
    # ML governance — downstream modules MUST consume these fields (v3)
    ml_confidence: float        # 0.0–1.0, injected by signal pipeline
    ml_prediction: str          # 'LONG' | 'SHORT' | 'NEUTRAL'

class PositioningDict(TypedDict):
    funding_momentum: float
    oi_divergence: str
    taker_delta: float
    positioning_bias: str
    positioning_score: int
    crowd_direction: str
    components: Dict[str, str]
    # ML governance — downstream modules MUST consume these fields (v3)
    ml_confidence: float        # 0.0–1.0, injected by signal pipeline
    ml_prediction: str          # 'LONG' | 'SHORT' | 'NEUTRAL'

class StopHuntDict(TypedDict):
    hunt_detected: bool
    direction: str
    strength: str
    score: int

class LiquidationMagnetsDict(TypedDict):
    closest_long_liq: float
    closest_short_liq: float
    dist_long_pct: float
    dist_short_pct: float
    magnet_bias: str
    imbalance: float


# ══════════════════════════════════════════════════════════════════════
#  LAYER 1: REGIME DETECTION
# ══════════════════════════════════════════════════════════════════════

# Regime constants
REGIME_COMPRESSION   = 'COMPRESSION'    # Coiling + Range → breakout imminent
REGIME_TREND_PAUSE   = 'TREND_PAUSE'    # Coiling + Trend → continuation likely
REGIME_CHOP          = 'CHOP'           # Normal + Range → avoid or scalp
REGIME_CLEAN_TREND   = 'CLEAN_TREND'    # Normal + Trend → bread and butter
REGIME_VOLATILE_CHOP = 'VOLATILE_CHOP'  # Expanding + Range → skip
REGIME_PARABOLIC     = 'PARABOLIC'      # Expanding + Trend → fade or ride

# Regime parameters for signal pipeline
REGIME_PARAMS = {
    REGIME_COMPRESSION: {
        'allow_entry': True,
        'stop_atr_mult': 1.5,   # Tight stops — breakout or nothing
        'target_atr_mult': 4.0, # Wide targets — catch the breakout
        'size_mult': 1.0,       # Full size — high conviction setups
        'skip_reason': None,
    },
    REGIME_TREND_PAUSE: {
        'allow_entry': True,
        'stop_atr_mult': 2.0,
        'target_atr_mult': 3.0,
        'size_mult': 0.75,
        'skip_reason': None,
    },
    REGIME_CHOP: {
        'allow_entry': True,     # Allow but reduce heavily
        'stop_atr_mult': 1.5,
        'target_atr_mult': 2.0,
        'size_mult': 0.35,       # Very small position in chop
        'skip_reason': None,
    },
    REGIME_CLEAN_TREND: {
        'allow_entry': True,
        'stop_atr_mult': 2.5,   # Standard stops
        'target_atr_mult': 3.0,
        'size_mult': 1.0,       # Full size
        'skip_reason': None,
    },
    REGIME_VOLATILE_CHOP: {
        'allow_entry': False,    # SKIP — no edge in volatile chop
        'stop_atr_mult': 0,
        'target_atr_mult': 0,
        'size_mult': 0,
        'skip_reason': 'VOLATILE_CHOP regime — no tradable edge',
    },
    REGIME_PARABOLIC: {
        'allow_entry': True,     # Allow but only countertrend (RH is mean-reversion anyway)
        'stop_atr_mult': 1.5,   # Tight — parabolic moves are violent
        'target_atr_mult': 3.5,
        'size_mult': 0.50,
        'skip_reason': None,
    },
}


def detect_regime(df: pd.DataFrame, atr_fast: int = 7, atr_slow: int = 21,
                  ema_len: int = 50, atr_base: int = 14) -> RegimeDict:
    """
    Classify market regime from OHLCV data.

    Returns dict with:
      'regime': one of 6 REGIME_* constants
      'atr_ratio': float (ATR7/ATR21)
      'trend_clarity': float (|close-EMA50| / ATR14)
      'vol_state': 'COILING' | 'NORMAL' | 'EXPANDING'
      'trend_state': 'STRONG_TREND' | 'WEAK_TREND' | 'RANGE'
      'params': dict from REGIME_PARAMS
    """
    if df is None or len(df) < max(atr_slow, ema_len, atr_base) + 5:
        return _default_regime()

    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)

    # True Range
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))

    # ATR via RMA (Wilder's smoothing)
    def rma(values, period):
        result = np.full(len(values), np.nan)
        if len(values) < period:
            return result
        result[period - 1] = np.mean(values[:period])
        alpha = 1.0 / period
        for i in range(period, len(values)):
            result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
        return result

    atr_f = rma(tr, atr_fast)
    atr_s = rma(tr, atr_slow)
    atr_b = rma(tr, atr_base)

    # Get latest valid values
    atr_fast_val = atr_f[-1] if not np.isnan(atr_f[-1]) else 0
    atr_slow_val = atr_s[-1] if not np.isnan(atr_s[-1]) else 1
    atr_base_val = atr_b[-1] if not np.isnan(atr_b[-1]) else 1

    # ATR Ratio: volatility regime
    atr_ratio = atr_fast_val / atr_slow_val if atr_slow_val > 0 else 1.0

    if atr_ratio < 0.7:
        vol_state = 'COILING'
    elif atr_ratio <= 1.3:
        vol_state = 'NORMAL'
    else:
        vol_state = 'EXPANDING'

    # EMA50
    ema = pd.Series(close).ewm(span=ema_len, adjust=False).mean().values
    ema_val = ema[-1]

    # Trend Clarity: |close - EMA50| / ATR14
    trend_clarity = abs(close[-1] - ema_val) / atr_base_val if atr_base_val > 0 else 0

    if trend_clarity > 3.0:
        trend_state = 'STRONG_TREND'
    elif trend_clarity >= 1.0:
        trend_state = 'WEAK_TREND'
    else:
        trend_state = 'RANGE'

    # Regime matrix
    regime_map = {
        ('COILING', 'RANGE'):        REGIME_COMPRESSION,
        ('COILING', 'WEAK_TREND'):   REGIME_TREND_PAUSE,
        ('COILING', 'STRONG_TREND'): REGIME_TREND_PAUSE,
        ('NORMAL',  'RANGE'):        REGIME_CHOP,
        ('NORMAL',  'WEAK_TREND'):   REGIME_CLEAN_TREND,
        ('NORMAL',  'STRONG_TREND'): REGIME_CLEAN_TREND,
        ('EXPANDING', 'RANGE'):      REGIME_VOLATILE_CHOP,
        ('EXPANDING', 'WEAK_TREND'): REGIME_PARABOLIC,
        ('EXPANDING', 'STRONG_TREND'): REGIME_PARABOLIC,
    }

    regime = regime_map.get((vol_state, trend_state), REGIME_CHOP)

    # Trend direction for positioning alignment
    trend_dir = 'UP' if close[-1] > ema_val else 'DOWN'

    return {
        'regime': regime,
        'atr_ratio': round(atr_ratio, 3),
        'trend_clarity': round(trend_clarity, 2),
        'vol_state': vol_state,
        'trend_state': trend_state,
        'trend_dir': trend_dir,
        'params': REGIME_PARAMS[regime],
    }


def _default_regime() -> RegimeDict:
    return {
        'regime': REGIME_CLEAN_TREND,
        'atr_ratio': 1.0,
        'trend_clarity': 1.5,
        'vol_state': 'NORMAL',
        'trend_state': 'WEAK_TREND',
        'trend_dir': 'UP',
        'params': REGIME_PARAMS[REGIME_CLEAN_TREND],
    }


# ══════════════════════════════════════════════════════════════════════
#  LAYER 2: POSITIONING (Crypto-Native)
# ══════════════════════════════════════════════════════════════════════

def analyze_positioning(funding_data: dict, oi_data: dict,
                        df: pd.DataFrame) -> PositioningDict:
    """
    Analyze market positioning using crypto-native data.

    Args:
        funding_data: from analyze_funding_rate_sentiment()
        oi_data: from get_open_interest_change()
        df: 1h OHLCV with taker_buy_base_asset_volume

    Returns dict with:
      'funding_momentum': float (-1 to +1, negative = shorts crowding)
      'oi_divergence': str (ACCUMULATION, SHORT_SQUEEZE, DISTRIBUTION, LONG_SQUEEZE, NEUTRAL)
      'taker_delta': float (positive = buy pressure, negative = sell pressure)
      'positioning_bias': 'LONG' | 'SHORT' | 'NEUTRAL'
      'positioning_score': int (0-20 for SQI v2)
      'crowd_direction': 'LONG' | 'SHORT' | 'NEUTRAL' (where crowd IS, not where to trade)
    """
    score = 0
    components = {}

    # ── Funding Rate Momentum ──
    funding_rate = funding_data.get('funding_rate', 0)
    funding_signal = funding_data.get('signal_bias', 'NONE')
    extreme_funding = funding_data.get('extreme_funding', False)

    # Interpret: negative funding = shorts paying longs = shorts crowded
    if funding_rate < -0.0005:
        funding_mom = -1.0  # shorts very crowded
        components['funding'] = 'SHORTS_CROWDED'
    elif funding_rate < -0.0001:
        funding_mom = -0.5
        components['funding'] = 'SHORTS_LEANING'
    elif funding_rate > 0.0005:
        funding_mom = 1.0   # longs very crowded
        components['funding'] = 'LONGS_CROWDED'
    elif funding_rate > 0.0001:
        funding_mom = 0.5
        components['funding'] = 'LONGS_LEANING'
    else:
        funding_mom = 0.0
        components['funding'] = 'NEUTRAL'

    # ── OI Divergence ──
    oi_change = oi_data.get('oi_change', 0)
    close_vals = df['close'].values.astype(float) if df is not None and len(df) > 5 else None

    if close_vals is not None and len(close_vals) >= 6:
        price_change = (close_vals[-1] / close_vals[-6]) - 1  # 5-bar price change
    else:
        price_change = 0

    # Divergence matrix
    if price_change > 0.005 and oi_change > 0.01:
        oi_div = 'ACCUMULATION'      # Real buying — continuation
    elif price_change > 0.005 and oi_change < -0.01:
        oi_div = 'SHORT_SQUEEZE'     # Shorts closing — will exhaust
    elif price_change < -0.005 and oi_change > 0.01:
        oi_div = 'DISTRIBUTION'      # Real selling — continuation
    elif price_change < -0.005 and oi_change < -0.01:
        oi_div = 'LONG_SQUEEZE'      # Longs closing — will exhaust
    else:
        oi_div = 'NEUTRAL'

    components['oi_divergence'] = oi_div

    # ── Taker Volume Delta ──
    taker_delta = 0.0
    if df is not None and 'taker_buy_base_asset_volume' in df.columns and len(df) >= 12:
        taker_buy = df['taker_buy_base_asset_volume'].astype(float).iloc[-12:].sum()
        total_vol = df['volume'].astype(float).iloc[-12:].sum()
        taker_sell = total_vol - taker_buy
        taker_delta = (taker_buy - taker_sell) / total_vol if total_vol > 0 else 0
    components['taker_delta'] = round(taker_delta, 4)

    # ── Composite Positioning ──
    # Determine where the CROWD is positioned (we want to trade AGAINST the crowd)
    crowd_long_signals = 0
    crowd_short_signals = 0

    # Funding: negative funding → crowd is short
    if funding_mom < -0.3:
        crowd_short_signals += 1
    elif funding_mom > 0.3:
        crowd_long_signals += 1

    # OI Divergence: squeeze = crowd getting wiped out
    if oi_div == 'LONG_SQUEEZE':
        crowd_long_signals += 1  # crowd was long, getting squeezed
    elif oi_div == 'SHORT_SQUEEZE':
        crowd_short_signals += 1  # crowd was short, getting squeezed

    # Taker delta: high buy delta = crowd buying
    if taker_delta > 0.08:
        crowd_long_signals += 1
    elif taker_delta < -0.08:
        crowd_short_signals += 1

    if crowd_long_signals > crowd_short_signals:
        crowd_direction = 'LONG'
    elif crowd_short_signals > crowd_long_signals:
        crowd_direction = 'SHORT'
    else:
        crowd_direction = 'NEUTRAL'

    # Positioning bias (contrarian: trade AGAINST the crowd)
    if crowd_direction == 'LONG':
        pos_bias = 'SHORT'  # crowd is long → fade them
    elif crowd_direction == 'SHORT':
        pos_bias = 'LONG'   # crowd is short → squeeze them
    else:
        pos_bias = 'NEUTRAL'

    # ── Positioning Score for SQI v2 (0-20) ──
    # Score for how strongly positioning aligns with a given signal direction
    # This will be evaluated in signal_quality.py against the actual signal direction

    # Funding alignment (0-5)
    if extreme_funding:
        score += 5  # Extreme funding is strongest positioning signal
    elif abs(funding_mom) >= 0.5:
        score += 3
    elif abs(funding_mom) >= 0.3:
        score += 1

    # OI Divergence (0-10) — highest weight, most predictive
    if oi_div in ('SHORT_SQUEEZE', 'LONG_SQUEEZE'):
        score += 10  # Squeeze = imminent reversal
    elif oi_div in ('ACCUMULATION', 'DISTRIBUTION'):
        score += 5   # Real flow — continuation

    # Taker delta (0-5)
    abs_delta = abs(taker_delta)
    if abs_delta > 0.10:
        score += 5
    elif abs_delta > 0.05:
        score += 3
    elif abs_delta > 0.02:
        score += 1

    return {
        'funding_momentum': round(funding_mom, 2),
        'oi_divergence': oi_div,
        'oi_change': round(oi_change, 4),
        'price_change_5h': round(price_change, 4),
        'taker_delta': round(taker_delta, 4),
        'positioning_bias': pos_bias,
        'crowd_direction': crowd_direction,
        'positioning_score': min(score, 20),
        'components': components,
    }


def positioning_aligns(positioning: dict, signal_direction: str) -> tuple:
    """
    Check if positioning data aligns with signal direction.

    Returns (aligned: bool, score_for_sqi: int 0-20)
    """
    pos_bias = positioning.get('positioning_bias', 'NEUTRAL')
    base_score = positioning.get('positioning_score', 0)

    if pos_bias == 'NEUTRAL':
        return True, base_score // 2  # Neutral = half credit

    aligned = pos_bias == signal_direction.upper()

    if aligned:
        return True, base_score  # Full score
    else:
        return False, 0  # No credit — positioning disagrees


# ══════════════════════════════════════════════════════════════════════
#  LAYER 3: STOP HUNT DETECTOR
# ══════════════════════════════════════════════════════════════════════

def detect_stop_hunt(df: pd.DataFrame, lookback: int = 20,
                     wick_ratio: float = 3.0,
                     vol_mult: float = 2.0) -> StopHuntDict:
    """
    Detect when price swept a key level and immediately rejected.
    Institutional entry pattern: retail stops get taken out, then smart
    money enters in opposite direction.

    Criteria (all must be true for a confirmed hunt):
      1. Current candle wick > wick_ratio × body
      2. Wick pierced a swing high/low from last lookback bars
      3. Volume on this candle > vol_mult × SMA(20) volume
      4. Close is back INSIDE the range (didn't break out)

    Returns dict with:
      'hunt_detected': bool
      'hunt_type': 'LONG_HUNT' | 'SHORT_HUNT' | None
      'wick_ratio': float
      'vol_ratio': float
      'swept_level': float (the level that was swept)
    """
    result = {
        'hunt_detected': False,
        'hunt_type': None,
        'wick_ratio': 0,
        'vol_ratio': 0,
        'swept_level': 0,
    }

    if df is None or len(df) < lookback + 2:
        return result

    candle = df.iloc[-1]
    body = abs(float(candle['close']) - float(candle['open']))
    if body < 1e-10:
        body = 1e-10  # prevent division by zero on doji

    upper_wick = float(candle['high']) - max(float(candle['open']), float(candle['close']))
    lower_wick = min(float(candle['open']), float(candle['close'])) - float(candle['low'])

    # Volume check
    vol_sma = df['volume'].astype(float).iloc[-lookback - 1:-1].mean()
    curr_vol = float(candle['volume'])
    vol_r = curr_vol / vol_sma if vol_sma > 0 else 1.0

    # Recent swing levels (excluding current candle)
    recent = df.iloc[-lookback - 1:-1]
    recent_low = float(recent['low'].min())
    recent_high = float(recent['high'].max())

    # ── Downside Hunt: long lower wick, swept recent low, closed above ──
    if (lower_wick > wick_ratio * body and
        float(candle['low']) < recent_low and
        float(candle['close']) > recent_low and
        vol_r >= vol_mult):
        result['hunt_detected'] = True
        result['hunt_type'] = 'LONG_HUNT'
        result['wick_ratio'] = round(lower_wick / body, 1)
        result['vol_ratio'] = round(vol_r, 2)
        result['swept_level'] = recent_low

    # ── Upside Hunt: long upper wick, swept recent high, closed below ──
    elif (upper_wick > wick_ratio * body and
          float(candle['high']) > recent_high and
          float(candle['close']) < recent_high and
          vol_r >= vol_mult):
        result['hunt_detected'] = True
        result['hunt_type'] = 'SHORT_HUNT'
        result['wick_ratio'] = round(upper_wick / body, 1)
        result['vol_ratio'] = round(vol_r, 2)
        result['swept_level'] = recent_high

    return result


# ══════════════════════════════════════════════════════════════════════
#  LAYER 2b: LIQUIDATION MAGNET DETECTOR
# ══════════════════════════════════════════════════════════════════════

# Common retail leverage tiers → approximate liquidation distance from entry
# Formula: liq_distance ≈ 1 / leverage (simplified, tightened for maint margin + fees)
_LEVERAGE_TIERS = {
    '5x':  0.180,   # ~18% from entry
    '10x': 0.090,   # ~9%
    '20x': 0.045,   # ~4.5%
    '25x': 0.038,   # ~3.8%
    '50x': 0.019,   # ~1.9%
    '75x': 0.012,   # ~1.2%
    '100x': 0.009,  # ~0.9%
}

# Weight per tier — higher leverage = more traders = denser cluster
_TIER_WEIGHTS = {
    '5x':  0.5,
    '10x': 1.5,
    '20x': 3.0,   # Most common retail tier
    '25x': 2.5,
    '50x': 2.0,
    '75x': 1.0,
    '100x': 0.5,
}


def _find_swing_points(df: pd.DataFrame, left: int = 5, right: int = 2) -> dict:
    """
    Find swing highs and lows using vectorised pivot detection.

    A swing high: bar whose high strictly exceeds every other high in the
    window [i-left, i+right].
    A swing low:  bar whose low is strictly below every other low in the
    same window.

    Uses NumPy ``sliding_window_view`` (O(N) memory, O(N * W) vectorised
    comparison) — zero Python‑level loops.

    Returns ``{'highs': list[float], 'lows': list[float]}``.
    """
    highs = df['high'].values.astype(float)
    lows  = df['low'].values.astype(float)
    n = len(highs)
    W = left + right + 1
    if n < W:
        return {'highs': [], 'lows': []}

    from numpy.lib.stride_tricks import sliding_window_view

    h_win = sliding_window_view(highs, W)
    l_win = sliding_window_view(lows,  W)
    center = left

    # Boolean mask: exclude the centre column from the comparison so we
    # can check "strictly greater / less than ALL other neighbours".
    mask_cols = np.ones(W, dtype=bool)
    mask_cols[center] = False

    h_c = h_win[:, center, None]   # (m, 1)  — centre of each window
    l_c = l_win[:, center, None]

    mask_highs = (h_win[:, mask_cols] < h_c).all(axis=1)
    mask_lows  = (l_win[:, mask_cols] > l_c).all(axis=1)

    return {
        'highs': h_win[mask_highs, center].tolist(),
        'lows':  l_win[mask_lows,  center].tolist(),
    }


def detect_liquidation_magnets(df: pd.DataFrame, current_price: float,
                               lookback: int = 100,
                               cluster_tolerance: float = 0.005) -> LiquidationMagnetsDict:
    """
    Identify liquidation clusters near current price.

    Logic:
      1. Find swing highs/lows (where retail traders entered positions)
      2. For each swing point, project liquidation levels at common leverage tiers
         - Longs entered at swing lows → liquidated BELOW entry at 1/leverage distance
         - Shorts entered at swing highs → liquidated ABOVE entry at 1/leverage distance
      3. Cluster nearby liquidation levels (within tolerance)
      4. Score clusters by density (more overlapping levels = stronger magnet)
      5. Return nearest cluster above and below current price

    Args:
        df: 1h OHLCV DataFrame
        current_price: Current market price
        lookback: Number of bars to search for swing points
        cluster_tolerance: % distance to merge nearby levels into one cluster

    Returns dict with:
      'magnets_above': list of {'level', 'density', 'type'} sorted by proximity
      'magnets_below': list of {'level', 'density', 'type'} sorted by proximity
      'nearest_above': {'level', 'density', 'distance_pct'} or None
      'nearest_below': {'level', 'density', 'distance_pct'} or None
      'magnet_bias': 'LONG' | 'SHORT' | 'NEUTRAL' (direction of nearest densest)
      'magnet_score': int (0-10 for positioning score boost)
    """
    default_result = {
        'magnets_above': [],
        'magnets_below': [],
        'nearest_above': None,
        'nearest_below': None,
        'magnet_bias': 'NEUTRAL',
        'magnet_score': 0,
    }

    if df is None or len(df) < lookback or current_price <= 0:
        return default_result

    # Use last N bars for swing detection
    df_window = df.iloc[-lookback:]
    swings = _find_swing_points(df_window)

    if not swings['highs'] and not swings['lows']:
        return default_result

    # ── Project liquidation levels ──
    raw_liq_levels = []

    for swing_low in swings['lows']:
        # Longs entered at swing lows → liquidated BELOW
        for tier_name, liq_dist in _LEVERAGE_TIERS.items():
            liq_price = swing_low * (1 - liq_dist)
            weight = _TIER_WEIGHTS[tier_name]
            raw_liq_levels.append({
                'level': liq_price,
                'weight': weight,
                'source': 'LONG_LIQ',
            })

    for swing_high in swings['highs']:
        # Shorts entered at swing highs → liquidated ABOVE
        for tier_name, liq_dist in _LEVERAGE_TIERS.items():
            liq_price = swing_high * (1 + liq_dist)
            weight = _TIER_WEIGHTS[tier_name]
            raw_liq_levels.append({
                'level': liq_price,
                'weight': weight,
                'source': 'SHORT_LIQ',
            })

    if not raw_liq_levels:
        return default_result

    # ── Cluster nearby levels ──
    raw_liq_levels.sort(key=lambda x: x['level'])

    clusters = []
    cur_cluster = {
        'levels': [raw_liq_levels[0]],
        'center': raw_liq_levels[0]['level'],
        'density': raw_liq_levels[0]['weight'],
        'types': {raw_liq_levels[0]['source']},
    }

    for liq in raw_liq_levels[1:]:
        dist = abs(liq['level'] - cur_cluster['center']) / cur_cluster['center']
        if dist <= cluster_tolerance:
            cur_cluster['levels'].append(liq)
            cur_cluster['density'] += liq['weight']
            cur_cluster['types'].add(liq['source'])
            total_w = sum(l['weight'] for l in cur_cluster['levels'])
            cur_cluster['center'] = sum(
                l['level'] * l['weight'] for l in cur_cluster['levels']
            ) / total_w if total_w > 0 else liq['level']
        else:
            clusters.append(cur_cluster)
            cur_cluster = {
                'levels': [liq],
                'center': liq['level'],
                'density': liq['weight'],
                'types': {liq['source']},
            }
    clusters.append(cur_cluster)

    # ── Split into above/below current price ──
    above = []
    below = []
    for c in clusters:
        dist_pct = (c['center'] - current_price) / current_price * 100
        entry = {
            'level': round(c['center'], 6),
            'density': round(c['density'], 1),
            'distance_pct': round(abs(dist_pct), 2),
            'type': 'SHORT_LIQ' if 'SHORT_LIQ' in c['types'] else 'LONG_LIQ',
            'mixed': len(c['types']) > 1,
            'count': len(c['levels']),
        }
        if c['center'] > current_price:
            above.append(entry)
        elif c['center'] < current_price:
            below.append(entry)

    above.sort(key=lambda x: x['distance_pct'])
    below.sort(key=lambda x: x['distance_pct'])

    # Keep only clusters within 15% of current price (tradable range)
    above = [a for a in above if a['distance_pct'] <= 15.0]
    below = [b for b in below if b['distance_pct'] <= 15.0]

    liq_result = {
        'magnets_above': above[:5],
        'magnets_below': below[:5],
        'nearest_above': above[0] if above else None,
        'nearest_below': below[0] if below else None,
        'magnet_bias': 'NEUTRAL',
        'magnet_score': 0,
    }

    # ── Determine magnet bias ──
    # Dense cluster ABOVE → shorts liquidated → LONG bias (squeeze fuel)
    # Dense cluster BELOW → longs liquidated → SHORT bias (cascade fuel)
    top_above_density = above[0]['density'] if above else 0
    top_below_density = below[0]['density'] if below else 0

    # Weight by proximity — closer clusters have more gravitational pull
    above_gravity = top_above_density / (above[0]['distance_pct'] + 0.1) if above else 0
    below_gravity = top_below_density / (below[0]['distance_pct'] + 0.1) if below else 0

    if above_gravity > below_gravity * 1.3:
        liq_result['magnet_bias'] = 'LONG'   # Shorts above will get squeezed
    elif below_gravity > above_gravity * 1.3:
        liq_result['magnet_bias'] = 'SHORT'  # Longs below will cascade

    # ── Magnet Score (0-10) for positioning ──
    max_gravity = max(above_gravity, below_gravity)
    if max_gravity > 50:
        liq_result['magnet_score'] = 10
    elif max_gravity > 30:
        liq_result['magnet_score'] = 8
    elif max_gravity > 15:
        liq_result['magnet_score'] = 6
    elif max_gravity > 5:
        liq_result['magnet_score'] = 4
    elif max_gravity > 1:
        liq_result['magnet_score'] = 2

    return liq_result


def liquidation_aligns(magnets: dict, signal_direction: str) -> tuple:
    """
    Check if liquidation magnets align with signal direction.

    LONG signal + dense cluster ABOVE (shorts liquidated) = ALIGNED (squeeze fuel)
    SHORT signal + dense cluster BELOW (longs liquidated) = ALIGNED (cascade fuel)

    Returns (aligned: bool, score_boost: int 0-10)
    """
    bias = magnets.get('magnet_bias', 'NEUTRAL')
    base_score = magnets.get('magnet_score', 0)

    if bias == 'NEUTRAL':
        return True, base_score // 3

    aligned = bias == signal_direction.upper()
    if aligned:
        return True, base_score
    else:
        return False, 0
