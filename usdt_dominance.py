"""
USDT Dominance Macro Indicator — Python port of REVERSE HUNT [MTF reg] on USDT.D

Implements the "Systemic Dominance Vector" layer intended by the original Pine
script. Calculated on CRYPTOCAP:USDT.D at 2H timeframe.

Parameters (operator TradingView screenshot, 2026-04-18):
  TSI:    long=69, short=9, scale=14, inverted=True
  LinReg: len=270, norm=69, smooth=39, inverted=False   (macro ~3-week filter)
  Levels: L1=±1.4,  L2_UP=+2.1,  L2_DN=-1.8  (asymmetric)

State interpretation (inverted TSI on USDT.D):
  TSI < lower_2 (-1.8)  ->  USDT.D pumping extreme  ->  FEAR_MAX_PAIN     (enable LONG alts)
  TSI < lower   (-1.4)  ->  USDT.D pumping moderate ->  FEAR_PAIN         (caution on SHORT alts)
  TSI > upper   (+1.4)  ->  USDT.D dumping moderate ->  GREED_PAIN        (caution on LONG alts)
  TSI > upper_2 (+2.1)  ->  USDT.D dumping extreme  ->  GREED_MAX_PAIN    (enable SHORT alts)
  otherwise             ->  NEUTRAL                 ->  no macro gate active

LinReg oscillator (NOT inverted, on USDT.D):
  > 0  ->  USDT.D trending UP  ->  alts BEARISH macro regime
  < 0  ->  USDT.D trending DN  ->  alts BULLISH macro regime
"""
from __future__ import annotations
import os
import time
import sqlite3
import json
import threading
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd
import requests

# Python 3.7 compatibility — Literal import
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

# ── Operator-spec parameters ──────────────────────────────────────────────────
TSI_LONG        = 69
TSI_SHORT       = 9
TSI_SCALE       = 14.0
TSI_INVERT      = True

LINREG_LEN      = 270         # operator spec
LINREG_NORM     = 69          # operator spec
LINREG_SMOOTH   = 39          # operator spec (EMA post-smooth)
LINREG_INVERT   = False       # operator spec (TV checkbox unchecked)

LEVEL_L1_UP     = +1.4
LEVEL_L1_DN     = -1.4
LEVEL_L2_UP     = +2.1
LEVEL_L2_DN     = -1.8

# Default operating timeframe — can be overridden via get_usdt_dominance_state(timeframe=...)
# The bot uses 1H; future multi-TF (scalp=15m, swing=4h) is a drop-in call.
DEFAULT_TIMEFRAME = '1h'
SUPPORTED_TIMEFRAMES = ('15m', '30m', '1h', '2h', '4h', '1d')

# LinReg needs LINREG_LEN + LINREG_NORM warmup = 339 bars; plus EMA(39) smoothing.
# 400 bars minimum regardless of TF (time spanned varies with TF).
MIN_BARS_READY  = 400

DB_PATH         = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'usdt_dominance.db')
REFRESH_SEC     = 1800        # 30 minutes

_State = Literal[
    'NEUTRAL',
    'GREED_PAIN',
    'GREED_MAX_PAIN',
    'FEAR_PAIN',
    'FEAR_MAX_PAIN',
]


@dataclass
class USDTDominanceState:
    value_pct:       Optional[float]   # current USDT dominance %, e.g. 5.23
    tsi_scaled:      Optional[float]   # inverted TSI / scale
    tsi_prev:        Optional[float]   # previous bar
    linreg:          Optional[float]   # inverted LinReg oscillator
    state:           str               # one of _State values
    bars_available:  int
    is_ready:        bool
    timestamp:       float
    source:          str                # 'computed' | 'cache'


# ── DB helpers ────────────────────────────────────────────────────────────────
def _init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS samples(
            ts     INTEGER PRIMARY KEY,   -- unix seconds (bar open)
            value  REAL    NOT NULL,      -- USDT.D %
            source TEXT    NOT NULL
        )"""
    )
    con.commit()
    con.close()


def _insert_samples(rows) -> None:
    if not rows:
        return
    con = sqlite3.connect(DB_PATH)
    con.executemany(
        "INSERT OR REPLACE INTO samples(ts, value, source) VALUES (?,?,?)", rows
    )
    con.commit()
    con.close()


def _load_series() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT ts, value FROM samples ORDER BY ts", con)
    con.close()
    if df.empty:
        return df
    df['time'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    df = df.set_index('time')
    return df


_PD_FREQ = {
    '1m':  '1min',  '3m':  '3min',  '5m':  '5min',
    '15m': '15min', '30m': '30min',
    '1h':  '1h',    '2h':  '2h',    '4h':  '4h',
    '6h':  '6h',    '8h':  '8h',    '12h': '12h',
    '1d':  '1D',    '3d':  '3D',    '1w':  '1W',
}


def _resample(df_raw: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample raw USDT.D samples to the given timeframe (pandas freq)."""
    if df_raw.empty:
        return df_raw
    freq = _PD_FREQ.get(timeframe, timeframe)
    ohlc = df_raw['value'].resample(freq, label='left', closed='left').agg(
        ['first', 'max', 'min', 'last']
    ).dropna()
    ohlc.columns = ['open', 'high', 'low', 'close']
    return ohlc


