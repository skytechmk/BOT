"""
REVERSE HUNT Strategy — Dual-Engine Mean Reversion
Port from PineScript to Python. Runs exclusively on 1H timeframe.

Original Blueprint: "Dual-Engine Mean Reversion Bot" by NIKCE
  Engine 1 (The Macro Sieve): LinReg 280/69/39 + TSI 89/28/14 — Exhaustion Detection
  Engine 2 (The Trigger):     Chandelier Exit Hybrid — Volatility Breakout Confirmation

Signal Flow (State Machine):
  State 0 [IDLE]:    TSI between -2.030 and +2.011. Bot ignores pair.
  State 1 [EXTREME]: TSI breaches > 2.011 (OB) or < -2.030 (OS). Pair is overextended.
  State 2 [WATCH]:   TSI was in EXTREME, has now reversed and crossed back inside boundaries.
                     Bot locks on. Waits for Engine 2 trigger.
  TRIGGER:           While in WATCH state, 1H candle closes with CE Line flipped matching direction.
                     → Execute MARKET order at next bar open.

Memory Flush: If pair enters WATCH but TSI returns to 0.000 without a CE flip, state resets to IDLE.
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple

# ══════════════════════════════════════════════════════════════════════
#  PARAMETERS — Aligned with TradingView "CE Pro Hybrid + REV HUNT [SkyTech]"
# ══════════════════════════════════════════════════════════════════════

# ── TSI: True Strength Index (Macro Momentum Rate-of-Change) ──
TSI_LONG   = 69       # Long EMA length  — matches TV config (69)
TSI_SHORT  = 9        # Short EMA length — matches TV config (9)
TSI_SCALE  = 14.0     # Visual Scale Divisor — matches TV config (14)
TSI_INVERT = False    # NOT inverted — TV config: negative TSI = price falling = oversold = LONG reversal

# ── TSI Threshold Grid — matches TV indicator levels ──
LEVEL_OB_L2 = 2.0    # Extreme Overbought — State 1 entry (SHORT side)
LEVEL_OB_L1 = 1.5    # Initial Overbought — Zone 1
LEVEL_OS_L1 = -1.5   # Initial Oversold   — Zone 1
LEVEL_OS_L2 = -2.0   # Extreme Oversold   — State 1 entry (LONG side)

# ── Adaptive TSI Thresholds (per-pair dynamic levels) ──
# Lowered from 90/97 to 80/92 to catch more signals in sustained crashes
ADAPTIVE_L1_PERCENTILE = 80    # 80th percentile of |TSI| → L1 zone (was 90)
ADAPTIVE_L2_PERCENTILE = 92    # 92nd percentile of |TSI| → L2 zone (was 97)
ADAPTIVE_L1_FLOOR = 0.4        # Minimum L1 threshold (was 0.5)
ADAPTIVE_L2_FLOOR = 0.6        # Minimum L2 threshold (was 0.8)
ADAPTIVE_WINDOW = 500          # Bars to look back for percentile calculation

# ── Linear Regression (Trend Stretch / Macro Sieve) ──
LINREG_LEN    = 278   # Rolling window — matches TV config (278)
LINREG_NORM   = 69    # Normalization lookback — matches TV config (69)
LINREG_SMOOTH = 39    # EMA smoothing — matches TV config (39)
LINREG_INVERT = False # NOT inverted — flipped to match TV visual direction

# ── Chandelier Exit — Line Layer (Engine 2 Fast Trigger) ──
CE_LINE_SRC_LONG  = 'close'
CE_LINE_SRC_SHORT = 'high'
CE_LINE_ATR_LEN   = 22
CE_LINE_LOOKBACK  = 14
CE_LINE_MULT      = 3.0
CE_LINE_SMOOTH    = 'RMA'
CE_LINE_WAIT      = True  # Wait for candle close (no repaint)

# ── Chandelier Exit — Cloud Layer (Macro Trend Safety Filter) ──
CE_CLOUD_SRC      = 'close'
CE_CLOUD_ATR_LEN  = 14
CE_CLOUD_LOOKBACK = 28
CE_CLOUD_MULT     = 3.2
CE_CLOUD_SMOOTH   = 'RMA'
CE_CLOUD_WAIT     = True

# ── Signal timing & safety ──
MIN_CANDLES = 200         # Minimum bars required (LinReg=20 + Norm=100 + buffer ≈ 150; 200 is safe)
WATCH_FLUSH_LEVEL = 0.30  # If TSI returns within this of zero while in WATCH → flush to IDLE
WATCH_MAX_BARS = 72       # Max bars to hold WATCH state before auto-flush (72h = 3 days on 1h)
CE_TRIGGER_WINDOW = 36    # After entering WATCH, CE must flip within 36 bars or flush
SIGNAL_COOLDOWN = 1       # Only blocks same-bar duplicate — CE indicator handles re-fire prevention
PERSISTENT_CE_WINDOW = 48 # Persistent extreme: max bars since CE flip to still qualify (2 days on 1h)

# ── Extreme Mode (V-Bottom / Blow-Off Top catcher) ──
EXTREME_MODE_VOL_MULT = 1.5  # CE flip while in EXTREME requires volume > 1.5x 20-bar SMA

# ── Prolonged EXTREME mode: fire signal if TSI stuck in OB/OS for too long ──
PROLONGED_EXTREME_BARS = 16  # After 16h stuck in EXTREME, allow CE flip signal without waiting for TSI exit

# ── Late Entry Mode (CE flips first, TSI catches up into L2) ──
LATE_ENTRY_CE_LOOKBACK = 12  # CE must have flipped within last 12 bars to qualify

# ── Armed state: immediate trigger window ──
ARMED_CE_LOOKBACK = 6   # If CE already flipped within this many bars when entering ARMED, fire immediately

# ── CE Momentum Mode (breakout catcher) ──
# Fires on CE flip even without OS/OB extreme when TSI has accelerated
# >= this delta in the flip direction over CE_MOMENTUM_BARS bars.
#   Tuned 2026-04-22: near-zero delay — fires on the same bar as CE flip as long
#   as TSI is moving in the flip direction (prevents firing against momentum).
CE_MOMENTUM_MIN_DELTA = 0.05  # Minimum TSI move over lookback window
CE_MOMENTUM_BARS      = 1     # Bars to measure TSI acceleration over


# ══════════════════════════════════════════════════════════════════════
#  ENGINE 1A: TSI CALCULATOR
# ══════════════════════════════════════════════════════════════════════

def calculate_tsi(df: pd.DataFrame) -> pd.Series:
    """
    True Strength Index: double-smoothed EMA of price change / abs price change.
    Inverted and scaled by TSI_SCALE (matching blueprint: scale=14).
    Returns scaled TSI series.
    """
    pc = df['close'].diff()
    double_smooth     = pc.ewm(span=TSI_LONG, adjust=False).mean().ewm(span=TSI_SHORT, adjust=False).mean()
    double_smooth_abs = pc.abs().ewm(span=TSI_LONG, adjust=False).mean().ewm(span=TSI_SHORT, adjust=False).mean()
    raw_tsi = 100.0 * (double_smooth / double_smooth_abs.replace(0, np.nan))
    if TSI_INVERT:
        raw_tsi = raw_tsi * -1
    return raw_tsi / TSI_SCALE


# ══════════════════════════════════════════════════════════════════════
#  ENGINE 1B: LINEAR REGRESSION OSCILLATOR
# ══════════════════════════════════════════════════════════════════════

def calculate_linreg_oscillator(df: pd.DataFrame) -> pd.Series:
    """
    Normalized Linear Regression Slope Oscillator with EMA smoothing.
    Matches TV config: len=278, norm=69, smooth=39, inverted.
    """
    close = df['close'].values
    n = len(close)
    raw = np.full(n, np.nan)

    for i in range(LINREG_LEN - 1, n):
        window = close[i - LINREG_LEN + 1: i + 1]
        x = np.arange(LINREG_LEN, dtype=float)
        sx  = x.sum()
        sy  = window.sum()
        sxy = (x * window).sum()
        sx2 = (x * x).sum()
        denom = LINREG_LEN * sx2 - sx * sx
        if denom == 0:
            continue
        m = (LINREG_LEN * sxy - sx * sy) / denom
        c = (sy - m * sx) / LINREG_LEN
        v = m * (LINREG_LEN - 1) + c  # predict at end of local window, not global index
        raw[i] = -v if LINREG_INVERT else v

    series = pd.Series(raw, index=df.index)

    # Normalize: (value - SMA) / StdDev over LINREG_NORM window
    sma = series.rolling(LINREG_NORM, min_periods=1).mean()
    std = series.rolling(LINREG_NORM, min_periods=1).std()
    normalized = (series - sma) / std.replace(0, np.nan)

    # EMA smoothing (blueprint 'Smoothing Factor' = 39)
    if LINREG_SMOOTH > 1:
        normalized = normalized.ewm(span=LINREG_SMOOTH, adjust=False).mean()

    return normalized


# ══════════════════════════════════════════════════════════════════════
#  ENGINE 2: CHANDELIER EXIT (Hybrid — Line + Cloud layers)
# ══════════════════════════════════════════════════════════════════════

def _get_ma(series: pd.Series, length: int, ma_type: str = 'RMA') -> pd.Series:
    """ATR smoothing: RMA (Wilder's), SMA, EMA, or WMA."""
    if ma_type == 'RMA':
        return series.ewm(alpha=1.0 / length, adjust=False).mean()
    elif ma_type == 'SMA':
        return series.rolling(length, min_periods=1).mean()
    elif ma_type == 'EMA':
        return series.ewm(span=length, adjust=False).mean()
    elif ma_type == 'WMA':
        weights = np.arange(1, length + 1, dtype=float)
        return series.rolling(length, min_periods=1).apply(
            lambda x: np.dot(x, weights[-len(x):]) / weights[-len(x):].sum(), raw=True)
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def calculate_chandelier_exit(df: pd.DataFrame,
                               src_long: str = 'close', src_short: str = 'high',
                               atr_len: int = 22, lookback: int = 22,
                               mult: float = 3.0, smooth: str = 'RMA',
                               wait: bool = True) -> dict:
    """
    Chandelier Exit calculation — single layer.
    Returns dict with 'long_stop', 'short_stop', 'direction', 'buy_signal', 'sell_signal' as Series.
    """
    h, l, c = df['high'], df['low'], df['close']
    src_l = df[src_long]
    src_s = df[src_short]

    # True Range
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = _get_ma(tr, atr_len, smooth)

    # Highest / Lowest over lookback
    highest = src_s.rolling(lookback, min_periods=1).max()
    lowest  = src_l.rolling(lookback, min_periods=1).min()

    if wait:
        atr     = atr.shift(1)
        highest = highest.shift(1)
        lowest  = lowest.shift(1)

    atr_val   = atr * mult
    long_raw  = lowest - atr_val
    short_raw = highest + atr_val

    # State machine — ratcheting stops
    n = len(df)
    long_stop  = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)
    direction  = np.zeros(n, dtype=int)

    close_vals     = c.values
    long_raw_vals  = long_raw.values
    short_raw_vals = short_raw.values

    long_stop[0]  = long_raw_vals[0]  if not np.isnan(long_raw_vals[0])  else 0.0
    short_stop[0] = short_raw_vals[0] if not np.isnan(short_raw_vals[0]) else 0.0
    direction[0]  = 1

    for i in range(1, n):
        lr = long_raw_vals[i]
        sr = short_raw_vals[i]
        if np.isnan(lr): lr = long_stop[i - 1]
        if np.isnan(sr): sr = short_stop[i - 1]

        # Ratchet long stop up only — never lower during uptrend
        long_stop[i]  = max(lr, long_stop[i - 1]) if close_vals[i - 1] > long_stop[i - 1] else lr
        # Ratchet short stop down only — never raise during downtrend
        short_stop[i] = min(sr, short_stop[i - 1]) if close_vals[i - 1] < short_stop[i - 1] else sr

        # Direction flip
        if   close_vals[i] > short_stop[i - 1]: direction[i] = 1
        elif close_vals[i] < long_stop[i - 1]:  direction[i] = -1
        else:                                    direction[i] = direction[i - 1]

    dir_series = pd.Series(direction, index=df.index)
    return {
        'long_stop':   pd.Series(long_stop,  index=df.index),
        'short_stop':  pd.Series(short_stop, index=df.index),
        'direction':   dir_series,
        'buy_signal':  (dir_series == 1)  & (dir_series.shift(1) == -1),
        'sell_signal': (dir_series == -1) & (dir_series.shift(1) == 1),
    }


