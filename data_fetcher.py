import pandas as pd
import numpy as np
import time
import asyncio
import os
import sqlite3
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectTimeout
from urllib3.exceptions import MaxRetryError
from utils_logger import log_message
from constants import *
from shared_state import client

# ── OHLCV SQLite Cache ────────────────────────────────────────────────────────
# Stores candles per (pair, interval). fetch_data() reads from DB first,
# then fetches only the missing (new) candles from Binance API.
_OHLCV_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ohlcv_cache.db')
_OHLCV_DB_LOCK = threading.Lock()

# How many candles to keep per (pair, interval) — older ones are pruned
_OHLCV_MAX_CANDLES = {
    '1w': 260,   # ~5 years
    '1d': 500,   # ~2 years
    '4h': 600,   # ~100 days
    '2h': 500,   # ~41 days (for pair_macro_indicator LinReg 278+69 warmup)
    '1h': 1000,  # ~42 days (increased for deep chart history via proxy pool)
    '15m': 600,  # ~6 days
    '5m':  500,
    '3m':  500,
}
_OHLCV_DEFAULT_MAX = 500

def _ohlcv_db_conn():
    """Return a thread-local SQLite connection (WAL mode for concurrency)."""
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
    """Load cached candles from DB as DataFrame. Returns empty DF if none."""
    table = f"{pair}_{interval}"
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
    """Upsert DataFrame rows into DB and prune old candles."""
    if df is None or df.empty:
        return
    table = f"{pair}_{interval}"
    max_rows = _OHLCV_MAX_CANDLES.get(interval, _OHLCV_DEFAULT_MAX)
    try:
        df_save = df.copy()
        # Convert index to int64 ms-epoch, handling both datetime64 and numeric inputs.
        # Previous versions assumed datetime64[ns] and did `astype('int64') // 10**6`
        # which corrupted numeric-ms indexes (ms / 1e6 = tiny microsecond value),
        # leaving timestamps frozen at 1970-01-01.
        idx = df_save.index
        if isinstance(idx, pd.DatetimeIndex) or pd.api.types.is_datetime64_any_dtype(idx):
            # Force ns precision before converting to int. In newer pandas,
            # pd.to_datetime(..., unit='ms') returns datetime64[ms]; doing
            # astype('int64') then gives ms directly, and dividing by 1e6
            # would corrupt the timestamp to microseconds.
            ms_idx = idx.astype('datetime64[ns]').astype('int64') // 10**6
        else:
            # Already numeric — detect unit by magnitude.
            ms_idx = idx.astype('int64')
            if (ms_idx >= 10**15).all():
                ms_idx = ms_idx // 10**6          # ns → ms
            elif (ms_idx < 10**10).all():
                ms_idx = ms_idx * 1000            # sec → ms
            # else: already in ms, leave as-is
        df_save.index = ms_idx
        rows = df_save[['open','high','low','close','volume']].reset_index()
        rows.columns = ['timestamp','open','high','low','close','volume']
        with _OHLCV_DB_LOCK:
            conn = _ohlcv_db_conn()
            _ohlcv_ensure_table(conn, table)
            conn.executemany(
                f'INSERT OR REPLACE INTO "{table}" VALUES (?,?,?,?,?,?)',
                rows.values.tolist()
            )
            # Prune: keep only latest max_rows candles
            conn.execute(f'''
                DELETE FROM "{table}" WHERE timestamp NOT IN (
                    SELECT timestamp FROM "{table}" ORDER BY timestamp DESC LIMIT {max_rows}
                )
            ''')
            conn.commit()
            conn.close()
    except Exception:
        pass

# ── USDT Dominance Cache (CoinGecko free API — no key required) ──────────────
_USDT_DOM_CACHE   = {'usdt_d': None, 'btc_d': None, 'trend': 'neutral', 'ts': 0}
_USDT_DOM_TTL     = 600   # Refresh every 10 minutes
_USDT_DOM_HISTORY = []    # Rolling buffer of last 5 readings for robust trend detection

def get_usdt_dominance():
    """
    Fetch USDT and BTC dominance % from CoinGecko /global endpoint (free, no key).
    Returns dict: {usdt_d: float, btc_d: float, trend: 'rising'|'falling'|'neutral'}

    Trend uses rolling average of last 5 readings (not single-diff) to avoid
    false signals when CoinGecko API is temporarily unavailable.

    USDT.D rising  → money flowing to stables → bearish crypto → block LONGs
    USDT.D falling → money flowing to crypto  → bullish        → block SHORTs
    """
    global _USDT_DOM_CACHE, _USDT_DOM_HISTORY
    now = time.time()
    if _USDT_DOM_CACHE['usdt_d'] is not None and now - _USDT_DOM_CACHE['ts'] < _USDT_DOM_TTL:
        return _USDT_DOM_CACHE

    try:
        import urllib.request, json as _json
        url = 'https://api.coingecko.com/api/v3/global'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read())['data']

        market_cap_pct = data.get('market_cap_percentage', {})
        usdt_d = float(market_cap_pct.get('usdt', 0.0))
        btc_d  = float(market_cap_pct.get('btc',  0.0))

        # Rolling history: keep last 5 readings
        _USDT_DOM_HISTORY.append(usdt_d)
        if len(_USDT_DOM_HISTORY) > 5:
            _USDT_DOM_HISTORY.pop(0)

        # Trend: compare oldest vs newest in rolling window (requires ≥3 readings)
        trend = 'neutral'
        if len(_USDT_DOM_HISTORY) >= 3:
            oldest = sum(_USDT_DOM_HISTORY[:2]) / 2   # avg of first 2
            newest = sum(_USDT_DOM_HISTORY[-2:]) / 2  # avg of last 2
            delta  = newest - oldest
            if delta > 0.2:
                trend = 'rising'
            elif delta < -0.2:
                trend = 'falling'

        _USDT_DOM_CACHE = {'usdt_d': usdt_d, 'btc_d': btc_d, 'trend': trend, 'ts': now}
        log_message(f"📊 USDT.D: {usdt_d:.2f}% | BTC.D: {btc_d:.2f}% | Trend: {trend} (history: {len(_USDT_DOM_HISTORY)} pts)")
        return _USDT_DOM_CACHE

    except Exception as e:
        log_message(f"USDT dominance fetch failed: {e} — using cached/neutral")
        if _USDT_DOM_CACHE['usdt_d'] is None:
            _USDT_DOM_CACHE = {'usdt_d': 5.0, 'btc_d': 50.0, 'trend': 'neutral', 'ts': now}
        return _USDT_DOM_CACHE