# ── Data fetchers ─────────────────────────────────────────────────────────────
def _fetch_coingecko_live() -> Optional[float]:
    """Return current USDT.D % from CoinGecko /global, or None on failure."""
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/global',
            timeout=8,
            headers={'User-Agent': 'aladdin-bot/1.0'},
        )
        r.raise_for_status()
        return float(r.json()['data']['market_cap_percentage']['usdt'])
    except Exception:
        return None


# Map pandas freq -> tvdatafeed Interval attr name
_TV_INTERVAL_MAP = {
    '15m': 'in_15_minute',
    '30m': 'in_30_minute',
    '1h':  'in_1_hour',
    '2h':  'in_2_hour',
    '4h':  'in_4_hour',
    '1d':  'in_daily',
}


def _bootstrap_tvdatafeed(n_bars: int = 1500, timeframe: str = DEFAULT_TIMEFRAME) -> int:
    """Fetch historical USDT.D bars from TradingView at the requested TF."""
    try:
        from tvDatafeed import TvDatafeed, Interval  # newer capitalization
    except ImportError:
        try:
            from tvdatafeed import TvDatafeed, Interval  # older capitalization
        except ImportError:
            return 0
    interval_attr = _TV_INTERVAL_MAP.get(timeframe, 'in_1_hour')
    try:
        interval = getattr(Interval, interval_attr)
    except AttributeError:
        return 0
    try:
        tv = TvDatafeed()
        df = tv.get_hist(
            symbol='USDT.D',
            exchange='CRYPTOCAP',
            interval=interval,
            n_bars=n_bars,
        )
        if df is None or df.empty:
            return 0
        rows = []
        for idx, row in df.iterrows():
            ts = int(pd.Timestamp(idx).tz_localize('UTC').timestamp()) \
                if pd.Timestamp(idx).tzinfo is None \
                else int(pd.Timestamp(idx).timestamp())
            rows.append((ts, float(row['close']), f'tvdatafeed_{timeframe}'))
        _insert_samples(rows)
        return len(rows)
    except Exception as exc:
        print(f'[usdt_dominance] tvdatafeed bootstrap failed: {exc}')
        return 0


# ── Indicator math (exact Pine port) ─────────────────────────────────────────
def _tsi(close: pd.Series) -> pd.Series:
    pc = close.diff()
    dbl_pc  = pc.ewm(span=TSI_LONG, adjust=False).mean().ewm(
        span=TSI_SHORT, adjust=False).mean()
    dbl_abs = pc.abs().ewm(span=TSI_LONG, adjust=False).mean().ewm(
        span=TSI_SHORT, adjust=False).mean()
    raw = 100.0 * (dbl_pc / dbl_abs.replace(0, np.nan))
    if TSI_INVERT:
        raw = -raw
    return raw / TSI_SCALE


def _linreg(close: pd.Series) -> pd.Series:
    """Match Pine exactly: raw = m * bar_index + c (global idx), then norm + EMA smooth."""
    vals = close.values
    n = len(vals)
    raw = np.full(n, np.nan)
    x = np.arange(LINREG_LEN, dtype=float)
    sx = x.sum()
    sx2 = (x * x).sum()
    denom = LINREG_LEN * sx2 - sx * sx
    if denom == 0:
        return pd.Series(raw, index=close.index)
    for i in range(LINREG_LEN - 1, n):
        w = vals[i - LINREG_LEN + 1: i + 1]
        sy = w.sum()
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


def _classify_state(tsi_val: float) -> str:
    if tsi_val is None or pd.isna(tsi_val):
        return 'NEUTRAL'
    if tsi_val <= LEVEL_L2_DN:
        return 'FEAR_MAX_PAIN'
    if tsi_val <= LEVEL_L1_DN:
        return 'FEAR_PAIN'
    if tsi_val >= LEVEL_L2_UP:
        return 'GREED_MAX_PAIN'
    if tsi_val >= LEVEL_L1_UP:
        return 'GREED_PAIN'
    return 'NEUTRAL'


# ── Public API ────────────────────────────────────────────────────────────────
_last_live_fetch: float = 0.0
_cached_states: dict = {}        # timeframe -> USDTDominanceState
_lock = threading.Lock()


def _maybe_refresh_live() -> None:
    """Non-blocking — append a CoinGecko sample if >= REFRESH_SEC since last."""
    global _last_live_fetch
    now = time.time()
    if now - _last_live_fetch < REFRESH_SEC:
        return
    v = _fetch_coingecko_live()
    if v is not None:
        _insert_samples([(int(now), v, 'coingecko')])
        _last_live_fetch = now