# ══════════════════════════════════════════════════════════════════════
#  STATE MACHINE — Per-pair persistent state
# ══════════════════════════════════════════════════════════════════════

# State constants — 5-stage sequential Rev Hunt pipeline
STATE_IDLE       = 0   # TSI neutral — pair ignored
STATE_MONITORING = 1   # TSI entered L1 zone — pair under watch
STATE_EXTREME    = 2   # TSI in L2 extreme zone
STATE_RECOVERING = 3   # TSI exited L2, still in L1 — returning from extreme
STATE_ARMED      = 4   # TSI fully exited L1 — CE trigger now active
STATE_WATCH      = STATE_RECOVERING   # backward-compat alias

_pair_states: dict = {}


def _get_state(pair: str) -> dict:
    if pair not in _pair_states:
        _pair_states[pair] = {
            'state':                STATE_IDLE,
            'extreme_side':         0,       # +1=was overbought, -1=was oversold
            'monitoring_entry_bar': -999,
            'extreme_entry_bar':    -999,
            'recovering_entry_bar': -999,
            'armed_entry_bar':      -999,
            'last_signal_bar':      -100,    # Prevent double-fire
            'tsi_zone':             None,
        }
    return _pair_states[pair]


def _simulate_state_machine(tsi_vals: np.ndarray, ce_dir_vals: np.ndarray,
                             vol_vals: np.ndarray, state: dict,
                             adapt_l1: float = None, adapt_l2: float = None,
                             adapt_l1_os: float = None, adapt_l2_os: float = None) -> tuple:
    """
    5-stage Rev Hunt state machine — full TSI reversal sequence required:
      IDLE → MONITORING → EXTREME → RECOVERING → ARMED → TRIGGER (CE flip)

    A signal fires ONLY after TSI completes the full sequence:
      1. Enters L1 monitoring zone        (MONITORING)
      2. Deepens into L2 extreme zone     (EXTREME)
      3. Exits L2, returns to L1          (RECOVERING)
      4. Exits L1 to neutral              (ARMED — CE trigger now active)
      5. CE Hybrid fires a flip matching direction → SIGNAL

    Special cases retained:
      - PROLONGED_EXTREME: TSI stuck in L2 ≥ PROLONGED_EXTREME_BARS + CE flip
      - EXTREME_MODE:      TSI at L2 + volume surge + CE flip (V-bottom/blow-off)
      - ARMED_IMMEDIATE:   CE flipped within ARMED_CE_LOOKBACK bars before ARMED entry

    adapt_l1/l2:    OB thresholds (positive)
    adapt_l1/l2_os: OS thresholds (negative)
    Returns (signal, signal_bar, zone_used, vol_surge_ratio)
    """
    l1_thresh    = adapt_l1    if adapt_l1    is not None else LEVEL_OB_L1
    l2_thresh    = adapt_l2    if adapt_l2    is not None else LEVEL_OB_L2
    os_l2_thresh = adapt_l2_os if adapt_l2_os is not None else -l2_thresh
    os_l1_thresh = adapt_l1_os if adapt_l1_os is not None else -l1_thresh

    n           = len(tsi_vals)
    signal      = None
    signal_bar  = -1
    zone_used   = None
    vol_ratio   = 1.0
    current_bar = n - 1

    # Volume SMA_20 for Extreme Mode gate
    vol_sma = np.full(n, np.nan)
    for i in range(19, n):
        vol_sma[i] = np.mean(vol_vals[i - 19: i + 1])

    def _reset_idle():
        state['state']        = STATE_IDLE
        state['extreme_side'] = 0

    def _check_armed_immediate(bar_idx, target_ce_dir, sig):
        """Return sig if CE already flipped to target_ce_dir within ARMED_CE_LOOKBACK bars."""
        _lkb = max(1, bar_idx - ARMED_CE_LOOKBACK)
        for j in range(_lkb, bar_idx + 1):
            if j > 0 and ce_dir_vals[j] == target_ce_dir and ce_dir_vals[j - 1] != target_ce_dir:
                return sig
        return None

    for i in range(1, n):
        t    = tsi_vals[i]
        t_p  = tsi_vals[i - 1]
        ce   = ce_dir_vals[i]
        ce_p = ce_dir_vals[i - 1]

        if np.isnan(t) or np.isnan(t_p):
            continue

        ce_flip_long  = (ce == 1  and ce_p == -1)
        ce_flip_short = (ce == -1 and ce_p == 1)

        s = state['state']

        # ══ STATE 0: IDLE ══════════════════════════════════════════════════
        if s == STATE_IDLE:
            if t < os_l2_thresh:
                # Directly entered extreme OS zone (skipped L1)
                state['state'] = STATE_EXTREME; state['extreme_side'] = -1
                state['extreme_entry_bar'] = i
            elif t < os_l1_thresh:
                # Entered L1 monitoring zone (oversold)
                state['state'] = STATE_MONITORING; state['extreme_side'] = -1
                state['monitoring_entry_bar'] = i
            elif t > l2_thresh:
                # Directly entered extreme OB zone (skipped L1)
                state['state'] = STATE_EXTREME; state['extreme_side'] = +1
                state['extreme_entry_bar'] = i
            elif t > l1_thresh:
                # Entered L1 monitoring zone (overbought)
                state['state'] = STATE_MONITORING; state['extreme_side'] = +1
                state['monitoring_entry_bar'] = i

        # ══ STATE 1: MONITORING (TSI in L1, not yet in L2) ════════════════
        elif s == STATE_MONITORING:
            side = state['extreme_side']
            if side == -1:
                if t < os_l2_thresh:
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i
                elif t > os_l1_thresh:
                    _reset_idle()   # Left L1 without hitting L2 — false alarm
            else:  # side == +1
                if t > l2_thresh:
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i
                elif t < l1_thresh:
                    _reset_idle()   # Left L1 without hitting L2 — false alarm

        # ══ STATE 2: EXTREME (TSI in L2 zone) ═════════════════════════════
        elif s == STATE_EXTREME:
            side            = state['extreme_side']
            bars_in_extreme = i - state.get('extreme_entry_bar', i)

            # Prolonged Extreme: CE flip while stuck in L2 ≥ threshold
            if bars_in_extreme >= PROLONGED_EXTREME_BARS:
                if side == +1 and ce_flip_short:
                    signal = 'SHORT'; signal_bar = i; zone_used = 'PROLONGED_OB'
                    _reset_idle(); continue
                elif side == -1 and ce_flip_long:
                    signal = 'LONG'; signal_bar = i; zone_used = 'PROLONGED_OS'
                    _reset_idle(); continue

            # Direction reversal while in extreme (re-anchor)
            if side == +1 and t < os_l2_thresh:
                state['extreme_side'] = -1; state['extreme_entry_bar'] = i; continue
            elif side == -1 and t > l2_thresh:
                state['extreme_side'] = +1; state['extreme_entry_bar'] = i; continue

            # TSI exiting L2
            if side == +1:
                if t < l1_thresh:
                    # Fast recovery: jumped past L1 directly to neutral → ARMED
                    state['state'] = STATE_ARMED; state['armed_entry_bar'] = i
                    imm = _check_armed_immediate(i, -1, 'SHORT')
                    if imm:
                        signal = imm; signal_bar = i; zone_used = 'OB_L2_ARMED_IMM'
                        _reset_idle()
                elif t < l2_thresh:
                    state['state'] = STATE_RECOVERING; state['recovering_entry_bar'] = i
            elif side == -1:
                if t > os_l1_thresh:
                    # Fast recovery → ARMED
                    state['state'] = STATE_ARMED; state['armed_entry_bar'] = i
                    imm = _check_armed_immediate(i, 1, 'LONG')
                    if imm:
                        signal = imm; signal_bar = i; zone_used = 'OS_L2_ARMED_IMM'
                        _reset_idle()
                elif t > os_l2_thresh:
                    state['state'] = STATE_RECOVERING; state['recovering_entry_bar'] = i

        # ══ STATE 3: RECOVERING (exited L2, still in L1) ══════════════════
        elif s == STATE_RECOVERING:
            side               = state['extreme_side']
            bars_in_recovering = i - state.get('recovering_entry_bar', i)

            if bars_in_recovering > WATCH_MAX_BARS:
                _reset_idle(); continue
            if abs(t) < WATCH_FLUSH_LEVEL:
                _reset_idle(); continue

            if side == -1:
                if t < os_l2_thresh:
                    # Re-deepened into extreme
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i
                elif t > os_l1_thresh:
                    # Exited L1 monitoring zone → ARMED
                    state['state'] = STATE_ARMED; state['armed_entry_bar'] = i
                    imm = _check_armed_immediate(i, 1, 'LONG')
                    if imm:
                        signal = imm; signal_bar = i; zone_used = 'OS_L2_ARMED_IMM'
                        _reset_idle()
            else:  # side == +1
                if t > l2_thresh:
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i
                elif t < l1_thresh:
                    # Exited L1 monitoring zone → ARMED
                    state['state'] = STATE_ARMED; state['armed_entry_bar'] = i
                    imm = _check_armed_immediate(i, -1, 'SHORT')
                    if imm:
                        signal = imm; signal_bar = i; zone_used = 'OB_L2_ARMED_IMM'
                        _reset_idle()

        # ══ STATE 4: ARMED (TSI fully exited L1 — CE trigger active) ══════
        elif s == STATE_ARMED:
            side          = state['extreme_side']
            bars_in_armed = i - state.get('armed_entry_bar', i)

            if bars_in_armed > CE_TRIGGER_WINDOW:
                _reset_idle(); continue
            if abs(t) < WATCH_FLUSH_LEVEL:
                _reset_idle(); continue

            # Re-entry into L1/L2 (rollback state)
            if side == -1:
                if t < os_l2_thresh:
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i; continue
                elif t < os_l1_thresh:
                    state['state'] = STATE_RECOVERING; state['recovering_entry_bar'] = i; continue
            else:  # side == +1
                if t > l2_thresh:
                    state['state'] = STATE_EXTREME; state['extreme_entry_bar'] = i; continue
                elif t > l1_thresh:
                    state['state'] = STATE_RECOVERING; state['recovering_entry_bar'] = i; continue

            # TRIGGER: fresh CE flip matching direction
            if side == -1 and ce_flip_long:
                signal = 'LONG'; signal_bar = i; zone_used = 'OS_L2_ARMED'
                _reset_idle()
            elif side == +1 and ce_flip_short:
                signal = 'SHORT'; signal_bar = i; zone_used = 'OB_L2_ARMED'
                _reset_idle()

    # ── EXTREME MODE: V-Bottom / Blow-Off Catcher ──────────────────────────
    # Fires when TSI still pegged at L2 + volume surge + CE flip NOW.
    if signal is None:
        t_now  = tsi_vals[current_bar]
        ce_now = ce_dir_vals[current_bar]
        ce_prv = ce_dir_vals[current_bar - 1] if current_bar > 0 else ce_now

        ce_just_long  = (ce_now == 1  and ce_prv == -1)
        ce_just_short = (ce_now == -1 and ce_prv == 1)

        v_now        = vol_vals[current_bar]
        v_sma        = vol_sma[current_bar - 1] if current_bar > 0 else vol_sma[current_bar]
        is_vol_surge = (v_now > EXTREME_MODE_VOL_MULT * v_sma) if not np.isnan(v_sma) else False
        vol_ratio    = v_now / v_sma if (not np.isnan(v_sma) and v_sma > 0) else 1.0

        if ce_just_long  and t_now < os_l2_thresh and is_vol_surge:
            signal = 'LONG';  signal_bar = current_bar; zone_used = 'EXTREME_OS_L2'
        elif ce_just_short and t_now > l2_thresh   and is_vol_surge:
            signal = 'SHORT'; signal_bar = current_bar; zone_used = 'EXTREME_OB_L2'

    # ── CE MOMENTUM MODE: Breakout catcher ────────────────────────────────
    # Fires when CE flips AND TSI has accelerated >= CE_MOMENTUM_MIN_DELTA
    # in the flip direction over CE_MOMENTUM_BARS bars.
    # Catches breakouts from neutral TSI (e.g. ATOM Apr 22) that the
    # OS/OB mean-reversion pipeline misses entirely.
    # Also overrides a stale historical signal (>3 bars old) that would
    # be discarded by the staleness check in process_pair anyway.
    _signal_is_stale = signal is not None and (current_bar - signal_bar) > 3
    if (signal is None or _signal_is_stale) and current_bar >= CE_MOMENTUM_BARS:
        t_now  = tsi_vals[current_bar]
        ce_now = ce_dir_vals[current_bar]
        ce_prv = ce_dir_vals[current_bar - 1] if current_bar > 0 else ce_now
        ce_just_long  = (ce_now == 1  and ce_prv != 1)
        ce_just_short = (ce_now == -1 and ce_prv != -1)

        # TSI delta over last CE_MOMENTUM_BARS bars
        t_prev  = tsi_vals[current_bar - CE_MOMENTUM_BARS]
        tsi_delta = t_now - t_prev

        if ce_just_long  and tsi_delta >= CE_MOMENTUM_MIN_DELTA:
            signal = 'LONG';  signal_bar = current_bar; zone_used = 'CE_MOMENTUM_LONG'
        elif ce_just_short and tsi_delta <= -CE_MOMENTUM_MIN_DELTA:
            signal = 'SHORT'; signal_bar = current_bar; zone_used = 'CE_MOMENTUM_SHORT'
        elif ce_just_long or ce_just_short:
            # Rejection log — CE flipped but TSI not moving in flip direction.
            # Useful for tuning CE_MOMENTUM_MIN_DELTA / CE_MOMENTUM_BARS.
            try:
                _dir = 'LONG' if ce_just_long else 'SHORT'
                print(f"[CE_MOM_REJECT] dir={_dir} tsi_delta={tsi_delta:+.3f} "
                      f"lookback={CE_MOMENTUM_BARS} need≥{CE_MOMENTUM_MIN_DELTA:.2f} "
                      f"tsi_now={t_now:+.3f}", flush=True)
            except Exception:
                pass

    return signal, signal_bar, zone_used, vol_ratio


