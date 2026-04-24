"""Tests for pair_macro_indicator.py — per-pair REV HUNT state."""
import os
import sys
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pair_macro_indicator import (  # noqa: E402
    _classify_state, _tsi, _linreg, _lr_regime, compute_state_from_df,
    LEVEL_L1_UP, LEVEL_L1_DN, LEVEL_L2_UP, LEVEL_L2_DN,
    TSI_LONG, TSI_SHORT, TSI_SCALE, TSI_INVERT,
    LINREG_LEN, LINREG_NORM, LINREG_SMOOTH, LINREG_INVERT,
    STATE_NEUTRAL, STATE_LONG_PAIN, STATE_LONG_MAX_PAIN,
    STATE_SHORT_PAIN, STATE_SHORT_MAX_PAIN,
    MIN_BARS_READY,
)


# ── Parameter parity ──────────────────────────────────────────────────────────
def test_tsi_params_match_spec():
    assert TSI_LONG   == 69
    assert TSI_SHORT  == 9
    assert TSI_SCALE  == 14.0
    assert TSI_INVERT is False      # NOT inverted for pair


def test_linreg_params_match_spec():
    assert LINREG_LEN    == 278
    assert LINREG_NORM   == 69
    assert LINREG_SMOOTH == 39
    assert LINREG_INVERT is True    # INVERTED for pair


def test_level_asymmetry():
    # Asymmetric L1: sensitive OB (+1.3), stricter OS (-1.6)
    assert LEVEL_L1_UP == +1.3
    assert LEVEL_L1_DN == -1.6
    assert abs(LEVEL_L1_UP) < abs(LEVEL_L1_DN)
    # Symmetric L2
    assert LEVEL_L2_UP == +2.2
    assert LEVEL_L2_DN == -2.2


# ── State classification ──────────────────────────────────────────────────────
def test_state_neutral_band():
    assert _classify_state(0.0)    == STATE_NEUTRAL
    assert _classify_state(1.29)   == STATE_NEUTRAL
    assert _classify_state(-1.59)  == STATE_NEUTRAL


def test_state_short_zones():
    # Overbought (pair pumped) -> SHORT bias
    assert _classify_state(1.3)    == STATE_SHORT_PAIN       # L1_UP boundary
    assert _classify_state(2.1)    == STATE_SHORT_PAIN
    assert _classify_state(2.2)    == STATE_SHORT_MAX_PAIN   # L2_UP boundary
    assert _classify_state(5.0)    == STATE_SHORT_MAX_PAIN


def test_state_long_zones():
    # Oversold (pair dumped) -> LONG bias
    assert _classify_state(-1.6)   == STATE_LONG_PAIN        # L1_DN boundary
    assert _classify_state(-2.1)   == STATE_LONG_PAIN
    assert _classify_state(-2.2)   == STATE_LONG_MAX_PAIN    # L2_DN boundary
    assert _classify_state(-5.0)   == STATE_LONG_MAX_PAIN


def test_state_nan_handling():
    assert _classify_state(float('nan')) == STATE_NEUTRAL
    assert _classify_state(None)         == STATE_NEUTRAL


# ── TSI sign semantics (pair-side: NOT inverted) ─────────────────────────────
def test_tsi_sign_not_inverted():
    """For PAIR: pumping -> positive TSI; dumping -> negative TSI."""
    rising  = pd.Series(np.linspace(100, 200, 300))
    falling = pd.Series(np.linspace(200, 100, 300))
    t_up = _tsi(rising).iloc[-1]
    t_dn = _tsi(falling).iloc[-1]
    assert t_up > 0, 'rising price should yield positive TSI (not inverted)'
    assert t_dn < 0, 'falling price should yield negative TSI (not inverted)'


