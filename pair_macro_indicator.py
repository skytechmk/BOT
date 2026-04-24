"""
Per-Pair Macro Indicator — Python port of REVERSE HUNT [MTF reg] on chart ticker.

Designed to be used ALONGSIDE usdt_dominance.py. While usdt_dominance gives the
systemic/macro view (USDT.D), this module gives the PAIR'S OWN macro direction
at 2H timeframe. Combined, they provide two-layer confirmation for signals.

Parameters (operator TradingView screenshot, 2026-04-18):
  TSI:    long=69, short=9, scale=14, inverted=False  (NOT inverted for pair)
  LinReg: len=278, norm=69, smooth=39, inverted=True  (INVERTED for pair)
  Levels: L1_UP=+1.3, L1_DN=-1.6  (asymmetric — sensitive OB, stricter OS)
          L2_UP=+2.2, L2_DN=-2.2  (symmetric extremes)

State interpretation (NOT inverted TSI, pair's own momentum):
  TSI > upper_2 (+2.2)  ->  pair extremely overbought   ->  SHORT_MAX_PAIN  (strong SHORT bias)
  TSI > upper   (+1.3)  ->  pair getting overbought     ->  SHORT_PAIN
  TSI < lower   (-1.6)  ->  pair getting oversold       ->  LONG_PAIN
  TSI < lower_2 (-2.2)  ->  pair extremely oversold     ->  LONG_MAX_PAIN   (strong LONG bias)
  otherwise             ->  NEUTRAL

LinReg oscillator (INVERTED — after sign flip):
  > 0  ->  pair in DOWNTREND (3-week macro)  ->  bearish pair regime
  < 0  ->  pair in UPTREND   (3-week macro)  ->  bullish pair regime

This indicator is slow-reacting (278-bar LinReg on 2H = ~3 week trend filter).
Cached per-pair for REFRESH_SEC to avoid recomputation on every scan cycle.
"""
from __future__ import annotations
import time
import threading
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

# ── Operator-spec parameters ──────────────────────────────────────────────────
TSI_LONG        = 69
TSI_SHORT       = 9
TSI_SCALE       = 14.0
TSI_INVERT      = False        # NOT inverted (opposite of USDT.D version)

LINREG_LEN      = 278          # operator spec (vs 270 on USDT.D)
LINREG_NORM     = 69           # operator spec
LINREG_SMOOTH   = 39           # operator spec
LINREG_INVERT   = True         # INVERTED (opposite of USDT.D version)

LEVEL_L1_UP     = +1.3         # asymmetric: sensitive OB
LEVEL_L1_DN     = -1.6         # asymmetric: stricter OS
LEVEL_L2_UP     = +2.2         # symmetric extreme
LEVEL_L2_DN     = -2.2

# Default operating timeframe — matches bot's main 1H scan loop.
# Multi-TF supported: 15m (scalp), 1h (default), 4h (swing).
DEFAULT_TIMEFRAME    = '1h'
SUPPORTED_TIMEFRAMES = ('15m', '30m', '1h', '2h', '4h')

# Minimum bars required for a stable reading:
# LinReg warmup = LINREG_LEN + LINREG_NORM = 347 bars, plus EMA(39) settles in ~100 more
MIN_BARS_READY  = 400

REFRESH_SEC     = 900          # 15 minutes — aligned with 1H bar cadence

# ── State names ──────────────────────────────────────────────────────────────
STATE_NEUTRAL          = 'NEUTRAL'
STATE_LONG_PAIN        = 'LONG_PAIN'         # TSI in [L1_DN, L2_DN) — oversold, mild
STATE_LONG_MAX_PAIN    = 'LONG_MAX_PAIN'     # TSI <= L2_DN — extreme oversold
STATE_SHORT_PAIN       = 'SHORT_PAIN'        # TSI in (L1_UP, L2_UP] — overbought, mild
STATE_SHORT_MAX_PAIN   = 'SHORT_MAX_PAIN'    # TSI >= L2_UP — extreme overbought


@dataclass
class PairMacroState:
    pair:            str
    timeframe:       str
    tsi_scaled:      Optional[float]
    tsi_prev:        Optional[float]
    linreg:          Optional[float]
    state:           str
    bars_available:  int
    is_ready:        bool
    timestamp:       float
    # Alignment helpers (for combined USDT.D + pair decisions)
    lr_regime:       str         # 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'UNKNOWN'


# ── Pine-faithful math (identical shape to usdt_dominance) ───────────────────
def _tsi(close: pd.Series) -> pd.Series:
    pc = close.diff()
    dbl_pc  = pc.ewm(span=TSI_LONG,  adjust=False).mean().ewm(
        span=TSI_SHORT, adjust=False).mean()
    dbl_abs = pc.abs().ewm(span=TSI_LONG,  adjust=False).mean().ewm(
        span=TSI_SHORT, adjust=False).mean()
    raw = 100.0 * (dbl_pc / dbl_abs.replace(0, np.nan))
    if TSI_INVERT:
        raw = -raw
    return raw / TSI_SCALE