# ══════════════════════════════════════════════════════════════════════
#  ADAPTIVE TSI THRESHOLD CALCULATION
# ══════════════════════════════════════════════════════════════════════

# Cache for per-pair adaptive thresholds to avoid recalculation
_adaptive_threshold_cache: dict = {}


def calculate_adaptive_tsi_thresholds(tsi_vals: np.ndarray) -> Tuple[float, float]:
    """
    Calculate adaptive TSI thresholds based on historical |TSI| distribution.
    (Symmetric magnitude version — retained for dashboard compatibility.)

    Returns (l1_threshold, l2_threshold) where:
    - L1 = max(floor, percentile(|TSI|, ADAPTIVE_L1_PERCENTILE))
    - L2 = max(floor, percentile(|TSI|, ADAPTIVE_L2_PERCENTILE))
    """
    # Use last N values for percentile calculation
    window = min(ADAPTIVE_WINDOW, len(tsi_vals))
    tsi_window = tsi_vals[-window:]
    
    # Calculate absolute TSI values (we care about magnitude, not direction)
    abs_tsi = np.abs(tsi_window)
    abs_tsi = abs_tsi[~np.isnan(abs_tsi)]  # Remove NaN values
    
    if len(abs_tsi) < 50:  # Not enough data
        return LEVEL_OB_L1, LEVEL_OB_L2  # Fall back to hardcoded
    
    # Calculate percentiles
    l1_threshold = np.percentile(abs_tsi, ADAPTIVE_L1_PERCENTILE)
    l2_threshold = np.percentile(abs_tsi, ADAPTIVE_L2_PERCENTILE)
    
    # Apply floors (minimum values)
    l1_threshold = max(l1_threshold, ADAPTIVE_L1_FLOOR)
    l2_threshold = max(l2_threshold, ADAPTIVE_L2_FLOOR)
    
    # Apply CEILINGS to prevent runaway thresholds on volatile pairs
    # L2 should never exceed the blueprint's extreme level (2.03/2.011)
    l2_threshold = min(l2_threshold, LEVEL_OB_L2)
    # L1 should never exceed the blueprint's L1 level (1.3)
    l1_threshold = min(l1_threshold, LEVEL_OB_L1)
    
    # CRITICAL: Ensure L2 > L1 with minimum separation
    # If L2 would be <= L1, set L2 to the larger of the two plus margin
    if l2_threshold <= l1_threshold:
        l2_threshold = max(l2_threshold, l1_threshold * 1.2, LEVEL_OB_L1 * 0.8)
    
    # Final safety: ensure L2 never exceeds blueprint maximum
    l2_threshold = min(l2_threshold, LEVEL_OB_L2)
    
    return l1_threshold, l2_threshold