def get_usdt_dominance_state(force_refresh: bool = False,
                             timeframe: str = DEFAULT_TIMEFRAME) -> USDTDominanceState:
    """
    Returns the current USDT.D macro state at the requested timeframe.
    Default = 1H (matches bot main loop). Use '15m' for scalping, '4h' for swing.
    Cached per-TF for REFRESH_SEC to avoid hot-loop overhead. Thread-safe.
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f'timeframe must be one of {SUPPORTED_TIMEFRAMES}, got {timeframe!r}')

    global _cached_states
    with _lock:
        _init_db()
        cached = _cached_states.get(timeframe)
        if (not force_refresh
                and cached is not None
                and (time.time() - cached.timestamp) < REFRESH_SEC):
            return cached

        _maybe_refresh_live()

        raw = _load_series()
        if raw.empty or len(raw) < 5:
            state = USDTDominanceState(
                value_pct=None, tsi_scaled=None, tsi_prev=None, linreg=None,
                state='NEUTRAL', bars_available=0, is_ready=False,
                timestamp=time.time(), source='cache',
            )
            _cached_states[timeframe] = state
            return state

        bars = _resample(raw, timeframe)
        if len(bars) < 5:
            state = USDTDominanceState(
                value_pct=float(raw['value'].iloc[-1]),
                tsi_scaled=None, tsi_prev=None, linreg=None,
                state='NEUTRAL',
                bars_available=len(bars),
                is_ready=False,
                timestamp=time.time(),
                source='cache',
            )
            _cached_states[timeframe] = state
            return state

        tsi = _tsi(bars['close'])
        lr  = _linreg(bars['close'])

        latest_tsi = float(tsi.iloc[-1]) if not pd.isna(tsi.iloc[-1]) else None
        prev_tsi   = (float(tsi.iloc[-2])
                      if len(tsi) >= 2 and not pd.isna(tsi.iloc[-2]) else None)
        latest_lr  = float(lr.iloc[-1])  if not pd.isna(lr.iloc[-1])  else None
        state = _classify_state(latest_tsi if latest_tsi is not None else float('nan'))
        ready = len(bars) >= MIN_BARS_READY and latest_tsi is not None

        _cached_states[timeframe] = USDTDominanceState(
            value_pct      = float(bars['close'].iloc[-1]),
            tsi_scaled     = latest_tsi,
            tsi_prev       = prev_tsi,
            linreg         = latest_lr,
            state          = state,
            bars_available = len(bars),
            is_ready       = ready,
            timestamp      = time.time(),
            source         = f'computed_{timeframe}',
        )
        return _cached_states[timeframe]


def bootstrap(n_bars: int = 1500, timeframe: str = DEFAULT_TIMEFRAME) -> int:
    """One-shot historical backfill at the given TF. Call from ops script or first-run."""
    _init_db()
    return _bootstrap_tvdatafeed(n_bars=n_bars, timeframe=timeframe)


# ── Signal-side helpers (Phase 2 gating) ─────────────────────────────────────
def long_allowed(timeframe: str = DEFAULT_TIMEFRAME) -> bool:
    """
    True iff USDT.D signals do NOT veto new LONGs at the given TF.
    Vetoes LONG when greed is extreme (TSI > +2.1 = alts already pumping too hot).
    Fail-open when not ready.
    """
    s = get_usdt_dominance_state(timeframe=timeframe)
    if not s.is_ready:
        return True
    return s.state != 'GREED_MAX_PAIN'


def short_allowed(timeframe: str = DEFAULT_TIMEFRAME) -> bool:
    """
    True iff USDT.D signals do NOT veto new SHORTs at the given TF.
    Vetoes SHORT when fear is extreme (TSI < -1.8 = capitulation imminent reversal).
    Fail-open when not ready.
    """
    s = get_usdt_dominance_state(timeframe=timeframe)
    if not s.is_ready:
        return True
    return s.state != 'FEAR_MAX_PAIN'


def state_snapshot(timeframe: str = DEFAULT_TIMEFRAME) -> dict:
    """Compact dict for logging / feature_snapshot attribution."""
    s = get_usdt_dominance_state(timeframe=timeframe)
    d = asdict(s)
    d['timeframe'] = timeframe
    d['levels'] = {
        'L1_UP': LEVEL_L1_UP, 'L1_DN': LEVEL_L1_DN,
        'L2_UP': LEVEL_L2_UP, 'L2_DN': LEVEL_L2_DN,
    }
    return d


if __name__ == '__main__':
    # CLI:
    #   python3 usdt_dominance.py                      -> current state (default 1H)
    #   python3 usdt_dominance.py 4h                   -> current state at 4H
    #   python3 usdt_dominance.py bootstrap [N] [TF]   -> backfill N bars at TF
    import sys
    args = sys.argv[1:]
    if args and args[0] == 'bootstrap':
        n  = int(args[1]) if len(args) > 1 else 1500
        tf = args[2] if len(args) > 2 else DEFAULT_TIMEFRAME
        inserted = bootstrap(n, timeframe=tf)
        print(f'[bootstrap] inserted {inserted} {tf}-bars into {DB_PATH}')
        tf_print = tf
    else:
        tf_print = args[0] if args else DEFAULT_TIMEFRAME
    print(json.dumps(state_snapshot(timeframe=tf_print), indent=2, default=str))
