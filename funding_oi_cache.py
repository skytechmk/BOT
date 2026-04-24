"""
Persistent cache for Binance funding rate + open interest history.

Why separate from `data_fetcher.py`?
  - ML features need 7-day history for z-scores; existing fetchers keep only the
    latest snapshot and a 5-minute in-memory cache.
  - Retrains need replay-able historical values; SQLite persistence solves that.
  - Batch refresh across 200+ pairs uses the rotating proxy pool so a single
    periodic task completes in ~5–10s instead of per-call sleeps.

Tables
  funding_<PAIR>  (funding_time INTEGER PRIMARY KEY, funding_rate REAL)
  oi_<PAIR>       (ts INTEGER PRIMARY KEY, open_interest REAL, notional REAL)

Public API
  refresh_funding(pairs)       → batch refresh funding rate history
  refresh_oi(pairs)            → batch refresh 5m open interest history
  get_funding_history(pair, hours=168)   → list[(ts_ms, rate)]
  get_oi_history(pair, hours=24)         → list[(ts_ms, oi, notional)]
  funding_features(pair)       → dict with now / z_24h / z_7d / extreme_flag
  oi_features(pair, df_1h)     → dict with change_1h / change_24h / z_24h /
                                 price_oi_divergence_1h

All functions are resilient: they return neutral values on any failure, so
feature_engine never produces NaN/None for the ML pipeline.
"""

from __future__ import annotations

import os
import sqlite3
import time
import threading
import concurrent.futures as _futures
from typing import Iterable

import numpy as np
import pandas as pd

try:
    import requests as _req
except Exception:
    _req = None

from utils_logger import log_message

try:
    from proxy_config import get_proxy_dict as _get_proxy
except Exception:
    def _get_proxy():
        return {}


_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'funding_oi_cache.db')

_FAPI_BASE = 'https://fapi.binance.com'

# Keep ~8 days of funding (funding is every 8h → 24 entries) and
# 48h of OI history (5-min period → 576 entries) — plenty for z-scores.
_FUNDING_LIMIT_PER_CALL = 200     # API max
_OI_LIMIT_PER_CALL      = 500     # API max for openInterestHist
_OI_RETENTION_HOURS     = 72      # prune anything older

_REQUEST_TIMEOUT = 10
_MAX_WORKERS     = 30             # parallel proxied requests

_db_lock = threading.Lock()


# ──────────────────────────────────── DB ────────────────────────────────────

def _conn():
    c = sqlite3.connect(_DB_PATH, timeout=10, check_same_thread=False)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')
    return c


def _ensure_funding_table(conn, pair: str):
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "funding_{pair}" (
            funding_time  INTEGER PRIMARY KEY,
            funding_rate  REAL
        )''')


def _ensure_oi_table(conn, pair: str):
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "oi_{pair}" (
            ts              INTEGER PRIMARY KEY,
            open_interest   REAL,
            notional        REAL
        )''')


# ──────────────────────────── Raw HTTP fetchers ─────────────────────────────