def calculate_adaptive_tsi_thresholds_split(tsi_vals: np.ndarray) -> Tuple[float, float, float, float]:
    """
    [UPGRADE 2026-04-19 — Directional Symmetry Fix]
    Calculate adaptive TSI thresholds SEPARATELY for overbought (positive)
    and oversold (negative) tails.

    The previous symmetric |TSI| percentile approach created LONG-bias in
    bull-leaning regimes: when TSI is inverted, bull pumps produce a long
    NEGATIVE tail, inflating the magnitude percentile and making the OS
    (LONG-trigger) side easy to reach while the OB (SHORT-trigger) side
    becomes unreachable.

    Returns (l1_ob, l2_ob, l1_os, l2_os) where OB thresholds are positive
    and OS thresholds are NEGATIVE (ready to compare `tsi < l2_os`).
    """
    window = min(ADAPTIVE_WINDOW, len(tsi_vals))
    tsi_window = tsi_vals[-window:]
    tsi_clean = tsi_window[~np.isnan(tsi_window)]

    # Fallback for insufficient data
    if len(tsi_clean) < 50:
        return LEVEL_OB_L1, LEVEL_OB_L2, -LEVEL_OB_L1, -LEVEL_OB_L2

    # Split into positive (OB) and negative (OS) tails
    pos_tsi = tsi_clean[tsi_clean > 0]
    neg_tsi = -tsi_clean[tsi_clean < 0]  # magnitudes of negative values

    # Each tail must have ≥25 samples for a meaningful percentile; else
    # fall back to symmetric magnitude calculation for that side.
    def _side(samples, pct, floor, ceiling):
        if len(samples) < 25:
            return max(floor, ceiling * 0.6)
        v = np.percentile(samples, pct)
        v = max(v, floor)
        v = min(v, ceiling)
        return v

    l1_ob = _side(pos_tsi, ADAPTIVE_L1_PERCENTILE, ADAPTIVE_L1_FLOOR, LEVEL_OB_L1)
    l2_ob = _side(pos_tsi, ADAPTIVE_L2_PERCENTILE, ADAPTIVE_L2_FLOOR, LEVEL_OB_L2)
    l1_os = _side(neg_tsi, ADAPTIVE_L1_PERCENTILE, ADAPTIVE_L1_FLOOR, LEVEL_OB_L1)
    l2_os = _side(neg_tsi, ADAPTIVE_L2_PERCENTILE, ADAPTIVE_L2_FLOOR, LEVEL_OB_L2)

    # Ensure L2 > L1 on each side
    if l2_ob <= l1_ob:
        l2_ob = max(l2_ob, l1_ob * 1.2, LEVEL_OB_L1 * 0.8)
    if l2_os <= l1_os:
        l2_os = max(l2_os, l1_os * 1.2, LEVEL_OB_L1 * 0.8)

    # ── Cross-side symmetry clamp ──
    # Prevent either side from drifting more than 30% easier than the other.
    # If OS is much tighter (harder) than OB, raise OB (ease SHORT trigger).
    # If OB is much tighter (harder) than OS, raise OS (ease LONG trigger).
    MAX_RATIO = 1.30
    for _ in range(2):  # 2-pass reconciliation
        if l2_os > l2_ob * MAX_RATIO:
            l2_ob = l2_os / MAX_RATIO
        elif l2_ob > l2_os * MAX_RATIO:
            l2_os = l2_ob / MAX_RATIO
        if l1_os > l1_ob * MAX_RATIO:
            l1_ob = l1_os / MAX_RATIO
        elif l1_ob > l1_os * MAX_RATIO:
            l1_os = l1_ob / MAX_RATIO

    # Final ceilings
    l2_ob = min(l2_ob, LEVEL_OB_L2)
    l2_os = min(l2_os, LEVEL_OB_L2)
    l1_ob = min(l1_ob, LEVEL_OB_L1)
    l1_os = min(l1_os, LEVEL_OB_L1)

    # Return OS side as NEGATIVE numbers (caller-friendly)
    return float(l1_ob), float(l2_ob), float(-l1_os), float(-l2_os)