# Exchange Info Cache (P1 fix: avoid 50 API calls/cycle for precision)
_EXCHANGE_INFO_CACHE = {'data': None, 'timestamp': 0, 'precision_map': {}}
_EXCHANGE_INFO_TTL = 86400  # Refresh every 24h

# Funding Rate Cache (Fix 403 Forbidden WAF bans)
_FUNDING_CACHE = {'current': {}, 'history': {}}
_FUNDING_TTL = 300  # Cache for 5 minutes

# Open Interest Cache (avoid repeated snapshot + history calls)
_OI_SNAPSHOT_CACHE = {}
_OI_SNAPSHOT_TTL = 300  # Cache for 5 minutes

# Leverage Brackets Cache (avoid redundant API call every scan cycle)
_LEVERAGE_CACHE = {'data': {}, 'timestamp': 0}
_LEVERAGE_TTL = 86400  # Refresh every 24h

# Static Binance Futures leverage tiers (used as fallback when API key lacks permissions).
# Source: Binance Futures leverage bracket documentation (major tiers as of 2025-Q4).
_STATIC_LEVERAGE_TIERS = {
    # BTC / ETH — highest tier
    'BTCUSDT': 125, 'ETHUSDT': 100,
    # Tier 2 (50x)
    'BNBUSDT': 75, 'SOLUSDT': 50, 'XRPUSDT': 50, 'ADAUSDT': 50,
    'MATICUSDT': 50, 'DOTUSDT': 50, 'LTCUSDT': 50, 'LINKUSDT': 50,
    'AVAXUSDT': 50, 'ATOMUSDT': 50, 'UNIUSDT': 50, 'FILUSDT': 50,
    'DOGEUSDT': 50, 'SHIBUSDT': 50, '1000SHIBUSDT': 50,
    # Tier 3 (25x) — mid-cap alts
    'VETUSDT': 25, 'ICPUSDT': 25, 'AAVEUSDT': 25, 'FTMUSDT': 25,
    'SANDUSDT': 25, 'MANAUSDT': 25, 'AXSUSDT': 25, 'GALAUSDT': 25,
    'NEARUSDT': 25, 'ALGOUSDT': 25, 'APTUSDT': 25, 'ARBUSDT': 25,
    'OPUSDT': 25, 'INJUSDT': 25, 'SUIUSDT': 25, 'SEIUSDT': 25,
    'PENGUUSDT': 25, 'NOTUSDT': 25, 'TURBOUSDT': 25,
}
# Default for unknown small/micro-cap altcoins
_DEFAULT_MAX_LEVERAGE = 20

def _get_cached_leverage_brackets():
    """Return leverage map from cache, refreshing if stale.
    Falls back to the static tier map when API key lacks futures permissions.
    """
    import time as _time
    now = _time.time()
    if _LEVERAGE_CACHE['data'] and (now - _LEVERAGE_CACHE['timestamp']) < _LEVERAGE_TTL:
        return _LEVERAGE_CACHE['data']
    try:
        rate_limit()
        leverage_brackets = client.futures_leverage_bracket()
        leverage_map = {}
        for item in leverage_brackets:
            sym = item['symbol']
            brackets = item.get('brackets', item.get('bracket', []))
            if isinstance(brackets, list) and len(brackets) > 0:
                leverage_map[sym] = brackets[0].get('initialLeverage', _DEFAULT_MAX_LEVERAGE)
            else:
                leverage_map[sym] = _DEFAULT_MAX_LEVERAGE
        _LEVERAGE_CACHE['data'] = leverage_map
        _LEVERAGE_CACHE['timestamp'] = now
        log_message(f"Refreshed leverage brackets cache: {len(leverage_map)} symbols")
        return leverage_map
    except BinanceAPIException as e:
        if e.code == -2015:
            log_message("⚠️ Leverage bracket API unavailable (key lacks futures permission). Using static tier map.")
        else:
            log_message(f"Error fetching leverage brackets: {e}")
        # Seed the cache with the static map so future calls don't hit the API
        if not _LEVERAGE_CACHE['data']:
            _LEVERAGE_CACHE['data'] = dict(_STATIC_LEVERAGE_TIERS)
            _LEVERAGE_CACHE['timestamp'] = now
        return _LEVERAGE_CACHE['data']
    except Exception as e:
        log_message(f"Error refreshing leverage brackets cache: {e}")
        return _LEVERAGE_CACHE.get('data', {})

