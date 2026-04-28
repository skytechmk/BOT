"""
MEXC Futures Data Fetcher
=========================
Parallel to data_fetcher.py (Binance), provides:
  - fetch_mexc_trading_pairs()  → list of MEXC USDT perp symbols (Binance format)
  - fetch_mexc_data(pair, interval) → OHLCV DataFrame (same shape as Binance)

Uses the same SQLite OHLCV cache as Binance (table names prefixed MEXC_).
All symbols are normalised to Binance format (BTCUSDT) internally; converted
to MEXC format (BTC_USDT) only at the API boundary.

MEXC kline response format:
    {"time": [...], "open": [...], "close": [...], "high": [...],
     "low": [...], "vol": [...], "amount": [...]}
    — parallel arrays, timestamps in seconds.
"""

import os
import time
import threading
from typing import Dict, List, Optional

import pandas as pd
import requests

from utils_logger import log_message

# ── MEXC API base ─────────────────────────────────────────────────────
_MEXC_BASE = "https://api.mexc.com"
_MEXC_TIMEOUT = 20

# ── Interval mapping: Binance → MEXC ─────────────────────────────────
_INTERVAL_MAP = {
    '1m':  'Min1',   '5m':  'Min5',   '15m': 'Min15',  '30m': 'Min30',
    '1h':  'Min60',  '4h':  'Hour4',  '8h':  'Hour8',
    '1d':  'Day1',   '1w':  'Week1',
}

# Interval → milliseconds (same as data_fetcher.py)
_INTERVAL_MS = {
    '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
    '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
    '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
    '12h': 43_200_000, '1d': 86_400_000, '1w': 604_800_000,
}

# How many candles to keep per (pair, interval)
_OHLCV_MAX_CANDLES = {
    '1w': 260, '1d': 500, '4h': 600, '1h': 1000, '15m': 600, '5m': 500,
}
_OHLCV_DEFAULT_MAX = 500

# ── OHLCV SQLite Cache (shared with data_fetcher) ────────────────────
import sqlite3
_OHLCV_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ohlcv_cache.db')
_OHLCV_DB_LOCK = threading.Lock()