def get_adaptive_tsi_zone(tsi_val: float, l1: float, l2: float) -> Optional[str]:
    """
    Get TSI zone using adaptive thresholds.
    
    Returns zone label or None for neutral.
    """
    abs_tsi = abs(tsi_val)
    
    if abs_tsi >= l2:
        return 'OS_L2' if tsi_val < 0 else 'OB_L2'
    elif abs_tsi >= l1:
        return 'OS_L1' if tsi_val < 0 else 'OB_L1'
    return None


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD COMPATIBILITY — Wrapper functions for web dashboard
# ══════════════════════════════════════════════════════════════════════

def compute_adaptive_levels(tsi_vals: np.ndarray) -> Tuple[float, float]:
    """
    Dashboard compatibility alias for calculate_adaptive_tsi_thresholds.
    
    Returns (l1_threshold, l2_threshold) for TSI zone detection.
    """
    return calculate_adaptive_tsi_thresholds(tsi_vals)


def get_tsi_zone(tsi_val: float, l1: float = LEVEL_OB_L1, l2: float = LEVEL_OB_L2) -> Optional[str]:
    """
    Dashboard compatibility wrapper for get_adaptive_tsi_zone.
    
    Returns zone label ('OS_L2', 'OB_L2', 'OS_L1', 'OB_L1') or None for neutral.
    """
    return get_adaptive_tsi_zone(tsi_val, l1, l2)