# ── LinReg (inverted for pair) ────────────────────────────────────────────────
def test_linreg_inversion_sign():
    """Pair LinReg is INVERTED: rising price -> negative LinReg after normalization."""
    # Sustained trend — mimics regime change
    # First flat, then steady rise — LinReg should be positive in flat region then
    # flip to negative as the rising trend kicks in (inverted)
    n = LINREG_LEN + LINREG_NORM + 50
    flat_rise = pd.Series(list(np.ones(n // 2) * 100.0) +
                          list(np.linspace(100.0, 150.0, n - n // 2)))
    lr = _linreg(flat_rise)
    # Latest value during rising segment: raw slope positive, inverted = negative
    latest = lr.iloc[-1]
    if not pd.isna(latest):
        assert latest < 0, f'inverted LinReg on rising pair should be negative, got {latest}'


def test_linreg_nan_warmup():
    """First LINREG_LEN-1 bars should be NaN (insufficient window)."""
    series = pd.Series(np.random.RandomState(1).randn(LINREG_LEN + 50).cumsum() + 100)
    lr = _linreg(series)
    assert lr.iloc[:LINREG_LEN - 1].isna().all()


# ── LinReg regime helper ──────────────────────────────────────────────────────
def test_lr_regime_thresholds():
    assert _lr_regime(None)       == 'UNKNOWN'
    assert _lr_regime(float('nan')) == 'UNKNOWN'
    assert _lr_regime(0.0)        == 'NEUTRAL'
    assert _lr_regime(0.3)        == 'NEUTRAL'
    assert _lr_regime(0.6)        == 'BEARISH'   # inverted: positive = bearish
    assert _lr_regime(-0.6)       == 'BULLISH'


# ── compute_state_from_df ─────────────────────────────────────────────────────
def test_compute_state_empty_df():
    s = compute_state_from_df('FAKE', pd.DataFrame())
    assert s.is_ready is False
    assert s.state == STATE_NEUTRAL
    assert s.bars_available == 0


def test_compute_state_insufficient_bars():
    df = pd.DataFrame({'close': np.random.RandomState(2).randn(50).cumsum() + 100})
    s = compute_state_from_df('FAKE', df)
    assert s.is_ready is False
    assert s.bars_available == 50


def test_compute_state_ready_with_enough_bars():
    n = MIN_BARS_READY + 10
    df = pd.DataFrame({'close': np.random.RandomState(3).randn(n).cumsum() + 100})
    s = compute_state_from_df('TESTUSDT', df)
    assert s.bars_available == n
    assert s.is_ready is True
    assert s.tsi_scaled is not None
    assert s.linreg is not None
    assert s.state in (STATE_NEUTRAL, STATE_LONG_PAIN, STATE_LONG_MAX_PAIN,
                       STATE_SHORT_PAIN, STATE_SHORT_MAX_PAIN)


# ── Multi-timeframe support ─────────────────────────────────────────────────
def test_default_timeframe_is_1h():
    """Bot's main loop runs on 1H — default must match."""
    from pair_macro_indicator import DEFAULT_TIMEFRAME
    assert DEFAULT_TIMEFRAME == '1h'


def test_timeframe_validation():
    from pair_macro_indicator import get_pair_macro_state
    with pytest.raises(ValueError):
        get_pair_macro_state('BTCUSDT', timeframe='7m')


def test_per_key_cache_isolation():
    """Cache entries are keyed by (pair, timeframe)."""
    import pair_macro_indicator as mod
    mod._cache.clear()
    # Feed the cache directly via compute_state_from_df
    n = mod.MIN_BARS_READY + 10
    df = pd.DataFrame({'close': np.random.RandomState(9).randn(n).cumsum() + 100})
    s_1h = mod.compute_state_from_df('TEST', df, timeframe='1h')
    s_4h = mod.compute_state_from_df('TEST', df, timeframe='4h')
    assert s_1h.timeframe == '1h'
    assert s_4h.timeframe == '4h'


def test_gate_helpers_fail_open():
    """When not ready, long_allowed/short_allowed must fail-open."""
    import pair_macro_indicator as mod
    mod._cache.clear()
    # Feed a non-ready state into the cache
    mod._cache[('NOTREADY', '1h')] = mod.PairMacroState(
        pair='NOTREADY', timeframe='1h',
        tsi_scaled=None, tsi_prev=None, linreg=None,
        state=mod.STATE_NEUTRAL, bars_available=10, is_ready=False,
        timestamp=9e12, lr_regime='UNKNOWN',
    )
    assert mod.long_allowed('NOTREADY') is True
    assert mod.short_allowed('NOTREADY') is True


def test_gate_helpers_veto_at_extremes():
    """SHORT_MAX_PAIN blocks LONGs; LONG_MAX_PAIN blocks SHORTs."""
    import pair_macro_indicator as mod
    mod._cache.clear()
    # Feed SHORT_MAX_PAIN into cache
    mod._cache[('OVERBOUGHT', '1h')] = mod.PairMacroState(
        pair='OVERBOUGHT', timeframe='1h',
        tsi_scaled=2.5, tsi_prev=2.3, linreg=-1.0,
        state=mod.STATE_SHORT_MAX_PAIN, bars_available=500, is_ready=True,
        timestamp=9e12, lr_regime='BULLISH',
    )
    assert mod.long_allowed('OVERBOUGHT')  is False
    assert mod.short_allowed('OVERBOUGHT') is True
    # Feed LONG_MAX_PAIN into cache
    mod._cache[('OVERSOLD', '1h')] = mod.PairMacroState(
        pair='OVERSOLD', timeframe='1h',
        tsi_scaled=-2.5, tsi_prev=-2.3, linreg=1.0,
        state=mod.STATE_LONG_MAX_PAIN, bars_available=500, is_ready=True,
        timestamp=9e12, lr_regime='BEARISH',
    )
    assert mod.long_allowed('OVERSOLD')  is True
    assert mod.short_allowed('OVERSOLD') is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
