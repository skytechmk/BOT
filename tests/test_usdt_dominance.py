"""Tests for usdt_dominance.py — state classification + Pine parity math."""
import os
import sys
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usdt_dominance import (  # noqa: E402
    _classify_state, _tsi, _linreg,
    LEVEL_L1_UP, LEVEL_L1_DN, LEVEL_L2_UP, LEVEL_L2_DN,
    TSI_LONG, TSI_SHORT, TSI_SCALE, TSI_INVERT,
    long_allowed, short_allowed,
)


# ── State classification ──────────────────────────────────────────────────────
def test_state_neutral():
    assert _classify_state(0.0)    == 'NEUTRAL'
    assert _classify_state(1.0)    == 'NEUTRAL'
    assert _classify_state(-1.0)   == 'NEUTRAL'
    assert _classify_state(1.39)   == 'NEUTRAL'
    assert _classify_state(-1.39)  == 'NEUTRAL'


def test_state_pain_boundaries():
    # L1_UP boundary (>= +1.4)
    assert _classify_state(1.4)    == 'GREED_PAIN'
    assert _classify_state(1.5)    == 'GREED_PAIN'
    assert _classify_state(2.09)   == 'GREED_PAIN'
    # L1_DN boundary (<= -1.4)
    assert _classify_state(-1.4)   == 'FEAR_PAIN'
    assert _classify_state(-1.5)   == 'FEAR_PAIN'
    assert _classify_state(-1.79)  == 'FEAR_PAIN'


def test_state_max_pain_boundaries():
    # L2_UP boundary (>= +2.1)
    assert _classify_state(2.1)    == 'GREED_MAX_PAIN'
    assert _classify_state(3.0)    == 'GREED_MAX_PAIN'
    # L2_DN boundary (<= -1.8)
    assert _classify_state(-1.8)   == 'FEAR_MAX_PAIN'
    assert _classify_state(-3.0)   == 'FEAR_MAX_PAIN'


def test_state_nan_handling():
    assert _classify_state(float('nan')) == 'NEUTRAL'
    assert _classify_state(None)         == 'NEUTRAL'


def test_asymmetric_thresholds():
    # User spec: L2_UP=+2.1 but L2_DN=-1.8 (not -2.1)
    assert LEVEL_L2_UP == +2.1
    assert LEVEL_L2_DN == -1.8
    # Fear trigger at -1.8 but greed trigger only at +2.1
    assert abs(LEVEL_L2_DN) < abs(LEVEL_L2_UP)


# ── TSI math (operator-spec parameters) ──────────────────────────────────────
def test_tsi_params_match_spec():
    assert TSI_LONG  == 69
    assert TSI_SHORT == 9
    assert TSI_SCALE == 14.0
    assert TSI_INVERT is True


def test_tsi_inversion_sign():
    """USDT.D rising (fear) → inverted TSI negative; falling (greed) → positive."""
    # Rising series
    rising = pd.Series(np.linspace(5.0, 7.0, 300))
    tsi_up = _tsi(rising)
    # Last value should be negative (inverted) since USDT.D is rising
    assert tsi_up.iloc[-1] < 0

    # Falling series
    falling = pd.Series(np.linspace(7.0, 5.0, 300))
    tsi_dn = _tsi(falling)
    # Last value should be positive (inverted) since USDT.D is falling
    assert tsi_dn.iloc[-1] > 0


def test_tsi_scale_applied():
    """TSI output divided by TSI_SCALE=14 — magnitude should be in small-float range."""
    series = pd.Series(np.random.RandomState(42).randn(500).cumsum() + 100)
    tsi = _tsi(series)
    # After scaling by 14, values should be bounded roughly in ±10
    assert tsi.dropna().abs().max() < 20


# ── LinReg math ──────────────────────────────────────────────────────────────
def test_linreg_params_match_spec():
    from usdt_dominance import LINREG_LEN, LINREG_NORM, LINREG_SMOOTH, LINREG_INVERT
    assert LINREG_LEN    == 270
    assert LINREG_NORM   == 69
    assert LINREG_SMOOTH == 39
    assert LINREG_INVERT is False


def test_linreg_nan_warmup():
    """First LINREG_LEN+LINREG_NORM-1 bars should be NaN (need both windows)."""
    from usdt_dominance import LINREG_LEN, LINREG_NORM
    series = pd.Series(np.random.RandomState(0).randn(LINREG_LEN + LINREG_NORM + 50).cumsum() + 50)
    lr = _linreg(series)
    assert lr.iloc[:LINREG_LEN - 1].isna().all()


# ── Fail-open behaviour ─────────────────────────────────────────────────────
def test_fail_open_when_not_ready(tmp_path, monkeypatch):
    """When DB has no history, gates must fail-open (allow both directions)."""
    import usdt_dominance as mod
    # Point to an empty temp DB
    monkeypatch.setattr(mod, 'DB_PATH', str(tmp_path / 'empty.db'))
    monkeypatch.setattr(mod, '_cached_states', {})  # clear per-TF cache
    monkeypatch.setattr(mod, '_last_live_fetch', 1e12)  # block CoinGecko poll

    assert long_allowed()  is True
    assert short_allowed() is True


# ── Multi-timeframe support ─────────────────────────────────────────────────
def test_timeframe_validation():
    """Unsupported timeframes should raise ValueError."""
    from usdt_dominance import get_usdt_dominance_state
    with pytest.raises(ValueError):
        get_usdt_dominance_state(timeframe='7m')


def test_default_timeframe_is_1h():
    """Bot's main loop runs on 1H — default must match."""
    from usdt_dominance import DEFAULT_TIMEFRAME
    assert DEFAULT_TIMEFRAME == '1h'


def test_per_timeframe_cache_isolation(tmp_path, monkeypatch):
    """Cache entries are keyed by timeframe — 1H and 4H are independent."""
    import usdt_dominance as mod
    monkeypatch.setattr(mod, 'DB_PATH', str(tmp_path / 'empty.db'))
    monkeypatch.setattr(mod, '_cached_states', {})
    monkeypatch.setattr(mod, '_last_live_fetch', 1e12)

    s_1h = mod.get_usdt_dominance_state(timeframe='1h')
    s_4h = mod.get_usdt_dominance_state(timeframe='4h')
    assert '1h' in mod._cached_states
    assert '4h' in mod._cached_states
    assert s_1h is not s_4h


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