def _ohlcv_db_conn():
    conn = sqlite3.connect(_OHLCV_DB_PATH, timeout=10, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def _ohlcv_ensure_table(conn, table):
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "{table}" (
            timestamp INTEGER PRIMARY KEY,
            open REAL, high REAL, low REAL, close REAL, volume REAL
        )
    ''')
    conn.commit()


def _ohlcv_load(pair, interval):
    table = f"MEXC_{pair}_{interval}"
    try:
        conn = _ohlcv_db_conn()
        with _OHLCV_DB_LOCK:
            _ohlcv_ensure_table(conn, table)
        df = pd.read_sql_query(
            f'SELECT timestamp, open, high, low, close, volume FROM "{table}" ORDER BY timestamp',
            conn)
        conn.close()
        if df.empty:
            return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def _ohlcv_save(pair, interval, df):
    if df is None or df.empty:
        return
    table = f"MEXC_{pair}_{interval}"
    max_rows = _OHLCV_MAX_CANDLES.get(interval, _OHLCV_DEFAULT_MAX)
    try:
        df_save = df.copy()
        idx = df_save.index
        if isinstance(idx, pd.DatetimeIndex) or pd.api.types.is_datetime64_any_dtype(idx):
            ms_idx = idx.astype('datetime64[ns]').astype('int64') // 10**6
        else:
            ms_idx = idx.astype('int64')
            if (ms_idx >= 10**15).all():
                ms_idx = ms_idx // 10**6
            elif (ms_idx < 10**10).all():
                ms_idx = ms_idx * 1000
        df_save.index = ms_idx
        rows = df_save[['open', 'high', 'low', 'close', 'volume']].reset_index()
        rows.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        with _OHLCV_DB_LOCK:
            conn = _ohlcv_db_conn()
            _ohlcv_ensure_table(conn, table)
            conn.executemany(
                f'INSERT OR REPLACE INTO "{table}" VALUES (?,?,?,?,?,?)',
                rows.values.tolist()
            )
            conn.execute(f'''
                DELETE FROM "{table}" WHERE timestamp NOT IN (
                    SELECT timestamp FROM "{table}" ORDER BY timestamp DESC LIMIT {max_rows}
                )
            ''')
            conn.commit()
            conn.close()
    except Exception as e:
        log_message(f"[MEXC] OHLCV save error for {pair} {interval}: {e}")


# ── Symbol helpers ────────────────────────────────────────────────────
def _to_mexc(binance_sym: str) -> str:
    """BTCUSDT → BTC_USDT"""
    s = binance_sym.upper().strip()
    if '_' in s:
        return s
    for quote in ('USDT', 'USDC', 'USD'):
        if s.endswith(quote):
            return s[:-len(quote)] + '_' + quote
    return s


def _to_binance(mexc_sym: str) -> str:
    """BTC_USDT → BTCUSDT"""
    return mexc_sym.replace('_', '')


# ── Pair Discovery ────────────────────────────────────────────────────
_MEXC_PAIRS_CACHE: Dict = {'data': None, 'timestamp': 0, 'contracts': {}}
_MEXC_PAIRS_TTL = 3600  # 1 hour


def fetch_mexc_trading_pairs(min_vol_24h: float = 50_000) -> List[str]:
    """Fetch all active MEXC USDT perpetual pairs, sorted by 24h volume.

    Returns symbols in Binance format (BTCUSDT).
    Filters: quoteCoin=USDT, state=0 (active), 24h volume >= min_vol_24h.
    """
    global _MEXC_PAIRS_CACHE
    now = time.time()
    if _MEXC_PAIRS_CACHE['data'] is not None and (now - _MEXC_PAIRS_CACHE['timestamp']) < _MEXC_PAIRS_TTL:
        return _MEXC_PAIRS_CACHE['data']

    try:
        r = requests.get(f'{_MEXC_BASE}/api/v1/contract/detail', timeout=_MEXC_TIMEOUT)
        r.raise_for_status()
        contracts = r.json().get('data', [])
        if not isinstance(contracts, list):
            log_message(f"[MEXC] Unexpected contract detail response: {type(contracts)}")
            return _MEXC_PAIRS_CACHE['data'] or []

        # Also fetch tickers for volume data
        rt = requests.get(f'{_MEXC_BASE}/api/v1/contract/ticker', timeout=_MEXC_TIMEOUT)
        rt.raise_for_status()
        tickers = rt.json().get('data', [])
        vol_map = {}
        if isinstance(tickers, list):
            for t in tickers:
                sym = t.get('symbol', '')
                vol_map[sym] = float(t.get('amount24', 0) or 0)  # 24h turnover in quote

        # Build contract cache & filter
        contract_map = {}
        pairs_with_vol = []
        for c in contracts:
            sym = c.get('symbol', '')
            if c.get('quoteCoin') != 'USDT' or c.get('state') != 0:
                continue
            contract_map[sym] = c
            vol_24h = vol_map.get(sym, 0)
            if vol_24h >= min_vol_24h:
                pairs_with_vol.append((_to_binance(sym), vol_24h))

        # Sort by volume descending
        pairs_with_vol.sort(key=lambda x: x[1], reverse=True)
        result = [p[0] for p in pairs_with_vol]

        log_message(f"[MEXC] Fetched {len(result)} USDT perp pairs "
                    f"(min vol ${min_vol_24h:,.0f}, total active={len(contract_map)})")

        _MEXC_PAIRS_CACHE['data'] = result
        _MEXC_PAIRS_CACHE['timestamp'] = now
        _MEXC_PAIRS_CACHE['contracts'] = contract_map
        return result

    except Exception as e:
        log_message(f"[MEXC] Error fetching pairs: {e}")
        return _MEXC_PAIRS_CACHE['data'] or []


def get_mexc_contract_info(pair: str) -> Optional[Dict]:
    """Get contract details for a MEXC pair (uses cached data from fetch_mexc_trading_pairs)."""
    mexc_sym = _to_mexc(pair)
    return _MEXC_PAIRS_CACHE.get('contracts', {}).get(mexc_sym)


# ── MEXC Kline Adapter ────────────────────────────────────────────────
def _parse_mexc_klines(raw: dict) -> pd.DataFrame:
    """Convert MEXC kline response to standard OHLCV DataFrame.

    MEXC format: {time: [int,...], open: [...], high: [...], low: [...],
                  close: [...], vol: [...], ...}
    Timestamps are in seconds.
    """
    if not isinstance(raw, dict):
        return pd.DataFrame()
    times = raw.get('time', [])
    opens = raw.get('open', [])
    highs = raw.get('high', [])
    lows = raw.get('low', [])
    closes = raw.get('close', [])
    vols = raw.get('vol', [])
    if not times or not closes:
        return pd.DataFrame()
    n = min(len(times), len(opens), len(highs), len(lows), len(closes), len(vols))
    try:
        df = pd.DataFrame({
            'open':   [float(opens[i]) for i in range(n)],
            'high':   [float(highs[i]) for i in range(n)],
            'low':    [float(lows[i]) for i in range(n)],
            'close':  [float(closes[i]) for i in range(n)],
            'volume': [float(vols[i]) for i in range(n)],
        }, index=pd.to_datetime([int(times[i]) for i in range(n)], unit='s'))
        df.index.name = 'timestamp'
        return df.sort_index()
    except Exception:
        return pd.DataFrame()


# ── Rate limiting ─────────────────────────────────────────────────────
_MEXC_LAST_CALL = 0.0
_MEXC_MIN_INTERVAL = 0.1  # 100ms between API calls


def _mexc_rate_limit():
    global _MEXC_LAST_CALL
    now = time.time()
    delta = now - _MEXC_LAST_CALL
    if delta < _MEXC_MIN_INTERVAL:
        time.sleep(_MEXC_MIN_INTERVAL - delta)
    _MEXC_LAST_CALL = time.time()


# ── Main data fetch ───────────────────────────────────────────────────
def fetch_mexc_data(pair: str, interval: str = '1h', retries: int = 3) -> pd.DataFrame:
    """Fetch MEXC kline data — cache-first, then incremental from API.

    Returns DataFrame with columns [open, high, low, close, volume]
    and DatetimeIndex, identical shape to data_fetcher.fetch_data().
    """
    mexc_interval = _INTERVAL_MAP.get(interval)
    if not mexc_interval:
        log_message(f"[MEXC] Unsupported interval: {interval}")
        return pd.DataFrame()

    max_candles = _OHLCV_MAX_CANDLES.get(interval, _OHLCV_DEFAULT_MAX)

    # Step 1: Load from cache
    cached_df = _ohlcv_load(pair, interval)

    # Step 2: Build API params
    mexc_sym = _to_mexc(pair)
    params = {'interval': mexc_interval}

    if not cached_df.empty:
        last_ts_ms = int(cached_df.index[-1].timestamp() * 1000)
        now_ms = int(time.time() * 1000)
        iv_ms = _INTERVAL_MS.get(interval, 3_600_000)
        gap_candles = max(1, int((now_ms - last_ts_ms) / iv_ms) + 5)
        if gap_candles <= 5:
            # Cache is fresh enough
            return cached_df.iloc[-max_candles:]
        # MEXC start/end are in seconds
        params['start'] = int(last_ts_ms / 1000)

    # Step 3: Fetch from MEXC API
    attempt = 0
    new_df = pd.DataFrame()
    while attempt < retries:
        try:
            _mexc_rate_limit()
            url = f'{_MEXC_BASE}/api/v1/contract/kline/{mexc_sym}'
            r = requests.get(url, params=params, timeout=_MEXC_TIMEOUT)
            r.raise_for_status()
            raw = r.json().get('data', {})
            new_df = _parse_mexc_klines(raw)
            break
        except Exception as e:
            attempt += 1
            if attempt < retries:
                backoff = min(2 ** attempt, 16)
                time.sleep(backoff)
            else:
                log_message(f"[MEXC] Kline fetch failed for {pair} {interval} after {retries} attempts: {e}")

    # Step 4: Merge cache + new
    if not new_df.empty:
        if not cached_df.empty:
            new_df = new_df[~new_df.index.isin(cached_df.index)]
        merged = pd.concat([cached_df, new_df]).sort_index() if not cached_df.empty else new_df
        _ohlcv_save(pair, interval, merged)
        return merged.iloc[-max_candles:]
    elif not cached_df.empty:
        return cached_df.iloc[-max_candles:]
    else:
        return pd.DataFrame()


# ── Batch fetch (for prefetch/warmup) ─────────────────────────────────
def fetch_mexc_data_batch(pairs: List[str], interval: str = '1h',
                          workers: int = 10) -> Dict[str, pd.DataFrame]:
    """Fetch klines for multiple MEXC pairs in parallel using ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}

    def _fetch_one(pair):
        return pair, fetch_mexc_data(pair, interval)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, p): p for p in pairs}
        for f in as_completed(futures):
            try:
                pair, df = f.result()
                if df is not None and not df.empty:
                    results[pair] = df
            except Exception:
                pass
    return results