def detect_tsi_exits(tsi_series: pd.Series, l1: float = LEVEL_OB_L1, l2: float = LEVEL_OB_L2) -> dict:
    """
    Dashboard compatibility function — detects TSI zone exit points.
    
    Returns dict with exit signal arrays for plotting on charts.
    """
    n = len(tsi_series)
    tsi_values = tsi_series.values
    
    # Initialize exit signal arrays (0 = no exit, 1 = exit detected)
    exit_top_l1 = np.zeros(n, dtype=int)  # Exited from overbought L1
    exit_top_l2 = np.zeros(n, dtype=int)  # Exited from overbought L2
    exit_bot_l1 = np.zeros(n, dtype=int)  # Exited from oversold L1
    exit_bot_l2 = np.zeros(n, dtype=int)  # Exited from oversold L2
    
    # Track if we were in each zone
    in_ob_l1 = False
    in_ob_l2 = False
    in_os_l1 = False
    in_os_l2 = False
    
    for i in range(n):
        t = tsi_values[i]
        if np.isnan(t):
            continue
        
        abs_t = abs(t)
        
        # Check current zone
        is_ob_l2 = t > l2
        is_ob_l1 = t > l1 and not is_ob_l2
        is_os_l2 = t < -l2
        is_os_l1 = t < -l1 and not is_os_l2
        
        # Detect exits (was in zone, now not in zone)
        if in_ob_l2 and not is_ob_l2:
            exit_top_l2[i] = 1
        if in_ob_l1 and not is_ob_l1 and not is_ob_l2:
            exit_top_l1[i] = 1
        if in_os_l2 and not is_os_l2:
            exit_bot_l2[i] = 1
        if in_os_l1 and not is_os_l1 and not is_os_l2:
            exit_bot_l1[i] = 1
        
        # Update zone states
        in_ob_l2 = is_ob_l2
        in_ob_l1 = is_ob_l1
        in_os_l2 = is_os_l2
        in_os_l1 = is_os_l1
    
    return {
        'exit_top_l1': pd.Series(exit_top_l1, index=tsi_series.index),
        'exit_top_l2': pd.Series(exit_top_l2, index=tsi_series.index),
        'exit_bot_l1': pd.Series(exit_bot_l1, index=tsi_series.index),
        'exit_bot_l2': pd.Series(exit_bot_l2, index=tsi_series.index),
    }


