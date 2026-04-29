"""
pine_bridge.py — Python client for the PineTS sidecar (port 3141).

Usage:
    from pine_bridge import run_pine_script, get_supertrend, get_indicators

    # Run any Pine Script v5
    result = await run_pine_script(
        script='//@version=5\\nindicator("x")\\nplot(ta.rsi(close,14),"RSI")',
        symbol='BTCUSDT', interval='1h', bars=200
    )

    # Supertrend shortcut
    st = await get_supertrend('BTCUSDT', '1h')  # {'direction': 1, 'line': 84120.0}

    # RSI + MACD + EMA shortcut
    ind = await get_indicators('ETHUSDT', '1h')  # {'rsi': 54.3, 'macd': ...}
"""

import asyncio
import aiohttp
import pandas as pd
from utils_logger import log_message


def _df_to_candles(df: pd.DataFrame) -> list[dict]:
    """
    Convert OHLCV DataFrame to the array-of-dicts format that PineTS expects.

    PineTS accepts either:
      • Provider.Binance(symbol, interval, bars) — live fetch (slow)
      • An array of candle objects: [{time, open, high, low, close, volume}, …]

    Column renaming is inserted here so callers can pass a raw DataFrame
    with any case conventions and we normalise the keys.
    """
    _df = df.copy()
    _rename = {
        'open': 'open', 'Open': 'open', 'OPEN': 'open',
        'high': 'high', 'High': 'high', 'HIGH': 'high',
        'low':  'low',  'Low':  'low',  'LOW':  'low',
        'close':'close','Close':'close','CLOSE':'close',
        'volume':'volume','Volume':'volume','VOLUME':'volume',
    }
    _df.rename(columns={k: v for k, v in _rename.items() if k in _df.columns}, inplace=True)
    if 'time' not in _df.columns:
        _df['time'] = _df.index.astype('int64') // 10**6  # ns → ms timestamp
    return _df[['time', 'open', 'high', 'low', 'close', 'volume']].to_dict('records')

SIDECAR_URL = "http://127.0.0.1:3141"
_SESSION: aiohttp.ClientSession | None = None


async def _session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    return _SESSION


async def _post(path: str, payload: dict) -> dict | None:
    try:
        sess = await _session()
        async with sess.post(f"{SIDECAR_URL}{path}", json=payload) as resp:
            data = await resp.json()
            if resp.status != 200:
                log_message(f"[pine_bridge] {path} error {resp.status}: {data.get('error','?')}")
                return None
            return data
    except Exception as exc:
        log_message(f"[pine_bridge] {path} request failed: {exc}")
        return None


async def run_pine_script(script: str, symbol: str = "BTCUSDT",
                          interval: str = "1h", bars: int = 200,
                          candles: list | None = None) -> dict | None:
    """Run arbitrary Pine Script v5 via PineTS sidecar."""
    payload = {"script": script, "symbol": symbol,
               "interval": interval, "bars": bars}
    if candles:
        payload["candles"] = candles
    return await _post("/run", payload)


async def get_supertrend(symbol: str = "BTCUSDT", interval: str = "1h",
                         period: int = 10, multiplier: float = 3.0,
                         bars: int = 100,
                         df: pd.DataFrame | None = None) -> dict | None:
    """
    Supertrend shortcut.

    If ``df`` is provided, the DataFrame is converted to PineTS candle format
    and sent inline — no duplicate Binance fetch occurs.
    Otherwise the sidecar fetches fresh data via Provider.Binance.
    """
    payload: dict = {
        "symbol": symbol, "interval": interval,
        "period": period, "multiplier": multiplier, "bars": bars
    }
    if df is not None and not df.empty:
        payload["candles"] = _df_to_candles(df)
    return await _post("/supertrend", payload)


async def get_indicators(symbol: str = "BTCUSDT", interval: str = "1h",
                          bars: int = 100,
                          df: pd.DataFrame | None = None) -> dict | None:
    """
    RSI + MACD + EMA21/50 + BB + Supertrend.

    Priority:
      1. If ``df`` is provided, try fast Python‑native ``pine_core_bridge`` first.
      2. If that fails (or is unavailable), forward the pre‑fetched data as
         ``candles`` to the Node.js sidecar so it does NOT perform its own
         duplicate Binance HTTP call.
      3. If no ``df``, delegate entirely to the sidecar (live fetch).
    """
    if df is not None and not df.empty:
        try:
            from pine_core_bridge import get_pine_indicators
            return get_pine_indicators(df)
        except Exception:
            pass
        # Fallback: sidecar, but with pre‑fetched candles — zero duplicate fetch.
        payload: dict = {"symbol": symbol, "interval": interval, "bars": bars}
        payload["candles"] = _df_to_candles(df)
        return await _post("/indicators", payload)
    return await _post("/indicators", {
        "symbol": symbol, "interval": interval, "bars": bars
    })


async def health_check() -> bool:
    """Return True if the PineTS sidecar is reachable."""
    try:
        sess = await _session()
        async with sess.get(f"{SIDECAR_URL}/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
            return r.status == 200
    except Exception:
        return False