def _linreg(close: pd.Series) -> pd.Series:
    """Pine-faithful: raw = m * bar_index + c, then z-score norm + EMA smooth."""
    vals = close.values
    n = len(vals)
    raw = np.full(n, np.nan)
    x = np.arange(LINREG_LEN, dtype=float)
    sx  = x.sum()
    sx2 = (x * x).sum()
    denom = LINREG_LEN * sx2 - sx * sx
    if denom == 0:
        return pd.Series(raw, index=close.index)
    for i in range(LINREG_LEN - 1, n):
        w = vals[i - LINREG_LEN + 1: i + 1]
        sy  = w.sum()
        sxy = (x * w).sum()
        m = (LINREG_LEN * sxy - sx * sy) / denom
        c = (sy - m * sx) / LINREG_LEN
        # Pine: raw = m * bar_index + c  (global bar index)
        v = m * i + c
        raw[i] = -v if LINREG_INVERT else v
    s = pd.Series(raw, index=close.index)
    sma = s.rolling(LINREG_NORM, min_periods=LINREG_NORM).mean()
    std = s.rolling(LINREG_NORM, min_periods=LINREG_NORM).std()
    norm = (s - sma) / std.replace(0, np.nan)
    if LINREG_SMOOTH > 1:
        norm = norm.ewm(span=LINREG_SMOOTH, adjust=False).mean()
    return norm


def _classify_state(tsi_val) -> str:
    """Classify TSI into 5 zones using asymmetric L1 and symmetric L2."""
    if tsi_val is None or pd.isna(tsi_val):
        return STATE_NEUTRAL
    if tsi_val <= LEVEL_L2_DN:
        return STATE_LONG_MAX_PAIN
    if tsi_val <= LEVEL_L1_DN:
        return STATE_LONG_PAIN
    if tsi_val >= LEVEL_L2_UP:
        return STATE_SHORT_MAX_PAIN
    if tsi_val >= LEVEL_L1_UP:
        return STATE_SHORT_PAIN
    return STATE_NEUTRAL


def _lr_regime(linreg_val) -> str:
    """LinReg regime — inverted semantics (pair-side): > 0 = bearish, < 0 = bullish."""
    if linreg_val is None or pd.isna(linreg_val):
        return 'UNKNOWN'
    if linreg_val >  0.5:  return 'BEARISH'
    if linreg_val < -0.5:  return 'BULLISH'
    return 'NEUTRAL'


# ── Data source resolver ──────────────────────────────────────────────────
def _fetch_pair_df(pair: str, timeframe: str) -> pd.DataFrame:
    """
    Resolve the pair's OHLCV df at the requested timeframe.
    Order: 1) BATCH_PROCESSOR in-memory cache (fastest, no I/O) for 1H
           2) data_fetcher.fetch_data() (SQLite cache + Binance API)
    """
    # Fast path for 1h — main bot already prefetches this into BATCH_PROCESSOR
    if timeframe == '1h':
        try:
            from rust_batch_processor import BATCH_PROCESSOR
            df = BATCH_PROCESSOR.get_df(pair, '1h')
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    # Fallback: SQLite cache + API (for 2h/4h/15m or cold-start 1h)
    try:
        from data_fetcher import fetch_data
        return fetch_data(pair, timeframe)
    except Exception:
        return pd.DataFrame()


# ── Public API ────────────────────────────────────────────────────────────────
_cache: dict = {}        # (pair, timeframe) -> PairMacroState
_cache_lock = threading.Lock()


def compute_state_from_df(pair: str, df: pd.DataFrame,
                           timeframe: str = DEFAULT_TIMEFRAME) -> PairMacroState:
    """
    Pure computation — given an OHLCV DataFrame (with 'close' column), return state.
    Does NOT fetch or cache. Use this if you already have the data in hand.
    """
    if df is None or df.empty:
        return PairMacroState(
            pair=pair, timeframe=timeframe,
            tsi_scaled=None, tsi_prev=None, linreg=None,
            state=STATE_NEUTRAL, bars_available=0, is_ready=False,
            timestamp=time.time(), lr_regime='UNKNOWN',
        )

    close = df['close'].astype(float)
    tsi = _tsi(close)
    lr  = _linreg(close)

    latest_tsi = float(tsi.iloc[-1]) if not pd.isna(tsi.iloc[-1]) else None
    prev_tsi   = (float(tsi.iloc[-2])
                  if len(tsi) >= 2 and not pd.isna(tsi.iloc[-2]) else None)
    latest_lr  = float(lr.iloc[-1])  if not pd.isna(lr.iloc[-1])  else None

    state = _classify_state(latest_tsi)
    ready = len(df) >= MIN_BARS_READY and latest_tsi is not None and latest_lr is not None

    return PairMacroState(
        pair=pair,
        timeframe=timeframe,
        tsi_scaled=latest_tsi,
        tsi_prev=prev_tsi,
        linreg=latest_lr,
        state=state,
        bars_available=len(df),
        is_ready=ready,
        timestamp=time.time(),
        lr_regime=_lr_regime(latest_lr),
    )


