"""
pine_core_bridge.py — Pure-Python Pine Script execution via PyneCore.

Runs Pine Script v5 logic natively in Python using AST transformations,
without a Node.js sidecar. Accepts pandas DataFrames directly.

Usage:
    from pine_core_bridge import run_pine_on_df, get_pine_indicators

    result = run_pine_on_df(df, script)
    indicators = get_pine_indicators(df)   # RSI, MACD, EMA21/50, BB, Supertrend
"""

import sys
import os
import tempfile
import importlib
from typing import Optional
import pandas as pd
import numpy as np
from utils_logger import log_message

_PYNECORE_AVAILABLE: bool = False
try:
    import pynecore  # noqa: F401
    _PYNECORE_AVAILABLE = True
except ImportError:
    pass


def is_available() -> bool:
    return _PYNECORE_AVAILABLE


def run_pine_on_df(df: pd.DataFrame, script: str) -> Optional[dict]:
    """
    Execute a PyneCore-annotated Python script against a DataFrame.

    The script must include the `\"\"\" @pyne \"\"\"` magic comment and use
    pynecore.lib functions (ta.rsi, ta.macd, etc.).

    Returns the output dict produced by the script, or None on failure.
    """
    if not _PYNECORE_AVAILABLE:
        log_message("[pine_core] PyneCore not available")
        return None
    try:
        # Write script to a temp file so the import hook can transform it
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, dir="/tmp", prefix="pyne_"
        ) as f:
            f.write(script)
            tmp_path = f.name

        # Add /tmp to sys.path temporarily
        if "/tmp" not in sys.path:
            sys.path.insert(0, "/tmp")

        mod_name = os.path.basename(tmp_path).replace(".py", "")
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        mod = importlib.import_module(mod_name)
        os.unlink(tmp_path)
        return vars(mod) if mod else None
    except Exception as exc:
        log_message(f"[pine_core] run_pine_on_df error: {exc}")
        return None


def get_pine_indicators(df: pd.DataFrame, rsi_period: int = 14,
                        ema_fast: int = 9, ema_slow: int = 21,
                        ema_trend: int = 50) -> dict:
    """
    Compute a standard set of TradingView-compatible indicators from a DataFrame
    using pynecore semantics. Falls back to numpy/pandas if PyneCore unavailable.

    Returns:
        {
          rsi: float,
          macd: float, macd_signal: float, macd_hist: float,
          ema_fast: float, ema_slow: float, ema_trend: float,
          bb_upper: float, bb_mid: float, bb_lower: float,
          supertrend_dir: int,   # 1=up, -1=down
          supertrend_line: float,
        }
    """
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    n     = len(close)

    def ema(src, span):
        alpha = 2.0 / (span + 1)
        out = np.zeros(n)
        out[0] = src[0]
        for i in range(1, n):
            out[i] = alpha * src[i] + (1 - alpha) * out[i - 1]
        return out

    def rma(src, period):
        alpha = 1.0 / period
        out = np.zeros(n)
        out[0] = src[0]
        for i in range(1, n):
            out[i] = alpha * src[i] + (1 - alpha) * out[i - 1]
        return out

    # RSI (Wilder/RMA)
    delta = np.diff(close, prepend=close[0])
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_g = rma(gains, rsi_period)
    avg_l = rma(losses, rsi_period)
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(avg_l < 1e-12, 100.0, avg_g / avg_l)
    rsi_arr = 100.0 - 100.0 / (1.0 + rs)

    # EMAs
    ema_f = ema(close, ema_fast)
    ema_s = ema(close, ema_slow)
    ema_t = ema(close, ema_trend)

    # MACD (12/26/9)
    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd_line   = ema12 - ema26
    macd_signal = ema(macd_line, 9)
    macd_hist   = macd_line - macd_signal

    # Bollinger Bands (20, 2)
    bb_period = 20
    bb_mid_arr = np.array([close[max(0, i - bb_period + 1):i + 1].mean() for i in range(n)])
    bb_std_arr = np.array([close[max(0, i - bb_period + 1):i + 1].std() for i in range(n)])
    bb_upper_arr = bb_mid_arr + 2.0 * bb_std_arr
    bb_lower_arr = bb_mid_arr - 2.0 * bb_std_arr

    # Supertrend (10, 3.0) via aladdin_core Rust if available
    st_dir, st_line = 1, float(close[-1])
    try:
        import aladdin_core
        st_arr, dir_arr = aladdin_core.calculate_supertrend_rust(
            list(high), list(low), list(close), 10, 3.0
        )
        st_dir  = int(dir_arr[-1])
        st_line = float(st_arr[-1])
    except Exception:
        pass

    return {
        "rsi":            round(float(rsi_arr[-1]), 2),
        "macd":           round(float(macd_line[-1]), 6),
        "macd_signal":    round(float(macd_signal[-1]), 6),
        "macd_hist":      round(float(macd_hist[-1]), 6),
        f"ema{ema_fast}": round(float(ema_f[-1]), 8),
        f"ema{ema_slow}": round(float(ema_s[-1]), 8),
        f"ema{ema_trend}": round(float(ema_t[-1]), 8),
        "bb_upper":       round(float(bb_upper_arr[-1]), 8),
        "bb_mid":         round(float(bb_mid_arr[-1]), 8),
        "bb_lower":       round(float(bb_lower_arr[-1]), 8),
        "supertrend_dir": st_dir,
        "supertrend_line": round(st_line, 8),
        "source":         "pynecore" if _PYNECORE_AVAILABLE else "numpy",
    }