# ══════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def process_pair(pair: str, df_1h: pd.DataFrame, rust_rh: dict = None) -> Optional[dict]:
    """
    Full Dual-Engine Mean Reversion signal pipeline.

    Args:
        pair:   Trading pair symbol (e.g. 'BTCUSDT')
        df_1h:  1H OHLCV DataFrame. MUST contain >= MIN_CANDLES (500) bars.
                LinReg=280 + norm=69 + EMA=39 requires ~390 bars to warm up.
        rust_rh: Pre-computed indicators from Rust batch (optional, ~78x faster)

    Returns:
        dict with signal info, or None if no signal.
    """
    if df_1h is None or df_1h.empty or len(df_1h) < MIN_CANDLES:
        return None

    state   = _get_state(pair)
    bar_idx = len(df_1h) - 1

    # ── Cooldown: prevent double-fire ──
    if (bar_idx - state['last_signal_bar']) < SIGNAL_COOLDOWN:
        return None

    # ── Calculate indicators (Rust pre-computed or Python fallback) ──
    if rust_rh and 'tsi' in rust_rh:
        tsi     = pd.Series(rust_rh['tsi'],         index=df_1h.index)
        ce_line = {
            'long_stop':  pd.Series(rust_rh['ce_line_long'],  index=df_1h.index),
            'short_stop': pd.Series(rust_rh['ce_line_short'], index=df_1h.index),
            'direction':  pd.Series(rust_rh['ce_line_dir'],   index=df_1h.index),
            'buy_signal': pd.Series(
                [1 if i > 0 and rust_rh['ce_line_dir'][i] == 1 and rust_rh['ce_line_dir'][i-1] == -1 else 0
                 for i in range(len(df_1h))], index=df_1h.index, dtype=bool),
            'sell_signal': pd.Series(
                [1 if i > 0 and rust_rh['ce_line_dir'][i] == -1 and rust_rh['ce_line_dir'][i-1] == 1 else 0
                 for i in range(len(df_1h))], index=df_1h.index, dtype=bool),
        }
        ce_cloud = {
            'long_stop':  pd.Series(rust_rh['ce_cloud_long'],  index=df_1h.index),
            'short_stop': pd.Series(rust_rh['ce_cloud_short'], index=df_1h.index),
            'direction':  pd.Series(rust_rh['ce_cloud_dir'],   index=df_1h.index),
        }
        linreg = pd.Series(rust_rh.get('linreg', [0.0] * len(df_1h)), index=df_1h.index)
    else:
        tsi     = calculate_tsi(df_1h)
        linreg  = calculate_linreg_oscillator(df_1h)
        ce_line = calculate_chandelier_exit(
            df_1h, src_long=CE_LINE_SRC_LONG, src_short=CE_LINE_SRC_SHORT,
            atr_len=CE_LINE_ATR_LEN, lookback=CE_LINE_LOOKBACK,
            mult=CE_LINE_MULT, smooth=CE_LINE_SMOOTH, wait=CE_LINE_WAIT)
        ce_cloud = calculate_chandelier_exit(
            df_1h, src_long=CE_CLOUD_SRC, src_short=CE_CLOUD_SRC,
            atr_len=CE_CLOUD_ATR_LEN, lookback=CE_CLOUD_LOOKBACK,
            mult=CE_CLOUD_MULT, smooth=CE_CLOUD_SMOOTH, wait=CE_CLOUD_WAIT)

    # ── Calculate Adaptive TSI Thresholds ──
    # [UPGRADE 2026-04-19] Use split OB/OS thresholds to fix LONG-bias.
    tsi_vals = tsi.values.astype(float)
    # Use cached thresholds if available (refresh every 100 bars)
    cache_key = f"{pair}_thresholds"
    if cache_key in _adaptive_threshold_cache and (bar_idx - _adaptive_threshold_cache[cache_key]['bar'] < 100):
        cached = _adaptive_threshold_cache[cache_key]
        adapt_l1    = cached['l1']
        adapt_l2    = cached['l2']
        adapt_l1_os = cached.get('l1_os', -cached['l1'])
        adapt_l2_os = cached.get('l2_os', -cached['l2'])
    else:
        adapt_l1, adapt_l2, adapt_l1_os, adapt_l2_os = calculate_adaptive_tsi_thresholds_split(tsi_vals)
        _adaptive_threshold_cache[cache_key] = {
            'l1': adapt_l1, 'l2': adapt_l2,
            'l1_os': adapt_l1_os, 'l2_os': adapt_l2_os,
            'bar': bar_idx,
        }

    # ── Run State Machine over full history with adaptive thresholds ──
    ce_dir_vals = ce_line['direction'].values.astype(float)
    vol_vals    = df_1h['volume'].values.astype(float)

    signal, signal_bar, zone_used, vol_ratio = _simulate_state_machine(
        tsi_vals, ce_dir_vals, vol_vals, state,
        adapt_l1=adapt_l1, adapt_l2=adapt_l2,
        adapt_l1_os=adapt_l1_os, adapt_l2_os=adapt_l2_os)

    # ── Only fire if signal is on the CURRENT or very recent bar (≤3 bars) ──
    if signal is None or (bar_idx - signal_bar) > 3:
        # ── Persistent Extreme Fallback ──
        # Fires when TSI stayed in L2 > CE_TRIGGER_WINDOW before CE confirmed.
        # Catches delayed reversals the state machine timed out on.
        # [UPGRADE 2026-04-19] Use split OS/OB thresholds.
        tsi_cur = float(tsi.iloc[-1])
        ce_cur  = int(ce_line['direction'].iloc[-1])
        pe_signal, pe_zone = None, None
        if tsi_cur < adapt_l2_os and ce_cur == 1:
            pe_signal, pe_zone = 'LONG', 'PERSISTENT_OS_L2'
        elif tsi_cur > adapt_l2 and ce_cur == -1:
            pe_signal, pe_zone = 'SHORT', 'PERSISTENT_OB_L2'

        if pe_signal:
            last_flip = None
            for i in range(bar_idx, 0, -1):
                if ce_dir_vals[i] != ce_dir_vals[i - 1]:
                    last_flip = i
                    break
            flip_age      = (bar_idx - last_flip) if last_flip is not None else 999
            last_sig_bar  = state.get('last_signal_bar', -9999)
            already_acted = last_flip is not None and last_sig_bar >= last_flip
            if flip_age <= PERSISTENT_CE_WINDOW and not already_acted:
                signal     = pe_signal
                signal_bar = bar_idx
                zone_used  = pe_zone
                vol_ratio  = 1.0
            else:
                return None
        else:
            return None

    # ── CE Chop Filter: reject signals when CE is whipsawing in a consolidation ──
    # Count CE Line direction flips in last N bars. High flip count = sideways chop.
    CHOP_CE_WINDOW     = 24   # Look at last 24 bars (1 day on 1h)
    CHOP_CE_FLIP_LIMIT = 3    # Max allowed flips before rejecting (≥3 = choppy)
    _dir_tail = ce_dir_vals[-CHOP_CE_WINDOW:]
    _ce_flip_count = int(np.sum(_dir_tail[1:] != _dir_tail[:-1]))
    if _ce_flip_count >= CHOP_CE_FLIP_LIMIT:
        log_message(
            f"🔀 CE CHOP FILTER [{pair}]: {_ce_flip_count} CE flips in last {CHOP_CE_WINDOW}h "
            f"→ rejecting {signal} signal (consolidation/whipsaw)")
        return None

    # ── Snapshot current indicator values ──
    tsi_now      = float(tsi.iloc[-1])
    linreg_now   = float(linreg.iloc[-1]) if not np.isnan(linreg.iloc[-1]) else 0.0
    ce_line_dir  = int(ce_line['direction'].iloc[-1])
    ce_cloud_dir = int(ce_cloud['direction'].iloc[-1])

    # ── Build conviction score ──
    is_extreme_mode = zone_used in ('EXTREME_OS_L2', 'EXTREME_OB_L2')
    is_late_entry   = zone_used in ('LATE_OS_L2', 'LATE_OB_L2')  # legacy, rarely fires
    is_persistent   = zone_used.startswith('PERSISTENT_')
    is_armed_imm    = zone_used in ('OS_L2_ARMED_IMM', 'OB_L2_ARMED_IMM')
    is_prolonged    = zone_used.startswith('PROLONGED_')
    conviction  = 0
    components  = {}

    # TSI zone depth (L2 = max conviction)
    conviction += 2
    components['tsi_l2_trigger'] = True

    # CE Line flip (mandatory — always +2)
    conviction += 2
    components['ce_line_flip'] = True

    # CE Cloud agrees with direction
    ce_cloud_match = (signal == 'LONG' and ce_cloud_dir == 1) or (signal == 'SHORT' and ce_cloud_dir == -1)
    if ce_cloud_match:
        conviction += 1
        components['ce_cloud_agree'] = True
    else:
        components['ce_cloud_agree'] = False

    # LinReg zero cross
    linreg_prev = float(linreg.iloc[-2]) if len(linreg) > 1 and not np.isnan(linreg.iloc[-2]) else 0.0
    lr_cross_up = linreg_prev <= 0 and linreg_now > 0
    lr_cross_dn = linreg_prev >= 0 and linreg_now < 0
    if (signal == 'LONG' and lr_cross_up) or (signal == 'SHORT' and lr_cross_dn):
        conviction += 1
        components['linreg_zero_cross'] = True
    else:
        components['linreg_zero_cross'] = False

    # Volume surge (Extreme Mode only — strong bonus)
    if is_extreme_mode:
        components['extreme_mode'] = True
        components['vol_surge']    = round(vol_ratio, 2)
        if vol_ratio >= 2.0:
            conviction += 1  # Extra bonus for very powerful surge
        conviction = max(1, conviction - 1)  # No TSI exit confirmation
    elif is_armed_imm:
        components['extreme_mode']   = False
        components['armed_immediate'] = True
        # CE flipped before TSI fully exited L1 — slightly weaker confirmation
        conviction = max(1, conviction - 1)
    elif is_prolonged:
        components['extreme_mode']    = False
        components['prolonged_extreme'] = True
        # TSI stuck in L2 too long — didn't wait for full reversal sequence
        conviction = max(1, conviction - 1)
    elif is_late_entry:
        components['extreme_mode'] = False
        components['late_entry']   = True
        conviction = max(1, conviction - 1)
    elif is_persistent:
        components['extreme_mode']       = False
        components['persistent_extreme'] = True
        conviction = max(1, conviction - 1)
    else:
        components['extreme_mode'] = False  # Standard ARMED signal — full conviction

    # ── CE stop levels ──
    if signal == 'LONG':
        ce_stop       = float(ce_line['long_stop'].iloc[-1])
        ce_cloud_stop = float(ce_cloud['long_stop'].iloc[-1])
    else:
        ce_stop       = float(ce_line['short_stop'].iloc[-1])
        ce_cloud_stop = float(ce_cloud['short_stop'].iloc[-1])

    # ── Update state ──
    state['tsi_zone']        = zone_used
    state['last_signal_bar'] = bar_idx

    from utils_logger import log_message
    mode_tag = ('⚡ EXTREME'   if is_extreme_mode else
                '🔒 ARMED_IMM' if is_armed_imm  else
                '⏳ PROLONGED' if is_prolonged  else
                '🔄 LATE'      if is_late_entry  else
                '🔁 PERSIST'   if is_persistent  else
                '🎯 ARMED')
    vol_str = f" | Vol={vol_ratio:.1f}x" if is_extreme_mode else ""
    # Show adaptive threshold info (if different from hardcoded)
    thresh_str = ""
    if abs(adapt_l2 - LEVEL_OB_L2) > 0.1:
        thresh_str = f" | L2={adapt_l2:.2f}"
    log_message(f"{mode_tag} [{pair}]: {signal} | Zone={zone_used} | TSI={tsi_now:.3f} | "
                f"Conviction={conviction} | CE_Line={'LONG' if ce_line_dir==1 else 'SHORT'}{vol_str}{thresh_str}")

    max_conviction = 6  # 2(TSI) + 2(CE flip) + 1(cloud) + 1(LR cross)

    return {
        'signal':          signal,
        'conviction':      conviction,
        'conviction_pct':  conviction / max_conviction,
        'components':      components,
        'levels': {
            'ce_line_stop':  ce_stop,
            'ce_cloud_stop': ce_cloud_stop,
        },
        'indicators': {
            'tsi':          tsi_now,
            'tsi_zone':     zone_used,
            'linreg':       linreg_now,
            'ce_line_dir':  ce_line_dir,
            'ce_cloud_dir': ce_cloud_dir,
        },
        'timeframe': '1h',
    }