def get_pair_macro_state(pair: str, force_refresh: bool = False,
                         timeframe: str = DEFAULT_TIMEFRAME) -> PairMacroState:
    """
    Fetch OHLCV at the requested timeframe and compute macro state.
    Default = 1H (bot's main TF). Use '15m' for scalp, '4h' for swing variants.
    Cached per (pair, tf) for REFRESH_SEC; fast-path for 1H via BATCH_PROCESSOR.
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f'timeframe must be one of {SUPPORTED_TIMEFRAMES}, got {timeframe!r}')

    key = (pair, timeframe)
    with _cache_lock:
        cached = _cache.get(key)
        if (not force_refresh
                and cached is not None
                and (time.time() - cached.timestamp) < REFRESH_SEC):
            return cached

    # Fetch outside the lock (I/O may block)
    df = _fetch_pair_df(pair, timeframe)
    state = compute_state_from_df(pair, df, timeframe=timeframe)
    with _cache_lock:
        _cache[key] = state
    return state


def state_snapshot(pair: str, timeframe: str = DEFAULT_TIMEFRAME) -> dict:
    """Compact dict for feature_snapshot / logging."""
    s = get_pair_macro_state(pair, timeframe=timeframe)
    d = asdict(s)
    d['levels'] = {
        'L1_UP': LEVEL_L1_UP, 'L1_DN': LEVEL_L1_DN,
        'L2_UP': LEVEL_L2_UP, 'L2_DN': LEVEL_L2_DN,
    }
    return d


# ── Signal-side helpers (used by main.py gate) ─────────────────────────
def long_bias(pair: str, timeframe: str = DEFAULT_TIMEFRAME) -> float:
    """
    Returns pair's LONG conviction score in [-1.0, +1.0]:
      +1.0 = extreme oversold (LONG_MAX_PAIN) with bullish regime
      +0.5 = mild oversold or bullish regime
       0.0 = neutral
      -0.5 = mild overbought or bearish regime
      -1.0 = extreme overbought (SHORT_MAX_PAIN) with bearish regime
    """
    s = get_pair_macro_state(pair, timeframe=timeframe)
    if not s.is_ready:
        return 0.0
    score = 0.0
    if   s.state == STATE_LONG_MAX_PAIN:    score += 1.0
    elif s.state == STATE_LONG_PAIN:        score += 0.5
    elif s.state == STATE_SHORT_PAIN:       score -= 0.5
    elif s.state == STATE_SHORT_MAX_PAIN:   score -= 1.0
    # Blend LinReg regime
    if   s.lr_regime == 'BULLISH':  score += 0.25
    elif s.lr_regime == 'BEARISH':  score -= 0.25
    return max(-1.0, min(1.0, score))


def long_allowed(pair: str, timeframe: str = DEFAULT_TIMEFRAME) -> bool:
    """
    Gate helper: True iff per-pair macro does NOT veto a new LONG.
    Vetoes when TSI >= L2_UP (+2.2) = pair extremely overbought = SHORT_MAX_PAIN.
    Fail-open when not ready.
    """
    s = get_pair_macro_state(pair, timeframe=timeframe)
    if not s.is_ready:
        return True
    return s.state != STATE_SHORT_MAX_PAIN


def short_allowed(pair: str, timeframe: str = DEFAULT_TIMEFRAME) -> bool:
    """
    Gate helper: True iff per-pair macro does NOT veto a new SHORT.
    Vetoes when TSI <= L2_DN (-2.2) = pair extremely oversold = LONG_MAX_PAIN.
    Fail-open when not ready.
    """
    s = get_pair_macro_state(pair, timeframe=timeframe)
    if not s.is_ready:
        return True
    return s.state != STATE_LONG_MAX_PAIN


def clear_cache(pair: Optional[str] = None, timeframe: Optional[str] = None) -> None:
    """Force refresh on next call. Useful from ops/debug scripts."""
    with _cache_lock:
        if pair is None and timeframe is None:
            _cache.clear()
        elif pair is not None and timeframe is not None:
            _cache.pop((pair, timeframe), None)
        elif pair is not None:
            for k in list(_cache.keys()):
                if k[0] == pair:
                    _cache.pop(k, None)
        else:  # only timeframe given
            for k in list(_cache.keys()):
                if k[1] == timeframe:
                    _cache.pop(k, None)


if __name__ == '__main__':
    # CLI:
    #   python3 pair_macro_indicator.py                 -> default pairs on 1H
    #   python3 pair_macro_indicator.py BTCUSDT ETHUSDT -> specific pairs on 1H
    #   python3 pair_macro_indicator.py --tf 4h BTCUSDT -> custom timeframe
    import sys, json
    args = sys.argv[1:]
    tf = DEFAULT_TIMEFRAME
    if '--tf' in args:
        idx = args.index('--tf')
        tf = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    pairs = args if args else ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT']
    for p in pairs:
        s = get_pair_macro_state(p, timeframe=tf)
        print(f"\n=== {p} @ {tf} ===")
        print(json.dumps(asdict(s), indent=2, default=str))