# Proxy-aware rate limiting: with rotating IPs each request hits a fresh IP,
# so the per-IP limit (1200 weight/min) never stacks. Skip the sleep entirely.
try:
    from proxy_config import is_enabled as _proxy_is_enabled
    _PROXY_ACTIVE = _proxy_is_enabled()
except Exception:
    _PROXY_ACTIVE = False

def rate_limit():
    """Rate limiting — skipped when rotating proxy pool is active (each req = fresh IP)."""
    if not _PROXY_ACTIVE:
        time.sleep(0.05)  # 50ms without proxy (was 100ms — halved for marginal gains)

def validate_api_response(response):
    """Validate Binance API response structure with detailed checks"""
    if response is None:
        log_message("API returned None response")
        return False
    if isinstance(response, str):
        log_message(f"API returned error string: {response}")
        return False
    if hasattr(response, 'message'):
        log_message(f"API returned error object: {response.message}")
        return False
    if not isinstance(response, (list, dict)):
        log_message(f"Unexpected API response type: {type(response)}")
        return False
        
    # Additional validation for dict responses
    if isinstance(response, dict):
        if 'error' in response:
            log_message(f"API returned error dict: {response['error']}")
            return False
        if 'data' not in response:
            log_message("API dict response missing 'data' key")
            return False
            
    return True

# ── Proxy-pool parallel batch fetcher ────────────────────────────────────────

import concurrent.futures as _futures

def _is_geo_restricted(resp) -> bool:
    """Detect Binance's 'Service unavailable from a restricted location' response."""
    if resp.status_code == 451:
        return True
    try:
        body = resp.text or ''
    except Exception:
        return False
    return 'restricted location' in body.lower()


def _fetch_klines_raw(pair: str, interval: str, limit: int, start_time_ms: int | None) -> tuple:
    """
    Fetch klines directly via raw HTTPS — no auth, no python-binance overhead.
    Binance Futures klines endpoint is public (no API key needed).

    First attempt uses a rotating proxy IP from the pool. If Binance rejects
    the proxy IP with a geo-restriction (HTTP 451 / "restricted location"),
    automatically retry WITHOUT the proxy using the server's direct public IP.
    Returns (pair, klines_list) or raises on failure.
    """
    try:
        from proxy_config import get_proxy_dict as _get_proxy
        _proxies = _get_proxy()
    except Exception:
        _proxies = {}
    import requests as _req
    params = {'symbol': pair, 'interval': interval, 'limit': limit}
    if start_time_ms:
        params['startTime'] = start_time_ms
    url = 'https://fapi.binance.com/fapi/v1/klines'

    # Attempt 1: via proxy
    resp = _req.get(url, params=params, proxies=_proxies, timeout=8)
    if _is_geo_restricted(resp) and _proxies:
        # Proxy IP is geo-blocked — retry via server's direct public IP
        try:
            resp = _req.get(url, params=params, proxies={}, timeout=8)
        except Exception:
            resp.raise_for_status()   # re-raise the original 451
    resp.raise_for_status()
    return pair, resp.json()


def fetch_data_batch(pairs: list, interval: str = '1h',
                     workers: int = 30) -> dict:
    """
    Fetch klines for multiple pairs in parallel using the rotating proxy pool.
    Each of the `workers` threads gets a different IP — total throughput is
    effectively workers × 1200 weight/min.

    Args:
        pairs:    list of Binance USDT perp symbols
        interval: klines interval (default '1h')
        workers:  max parallel HTTP connections (default 30)
    Returns:
        dict mapping pair → DataFrame (merged cache + new candles)
    """
    max_c = _OHLCV_MAX_CANDLES.get(interval, _OHLCV_DEFAULT_MAX)

    # Build (pair, interval, limit, startTime) for each pair
    _INTERVAL_MS_B = {
        '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
        '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
        '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
        '12h': 43_200_000, '1d': 86_400_000, '1w': 604_800_000,
    }
    _now_ms_b = int(time.time() * 1000)
    _iv_ms_b  = _INTERVAL_MS_B.get(interval, 3_600_000)
    fetch_tasks = []
    cached_map  = {}
    for pair in pairs:
        cached = _ohlcv_load(pair, interval)
        cached_map[pair] = cached
        if not cached.empty:
            last_ts_ms = int(cached.index[-1].timestamp() * 1000)
            # Compute required fetch size from actual gap to avoid stale tails.
            gap_candles = max(1, int((_now_ms_b - last_ts_ms) / _iv_ms_b) + 5)
            fetch_limit = max(20, min(gap_candles, 1500))  # Binance cap: 1500
            fetch_tasks.append((pair, interval, fetch_limit, last_ts_ms))
        else:
            fetch_tasks.append((pair, interval, max_c, None))

    results = {}
    with _futures.ThreadPoolExecutor(max_workers=min(workers, len(fetch_tasks) or 1)) as pool:
        future_map = {
            pool.submit(_fetch_klines_raw, p, iv, lim, st): p
            for p, iv, lim, st in fetch_tasks
        }
        for fut in _futures.as_completed(future_map, timeout=30):
            pair = future_map[fut]
            try:
                _, raw = fut.result(timeout=10)
                new_df  = _parse_klines_to_df(raw)
                cached  = cached_map[pair]
                if not new_df.empty:
                    if not cached.empty:
                        new_df = new_df[~new_df.index.isin(cached.index)]
                    merged = (
                        pd.concat([cached, new_df]).sort_index()
                        if not cached.empty else new_df
                    )
                    _ohlcv_save(pair, interval, merged)
                    results[pair] = merged.iloc[-max_c:]
                elif not cached.empty:
                    results[pair] = cached
            except Exception as _e:
                # Degrade gracefully — use stale cache if available
                if cached_map.get(pair) is not None and not cached_map[pair].empty:
                    results[pair] = cached_map[pair]
    return results