def _fetch_funding_raw(pair: str, limit: int = _FUNDING_LIMIT_PER_CALL):
    """Returns list of dicts: [{fundingTime, fundingRate}, ...]"""
    if _req is None:
        return []
    try:
        url = f'{_FAPI_BASE}/fapi/v1/fundingRate'
        params = {'symbol': pair, 'limit': limit}
        resp = _req.get(url, params=params, proxies=_get_proxy(),
                        timeout=_REQUEST_TIMEOUT)
        # Retry without proxy on geo-block
        if resp.status_code == 451 or 'restricted location' in resp.text.lower():
            resp = _req.get(url, params=params, proxies={}, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        return resp.json() or []
    except Exception:
        return []


def _fetch_oi_raw(pair: str, period: str = '5m', limit: int = _OI_LIMIT_PER_CALL):
    """Returns list of dicts: [{timestamp, sumOpenInterest, sumOpenInterestValue}, ...]"""
    if _req is None:
        return []
    try:
        url = f'{_FAPI_BASE}/futures/data/openInterestHist'
        params = {'symbol': pair, 'period': period, 'limit': limit}
        resp = _req.get(url, params=params, proxies=_get_proxy(),
                        timeout=_REQUEST_TIMEOUT)
        if resp.status_code == 451 or 'restricted location' in resp.text.lower():
            resp = _req.get(url, params=params, proxies={}, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        return resp.json() or []
    except Exception:
        return []


# ───────────────────────────── Batch refresh ────────────────────────────────

def _upsert_funding(pair: str, rows: list):
    if not rows:
        return 0
    with _db_lock:
        conn = _conn()
        try:
            _ensure_funding_table(conn, pair)
            tuples = [(int(r['fundingTime']), float(r['fundingRate'])) for r in rows
                      if 'fundingTime' in r and 'fundingRate' in r]
            conn.executemany(
                f'INSERT OR REPLACE INTO "funding_{pair}" (funding_time, funding_rate) VALUES (?,?)',
                tuples,
            )
            conn.commit()
            return len(tuples)
        finally:
            conn.close()


def _upsert_oi(pair: str, rows: list):
    if not rows:
        return 0
    with _db_lock:
        conn = _conn()
        try:
            _ensure_oi_table(conn, pair)
            tuples = []
            for r in rows:
                try:
                    ts = int(r.get('timestamp') or 0)
                    oi = float(r.get('sumOpenInterest') or 0.0)
                    notional = float(r.get('sumOpenInterestValue') or 0.0)
                    if ts > 0:
                        tuples.append((ts, oi, notional))
                except Exception:
                    continue
            conn.executemany(
                f'INSERT OR REPLACE INTO "oi_{pair}" (ts, open_interest, notional) VALUES (?,?,?)',
                tuples,
            )
            # Prune anything older than retention window
            cutoff_ms = int((time.time() - _OI_RETENTION_HOURS * 3600) * 1000)
            conn.execute(f'DELETE FROM "oi_{pair}" WHERE ts < ?', (cutoff_ms,))
            conn.commit()
            return len(tuples)
        finally:
            conn.close()


def refresh_funding(pairs: Iterable[str], workers: int = _MAX_WORKERS) -> int:
    """Batch fetch funding history for `pairs`. Returns total rows written."""
    pairs = list(pairs)
    if not pairs:
        return 0
    total = 0
    with _futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_pair = {pool.submit(_fetch_funding_raw, p): p for p in pairs}
        for fut in _futures.as_completed(future_to_pair):
            p = future_to_pair[fut]
            try:
                rows = fut.result()
                total += _upsert_funding(p, rows)
            except Exception as e:
                log_message(f"funding refresh failed for {p}: {e}")
    return total


def refresh_oi(pairs: Iterable[str], workers: int = _MAX_WORKERS) -> int:
    """Batch fetch 5m OI history for `pairs`. Returns total rows written."""
    pairs = list(pairs)
    if not pairs:
        return 0
    total = 0
    with _futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_pair = {pool.submit(_fetch_oi_raw, p): p for p in pairs}
        for fut in _futures.as_completed(future_to_pair):
            p = future_to_pair[fut]
            try:
                rows = fut.result()
                total += _upsert_oi(p, rows)
            except Exception as e:
                log_message(f"OI refresh failed for {p}: {e}")
    return total


# ─────────────────────────────── Readers ────────────────────────────────────

def get_funding_history(pair: str, hours: int = 168):
    """Return [(ts_ms, rate), ...] for the last `hours` hours, oldest → newest."""
    cutoff = int((time.time() - hours * 3600) * 1000)
    try:
        conn = _conn()
        try:
            _ensure_funding_table(conn, pair)
            cur = conn.execute(
                f'SELECT funding_time, funding_rate FROM "funding_{pair}" '
                f'WHERE funding_time >= ? ORDER BY funding_time ASC',
                (cutoff,),
            )
            return cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []


def get_oi_history(pair: str, hours: int = 24):
    """Return [(ts_ms, oi, notional), ...] for the last `hours`, oldest → newest."""
    cutoff = int((time.time() - hours * 3600) * 1000)
    try:
        conn = _conn()
        try:
            _ensure_oi_table(conn, pair)
            cur = conn.execute(
                f'SELECT ts, open_interest, notional FROM "oi_{pair}" '
                f'WHERE ts >= ? ORDER BY ts ASC',
                (cutoff,),
            )
            return cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []


# ────────────────────────────── ML features ─────────────────────────────────

_NEUTRAL_FUNDING = {
    'funding_rate_now':    0.0,
    'funding_z_24h':       0.0,
    'funding_z_7d':        0.0,
    'funding_extreme_flag': 0.0,
}

_NEUTRAL_OI = {
    'oi_change_1h':         0.0,
    'oi_change_24h':        0.0,
    'oi_z_24h':             0.0,
    'price_oi_divergence_1h': 0.0,
}


def funding_features(pair: str) -> dict:
    """Derive funding-based ML features. Returns neutral dict on any failure."""
    try:
        hist = get_funding_history(pair, hours=168)
        if len(hist) < 4:
            return dict(_NEUTRAL_FUNDING)
        rates = np.array([r[1] for r in hist], dtype=float)
        now_rate = float(rates[-1])

        # z-scores
        last_3 = rates[-3:] if len(rates) >= 3 else rates  # last ~24h (3 × 8h)
        mu_24 = float(np.mean(last_3))
        sd_24 = float(np.std(last_3, ddof=0)) or 1e-9
        z_24 = (now_rate - mu_24) / sd_24 if sd_24 > 1e-12 else 0.0

        mu_7 = float(np.mean(rates))
        sd_7 = float(np.std(rates, ddof=0)) or 1e-9
        z_7 = (now_rate - mu_7) / sd_7 if sd_7 > 1e-12 else 0.0

        return {
            'funding_rate_now':    now_rate,
            'funding_z_24h':       float(np.clip(z_24, -5.0, 5.0)),
            'funding_z_7d':        float(np.clip(z_7,  -5.0, 5.0)),
            'funding_extreme_flag': 1.0 if abs(z_7) > 2.0 else 0.0,
        }
    except Exception:
        return dict(_NEUTRAL_FUNDING)


def oi_features(pair: str, df_1h: pd.DataFrame | None = None) -> dict:
    """Derive OI-based ML features. Needs df_1h for price divergence; optional."""
    try:
        hist = get_oi_history(pair, hours=48)
        if len(hist) < 15:  # need ~1h of 5-min bars
            return dict(_NEUTRAL_OI)
        oi_arr = np.array([r[1] for r in hist], dtype=float)
        ts_arr = np.array([r[0] for r in hist], dtype=np.int64)
        now_oi = float(oi_arr[-1])

        # change over ~1h (12 × 5-min bars) and ~24h (288)
        def _pct_change(arr, bars):
            if len(arr) <= bars or arr[-bars - 1] == 0:
                return 0.0
            return float((arr[-1] - arr[-bars - 1]) / arr[-bars - 1])

        chg_1h  = _pct_change(oi_arr, 12)
        chg_24h = _pct_change(oi_arr, 288)

        # z-score of recent OI vs last 24h distribution
        win_24 = oi_arr[-288:] if len(oi_arr) >= 288 else oi_arr
        mu = float(np.mean(win_24))
        sd = float(np.std(win_24, ddof=0)) or 1e-9
        z_24 = (now_oi - mu) / sd if sd > 1e-12 else 0.0

        # Price / OI divergence over ~1h
        div = 0.0
        if df_1h is not None and len(df_1h) >= 2:
            try:
                price_chg_1h = float(
                    (df_1h['close'].iloc[-1] - df_1h['close'].iloc[-2])
                    / df_1h['close'].iloc[-2]
                )
                # Divergence: sign mismatch between OI change and price change
                if price_chg_1h * chg_1h < 0 and abs(price_chg_1h) > 1e-4:
                    div = 1.0
            except Exception:
                div = 0.0

        return {
            'oi_change_1h':         float(np.clip(chg_1h,  -0.5, 0.5)),
            'oi_change_24h':        float(np.clip(chg_24h, -1.0, 1.0)),
            'oi_z_24h':             float(np.clip(z_24, -5.0, 5.0)),
            'price_oi_divergence_1h': div,
        }
    except Exception:
        return dict(_NEUTRAL_OI)


# ───────────────────────── Periodic task helper ─────────────────────────────

async def periodic_refresh(fetch_pairs_fn, interval_sec: int = 600):
    """Background coroutine for main.py — refreshes funding + OI every 10 min."""
    import asyncio
    while True:
        try:
            pairs = await asyncio.to_thread(fetch_pairs_fn)
            if pairs:
                t0 = time.time()
                f_rows = await asyncio.to_thread(refresh_funding, pairs)
                o_rows = await asyncio.to_thread(refresh_oi, pairs)
                log_message(
                    f"📊 Funding/OI refresh: {len(pairs)} pairs | "
                    f"funding_rows={f_rows} oi_rows={o_rows} | "
                    f"{time.time() - t0:.1f}s"
                )
        except Exception as e:
            log_message(f"Funding/OI periodic refresh error: {e}")
        await asyncio.sleep(interval_sec)