# ══════════════════════════════════════════════════════════════════════
#  DIAGNOSTIC HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_pair_status(pair: str, df_1h: pd.DataFrame, rust_rh: dict = None) -> dict:
    """Quick diagnostic: return current state machine status for a pair (no signal generation)."""
    if df_1h is None or df_1h.empty or len(df_1h) < 50:
        return {'pair': pair, 'status': 'no_data'}
    try:
        if rust_rh and 'tsi' in rust_rh:
            tsi_now      = rust_rh['tsi'][-1]
            ce_line_dir  = rust_rh['ce_line_dir'][-1]
            ce_cloud_dir = rust_rh['ce_cloud_dir'][-1]
        else:
            tsi_now      = float(calculate_tsi(df_1h).iloc[-1])
            ce_line_dir  = 0
            ce_cloud_dir = 0

        s = _get_state(pair)
        state_name = {
            STATE_IDLE: 'IDLE', STATE_MONITORING: 'MONITORING',
            STATE_EXTREME: 'EXTREME', STATE_RECOVERING: 'RECOVERING',
            STATE_ARMED: 'ARMED'
        }.get(s['state'], 'UNKNOWN')

        return {
            'pair':        pair,
            'tsi':         round(tsi_now, 3),
            'state':       state_name,
            'extreme_side': s['extreme_side'],
            'ce_line':     'LONG' if ce_line_dir == 1 else 'SHORT',
            'ce_cloud':    'LONG' if ce_cloud_dir == 1 else 'SHORT',
            'ob_l2':       LEVEL_OB_L2,
            'os_l2':       LEVEL_OS_L2,
        }
    except Exception:
        return {'pair': pair, 'status': 'error'}


def get_all_indicator_values(df_1h: pd.DataFrame) -> dict:
    """
    Calculate all RH indicators and return current values (for ML feature extraction).
    Does NOT generate signals — just returns raw indicator values.
    """
    if df_1h is None or df_1h.empty or len(df_1h) < 200:
        return {}

    tsi    = calculate_tsi(df_1h)
    linreg = calculate_linreg_oscillator(df_1h)
    ce_line = calculate_chandelier_exit(
        df_1h, src_long=CE_LINE_SRC_LONG, src_short=CE_LINE_SRC_SHORT,
        atr_len=CE_LINE_ATR_LEN, lookback=CE_LINE_LOOKBACK,
        mult=CE_LINE_MULT, smooth=CE_LINE_SMOOTH, wait=CE_LINE_WAIT)
    ce_cloud = calculate_chandelier_exit(
        df_1h, src_long=CE_CLOUD_SRC, src_short=CE_CLOUD_SRC,
        atr_len=CE_CLOUD_ATR_LEN, lookback=CE_CLOUD_LOOKBACK,
        mult=CE_CLOUD_MULT, smooth=CE_CLOUD_SMOOTH, wait=CE_CLOUD_WAIT)

    tsi_val    = float(tsi.iloc[-1])
    linreg_val = float(linreg.iloc[-1]) if not np.isnan(linreg.iloc[-1]) else 0.0

    return {
        'rh_tsi':              tsi_val,
        'rh_tsi_prev':         float(tsi.iloc[-2]) if len(tsi) > 1 else 0.0,
        'rh_tsi_in_extreme':   tsi_val > LEVEL_OB_L2 or tsi_val < LEVEL_OS_L2,
        'rh_tsi_in_ob_l1':     tsi_val > LEVEL_OB_L1,
        'rh_tsi_in_os_l1':     tsi_val < LEVEL_OS_L1,
        'rh_linreg':           linreg_val,
        'rh_linreg_prev':      float(linreg.iloc[-2]) if len(linreg) > 1 and not np.isnan(linreg.iloc[-2]) else 0.0,
        'rh_ce_line_dir':      int(ce_line['direction'].iloc[-1]),
        'rh_ce_cloud_dir':     int(ce_cloud['direction'].iloc[-1]),
        'rh_ce_line_long_stop':  float(ce_line['long_stop'].iloc[-1]),
        'rh_ce_line_short_stop': float(ce_line['short_stop'].iloc[-1]),
        'rh_ce_cloud_long_stop': float(ce_cloud['long_stop'].iloc[-1]),
        'rh_ce_cloud_short_stop':float(ce_cloud['short_stop'].iloc[-1]),
        'rh_ce_buy':           bool(ce_line['buy_signal'].iloc[-1]),
        'rh_ce_sell':          bool(ce_line['sell_signal'].iloc[-1]),
    }