def _parse_klines_to_df(klines):
    """Convert raw Binance klines list to a clean OHLCV DataFrame."""
    if not isinstance(klines, list) or len(klines) == 0:
        return pd.DataFrame()
    if not all(isinstance(k, (list, tuple)) and len(k) >= 6 for k in klines):
        return pd.DataFrame()
    try:
        df = pd.DataFrame(klines, columns=[
            'timestamp','open','high','low','close','volume','close_time',
            'quote_asset_volume','number_of_trades',
            'taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        for c in ['open','high','low','close','volume']:
            df[c] = df[c].astype(float)
        return df
    except Exception:
        return pd.DataFrame()

def fetch_data(pair, interval='1d', retries=5, timeout=20):
    """Fetch market data — reads from SQLite OHLCV cache first, then fetches
    only the missing (newest) candles from Binance API and persists them.
    """
    max_candles = _OHLCV_MAX_CANDLES.get(interval, _OHLCV_DEFAULT_MAX)

    # ── Step 1: Load from cache ───────────────────────────────────────
    cached_df = _ohlcv_load(pair, interval)

    # ── Step 2: Determine how many new candles to fetch ───────────────
    # Interval → milliseconds map for gap calculation
    _INTERVAL_MS = {
        '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
        '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
        '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
        '12h': 43_200_000, '1d': 86_400_000, '1w': 604_800_000,
    }
    if not cached_df.empty:
        # Only fetch candles newer than the last cached timestamp.
        # CRITICAL: the fetch limit MUST cover the actual gap, otherwise
        # the returned data won't reach the current time and `df.iloc[-1]`
        # will still be a stale candle from days/weeks ago.
        last_ts_ms = int(cached_df.index[-1].timestamp() * 1000)
        now_ms     = int(time.time() * 1000)
        iv_ms      = _INTERVAL_MS.get(interval, 3_600_000)
        gap_candles = max(1, int((now_ms - last_ts_ms) / iv_ms) + 5)  # +5 safety
        fetch_limit = max(20, min(gap_candles, 1500))  # Binance cap: 1500
        fetch_kwargs = dict(symbol=pair, interval=interval,
                            startTime=last_ts_ms, limit=fetch_limit)
    else:
        # Cold start: fetch full history
        fetch_kwargs = dict(symbol=pair, interval=interval, limit=max_candles)

    # ── Step 3: Fetch incremental candles from Binance ────────────────
    attempt = 0
    new_df = pd.DataFrame()
    while attempt < retries:
        try:
            rate_limit()
            response = client.futures_klines(**fetch_kwargs)
            if not isinstance(response, list):
                log_message(f"Invalid API response format for {pair}: {response}")
                break
            klines = list(response) if not isinstance(response, dict) else response.get('data', [])
            new_df = _parse_klines_to_df(klines)
            break
        except (ConnectTimeout, MaxRetryError) as e:
            attempt += 1
            backoff = min(2 ** attempt, 64)
            log_message(f"Attempt {attempt}/{retries} failed for {pair} {interval}: {e} — retry in {backoff}s")
            time.sleep(backoff)
        except BinanceAPIException as e:
            # Binance rejected the configured proxy IP as geo-restricted.
            # Retry via raw HTTP without proxy (server's direct public IP).
            if 'restricted location' in str(e).lower():
                try:
                    import requests as _req
                    _params = {'symbol': pair, 'interval': interval,
                               'limit': fetch_kwargs.get('limit', 500)}
                    if 'startTime' in fetch_kwargs:
                        _params['startTime'] = fetch_kwargs['startTime']
                    _r = _req.get('https://fapi.binance.com/fapi/v1/klines',
                                  params=_params, proxies={}, timeout=10)
                    _r.raise_for_status()
                    new_df = _parse_klines_to_df(_r.json())
                    break
                except Exception as _e2:
                    log_message(f"Direct-IP fallback also failed for {pair} {interval}: {_e2}")
                    break
            log_message(f"API Error fetching {pair} {interval}: {e}")
            break
        except Exception as e:
            log_message(f"Unexpected error fetching {pair} {interval}: {e}")
            break

    # ── Step 4: Merge cache + new candles ─────────────────────────────
    if not new_df.empty:
        if not cached_df.empty:
            # Drop overlap (last cached candle may be re-fetched as open candle)
            new_df = new_df[~new_df.index.isin(cached_df.index)]
        merged = pd.concat([cached_df, new_df]).sort_index() if not cached_df.empty else new_df
        # Persist updated data back to DB
        _ohlcv_save(pair, interval, merged)
        # Return latest max_candles rows
        return merged.iloc[-max_candles:]
    elif not cached_df.empty:
        # API failed but we have cached data — use it
        return cached_df.iloc[-max_candles:]
    else:
        log_message(f"No data available for {pair} {interval}")
        return pd.DataFrame()

_TOP_PAIRS_CACHE = {'data': None, 'timestamp': 0}
_TOP_PAIRS_TTL = 3600  # Cache top volume pairs for 1 hour

def fetch_top_volume_pairs(limit=TOP_PAIRS_COUNT):
    """Fetch ALL qualifying USDT perp pairs by 24h volume. Cached to prevent bans."""
    global _TOP_PAIRS_CACHE
    import time as _time
    now = _time.time()
    
    if _TOP_PAIRS_CACHE['data'] is not None and (now - _TOP_PAIRS_CACHE['timestamp']) < _TOP_PAIRS_TTL:
        return _TOP_PAIRS_CACHE['data']

    try:
        rate_limit()
        try:
            ticker_24hr = client.futures_ticker()
        except Exception as _e:
            # Proxy IP geo-restricted — fall back to server's direct public IP
            if 'restricted location' in str(_e).lower():
                import requests as _req
                _r = _req.get('https://fapi.binance.com/fapi/v1/ticker/24hr',
                              proxies={}, timeout=15)
                _r.raise_for_status()
                ticker_24hr = _r.json()
                log_message("ℹ️ fetch_top_volume_pairs: proxy geo-restricted, used direct IP")
            else:
                raise

        # Import blacklist lazily to avoid circular imports
        try:
            from constants import MANUAL_BLACKLIST as _BL
        except ImportError:
            _BL = set()

        # All USDT perp pairs — no volume or leverage floor, sorted by 24h volume (highest priority first)
        usdt_pairs = [
            ticker for ticker in ticker_24hr
            if ticker['symbol'].endswith('USDT') and ticker['symbol'] not in _BL
        ]
        usdt_pairs.sort(key=lambda x: float(x['volume']), reverse=True)
        # Deduplicate while preserving sort order (some exchanges list same symbol twice)
        filtered_pairs = list(dict.fromkeys(ticker['symbol'] for ticker in usdt_pairs))

        log_message(f"Fetched {len(filtered_pairs)} USDT perp pairs (all available, sorted by volume)")
        
        _TOP_PAIRS_CACHE['data'] = filtered_pairs
        _TOP_PAIRS_CACHE['timestamp'] = now
        return filtered_pairs
        
    except Exception as e:
        log_message(f"Error fetching top volume pairs: {e}")
        if _TOP_PAIRS_CACHE['data'] is not None:
            return _TOP_PAIRS_CACHE['data']
        # Fallback to default pairs
        return [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT',
            'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT',
            'UNIUSDT', 'POLUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT'
        ][:limit]

def fetch_trading_pairs(retries=5, timeout=20):
    """Enhanced trading pairs fetching with volume-based selection"""
    attempt = 0
    while attempt < retries:
        try:
            # Use volume-based selection for better pairs
            return fetch_top_volume_pairs()
        except (ConnectTimeout, MaxRetryError) as e:
            log_message(f"Attempt {attempt + 1}/{retries} failed to fetch trading pairs: {e}")
            attempt += 1
            backoff = min(2 ** attempt, 64)
            log_message(f"Retrying in {backoff} seconds...")
            time.sleep(backoff)
        except BinanceAPIException as e:
            log_message(f"Error fetching trading pairs: {e}")
            return []
        except Exception as e:
            log_message(f"An unexpected error occurred while fetching trading pairs: {e}")
            return []
    return []

def _refresh_exchange_info_cache():
    """Refresh the exchange info cache if stale (called lazily)"""
    import time as _time
    now = _time.time()
    if _EXCHANGE_INFO_CACHE['data'] is None or (now - _EXCHANGE_INFO_CACHE['timestamp']) > _EXCHANGE_INFO_TTL:
        try:
            rate_limit()
            info = client.futures_exchange_info()
            _EXCHANGE_INFO_CACHE['data'] = info
            _EXCHANGE_INFO_CACHE['timestamp'] = now
            _EXCHANGE_INFO_CACHE['precision_map'] = {
                s['symbol']: s['pricePrecision'] for s in info.get('symbols', [])
            }
            log_message(f"Refreshed exchange_info cache: {len(_EXCHANGE_INFO_CACHE['precision_map'])} symbols")
        except Exception as e:
            log_message(f"Error refreshing exchange_info cache: {e}")

def get_precision(pair):
    """Get quote precision from cached exchange info (1 API call per 24h instead of per pair)"""
    _refresh_exchange_info_cache()
    return _EXCHANGE_INFO_CACHE['precision_map'].get(pair, 6)

def get_order_book_depth(pair, depth=100):
    """Calculate bid/ask imbalance and identify key supply/demand walls"""
    try:
        rate_limit()
        order_book = client.futures_order_book(symbol=pair, limit=depth)
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return {'imbalance': 1.0, 'buy_walls': [], 'sell_walls': []}
            
        # Calculate volume at different depths (1%, 5%)
        current_price = float(bids[0][0])
        depth_1pct = current_price * 0.01
        depth_5pct = current_price * 0.05
        
        vol_bid_1pct = sum(float(b[1]) for b in bids if float(b[0]) > current_price - depth_1pct)
        vol_ask_1pct = sum(float(a[1]) for a in asks if float(a[0]) < current_price + depth_1pct)
        
        # Identify "Walls" (Price levels with > 3x average volume)
        avg_bid_vol = sum(float(b[1]) for b in bids) / len(bids)
        avg_ask_vol = sum(float(a[1]) for a in asks) / len(asks)
        
        buy_walls = [float(b[0]) for b in bids if float(b[1]) > avg_bid_vol * 3]
        sell_walls = [float(a[0]) for a in asks if float(a[1]) > avg_ask_vol * 3]
        
        imbalance = vol_bid_1pct / vol_ask_1pct if vol_ask_1pct > 0 else 2.0
        
        return {
            'imbalance': imbalance,
            'buy_walls': sorted(buy_walls, reverse=True)[:3],
            'sell_walls': sorted(sell_walls)[:3],
            'vol_ratio': vol_bid_1pct / (vol_bid_1pct + vol_ask_1pct) if (vol_bid_1pct + vol_ask_1pct) > 0 else 0.5
        }
    except Exception as e:
        log_message(f"Error fetching order book for {pair}: {e}")
        return {'imbalance': 1.0, 'buy_walls': [], 'sell_walls': []}

def get_funding_rate(pair):
    """Get current funding rate for the pair.

    Resolution order:
      1. LIVE_FEED (markPrice@1s WS stream) — zero weight, always preferred.
      2. In-memory TTL cache (REST result reuse).
      3. REST `futures_funding_rate` (last resort, costs weight + IP-ban risk).
    """
    import time as _time
    now = _time.time()

    # ── 1. WS LIVE_FEED (preferred) ─────────────────────────────────────
    try:
        from live_price_feed import LIVE_FEED
        ws_pkg = LIVE_FEED.get_funding_rate(pair)
        if ws_pkg is not None:
            rate, next_T = ws_pkg
            # next_funding_ts in markPrice is the *next* settlement; the historical
            # API returns the *previous* settlement timestamp. Approximate the
            # previous settlement as next - 8h (Binance default funding interval).
            funding_time_ms = next_T - 8 * 3600 * 1000 if next_T else 0
            _FUNDING_CACHE['current'][pair] = ((rate, funding_time_ms), now)
            return rate, funding_time_ms
    except Exception:
        pass

    # ── 2. Cache ───────────────────────────────────────────────────────
    if pair in _FUNDING_CACHE['current']:
        cached_data, cached_time = _FUNDING_CACHE['current'][pair]
        if now - cached_time < _FUNDING_TTL:
            return cached_data

    # ── 3. REST fallback ───────────────────────────────────────────────
    try:
        rate_limit()
        funding_rate_info = client.futures_funding_rate(symbol=pair, limit=1)
        if funding_rate_info and len(funding_rate_info) > 0:
            funding_rate = float(funding_rate_info[0]['fundingRate'])
            funding_time = int(funding_rate_info[0]['fundingTime'])
            # Save to cache
            _FUNDING_CACHE['current'][pair] = ((funding_rate, funding_time), now)
            log_message(f"Funding rate for {pair}: {funding_rate:.6f} ({funding_rate*100:.4f}%)")
            return funding_rate, funding_time
        return 0.0, 0
    except BinanceAPIException as e:
        log_message(f"API Error fetching funding rate for {pair}: {e}")
        return 0.0, 0
    except Exception as e:
        log_message(f"Error fetching funding rate for {pair}: {e}")
        return 0.0, 0

def get_funding_rate_history(pair, limit=10):
    """Get historical funding rates for trend analysis.

    Resolution order:
      1. LIVE_FEED rolling history (built up from observed WS settlements).
         Used only if WS has accumulated >= `limit` entries.
      2. In-memory TTL cache (REST result reuse).
      3. REST `futures_funding_rate` (last resort).
    """
    import time as _time
    now = _time.time()

    # ── 1. WS LIVE_FEED rolling history (preferred when deep enough) ───
    try:
        from live_price_feed import LIVE_FEED
        ws_hist = LIVE_FEED.get_funding_history(pair, limit=limit)
        if ws_hist and len(ws_hist) >= limit:
            rates = [r for _t, r in ws_hist]
            times = [t for t, _r in ws_hist]
            return rates, times
    except Exception:
        pass

    # ── 2. Cache ───────────────────────────────────────────────────────
    cache_key = f"{pair}_{limit}"
    if cache_key in _FUNDING_CACHE['history']:
        cached_data, cached_time = _FUNDING_CACHE['history'][cache_key]
        if now - cached_time < _FUNDING_TTL:
            return cached_data

    # ── 3. REST fallback ───────────────────────────────────────────────
    try:
        rate_limit()
        funding_history = client.futures_funding_rate(symbol=pair, limit=limit)
        if funding_history and len(funding_history) > 0:
            rates = [float(item['fundingRate']) for item in funding_history]
            times = [int(item['fundingTime']) for item in funding_history]
            # Save to cache
            _FUNDING_CACHE['history'][cache_key] = ((rates, times), now)
            log_message(f"Retrieved {len(rates)} historical funding rates for {pair}")
            return rates, times
        return [], []
    except BinanceAPIException as e:
        log_message(f"API Error fetching funding rate history for {pair}: {e}")
        return [], []
    except Exception as e:
        log_message(f"Error fetching funding rate history for {pair}: {e}")
        return [], []

def analyze_funding_rate_sentiment(pair):
    """Analyze funding rate to determine market sentiment and signal strength"""
    try:
        # Get current funding rate
        current_rate, funding_time = get_funding_rate(pair)
        
        # Get historical rates for trend analysis
        historical_rates, historical_times = get_funding_rate_history(pair, limit=10)
        
        analysis = {
            'current_rate': current_rate,
            'current_rate_pct': current_rate * 100,
            'sentiment': 'NEUTRAL',
            'strength': 0.0,
            'signal_bias': 'NONE',
            'confidence_adjustment': 0.0,
            'funding_trend': 'STABLE',
            'extreme_funding': False
        }
        
        # Analyze current funding rate
        if current_rate > 0.01:  # 1% funding rate (very high)
            analysis['sentiment'] = 'EXTREMELY_BULLISH'
            analysis['strength'] = 1.0
            analysis['signal_bias'] = 'SHORT'  # High funding favors shorts
            analysis['confidence_adjustment'] = 15.0  # Boost short confidence
            analysis['extreme_funding'] = True
        elif current_rate > 0.005:  # 0.5% funding rate (high)
            analysis['sentiment'] = 'VERY_BULLISH'
            analysis['strength'] = 0.8
            analysis['signal_bias'] = 'SHORT'
            analysis['confidence_adjustment'] = 10.0
        elif current_rate > 0.001:  # 0.1% funding rate (moderately high)
            analysis['sentiment'] = 'BULLISH'
            analysis['strength'] = 0.6
            analysis['signal_bias'] = 'SHORT'
            analysis['confidence_adjustment'] = 5.0
        elif current_rate > 0.0001:  # 0.01% funding rate (slightly positive)
            analysis['sentiment'] = 'SLIGHTLY_BULLISH'
            analysis['strength'] = 0.3
            analysis['signal_bias'] = 'SLIGHT_SHORT'
            analysis['confidence_adjustment'] = 2.0
        elif current_rate < -0.01:  # -1% funding rate (very negative)
            analysis['sentiment'] = 'EXTREMELY_BEARISH'
            analysis['strength'] = 1.0
            analysis['signal_bias'] = 'LONG'  # Negative funding favors longs
            analysis['confidence_adjustment'] = 15.0  # Boost long confidence
            analysis['extreme_funding'] = True
        elif current_rate < -0.005:  # -0.5% funding rate (negative)
            analysis['sentiment'] = 'VERY_BEARISH'
            analysis['strength'] = 0.8
            analysis['signal_bias'] = 'LONG'
            analysis['confidence_adjustment'] = 10.0
        elif current_rate < -0.001:  # -0.1% funding rate (moderately negative)
            analysis['sentiment'] = 'BEARISH'
            analysis['strength'] = 0.6
            analysis['signal_bias'] = 'LONG'
            analysis['confidence_adjustment'] = 5.0
        elif current_rate < -0.0001:  # -0.01% funding rate (slightly negative)
            analysis['sentiment'] = 'SLIGHTLY_BEARISH'
            analysis['strength'] = 0.3
            analysis['signal_bias'] = 'SLIGHT_LONG'
            analysis['confidence_adjustment'] = 2.0
        else:
            analysis['sentiment'] = 'NEUTRAL'
            analysis['strength'] = 0.0
            analysis['signal_bias'] = 'NONE'
            analysis['confidence_adjustment'] = 0.0
        
        # Analyze funding rate trend if we have historical data
        if len(historical_rates) >= 3:
            recent_avg = sum(historical_rates[:3]) / 3  # Last 3 periods
            older_avg = sum(historical_rates[3:6]) / 3 if len(historical_rates) >= 6 else recent_avg
            
            trend_change = recent_avg - older_avg
            
            if trend_change > 0.001:  # Increasing funding rate
                analysis['funding_trend'] = 'INCREASING'
                if analysis['signal_bias'] == 'SHORT':
                    analysis['confidence_adjustment'] += 3.0  # Strengthen short bias
            elif trend_change < -0.001:  # Decreasing funding rate
                analysis['funding_trend'] = 'DECREASING'
                if analysis['signal_bias'] == 'LONG':
                    analysis['confidence_adjustment'] += 3.0  # Strengthen long bias
            else:
                analysis['funding_trend'] = 'STABLE'
        
        # Calculate funding rate volatility
        if len(historical_rates) >= 5:
            import statistics
            funding_volatility = statistics.stdev(historical_rates[:5])
            if funding_volatility > 0.002:  # High volatility in funding
                analysis['high_volatility'] = True
                analysis['confidence_adjustment'] *= 0.8  # Reduce confidence in volatile funding
            else:
                analysis['high_volatility'] = False
        
        log_message(f"Funding analysis for {pair}: {analysis['sentiment']} "
                   f"({analysis['current_rate_pct']:.4f}%), bias: {analysis['signal_bias']}, "
                   f"confidence adj: {analysis['confidence_adjustment']:.1f}%")
        
        return analysis
        
    except Exception as e:
        log_message(f"Error analyzing funding rate for {pair}: {e}")
        return {
            'current_rate': 0.0,
            'current_rate_pct': 0.0,
            'sentiment': 'NEUTRAL',
            'strength': 0.0,
            'signal_bias': 'NONE',
            'confidence_adjustment': 0.0,
            'funding_trend': 'UNKNOWN',
            'extreme_funding': False
        }

def get_open_interest(symbol):
    """Get current open interest snapshot for a symbol with short-term change context."""
    try:
        now = time.time()
        if symbol in _OI_SNAPSHOT_CACHE and now - _OI_SNAPSHOT_CACHE[symbol]['ts'] < _OI_SNAPSHOT_TTL:
            return _OI_SNAPSHOT_CACHE[symbol]['data']

        rate_limit()
        current_oi = 0.0
        oi_time = 0

        # Prefer the direct current snapshot endpoint when available.
        try:
            snapshot_fn = getattr(client, 'futures_open_interest', None)
            if snapshot_fn is None:
                raise AttributeError('client.futures_open_interest is not available')
            oi_snapshot = snapshot_fn(symbol=symbol)
            current_oi = float(oi_snapshot.get('openInterest', 0.0))
            oi_time = int(float(oi_snapshot.get('time', now * 1000)))
        except Exception as direct_err:
            log_message(f"Direct open interest lookup failed for {symbol}: {direct_err}; falling back to history endpoint")
            oi_history = client.futures_open_interest_hist(symbol=symbol, period='5m', limit=2)
            if oi_history and len(oi_history) > 0:
                latest = oi_history[-1]
                current_oi = float(latest.get('sumOpenInterest', 0.0))
                oi_time = int(float(latest.get('timestamp', now * 1000)))

        change_data = get_open_interest_change(symbol)
        result = {
            'symbol': symbol,
            'open_interest': current_oi,
            'open_interest_time': oi_time,
            'open_interest_time_iso': pd.to_datetime(oi_time, unit='ms').isoformat() if oi_time else None,
            'oi_change': change_data.get('oi_change', 0.0),
            'oi_current_hist': change_data.get('oi_current', current_oi),
        }

        _OI_SNAPSHOT_CACHE[symbol] = {'data': result, 'ts': now}
        log_message(f"OI snapshot for {symbol}: {current_oi:.0f} contracts, change {result['oi_change']:+.2%}")
        return result

    except BinanceAPIException as e:
        log_message(f"API Error fetching open interest for {symbol}: {e}")
    except Exception as e:
        log_message(f"Error fetching open interest for {symbol}: {e}")

    return {
        'symbol': symbol,
        'open_interest': 0.0,
        'open_interest_time': 0,
        'open_interest_time_iso': None,
        'oi_change': 0.0,
        'oi_current_hist': 0.0,
    }

def get_max_leverage(pair):
    """Return the Binance Futures max leverage for *pair*.
    Uses a 24h in-process cache; falls back to the static tier map for
    API keys that lack futures/leverage-bracket permissions.
    Hard cap is 20x for any pair not in the tier map (small/micro-cap safety).
    """
    try:
        bracket_map = _get_cached_leverage_brackets()
        if bracket_map:
            return bracket_map.get(pair, _STATIC_LEVERAGE_TIERS.get(pair, _DEFAULT_MAX_LEVERAGE))
        return _STATIC_LEVERAGE_TIERS.get(pair, _DEFAULT_MAX_LEVERAGE)
    except Exception as e:
        log_message(f"Error getting max leverage for {pair}: {e}")
        return _STATIC_LEVERAGE_TIERS.get(pair, _DEFAULT_MAX_LEVERAGE)

def set_cross_leverage(pair):
    try:
        max_leverage = get_max_leverage(pair)
        rate_limit()
        
        # Directly check permissions for this specific pair
        try:
            # First check if we can trade this pair at all
            exchange_info = client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == pair), None)
            if not symbol_info or not symbol_info.get('status') == 'TRADING':
                log_message(f"Pair {pair} not available for trading")
                return max_leverage
                
            # Initialize all permission variables first
            can_trade = False
            can_change_margin = False
            can_change_leverage = False
            
            # Then check account permissions
            account_info = client.futures_account()
            can_trade = account_info.get('canTrade', False)
            can_change_margin = account_info.get('canChangeMarginType', False)
            can_change_leverage = account_info.get('canTrade', False)  # Using canTrade as proxy
            
            # Log all permission states
            log_message(f"Permissions for {pair}: Trade={can_trade}, Margin={can_change_margin}, Leverage={can_change_leverage}")
            
            if not can_trade:
                log_message(f"Cannot trade {pair} - skipping")
                log_message(f"API key lacks specific permissions for {pair}: "
                          f"can_change_margin={can_change_margin}, "
                          f"can_change_leverage={can_change_leverage}")
                return max_leverage
        except BinanceAPIException as e:
            log_message(f"Detailed API key verification failed for {pair}: {e}")
            return max_leverage
            
        # Try to set margin type with better error handling
        try:
            client.futures_change_margin_type(symbol=pair, marginType='CROSSED')
        except BinanceAPIException as e:
            if 'No need to change margin type' not in str(e):
                if 'permissions' in str(e).lower():
                    log_message(f"Skipping margin type change for {pair} (permission denied)")
                else:
                    log_message(f"Margin type change failed for {pair}: {e}")
            return max_leverage  # Still return max leverage even if change failed
            
        # Try to set leverage (skip if permission denied)
        try:
            client.futures_change_leverage(symbol=pair, leverage=max_leverage)
            log_message(f"Set cross leverage x{max_leverage} for {pair}")
        except BinanceAPIException as e:
            if 'permissions' in str(e).lower():
                log_message(f"Skipping leverage change for {pair} (permission denied)")
            else:
                log_message(f"Leverage change failed for {pair}: {e}")
                
        return max_leverage
            
    except Exception as e:
        log_message(f"Unexpected error setting leverage for {pair}: {e}")
        return 20  # Fallback to default leverage

# Global variable to track API permissions
API_PERMISSIONS = {
    'can_change_margin': None,
    'can_change_leverage': None,
    'last_checked': 0
}

# PROPOSAL 4: Open Interest Flow Analysis
_OI_CACHE = {}
_OI_CACHE_TTL = 300  # 5 minutes

def get_open_interest_change(symbol):
    """Get Open Interest change to detect crowded positioning or weak rallies."""
    try:
        now = time.time()
        if symbol in _OI_CACHE and now - _OI_CACHE[symbol]['ts'] < _OI_CACHE_TTL:
            return _OI_CACHE[symbol]['data']
        
        oi_data = client.futures_open_interest_hist(symbol=symbol, period='5m', limit=3)
        if oi_data and len(oi_data) >= 2:
            oi_current = float(oi_data[-1]['sumOpenInterest'])
            oi_prev = float(oi_data[-2]['sumOpenInterest'])
            oi_change = (oi_current - oi_prev) / oi_prev if oi_prev > 0 else 0.0
            result = {'oi_change': oi_change, 'oi_current': oi_current}
            _OI_CACHE[symbol] = {'data': result, 'ts': now}
            log_message(f"📈 OI for {symbol}: {oi_change:+.2%} change ({oi_current:.0f})")
            return result
        return {'oi_change': 0.0, 'oi_current': 0.0}
    except Exception:
        return {'oi_change': 0.0, 'oi_current': 0.0}
