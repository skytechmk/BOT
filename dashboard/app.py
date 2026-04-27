"""
Anunnaki World Dashboard — Premium WebSocket-powered real-time monitoring.
3-tier system: Free (24h delayed) / Plus 53 USDT / Pro 109 USDT
Subscribes to Binance futures kline_1h streams for ALL USDT perps.
"""
import sys, os, json, time, asyncio, sqlite3, logging, urllib.request, html
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

import hmac
import hashlib
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse, RedirectResponse, FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn
import numpy as np
import pandas as pd
import websockets

from data_fetcher import fetch_data, client as binance_client
from reverse_hunt import (
    calculate_tsi, calculate_chandelier_exit, calculate_linreg_oscillator,
    detect_tsi_exits, compute_adaptive_levels, get_tsi_zone,
    CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT, CE_LINE_ATR_LEN, CE_LINE_LOOKBACK,
    CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT,
    CE_CLOUD_SRC, CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK,
    CE_CLOUD_MULT, CE_CLOUD_SMOOTH, CE_CLOUD_WAIT,
)
from rust_batch_processor import BATCH_PROCESSOR

# Dashboard modules
from auth import (
    init_user_db, get_current_user, require_tier, require_admin, to_user_info,
    create_user, authenticate_user, create_access_token,
    UserRegister, UserLogin, get_user_count, TIERS,
    is_admin as check_is_admin, get_all_users, admin_set_tier,
    admin_deactivate_user, admin_delete_user, check_subscription_expiry,
    request_password_reset, reset_password_with_token,
    validate_email_format, validate_password_strength,
)
from payments import (
    create_payment, check_payment_status, submit_payment_proof,
    admin_confirm_payment, admin_get_pending_payments,
    get_payment_history, get_plans, get_payment_methods,
    CreatePaymentRequest, ConfirmPaymentRequest, TIER_PRICES,
)
from referrals import (
    get_or_create_code, get_referral_stats, get_admin_referral_stats,
    resolve_code, force_mark_credited,
)
from analytics import (
    get_performance_summary, get_equity_curve, get_pair_performance,
    get_hourly_heatmap, get_daily_pnl, get_signal_breakdown,
    get_indicator_attribution, get_regime_performance,
    get_public_pair_summary,
)
from analytics_live import get_live_kpis, run_backtest
from liquidation_collector import get_collector as _get_liq_collector
_LIQ_COLLECTOR = _get_liq_collector()

from price_broadcaster import PRICE_BROADCASTER

from server_ip import get_cached_server_ip, force_refresh_ip
from copy_trading import (
    init_copy_trading_db, save_api_keys, get_config as get_ct_config,
    toggle_active as ct_toggle, update_settings as ct_update_settings,
    delete_config as ct_delete_config, get_trade_history as ct_history,
    get_trade_stats as ct_stats, get_all_active_traders as ct_admin_traders,
    get_live_balance as ct_live_balance,
    close_all_positions as ct_close_all,
    close_single_position as ct_close_single,
    run_position_monitor as ct_run_monitor,
    mark_tradefi_signed as ct_mark_tradefi_signed,
    save_filters as ct_save_filters,
    retry_missing_sl_tp as ct_retry_sl_tp,
    run_sl_monitor as ct_run_sl_monitor,
    quick_entry_trade as ct_quick_entry,
    get_open_trades_live_pnl as ct_live_pnl,
    backfill_closed_pnl as ct_backfill_pnl,
)

from market_classifier import (
    init_market_db, run_market_refresh_loop,
    get_all_classifications, get_tier_labels, get_sector_labels, get_pair_info,
)

from blog_content import BLOG_POSTS

from device_security import (
    init_device_security_db,
    get_maintenance_info, set_maintenance_mode, is_maintenance_mode,
    verify_email_token, issue_and_send_verification, is_email_verified,
    register_or_touch_device, list_devices, revoke_device,
    admin_set_device_override, admin_grant_extra_slots,
    effective_device_limit, client_ip_from_request, geolocate_ip,
    EXTRA_DEVICE_MONTHLY_PRICE, TIER_DEVICE_LIMIT,
)


# ══════════════════════════════════════════════════════════════════════
#  In-memory store
# ══════════════════════════════════════════════════════════════════════
_store = {
    "all_pairs": [],
    "ohlcv": {},
    "monitored": [],
    "last_scan": 0,
    "bootstrapped": False,
    "bootstrap_progress": 0,
    "ws_connected": 0,
}

_SCAN_INTERVAL = 5
_chart_cache = {}
_CHART_CACHE_TTL = 4
_TF_STALENESS_H  = {"5m": 0.08, "15m": 0.25, "1h": 2.0, "4h": 4.0, "1d": 24.0}
_TF_CACHE_TTL    = {"5m": 8,    "15m": 15,   "1h": 4,   "4h": 60,  "1d": 300}
_TF_MAX_BARS     = {"5m": 500,  "15m": 400,  "1h": 1000, "4h": 600, "1d": 500}
_VALID_TF        = {"5m", "15m", "1h", "4h", "1d"}
_SIGNAL_DELAY_FREE = 86400  # 24 hours delay for free tier

# ── Stream mode (YouTube/OBS public view) ────────────────────────────
# Serves /stream with live zones + macro but embargoes signal details
# for N minutes so the stream can run publicly without leaking alpha.
_STREAM_ENABLED     = os.environ.get('STREAM_ENABLED', '1') == '1'
_STREAM_EMBARGO_SEC = int(os.environ.get('STREAM_EMBARGO_SEC', '1800'))  # 30 min
_STREAM_TOKEN       = os.environ.get('STREAM_TOKEN', '').strip()         # empty = public
_STREAM_SHOW_DIRECTION = os.environ.get('STREAM_SHOW_DIRECTION', '0') == '1'


def _normalize_pair(pair: str) -> str:
    pair = (pair or "").upper().strip()
    if not pair:
        return ""
    return pair if pair.endswith("USDT") else f"{pair}USDT"


def _known_public_pairs() -> set:
    if not _SIGNAL_DB_PATH.exists():
        return set()
    conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
    try:
        pairs = set()
        rows = conn.execute(
            "SELECT DISTINCT pair FROM signals WHERE COALESCE(signal_tier,'production')='production'"
        ).fetchall()
        pairs.update(r[0] for r in rows if r and r[0] and r[0].isascii())
        try:
            archived = conn.execute(
                "SELECT DISTINCT pair FROM archived_signals WHERE COALESCE(signal_tier,'production')='production'"
            ).fetchall()
            pairs.update(r[0] for r in archived if r and r[0] and r[0].isascii())
        except sqlite3.Error:
            pass
        return pairs
    finally:
        conn.close()


def _render_public_pair_rows(rows) -> str:
    if not rows:
        return '<p class="table-empty">No closed production signals have been recorded for this pair yet.</p>'

    out = [
        '<table class="recent-table">',
        '<thead><tr><th>Time</th><th>Direction</th><th>Targets Hit</th><th>PnL</th></tr></thead>',
        '<tbody>',
    ]
    for row in rows:
        pnl = float(row.get("pnl", 0) or 0)
        pnl_class = "pnl-pos" if pnl > 0 else "pnl-neg" if pnl < 0 else "pnl-flat"
        out.append(
            "<tr>"
            f"<td>{html.escape(row.get('time_local', '—'))}</td>"
            f"<td>{html.escape(str(row.get('direction', '—')))}</td>"
            f"<td>{int(row.get('targets_hit', 0) or 0)}</td>"
            f"<td class=\"{pnl_class}\">{pnl:.2f}%</td>"
            "</tr>"
        )
    out.append('</tbody></table>')
    return ''.join(out)

_WS_BASE = "wss://fstream.binance.com/market/stream"
_MAX_STREAMS_PER_CONN = 200


# ══════════════════════════════════════════════════════════════════════
#  Phase 1-4: Bootstrap, WebSocket, Kline handler, Scanner
#  (unchanged from original — just imported logic)
# ══════════════════════════════════════════════════════════════════════
def _fetch_exchange_info_raw() -> dict:
    """
    Fetch Binance Futures exchange info via raw HTTPS with geo-fallback.
    Same pattern as data_fetcher._fetch_klines_raw: try proxy IP first,
    on HTTP 451 / "restricted location" retry via server's direct public IP.
    Public endpoint — no auth required.
    """
    import requests as _req
    try:
        from proxy_config import get_proxy_dict as _get_proxy
        _proxies = _get_proxy()
    except Exception:
        _proxies = {}
    url = 'https://fapi.binance.com/fapi/v1/exchangeInfo'
    resp = _req.get(url, proxies=_proxies, timeout=10)
    # Detect geo-restriction: HTTP 451 or body mentions "restricted location"
    is_geo_blocked = (
        resp.status_code == 451
        or (resp.status_code != 200 and 'restricted location' in (resp.text or '').lower())
    )
    if is_geo_blocked and _proxies:
        # Proxy IP geo-blocked — retry via server's direct public IP
        resp = _req.get(url, proxies={}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _fetch_all_usdt_perps() -> list[str]:
    try:
        from constants import MANUAL_BLACKLIST as _BL
    except ImportError:
        _BL = set()
    try:
        info = _fetch_exchange_info_raw()
        pairs = [
            s['symbol'] for s in info.get('symbols', [])
            if s.get('contractType') == 'PERPETUAL'
            and s['symbol'].endswith('USDT')
            and s.get('status') == 'TRADING'
            and s['symbol'] not in _BL
        ]
        pairs.sort()
        print(f"[dashboard] Loaded {len(pairs)} USDT perpetuals from exchangeInfo")
        return pairs
    except Exception as e:
        print(f"[dashboard] Error fetching exchange info: {e}. Falling back to default list.")
        return ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT', 'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT', 'UNIUSDT', 'POLUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT']

async def _bootstrap():
    pairs = await asyncio.to_thread(_fetch_all_usdt_perps)
    _store["all_pairs"] = pairs
    total = len(pairs)
    # ── Primary path: read from main bot's shared SQLite OHLCV cache ─────
    # The main trading bot (main.py) continuously writes 1h/15m/4h candles
    # to ohlcv_cache.db via data_fetcher._ohlcv_save() on every scan cycle.
    # We share the same DB file, so the dashboard starts instantly with
    # up-to-date history — zero Binance REST calls, zero geo-block risk.
    print(f"[dashboard] Bootstrap: reading {total} pairs from shared SQLite cache...")
    from data_fetcher import _ohlcv_load
    t0 = time.time()
    def _load_all():
        loaded = {}
        for pair in pairs:
            try:
                df = _ohlcv_load(pair, '1h')
                if df is not None and not df.empty and len(df) >= 200:
                    loaded[pair] = df.tail(1000).copy()
            except Exception:
                continue
        return loaded
    cached = await asyncio.to_thread(_load_all)
    for pair, df in cached.items():
        _store["ohlcv"][pair] = df
    _store["bootstrap_progress"] = int(len(cached) / max(total, 1) * 100)
    print(
        f"[dashboard] Shared-cache bootstrap: {len(cached)}/{total} pairs "
        f"loaded in {time.time()-t0:.1f}s"
    )

    # ── Fallback: for pairs not in shared cache (e.g. fresh DB or pair
    # not yet seen by main bot), fetch via REST proxy pool. This only
    # runs for the gap — usually 0 pairs after main bot has been up.
    missing = [p for p in pairs if p not in _store["ohlcv"]]
    if missing:
        print(f"[dashboard] Fallback REST fetch for {len(missing)} missing pairs...")
        from data_fetcher import fetch_data_batch as _fetch_batch
        _CHUNK = 200
        for chunk_start in range(0, len(missing), _CHUNK):
            chunk = missing[chunk_start: chunk_start + _CHUNK]
            try:
                batch = await asyncio.to_thread(_fetch_batch, chunk, '1h', 30)
                for pair, df in batch.items():
                    if len(df) >= 200:
                        _store["ohlcv"][pair] = df.tail(1000).copy()
            except Exception as _be:
                print(f"[dashboard] Fallback chunk {chunk_start} error: {_be}")
        print(f"[dashboard] Fallback complete: {len(_store['ohlcv'])}/{total} pairs total")
    _store["bootstrap_progress"] = 100
    _store["bootstrapped"] = True
    print(f"[dashboard] Bootstrap complete: {len(_store['ohlcv'])}/{total} pairs, 1000 candles each")

async def _ws_listener(pairs_chunk, chunk_id):
    streams = "/".join(f"{p.lower()}@kline_1h" for p in pairs_chunk)
    url = f"{_WS_BASE}?streams={streams}"
    _backoff = 5  # start at 5s, double on each failure, cap at 60s
    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=10,
                max_size=10 * 1024 * 1024, close_timeout=5,
            ) as ws:
                _backoff = 5  # reset backoff on successful connect
                _store["ws_connected"] += 1
                print(f"[ws-{chunk_id}] Connected ({len(pairs_chunk)} streams)")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        data = msg.get("data", {})
                        if data.get("e") == "kline":
                            _handle_kline(data)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            _store["ws_connected"] = max(0, _store["ws_connected"] - 1)
            print(f"[ws-{chunk_id}] Disconnected: {e}, reconnecting in {_backoff}s...")
            await asyncio.sleep(_backoff)
            _backoff = min(_backoff * 2, 60)  # exponential backoff, cap 60s

def _handle_kline(data):
    pair = data["s"]
    k = data["k"]
    df = _store["ohlcv"].get(pair)
    if df is None:
        return
    ts = pd.Timestamp(k["t"], unit="ms", tz="UTC")
    if df.index.tz is None:
        ts = ts.tz_localize(None)
    o, h, l, c, v = float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])
    if ts in df.index:
        df.at[ts, "open"] = o
        df.at[ts, "high"] = h
        df.at[ts, "low"] = l
        df.at[ts, "close"] = c
        df.at[ts, "volume"] = v
    else:
        new_row = pd.DataFrame(
            {"open": [o], "high": [h], "low": [l], "close": [c], "volume": [v]},
            index=pd.DatetimeIndex([ts], name="timestamp"),
        )
        _store["ohlcv"][pair] = pd.concat([df, new_row]).tail(1000)
    # Invalidate all cached chart resolutions for this pair (keys are "PAIR:bars")
    for _k in [k for k in _chart_cache if k.startswith(f"{pair}:")]:
        _chart_cache.pop(_k, None)

async def _indicator_scanner():
    while True:
        if not _store["bootstrapped"]:
            await asyncio.sleep(3)
            continue
        try:
            t0 = time.time()
            monitored = await asyncio.to_thread(_compute_monitored)
            _store["monitored"] = monitored
            _store["last_scan"] = time.time()
            elapsed = time.time() - t0
            print(f"[dashboard] Scan: {len(monitored)}/{len(_store['ohlcv'])} in zones ({elapsed:.1f}s)")
        except Exception as e:
            print(f"[dashboard] Scan error: {e}")
        await asyncio.sleep(_SCAN_INTERVAL)


def _compute_monitored() -> list[dict]:
    try:
        import aladdin_core as _ac
        _rust_avail = True
    except ImportError:
        _rust_avail = False

    monitored = []
    for pair, df in _store["ohlcv"].items():
        try:
            if df is None or df.empty or len(df) < 200:
                continue

            # ── Indicators: Rust path ──────────────────────────────────
            if _rust_avail:
                try:
                    _rh = _ac.batch_reverse_hunt_rust([(
                        df['high'].ffill().tolist(),
                        df['low'].ffill().tolist(),
                        df['close'].ffill().tolist(),
                    )])
                    _tv, _lv, _cll, _cls, _cld, _ccl, _ccs, _ccd = _rh[0]
                    _idx = df.index
                    tsi       = pd.Series(_tv,  index=_idx)
                    linreg    = pd.Series(_lv,  index=_idx)
                    ce_line   = {'long_stop': pd.Series(_cll, index=_idx),
                                 'short_stop': pd.Series(_cls, index=_idx),
                                 'direction':  pd.Series(_cld, index=_idx)}
                    ce_cloud  = {'long_stop': pd.Series(_ccl, index=_idx),
                                 'short_stop': pd.Series(_ccs, index=_idx),
                                 'direction':  pd.Series(_ccd, index=_idx)}
                except Exception:
                    _rust_avail = False  # disable for remainder of loop

            if not _rust_avail:
                tsi     = calculate_tsi(df)
                ce_line = calculate_chandelier_exit(
                    df, src_long=CE_LINE_SRC_LONG, src_short=CE_LINE_SRC_SHORT,
                    atr_len=CE_LINE_ATR_LEN, lookback=CE_LINE_LOOKBACK,
                    mult=CE_LINE_MULT, smooth=CE_LINE_SMOOTH, wait=CE_LINE_WAIT,
                )
                ce_cloud = calculate_chandelier_exit(
                    df, src_long=CE_CLOUD_SRC, src_short=CE_CLOUD_SRC,
                    atr_len=CE_CLOUD_ATR_LEN, lookback=CE_CLOUD_LOOKBACK,
                    mult=CE_CLOUD_MULT, smooth=CE_CLOUD_SMOOTH, wait=CE_CLOUD_WAIT,
                )
                linreg = calculate_linreg_oscillator(df)

            tsi_now = float(tsi.iloc[-1])
            if np.isnan(tsi_now):
                continue
            adapt_l1, adapt_l2 = compute_adaptive_levels(tsi.values)
            zone = get_tsi_zone(tsi_now, l1=adapt_l1, l2=adapt_l2)
            if zone is None:
                continue
            ce_line_dir  = int(ce_line['direction'].iloc[-1])
            ce_cloud_dir = int(ce_cloud['direction'].iloc[-1])
            lr_val = float(linreg.iloc[-1])
            price_now = float(df['close'].iloc[-1])
            if ce_line_dir == 1:
                ce_level = float(ce_line['long_stop'].iloc[-1])
                ce_distance_pct = (price_now - ce_level) / ce_level * 100
            else:
                ce_level = float(ce_line['short_stop'].iloc[-1])
                ce_distance_pct = (ce_level - price_now) / price_now * 100
            tsi_vals = tsi.values
            hooked = False
            if len(tsi_vals) >= 3:
                tsi_2back, tsi_1back, tsi_now_val = tsi_vals[-3], tsi_vals[-2], tsi_vals[-1]
                if tsi_now_val < 0:
                    hooked = tsi_1back < tsi_2back and tsi_now_val > tsi_1back
                elif tsi_now_val > 0:
                    hooked = tsi_1back > tsi_2back and tsi_now_val < tsi_1back
            monitored.append({
                "pair": pair, "zone": zone,
                "tsi": round(tsi_now, 3),
                "adapt_l1": round(adapt_l1, 2), "adapt_l2": round(adapt_l2, 2),
                "ce_line": "LONG" if ce_line_dir == 1 else "SHORT",
                "ce_cloud": "LONG" if ce_cloud_dir == 1 else "SHORT",
                "ce_level": round(ce_level, 6),
                "ce_distance_pct": round(ce_distance_pct, 2),
                "linreg": round(lr_val, 4) if not np.isnan(lr_val) else 0,
                "hooked": bool(hooked),
                "price": round(price_now, 6),
                "change_pct": round(
                    (price_now / float(df['close'].iloc[-25]) - 1) * 100, 2
                ) if len(df) > 25 else 0,
            })
        except Exception:
            continue
    zone_order = {'OS_L2': 0, 'OB_L2': 1, 'OS_L1': 2, 'OB_L1': 3}
    monitored.sort(key=lambda x: zone_order.get(x['zone'], 99))
    return monitored


def _heal_large_gaps(pair: str, df: pd.DataFrame, min_gap_hours: int = 6) -> pd.DataFrame:
    """
    For gaps > min_gap_hours:
      1. Try to fetch the missing range from Binance (real data).
      2. If Binance has no data for that window (pair suspended/illiquid),
         fill with flat synthetic bars at the last close so the chart looks continuous.
    Mutates _store["ohlcv"][pair] in-place when data is fetched.
    """
    if df is None or df.empty:
        return df
    try:
        df = df.sort_index()
        idx = df.index
        healed = False
        new_segments = []
        for i in range(len(idx) - 1):
            gap_hours = (idx[i + 1] - idx[i]).total_seconds() / 3600
            if gap_hours <= min_gap_hours:
                continue
            # ── 1. Try Binance for this specific window ──────────────────────
            gap_start_ms = int((idx[i] + pd.Timedelta(hours=1)).timestamp() * 1000)
            gap_end_ms   = int((idx[i + 1] - pd.Timedelta(hours=1)).timestamp() * 1000)
            fetched = pd.DataFrame()
            try:
                raw = binance_client.futures_klines(
                    symbol=pair, interval='1h',
                    startTime=gap_start_ms, endTime=gap_end_ms, limit=500
                )
                if raw:
                    rows = []
                    for k in raw:
                        ts = pd.Timestamp(int(k[0]), unit='ms', tz='UTC')
                        if df.index.tz is None:
                            ts = ts.tz_localize(None)
                        rows.append({'timestamp': ts,
                                     'open': float(k[1]), 'high': float(k[2]),
                                     'low':  float(k[3]), 'close': float(k[4]),
                                     'volume': float(k[5])})
                    if rows:
                        fetched = pd.DataFrame(rows).set_index('timestamp')
            except Exception:
                pass

            if not fetched.empty:
                new_segments.append(fetched)
                healed = True
            else:
                # ── 2. Binance has nothing → flat synthetic bars ──────────────
                prev = df.iloc[i]
                synth_rows = []
                gap_count = int(gap_hours) - 1
                for h in range(1, gap_count + 1):
                    synth_ts = idx[i] + pd.Timedelta(hours=h)
                    synth_rows.append({
                        'timestamp': synth_ts,
                        'open': prev['close'], 'high': prev['close'],
                        'low':  prev['close'], 'close': prev['close'],
                        'volume': 0.0
                    })
                if synth_rows:
                    synth_df = pd.DataFrame(synth_rows).set_index('timestamp')
                    new_segments.append(synth_df)
                    healed = True

        if healed and new_segments:
            df = pd.concat([df] + new_segments).sort_index()
            df = df[~df.index.duplicated(keep='last')]
            _store["ohlcv"][pair] = df.tail(1000).copy()
            # Invalidate chart cache for this pair
            for k in [k for k in _chart_cache if k.startswith(f"{pair}:")]:
                _chart_cache.pop(k, None)
    except Exception as _e:
        print(f"[gap-heal] {pair}: {_e}")
    return df


def _fill_ohlcv_gaps(df: pd.DataFrame, max_gap_hours: int = 6) -> pd.DataFrame:
    """Fill small missing 1-hour gaps (≤ max_gap_hours) with flat synthetic candles."""
    if df is None or df.empty:
        return df
    try:
        df = df.sort_index()
        # Only fill gaps within the last 1000 bars window to be safe
        idx = df.index
        rows = []
        for i in range(len(idx) - 1):
            rows.append(df.iloc[i])
            gap_hours = int((idx[i + 1] - idx[i]).total_seconds() / 3600)
            if 1 < gap_hours <= max_gap_hours:
                prev = df.iloc[i]
                for h in range(1, gap_hours):
                    synthetic = prev.copy()
                    synthetic.name = idx[i] + pd.Timedelta(hours=h)
                    synthetic['volume'] = 0.0
                    rows.append(synthetic)
        rows.append(df.iloc[-1])
        df = pd.DataFrame(rows).sort_index()
        df = df[~df.index.duplicated(keep='last')]
    except Exception:
        pass
    return df


def _compute_chart_data(pair: str, bars: int = 500, interval: str = "1h") -> dict:
    if interval not in _VALID_TF:
        interval = "1h"

    if interval == "1h":
        # ── 1h: hot path — use in-memory WebSocket-fed store ──────────────
        full_df = _store["ohlcv"].get(pair)
        data_stale = True
        if full_df is not None and not full_df.empty:
            last_ts = full_df.index[-1]
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize('UTC')
            hours_stale = (pd.Timestamp.now(tz='UTC') - last_ts).total_seconds() / 3600
            data_stale = hours_stale > 2
        if full_df is None or full_df.empty or len(full_df) < 50 or data_stale:
            try:
                fresh = fetch_data(pair, '1h')
                if fresh is not None and not fresh.empty and len(fresh) >= 50:
                    _store["ohlcv"][pair] = fresh.tail(1000).copy()
                    full_df = _store["ohlcv"][pair]
                elif full_df is None or full_df.empty:
                    return {}
            except Exception:
                if full_df is None or full_df.empty:
                    return {}
        full_df = _heal_large_gaps(pair, full_df)
        full_df = _fill_ohlcv_gaps(full_df)
    else:
        # ── Non-1h: SQLite OHLCV cache → Binance REST fallback ─────────────
        # Read local DB first (zero-latency, already populated by bot scan cycles)
        from data_fetcher import _ohlcv_load as _local_load
        full_df = _local_load(pair, interval)
        stale_threshold = _TF_STALENESS_H.get(interval, 2.0)
        is_stale = True
        if full_df is not None and not full_df.empty and len(full_df) >= 30:
            last_ts = full_df.index[-1]
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize('UTC')
            hours_stale = (pd.Timestamp.now(tz='UTC') - last_ts).total_seconds() / 3600
            is_stale = hours_stale > stale_threshold
        if full_df is None or full_df.empty or len(full_df) < 30 or is_stale:
            try:
                # fetch_data handles SQLite cache + incremental Binance REST fetch
                # with automatic geo-IP fallback to server's direct IP
                fresh = fetch_data(pair, interval, retries=2, timeout=15)
                if fresh is not None and not fresh.empty and len(fresh) >= 30:
                    full_df = fresh
            except Exception:
                pass
        if full_df is None or full_df.empty or len(full_df) < 30:
            return {}

    bars = min(bars, len(full_df), _TF_MAX_BARS.get(interval, 1000))

    # ── Indicators: Rust path (identical params to signal engine) ──────────
    _rust_ok = False
    try:
        import aladdin_core as _ac
        _rh = _ac.batch_reverse_hunt_rust([(
            full_df['high'].ffill().tolist(),
            full_df['low'].ffill().tolist(),
            full_df['close'].ffill().tolist(),
        )])
        _tsi_v, _lr_v, _ce_ll, _ce_ls, _ce_ld, _ce_cl, _ce_cs, _ce_cd = _rh[0]
        _idx = full_df.index
        tsi_full    = pd.Series(_tsi_v, index=_idx)
        linreg_full = pd.Series(_lr_v,  index=_idx)
        _ld_s = pd.Series(_ce_ld, index=_idx)
        _cd_s = pd.Series(_ce_cd, index=_idx)
        ce_line_full = {
            'long_stop':  pd.Series(_ce_ll, index=_idx),
            'short_stop': pd.Series(_ce_ls, index=_idx),
            'direction':  _ld_s,
            'buy_signal':  (_ld_s == 1)  & (_ld_s.shift(1) == -1),
            'sell_signal': (_ld_s == -1) & (_ld_s.shift(1) == 1),
        }
        ce_cloud_full = {
            'long_stop':  pd.Series(_ce_cl, index=_idx),
            'short_stop': pd.Series(_ce_cs, index=_idx),
            'direction':  _cd_s,
        }
        _rust_ok = True
    except Exception as _rust_err:
        logger.warning(f"[chart] Rust indicator path failed ({_rust_err}), using Python fallback")

    if not _rust_ok:
        tsi_full    = calculate_tsi(full_df)
        linreg_full = calculate_linreg_oscillator(full_df)
        ce_line_full = calculate_chandelier_exit(
            full_df, src_long=CE_LINE_SRC_LONG, src_short=CE_LINE_SRC_SHORT,
            atr_len=CE_LINE_ATR_LEN, lookback=CE_LINE_LOOKBACK,
            mult=CE_LINE_MULT, smooth=CE_LINE_SMOOTH, wait=CE_LINE_WAIT,
        )
        ce_cloud_full = calculate_chandelier_exit(
            full_df, src_long=CE_CLOUD_SRC, src_short=CE_CLOUD_SRC,
            atr_len=CE_CLOUD_ATR_LEN, lookback=CE_CLOUD_LOOKBACK,
            mult=CE_CLOUD_MULT, smooth=CE_CLOUD_SMOOTH, wait=CE_CLOUD_WAIT,
        )

    df = full_df.tail(bars)
    tsi = tsi_full.iloc[-bars:]
    linreg = linreg_full.iloc[-bars:]
    ce_line = {k: v.iloc[-bars:] for k, v in ce_line_full.items()}
    ce_cloud = {k: v.iloc[-bars:] for k, v in ce_cloud_full.items()}
    adapt_l1, adapt_l2 = compute_adaptive_levels(tsi_full.values)
    tsi_exits = detect_tsi_exits(tsi, l1=adapt_l1, l2=adapt_l2)
    timestamps = [t.isoformat() if hasattr(t, 'isoformat') else str(t) for t in df.index]
    return {
        "pair": pair,
        "interval": interval,
        "timestamps": timestamps,
        "open": df['open'].round(6).tolist(),
        "high": df['high'].round(6).tolist(),
        "low": df['low'].round(6).tolist(),
        "close": df['close'].round(6).tolist(),
        "volume": df['volume'].round(2).tolist(),
        "tsi": [round(v, 3) if not np.isnan(v) else 0 for v in tsi.values],
        "linreg": [round(v, 4) if not np.isnan(v) else 0 for v in linreg.values],
        "ce_line_long_stop": [round(v, 6) if not np.isnan(v) else 0 for v in ce_line['long_stop'].values],
        "ce_line_short_stop": [round(v, 6) if not np.isnan(v) else 0 for v in ce_line['short_stop'].values],
        "ce_line_dir": ce_line['direction'].astype(int).tolist(),
        "ce_cloud_long_stop": [round(v, 6) if not np.isnan(v) else 0 for v in ce_cloud['long_stop'].values],
        "ce_cloud_short_stop": [round(v, 6) if not np.isnan(v) else 0 for v in ce_cloud['short_stop'].values],
        "ce_cloud_dir": ce_cloud['direction'].astype(int).tolist(),
        "adapt_l1": round(adapt_l1, 2),
        "adapt_l2": round(adapt_l2, 2),
        "tsi_exit_top_l1": tsi_exits['exit_top_l1'].astype(int).tolist(),
        "tsi_exit_top_l2": tsi_exits['exit_top_l2'].astype(int).tolist(),
        "tsi_exit_bot_l1": tsi_exits['exit_bot_l1'].astype(int).tolist(),
        "tsi_exit_bot_l2": tsi_exits['exit_bot_l2'].astype(int).tolist(),
    }


# ══════════════════════════════════════════════════════════════════════
#  Signal DB reader (tier-aware)
# ══════════════════════════════════════════════════════════════════════
_SIGNAL_DB_PATH = Path(__file__).resolve().parent.parent / "signal_registry.db"
_SERVER_TZ = timezone(timedelta(hours=2))

def _read_signals(limit: int = 50, tier: str = "free") -> list:
    """Read signals. Free tier: 24h delayed, no entry/targets/SL."""
    if not _SIGNAL_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if tier == "free":
            # Free: only signals older than 24h
            cutoff_new = time.time() - _SIGNAL_DELAY_FREE
            cutoff_old = time.time() - 7 * 86400
            cur.execute(
                'SELECT signal_id, pair, signal, price, confidence, targets_json, '
                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json, signal_tier, zone_used, close_reason '
                "FROM signals WHERE timestamp > ? AND timestamp < ? "
                "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
                'ORDER BY timestamp DESC LIMIT ?',
                (cutoff_old, cutoff_new, limit)
            )
        else:
            # Plus/Pro: real-time, last 30 days
            cutoff = time.time() - 30 * 86400
            cur.execute(
                'SELECT signal_id, pair, signal, price, confidence, targets_json, '
                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json, signal_tier, zone_used, close_reason '
                "FROM signals WHERE timestamp > ? "
                "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
                'ORDER BY timestamp DESC LIMIT ?',
                (cutoff, limit)
            )

        signals = []
        for row in cur.fetchall():
            ts_utc = datetime.fromtimestamp(row['timestamp'], tz=timezone.utc)
            ts_local = ts_utc.astimezone(_SERVER_TZ)
            targets = []
            if row['targets_json']:
                try:
                    targets = json.loads(row['targets_json'])
                except (json.JSONDecodeError, TypeError):
                    pass

            # targets_hit: legacy rows = INTEGER, migrated rows = JSON list string
            _th_raw = row['targets_hit']
            if isinstance(_th_raw, int):
                _targets_hit_count = _th_raw
            elif isinstance(_th_raw, str):
                try:
                    _v = json.loads(_th_raw)
                    _targets_hit_count = len(_v) if isinstance(_v, list) else int(_v)
                except Exception:
                    _targets_hit_count = 0
            else:
                _targets_hit_count = 0

            signal = {
                'signal_id': row['signal_id'][:8] if tier == 'free' else row['signal_id'],
                'pair': row['pair'],
                'direction': row['signal'],
                'status': row['status'] or 'SENT',
                'pnl': round(row['pnl'], 2) if row['pnl'] else 0,
                'targets_hit': _targets_hit_count,
                'time_utc': ts_utc.isoformat(),
                'time_local': ts_local.strftime('%d %b %H:%M'),
                'timestamp': row['timestamp'],
                'signal_tier': row['signal_tier'] or 'production',
                'zone_used': row['zone_used'],
                'close_reason': row['close_reason'],
            }

            # Parse features for drift alert (available to all tiers — it's a safety flag)
            _feat = {}
            try:
                if row['features_json']:
                    _feat = json.loads(row['features_json'])
            except Exception:
                pass
            _drift_alert = bool(_feat.get('entry_drift_alert', False))
            _drift_pct   = float(_feat.get('entry_drift_pct', 0.0))
            signal['entry_drift_alert'] = _drift_alert
            signal['entry_drift_pct']   = round(_drift_pct, 2)

            # Plus/Pro: include full trade data
            if TIERS.get(tier, 0) >= TIERS['pro']:
                signal.update({
                    'price': row['price'],
                    'confidence': round(row['confidence'] * 100, 1) if row['confidence'] else 0,
                    'targets': targets,
                    'stop_loss': row['stop_loss'],
                    'leverage': row['leverage'],
                })
            else:
                # Free: hide entry/targets/SL
                signal.update({
                    'price': None,
                    'confidence': None,
                    'targets': [],
                    'stop_loss': None,
                    'leverage': None,
                })

            signals.append(signal)

        conn.close()
        return signals
    except Exception as e:
        print(f"[dashboard] DB read error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════
#  FastAPI App
# ══════════════════════════════════════════════════════════════════════
_bg_tasks = []

async def _subscription_checker():
    """Background task: check subscription expiry every hour."""
    await asyncio.sleep(30)  # Wait for startup
    while True:
        try:
            actions = await asyncio.to_thread(check_subscription_expiry)
            if actions['reminders_sent'] or actions['deactivated']:
                print(f"[dashboard] Subscription check: {len(actions['reminders_sent'])} reminders, {len(actions['deactivated'])} deactivated")
        except Exception as e:
            print(f"[dashboard] Subscription check error: {e}")
        await asyncio.sleep(3600)  # Check every hour

@asynccontextmanager
async def lifespan(app):
    # ── Startup ──
    init_user_db()
    init_copy_trading_db()
    init_market_db()
    init_device_security_db()
    
    async def _init_background():
        await _bootstrap()
        pairs = _store["all_pairs"]
        for i in range(0, len(pairs), _MAX_STREAMS_PER_CONN):
            chunk = pairs[i:i + _MAX_STREAMS_PER_CONN]
            chunk_id = i // _MAX_STREAMS_PER_CONN + 1
            _bg_tasks.append(asyncio.create_task(_ws_listener(chunk, chunk_id)))
        _bg_tasks.append(asyncio.create_task(_indicator_scanner()))
        _store["monitored"] = await asyncio.to_thread(_compute_monitored)
        _store["last_scan"] = time.time()
        print(f"[dashboard] Initial scan: {len(_store['monitored'])} pairs in zones")

    _bg_tasks.append(asyncio.create_task(_init_background()))
    _bg_tasks.append(asyncio.create_task(_subscription_checker()))
    _bg_tasks.append(asyncio.create_task(_LIQ_COLLECTOR.run()))
    _bg_tasks.append(asyncio.create_task(PRICE_BROADCASTER.run()))
    _bg_tasks.append(asyncio.create_task(ct_run_monitor()))
    _bg_tasks.append(asyncio.create_task(ct_run_sl_monitor()))
    _bg_tasks.append(asyncio.create_task(run_market_refresh_loop()))

    # ── Capture main event loop for sync→async bridge ───────────────
    # copy_trading._execute_single_trade_blocking runs in a thread pool
    # but needs to call async WS-API methods. It submits coroutines back
    # to this loop via run_coroutine_threadsafe.
    try:
        import copy_trading as _ct_mod
        _ct_mod.set_main_loop(asyncio.get_running_loop())
    except Exception as _loop_e:
        print(f"[dashboard] main-loop capture failed: {_loop_e}")

    # ── Binance User Data Streams (push-based balance/position) ──────
    # One persistent WebSocket per active copy-trading user. Replaces
    # REST polling of futures_account / futures_account_balance, which
    # was the #1 cause of -1003 IP bans on 2026-04-23.
    try:
        import binance_user_stream as _uds
        async def _boot_user_streams():
            # Give the DB a moment to be ready, then spawn per-user tasks.
            await asyncio.sleep(2)
            n = await _uds.start_all_active()
            print(f"[dashboard] Binance user-streams: {n} tasks started")
        _bg_tasks.append(asyncio.create_task(_boot_user_streams()))
    except Exception as _uds_e:
        print(f"[dashboard] user-stream init failed (non-fatal): {_uds_e}")

    yield

    # ── Shutdown: close all user-streams before cancelling bg tasks ──
    try:
        import binance_user_stream as _uds
        await _uds.stop_all()
    except Exception:
        pass

    for t in _bg_tasks:
        t.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)
    print("[dashboard] Shut down cleanly")


_limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Anunnaki World Dashboard", lifespan=lifespan)
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=500)

# ═══ S5 · CORS — env-gated origins ══════════════════════════════════════
# Localhost origins are a gratuitous attack surface in production. Only
# admit them when ENVIRONMENT != "production" (dev laptop & staging).
_ENV = os.getenv("ENVIRONMENT", "development").lower()
_PROD_ORIGINS = ["https://anunnakiworld.com", "https://www.anunnakiworld.com"]
_DEV_EXTRA    = ["http://localhost:8050", "http://127.0.0.1:8050"]
_CORS_ORIGINS = _PROD_ORIGINS if _ENV == "production" else (_PROD_ORIGINS + _DEV_EXTRA)

app.add_middleware(CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    allow_credentials=True,
)

_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_MOBILE_ASSETS_DIR = Path(__file__).parent.parent / "mobile" / "dist" / "assets"
if _MOBILE_ASSETS_DIR.exists():
    app.mount("/mobile/assets", StaticFiles(directory=str(_MOBILE_ASSETS_DIR)), name="mobile-assets")

# ── No-cache middleware for JS/CSS — prevents Cloudflare caching stale assets ──
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _Req
from starlette.responses import Response as _Resp

class NoCacheJSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _Req, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith('.js') or path.endswith('.css'):
            response.headers['Cache-Control'] = 'no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
        return response

app.add_middleware(NoCacheJSMiddleware)


# ═══ S4 · SecurityHeadersMiddleware — institutional-grade HTTP hardening
# ═══════════════════════════════════════════════════════════════════════
# Every response carries the modern browser-security header set. Starts
# with CSP in Report-Only so we can observe violations for 48h before
# flipping to enforcing (flip by renaming the header key to
# "Content-Security-Policy"). All other headers are enforcing from day 1.
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _Req, call_next):
        r = await call_next(request)
        # Prevent clickjacking — no framing of our pages, anywhere.
        r.headers["X-Frame-Options"] = "DENY"
        # Stop MIME-sniff attacks on user-uploaded / user-facing assets.
        r.headers["X-Content-Type-Options"] = "nosniff"
        # HSTS — one year, include subdomains, preload-ready. Only meaningful
        # when served over HTTPS (Cloudflare/edge), harmless over plain HTTP.
        r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # Strip Referer cross-origin so we don't leak path params to
        # third-party tools (e.g. chart vendors loaded in iframes).
        r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Deny browser APIs we never use. Reduces side-channel attack surface.
        r.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        # CSP — Report-Only mode for the first 48 h. Tuned to our actual
        # asset sources (TradingView, Google Fonts, inline styles, WSS).
        # Flip to enforcing by replacing the header name below.
        #
        # Allowed external origins (learned from first 48 h of report-only):
        #   s3.tradingview.com          — TradingView widget loader
        #   www.google-analytics.com    — GA beacons
        #   unpkg.com                   — lightweight-charts library (screener/heatmap)
        #   static.cloudflareinsights.com — Cloudflare web-analytics beacon
        #   *.tradingview-widget.com    — TV widget iframes (frame-src only)
        #
        # We also set script-src-elem and frame-src EXPLICITLY so the
        # browser never has to fall back to default-src (which logs
        # spurious violations for widget iframes).
        r.headers["Content-Security-Policy-Report-Only"] = (
            "default-src 'self'; "
            "script-src  'self' 'unsafe-inline' 'unsafe-eval' "
            "            https://s3.tradingview.com https://www.google-analytics.com "
            "            https://unpkg.com https://static.cloudflareinsights.com; "
            "script-src-elem 'self' 'unsafe-inline' "
            "            https://s3.tradingview.com https://www.google-analytics.com "
            "            https://unpkg.com https://static.cloudflareinsights.com; "
            "style-src   'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src    'self' data: https://fonts.gstatic.com; "
            "img-src     'self' data: blob: https:; "
            "connect-src 'self' wss: https:; "
            "frame-src   'self' https://*.tradingview.com https://*.tradingview-widget.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "object-src 'none';"
        )
        return r

app.add_middleware(SecurityHeadersMiddleware)


# ── Public / Frontend Routes ───────────────────────────────────────────

@app.get("/.well-known/security.txt", response_class=PlainTextResponse)
async def security_txt():
    """RFC 9116 responsible-disclosure contact. Scanned by every security
    auditor / bug-bounty aggregator. Contents in static/.well-known/."""
    p = _STATIC_DIR / ".well-known" / "security.txt"
    if p.exists():
        return PlainTextResponse(p.read_text())
    return PlainTextResponse("Contact: mailto:security@anunnakiworld.com\n")


@app.get("/signals/{pair}", response_class=HTMLResponse)
async def seo_pair_page(pair: str):
    """Programmatic SEO page showing historical signal data for any monitored pair.

    Shows aggregate stats and closed-signal history only — never exposes
    live premium entry, TP, or stop-loss data.  Returns a graceful page
    even for pairs that have no signal history yet (0 signals rendered).
    Only truly invalid pair strings get a 404.
    """
    pair = _normalize_pair(pair)
    if not pair or len(pair) < 5 or len(pair) > 30:
        raise HTTPException(status_code=404, detail="Unknown pair")

    html_path = Path(__file__).parent / "signal_seo.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Pair page not found</h1>", status_code=404)

    try:
        summary = await asyncio.to_thread(get_public_pair_summary, pair, 8)
    except Exception:
        summary = {"exists": False, "pair": pair}

    try:
        pair_meta = get_pair_info(pair)
    except Exception:
        pair_meta = {}

    last_signal = summary.get("last_signal") or {}
    recent_rows_html = _render_public_pair_rows(summary.get("recent_closed") or [])

    template = html_path.read_text()
    page_html = (
        template
        .replace("__PAIR__", html.escape(pair))
        .replace("__WIN_RATE__", f"{float(summary.get('win_rate', 0) or 0):.1f}")
        .replace("__TOTAL_SIGNALS__", str(int(summary.get("total_signals", 0) or 0)))
        .replace("__CLOSED_SIGNALS__", str(int(summary.get("closed_signals", 0) or 0)))
        .replace("__AVG_PNL__", f"{float(summary.get('avg_pnl', 0) or 0):.2f}")
        .replace("__BEST_TRADE__", "—" if summary.get("best_trade") is None else f"{float(summary['best_trade']):.2f}%")
        .replace("__WORST_TRADE__", "—" if summary.get("worst_trade") is None else f"{float(summary['worst_trade']):.2f}%")
        .replace("__SECTOR__", html.escape(str(pair_meta.get("sector", "other"))))
        .replace("__TIER__", html.escape(str(pair_meta.get("tier", "high_risk"))))
        .replace("__RANK__", "—" if pair_meta.get("rank") is None else str(pair_meta.get("rank")))
        .replace("__HOT_STATUS__", "HOT" if pair_meta.get("is_hot") else "Stable")
        .replace("__LAST_SIGNAL_DIRECTION__", html.escape(str(last_signal.get("direction", "—"))))
        .replace("__LAST_SIGNAL_STATUS__", html.escape(str(last_signal.get("status", "—"))))
        .replace("__LAST_SIGNAL_CONFIDENCE__", f"{float(last_signal.get('confidence', 0) or 0):.1f}")
        .replace("__RECENT_SIGNALS_TABLE__", recent_rows_html)
    )
    return HTMLResponse(content=page_html, status_code=200, headers={"Cache-Control": "public, max-age=300"})


@app.get("/affiliate", response_class=HTMLResponse)
async def affiliate_page():
    html_path = Path(__file__).parent / "affiliate.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Affiliate page coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    html_path = Path(__file__).parent / "tos.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Terms of Service coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    html_path = Path(__file__).parent / "privacy.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Privacy Policy coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/faq", response_class=HTMLResponse)
async def faq_page():
    html_path = Path(__file__).parent / "faq.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>FAQ coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/blog", response_class=HTMLResponse)
async def blog_index_page():
    html_path = Path(__file__).parent / "blog_index.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Blog coming soon</h1>", status_code=200)

    cards = []
    for slug, post in BLOG_POSTS.items():
        cards.append(
            '<article class="post-card">'
            f'<div class="post-date">{html.escape(post.get("published", ""))}</div>'
            f'<h2><a href="/blog/{slug}">{html.escape(post["title"])}</a></h2>'
            f'<p>{html.escape(post["description"])}</p>'
            f'<a class="post-link" href="/blog/{slug}">Read article →</a>'
            '</article>'
        )

    template = html_path.read_text()
    return HTMLResponse(content=template.replace("__BLOG_CARDS__", "\n".join(cards)), status_code=200)


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post_page(slug: str):
    post = BLOG_POSTS.get(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Article not found")

    html_path = Path(__file__).parent / "blog_post.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Article template missing</h1>", status_code=500)

    template = html_path.read_text()
    page_html = (
        template
        .replace("__TITLE__", html.escape(post["title"]))
        .replace("__DESCRIPTION__", html.escape(post["description"]))
        .replace("__PUBLISHED__", html.escape(post.get("published", "")))
        .replace("__UPDATED__", html.escape(post.get("updated", post.get("published", ""))))
        .replace("__SLUG__", html.escape(slug))
        .replace("__BODY__", post["body_html"])
    )
    return HTMLResponse(content=page_html, status_code=200)

@app.get("/favicon.ico")
async def favicon():
    ico_path = Path(__file__).parent / "static" / "logo.jpeg"
    return FileResponse(ico_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "Sitemap: https://anunnakiworld.com/sitemap.xml\n",
        media_type="text/plain"
    )

@app.get("/sitemap.xml")
async def sitemap_xml():
    """Dynamic sitemap for public landing, content hubs, articles, and pair pages."""
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    base_url = "https://anunnakiworld.com"
    static_routes = ["/", "/whitepaper", "/whitepaper/mk", "/affiliate", "/faq", "/blog", "/terms", "/privacy"]

    for route in static_routes:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}{route}</loc>')
        if route == "/":
            xml.append('    <priority>1.0</priority>')
            xml.append('    <changefreq>daily</changefreq>')
        else:
            xml.append('    <priority>0.8</priority>')
            xml.append('    <changefreq>weekly</changefreq>')
        xml.append('  </url>')

    for slug, post in BLOG_POSTS.items():
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}/blog/{slug}</loc>')
        lastmod = post.get("updated") or post.get("published")
        if lastmod:
            xml.append(f'    <lastmod>{lastmod}</lastmod>')
        xml.append('    <priority>0.6</priority>')
        xml.append('    <changefreq>monthly</changefreq>')
        xml.append('  </url>')

    try:
        for pair in sorted(_known_public_pairs()):
            xml.append('  <url>')
            xml.append(f'    <loc>{base_url}/signals/{pair}</loc>')
            xml.append('    <priority>0.7</priority>')
            xml.append('    <changefreq>weekly</changefreq>')
            xml.append('  </url>')
    except Exception as e:
        logger.warning(f"[sitemap] Failed to build pair URLs: {e}")

    xml.append('</urlset>')
    return Response(content='\n'.join(xml), media_type="application/xml")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Root route serves the public marketing landing page.
    The landing page's own JS validates any stored JWT against
    /api/auth/me and redirects authenticated users to /app.
    First-time visitors, logged-out users, and holders of stale
    tokens (e.g. after a JWT-secret rotation) see the landing page."""
    html_path = Path(__file__).parent / "landing.html"
    if not html_path.exists():
        # Fallback to SPA if landing is missing so we never 404 the root.
        html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

@app.get("/landing", response_class=HTMLResponse)
async def landing():
    """Explicit landing-page route (same content as /). Kept so external
    links and ?stay=1 bookmarks continue to resolve even if we ever
    change what `/` serves."""
    html_path = Path(__file__).parent / "landing.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Landing page coming soon</h1>", status_code=200)
    
    html = html_path.read_text()
    if "<head>" in html:
        html = html.replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow">')
    return HTMLResponse(content=html, status_code=200)

@app.get("/app", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def app_shell():
    """Dashboard SPA shell. The landing page's CTAs point here;
    /app?signup=1 opens the register modal, /app?plan=pro_monthly starts
    the upgrade flow. The JS logic parses the fragment/query vars."""
    html_path = Path(__file__).parent / "index.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Dashboard missing</h1>", status_code=500)
    
    html = html_path.read_text()
    if "<head>" in html:
        html = html.replace("<head>", '<head>\n    <meta name="robots" content="noindex,nofollow">')
    return HTMLResponse(content=html, status_code=200)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Serve the admin panel shell ONLY to authenticated admins.

    Non-admins, unauthenticated visitors, and holders of stale tokens get
    a 404 — indistinguishable from a non-existent route (security through
    silence; we refuse to even confirm the panel exists to unauthorised
    requesters). This closes the attack-surface leak where attackers could
    previously fingerprint the admin tab layout + discover admin.js paths
    without any credentials.

    The route accepts the JWT via `Authorization: Bearer …` header,
    `?t=<token>` query param (for direct /admin?t=… bookmarks), or the
    `aladdin_token` cookie (for seamless SPA navigation).
    """
    from auth import SECRET_KEY, ALGORITHM, get_user_by_id, is_admin as _is_admin
    from jose import jwt as _jwt

    token = (
        request.headers.get("authorization", "").replace("Bearer ", "").strip()
        or request.query_params.get("t", "").strip()
        or request.cookies.get("aladdin_token", "").strip()
    )
    try:
        if not token:
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
        payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = get_user_by_id(int(payload.get("sub", 0)))
        if not user or not _is_admin(user):
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
    except Exception:
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)

    html_path = Path(__file__).parent / "admin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

@app.get("/whitepaper", response_class=HTMLResponse)
async def whitepaper():
    wp_path = Path(__file__).parent / "static" / "whitepaper.html"
    if not wp_path.exists():
        return HTMLResponse(content="<h1>Whitepaper coming soon</h1>", status_code=200)
    return HTMLResponse(content=wp_path.read_text(), status_code=200)

@app.get("/whitepaper/mk", response_class=HTMLResponse)
async def whitepaper_mk():
    wp_path = Path(__file__).parent / "static" / "whitepaper-mk.html"
    if not wp_path.exists():
        return HTMLResponse(content="<h1>Бела книга наскоро</h1>", status_code=200)
    return HTMLResponse(content=wp_path.read_text(), status_code=200)


# ── Auth Routes ──────────────────────────────────────────────────────

def _extract_device_info(request: Request):
    """Pull fingerprint/label/UA/IP from headers + body for register/login."""
    fp = request.headers.get("X-Device-Fingerprint", "") or ""
    label = request.headers.get("X-Device-Label", "") or ""
    ua = request.headers.get("user-agent", "") or ""
    ip = client_ip_from_request(request)
    return fp, label, ua, ip


@app.post("/api/auth/register")
@_limiter.limit("10/hour")
async def api_register(request: Request, body: UserRegister):
    email_err = validate_email_format(body.email)
    if email_err:
        return JSONResponse({"error": email_err}, status_code=400)
    pw_err = validate_password_strength(body.password)
    if pw_err:
        return JSONResponse({"error": pw_err}, status_code=400)
    ref_code = request.query_params.get('ref', '') or ''
    user = create_user(body.email, body.password, body.username, ref_code=ref_code)
    # Register the registering browser as the first device (pre-authorized)
    fp, label, ua, ip = _extract_device_info(request)
    if fp:
        await asyncio.to_thread(register_or_touch_device, user, fp, ip, ua, label)
    token = create_access_token(user)
    return JSONResponse(content={
        "access_token": token,
        "token_type": "bearer",
        "user": to_user_info(user),
    })

@app.post("/api/auth/login")
@_limiter.limit("20/hour;5/minute")
async def api_login(request: Request, body: UserLogin):
    user = authenticate_user(body.email, body.password, body.username)
    if not user:
        return JSONResponse(content={"error": "Invalid credentials"}, status_code=401)
    # Device enforcement — admin bypasses via effective_device_limit
    fp, label, ua, ip = _extract_device_info(request)
    if fp:
        result = await asyncio.to_thread(register_or_touch_device, user, fp, ip, ua, label)
        if result.get("blocked"):
            return JSONResponse(
                content={
                    "error": "device_limit",
                    "detail": result.get("reason", "Device limit reached"),
                    "limit": result.get("limit"),
                    "current_count": result.get("current_count"),
                },
                status_code=403
            )
    token = create_access_token(user)
    return JSONResponse(content={
        "access_token": token,
        "token_type": "bearer",
        "user": to_user_info(user),
    })

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page():
    html_path = Path(__file__).parent / "reset_password.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

@app.post("/api/auth/forgot-password")
@_limiter.limit("5/hour")
async def api_forgot_password(request: Request):
    body = await request.json()
    email = body.get("email", "").strip()
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    result = await asyncio.to_thread(request_password_reset, email)
    return JSONResponse(result)

@app.post("/api/auth/reset-password")
@_limiter.limit("10/hour")
async def api_reset_password(request: Request):
    body = await request.json()
    token = body.get("token", "").strip()
    new_password = body.get("password", "")
    if not token or not new_password:
        return JSONResponse({"error": "Token and password required"}, status_code=400)
    result = await asyncio.to_thread(reset_password_with_token, token, new_password)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)

@app.get("/api/auth/me")
async def api_me(user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse(content={"error": "Not authenticated"}, status_code=401)
    return JSONResponse(content={"user": to_user_info(user)})


# ── Public site meta (used by UI on every page load) ─────────────────
@app.get("/api/public/sessions")
async def api_public_sessions():
    """Live trading session state — no auth required."""
    try:
        import sys, os
        _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _proj not in sys.path:
            sys.path.insert(0, _proj)
        from trading_sessions import get_session_state
        return JSONResponse(get_session_state())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/public/site")
async def api_public_site(request: Request):
    """Serves maintenance flag + IP geo hint + session state for auto theme."""
    ip = client_ip_from_request(request)
    geo = await asyncio.to_thread(geolocate_ip, ip)
    try:
        import sys, os
        _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _proj not in sys.path:
            sys.path.insert(0, _proj)
        from trading_sessions import get_session_state as _gss
        _sessions = _gss()
    except Exception:
        _sessions = {}
    return JSONResponse({
        "maintenance": get_maintenance_info(),
        "sessions": _sessions,
        "client": {
            "ip": ip,
            "city": geo.get("city", ""),
            "country": geo.get("country", ""),
            "country_code": geo.get("country_code", ""),
            "timezone": geo.get("timezone", ""),
        },
        "device_pricing": {
            # Canonical tier names after Phase-2 rename.
            "plus_monthly":  EXTRA_DEVICE_MONTHLY_PRICE.get("plus",  16),
            "pro_monthly":   EXTRA_DEVICE_MONTHLY_PRICE.get("pro",   33),
            "ultra_monthly": EXTRA_DEVICE_MONTHLY_PRICE.get("ultra", 60),
            "base_limits":   TIER_DEVICE_LIMIT,
        },
    })


# ── Email verification ───────────────────────────────────────────────
@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(request: Request):
    token = request.query_params.get("token", "").strip()
    if not token:
        return HTMLResponse("<h1>Missing token</h1>", status_code=400)
    result = await asyncio.to_thread(verify_email_token, token)
    ok = not result.get("error")
    body_color = "#00c853" if ok else "#ff6b85"
    title = "Email verified ✓" if ok else "Verification failed"
    msg = "Your email is confirmed. You can close this tab and return to the dashboard." if ok else result.get("error", "Invalid link")
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>
        <style>body{{font-family:Inter,sans-serif;background:#0d0d0f;color:#e8e8e8;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
        .card{{background:#1a1a1f;border:1px solid #2a2a30;border-radius:14px;padding:36px 44px;max-width:440px;text-align:center}}
        h1{{color:{body_color};margin:0 0 10px}} a{{color:#f4a236;text-decoration:none;font-weight:700}}</style></head>
        <body><div class='card'><h1>{title}</h1><p style='color:#aaa'>{msg}</p>
        <p><a href='/'>← Back to dashboard</a></p></div></body></html>""",
        status_code=200 if ok else 400
    )


@app.post("/api/auth/resend-verification")
@_limiter.limit("5/hour")
async def api_resend_verification(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if user.get("email_verified"):
        return JSONResponse({"ok": True, "already_verified": True})
    ok = await asyncio.to_thread(issue_and_send_verification, user)
    return JSONResponse({"ok": ok, "email": user["email"]})


# ── Device management (user) ────────────────────────────────────────
@app.get("/api/devices")
async def api_devices_list(user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    devices = await asyncio.to_thread(list_devices, user["id"])
    limit_info = await asyncio.to_thread(effective_device_limit, user)
    return JSONResponse({
        "devices": devices,
        "limit_info": limit_info,
        "extra_pricing": EXTRA_DEVICE_MONTHLY_PRICE,
    })


@app.delete("/api/devices/{device_id}")
async def api_devices_revoke(device_id: int, user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    result = await asyncio.to_thread(revoke_device, user["id"], device_id, False)
    return JSONResponse(result)


# ── Payment Routes ───────────────────────────────────────────────────

@app.get("/api/plans")
async def api_plans():
    return JSONResponse(content={"plans": get_plans(), "methods": get_payment_methods()})

@app.post("/api/payment/create")
async def api_create_payment(body: CreatePaymentRequest, user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse(content={"error": "Login required"}, status_code=401)
    result = create_payment(user['id'], body.plan_id, body.pay_method)
    return JSONResponse(content=result)


from pydantic import BaseModel as _BaseModel

class CreateInvoiceRequest(_BaseModel):
    plan_id: str


@app.post("/api/payment/invoice/create")
async def api_create_invoice(body: CreateInvoiceRequest, user: dict = Depends(get_current_user)):
    """
    Create a NOWPayments hosted-checkout invoice. Client should redirect the user
    to the returned `invoice_url` (user picks any of 300+ cryptos on the NOWPayments
    page, pays, and is auto-redirected back to our /payment/success route).
    """
    if not user:
        return JSONResponse(content={"error": "Login required"}, status_code=401)
    from payments import create_invoice
    try:
        result = create_invoice(user['id'], body.plan_id)
        return JSONResponse(content=result)
    except HTTPException as e:
        return JSONResponse(content={"error": e.detail}, status_code=e.status_code)


@app.get("/api/payments/config")
async def api_payments_public_config():
    """
    Public (no-auth) — tells the frontend whether crypto-checkout is available,
    so the 'Pay with Crypto (300+ coins)' button can be shown or hidden.
    Does NOT leak API keys or secrets.
    """
    import nowpayments as np_client
    return JSONResponse(content={
        "crypto_checkout_enabled": np_client.is_configured(),
        "sandbox": np_client.describe_config()["sandbox"],
    })

@app.post("/api/payment/confirm")
async def api_confirm_payment(body: ConfirmPaymentRequest, user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse(content={"error": "Login required"}, status_code=401)
    result = submit_payment_proof(user['id'], body.payment_id, body.tx_hash)
    return JSONResponse(content=result)

@app.post("/api/webhooks/nowpayments")
async def nowpayments_ipn_webhook(request: Request):
    """
    NOWPayments IPN webhook — fires on every payment status transition.
    Signature is verified via HMAC-SHA512 (constant-time comparison).
    All 9 statuses handled; tier is upgraded only on `finished`.
    """
    import nowpayments as np_client
    from payments import update_payment_status

    sig_header = request.headers.get("x-nowpayments-sig", "")
    raw_body   = await request.body()

    if not np_client.verify_ipn_signature(raw_body, sig_header):
        logger.warning(f"IPN rejected: invalid signature (header len={len(sig_header)})")
        return JSONResponse({"status": "ignored", "reason": "Invalid signature"}, status_code=403)

    try:
        payload = json.loads(raw_body)
    except Exception:
        return JSONResponse({"status": "ignored", "reason": "Invalid JSON"}, status_code=400)

    status   = payload.get("payment_status", "")
    order_id = payload.get("order_id", "")
    tx_hash  = payload.get("outcome_currency", "")  # not the actual tx hash but what NP provides

    if not order_id or not status:
        return JSONResponse({"status": "ignored", "reason": "Missing order_id or status"}, status_code=400)

    try:
        result = update_payment_status(order_id, status, tx_hash=tx_hash)
        logger.info(f"IPN processed: order={order_id} status={status} result={result}")
        return JSONResponse({"status": "ok", **result})
    except Exception as e:
        logger.exception(f"IPN processing failed for order={order_id}: {e}")
        return JSONResponse({"status": "error", "detail": str(e)[:200]}, status_code=500)


@app.get("/api/payment/status/{payment_id}")
async def api_payment_status(payment_id: str, user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse(content={"error": "Login required"}, status_code=401)
    return JSONResponse(content=check_payment_status(payment_id))

@app.get("/api/payment/history")
async def api_payment_history(user: dict = Depends(get_current_user)):
    if not user:
        return JSONResponse(content={"error": "Login required"}, status_code=401)
    return JSONResponse(content={"payments": get_payment_history(user['id'])})

# ── Admin Routes (for payment verification) ──────────────────────────

@app.get("/api/admin/payments/pending")
async def api_admin_pending(user: dict = Depends(require_admin)):
    """Admin: list pending payments."""
    return JSONResponse(content={"payments": admin_get_pending_payments()})

@app.post("/api/admin/payments/activate/{payment_id}")
async def api_admin_activate(payment_id: str, user: dict = Depends(require_admin)):
    """Admin: confirm a payment and activate subscription."""
    result = admin_confirm_payment(payment_id)
    return JSONResponse(content=result)

@app.get("/api/admin/users")
async def api_admin_users(user: dict = Depends(require_admin)):
    """Admin: list all registered users."""
    users = await asyncio.to_thread(get_all_users)
    return JSONResponse(content={"users": users})

@app.post("/api/admin/users/{user_id}/tier")
async def api_admin_set_tier(
    user_id: int,
    request: Request,
    user: dict = Depends(require_admin)
):
    """Admin: set user tier."""
    body = await request.json()
    tier = body.get('tier', 'free')
    days = body.get('days', 30)
    # Canonical tier names only (Phase 2 rename applied).
    if tier not in ('free', 'plus', 'pro', 'ultra'):
        return JSONResponse(content={"error": "Invalid tier"}, status_code=400)
    result = await asyncio.to_thread(admin_set_tier, user_id, tier, days)
    if result.get('success') and tier != 'free':
        # Auto-credit any pending referral so it doesn't stay 'pending'
        await asyncio.to_thread(force_mark_credited, user_id, 'manual_grant')
    return JSONResponse(content=result)

@app.post("/api/admin/users/{user_id}/deactivate")
async def api_admin_deactivate(user_id: int, user: dict = Depends(require_admin)):
    """Admin: deactivate user (downgrade to free)."""
    result = await asyncio.to_thread(admin_deactivate_user, user_id)
    return JSONResponse(content=result)

@app.delete("/api/admin/users/{user_id}")
async def api_admin_delete_user(user_id: int, user: dict = Depends(require_admin)):
    """Admin: permanently delete a user."""
    result = await asyncio.to_thread(admin_delete_user, user_id)
    return JSONResponse(content=result)

@app.post("/api/admin/check-expiry")
async def api_admin_check_expiry(user: dict = Depends(require_admin)):
    """Admin: manually trigger subscription expiry check."""
    result = await asyncio.to_thread(check_subscription_expiry)
    return JSONResponse(content=result)


# ── Admin: Lab Signals (experimental RH paths) ────────────────────
@app.get("/api/admin/lab/signals")
async def api_admin_lab_signals(
    days: int = 30,
    limit: int = 200,
    user: dict = Depends(require_admin),
):
    """Admin: list experimental-tier signals (the 6 RH short-circuit paths).

    Production-tier signals (clean ARMED path) are NOT included here — they're
    available via the standard /api/signals endpoint that all users see.
    """
    if not _SIGNAL_DB_PATH.exists():
        return JSONResponse({"signals": [], "stats": {}, "by_zone": []})
    cutoff = time.time() - max(1, int(days)) * 86400
    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        # Detail rows
        cur.execute(
            "SELECT signal_id, pair, signal, price, confidence, targets_json, "
            "stop_loss, leverage, timestamp, status, pnl, targets_hit, "
            "zone_used, signal_tier, close_reason, closed_timestamp "
            "FROM signals WHERE signal_tier = 'experimental' AND timestamp > ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (cutoff, max(1, min(int(limit), 1000))),
        )
        signals = []
        for row in cur.fetchall():
            try:
                targets = json.loads(row["targets_json"]) if row["targets_json"] else []
            except Exception:
                targets = []
            try:
                t_hit = json.loads(row["targets_hit"]) if isinstance(row["targets_hit"], str) else []
            except Exception:
                t_hit = []
            pnl_value = row["pnl"]
            close_reason = row["close_reason"]
            status_upper = (row["status"] or "").upper()
            pnl_missing = (
                status_upper in ("CLOSED", "CANCELLED")
                and (pnl_value is None or float(pnl_value or 0) == 0.0)
                and close_reason not in ("SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT")
            )

            signals.append({
                "signal_id":   row["signal_id"],
                "pair":        row["pair"],
                "signal":      row["signal"],
                "price":       row["price"],
                "confidence":  row["confidence"],
                "targets":     targets,
                "stop_loss":   row["stop_loss"],
                "leverage":    row["leverage"],
                "timestamp":   row["timestamp"],
                "status":      row["status"],
                "pnl":         pnl_value,
                "pnl_missing": pnl_missing,
                "targets_hit": t_hit,
                "zone_used":   row["zone_used"],
                "close_reason": close_reason,
                "closed_timestamp": row["closed_timestamp"],
            })

        # Per-zone aggregates. Win/loss is decided by PnL sign on closed/decided
        # rows so generic 'CLOSED' statuses (no TP/SL hit tag) still classify
        # correctly. Open/SENT signals are excluded from wins/losses but counted
        # in `count`.
        DECIDED_STATUSES = ('CLOSED','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT',
                            'CLOSED_WIN','CLOSED_LOSS','LOSS','CANCELLED')
        placeholders = ','.join('?' * len(DECIDED_STATUSES))
        cur.execute(
            f"SELECT zone_used, COUNT(*) AS n, "
            f"AVG(pnl) AS avg_pnl, "
            f"SUM(CASE WHEN status IN ({placeholders}) AND status != 'CANCELLED' AND COALESCE(pnl,0) > 0 THEN 1 ELSE 0 END) AS wins, "
            f"SUM(CASE WHEN status IN ({placeholders}) AND status != 'CANCELLED' AND COALESCE(pnl,0) < 0 THEN 1 ELSE 0 END) AS losses "
            f"FROM signals WHERE signal_tier = 'experimental' AND timestamp > ? "
            f"GROUP BY zone_used ORDER BY n DESC",
            DECIDED_STATUSES + DECIDED_STATUSES + (cutoff,),
        )
        by_zone = []
        for row in cur.fetchall():
            n     = int(row["n"] or 0)
            wins  = int(row["wins"] or 0)
            loss  = int(row["losses"] or 0)
            decided = wins + loss
            by_zone.append({
                "zone_used": row["zone_used"] or "UNKNOWN",
                "count":     n,
                "wins":      wins,
                "losses":    loss,
                "win_rate":  (wins / decided) if decided > 0 else None,
                "avg_pnl":   round(float(row["avg_pnl"] or 0), 4),
            })

        # Headline stats
        total      = sum(z["count"] for z in by_zone)
        total_w    = sum(z["wins"]   for z in by_zone)
        total_l    = sum(z["losses"] for z in by_zone)
        decided    = total_w + total_l
        avg_pnl    = (sum((z["avg_pnl"] or 0) * z["count"] for z in by_zone) / total) if total else 0.0
        stats = {
            "total":     total,
            "wins":      total_w,
            "losses":    total_l,
            "win_rate":  (total_w / decided) if decided > 0 else None,
            "avg_pnl":   round(avg_pnl, 4),
            "window_days": int(days),
        }
        conn.close()
        return JSONResponse({"signals": signals, "stats": stats, "by_zone": by_zone})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Admin: ERR/WARN telemetry ─────────────────────────────────────
@app.get("/api/admin/telemetry")
async def api_admin_telemetry(
    lines: int = 200,
    level: str = "ALL",
    user: dict = Depends(require_admin)
):
    """Admin: tail the dashboard debug log and return the most recent
    ERROR and WARNING entries (or all lines when level=ALL).

    Reads only the dashboard debug log (debug_log10.txt by convention)
    so no system/secrets are ever exposed.  Returns up to 50 parsed
    entries regardless of how many raw lines are read.
    """
    import re as _re
    log_candidates = [
        Path(__file__).parent.parent / "debug_log10.txt",
        Path(__file__).parent / "debug_log10.txt",
        Path("/var/log/aladdin/dashboard.log"),
    ]
    log_path = next((p for p in log_candidates if p.exists()), None)
    if not log_path:
        return JSONResponse({"entries": [], "log_path": None,
                             "message": "No log file found"})

    # Read the last `lines` lines without loading the whole file
    try:
        with open(str(log_path), "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    except OSError as e:
        return JSONResponse({"entries": [], "error": str(e)}, status_code=500)

    # Simple log-level filter
    level_up = level.upper()
    _LOG_PAT = _re.compile(
        r'(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},?\d*)'
        r'.*?- (?P<lvl>ERROR|WARNING|INFO|DEBUG)\s*-'
        r'(?P<msg>.*)', _re.S
    )

    entries = []
    for raw in reversed(tail):
        m = _LOG_PAT.match(raw.strip())
        if not m:
            # Include raw line if level filter is ALL
            if level_up == "ALL":
                entries.append({"ts": None, "level": "RAW",
                                "msg": raw.strip()[:300]})
        else:
            lvl = m.group("lvl")
            if level_up in ("ALL", "RAW") or lvl == level_up or \
               (level_up == "WARN" and lvl == "WARNING") or \
               (level_up in ("ERR", "ERROR") and lvl == "ERROR") or \
               (level_up == "CRITICAL" and lvl in ("ERROR", "WARNING")):
                entries.append({"ts": m.group("ts").strip(),
                                "level": lvl,
                                "msg": m.group("msg").strip()[:400]})
        if len(entries) >= 50:
            break

    return JSONResponse({
        "entries": entries,
        "log_path": str(log_path),
        "total_lines_in_file": len(all_lines),
        "lines_read": len(tail),
    })


# ── Admin: maintenance / dev mode ────────────────────────────────────
@app.get("/api/admin/settings")
async def api_admin_get_settings(user: dict = Depends(require_admin)):
    return JSONResponse({"maintenance": get_maintenance_info()})


@app.post("/api/admin/settings/maintenance")
async def api_admin_set_maintenance(request: Request, user: dict = Depends(require_admin)):
    body = await request.json()
    enabled = bool(body.get("enabled", False))
    message = (body.get("message") or "").strip()
    kind = (body.get("kind") or "maintenance").strip()
    try:
        eta = int(body.get("eta_minutes") or 0)
    except Exception:
        eta = 0
    await asyncio.to_thread(set_maintenance_mode, enabled, message, kind, eta)
    return JSONResponse({"ok": True, "maintenance": get_maintenance_info()})


# ── Admin: device management per user ────────────────────────────────
@app.get("/api/admin/users/{user_id}/devices")
async def api_admin_user_devices(user_id: int, user: dict = Depends(require_admin)):
    from auth import get_user_by_id
    target = await asyncio.to_thread(get_user_by_id, user_id)
    if not target:
        return JSONResponse({"error": "User not found"}, status_code=404)
    devices = await asyncio.to_thread(list_devices, user_id)
    limit_info = await asyncio.to_thread(effective_device_limit, target)
    return JSONResponse({"devices": devices, "limit_info": limit_info})


@app.post("/api/admin/users/{user_id}/device-limit")
async def api_admin_set_device_limit(user_id: int, request: Request, user: dict = Depends(require_admin)):
    """Admin: set explicit device limit (or unlimited) on a user."""
    body = await request.json()
    limit = body.get("limit", None)
    if limit is not None:
        try:
            limit = int(limit)
            if limit < 0:
                limit = None  # reset to default
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit must be integer or null"}, status_code=400)
    result = await asyncio.to_thread(admin_set_device_override, user_id, limit)
    return JSONResponse(result)


@app.post("/api/admin/users/{user_id}/grant-slots")
async def api_admin_grant_slots(user_id: int, request: Request, user: dict = Depends(require_admin)):
    body = await request.json()
    slots = int(body.get("slots", 1))
    months = int(body.get("months", 0))
    note = body.get("note", "")
    if slots <= 0 or slots > 50:
        return JSONResponse({"error": "slots must be 1..50"}, status_code=400)
    result = await asyncio.to_thread(admin_grant_extra_slots, user_id, slots, months, note)
    return JSONResponse(result)


@app.delete("/api/admin/users/{user_id}/devices/{device_id}")
async def api_admin_revoke_device(user_id: int, device_id: int, user: dict = Depends(require_admin)):
    result = await asyncio.to_thread(revoke_device, user_id, device_id, True)
    return JSONResponse(result)


@app.post("/api/admin/users/{user_id}/resend-verification")
async def api_admin_resend_verification(user_id: int, user: dict = Depends(require_admin)):
    from auth import get_user_by_id
    target = await asyncio.to_thread(get_user_by_id, user_id)
    if not target:
        return JSONResponse({"error": "User not found"}, status_code=404)
    ok = await asyncio.to_thread(issue_and_send_verification, target)
    return JSONResponse({"ok": ok, "email": target["email"]})


# ── Data Routes (tier-gated) ─────────────────────────────────────────

@app.get("/api/monitored")
async def api_monitored(user: Optional[dict] = Depends(get_current_user)):
    tier = user.get('_effective_tier', 'free') if user else 'free'

    pairs_data = _store["monitored"]

    # Free tier: limited info (zone + pair + price only, no indicator details)
    if tier == "free":
        pairs_data = [{
            "pair": p["pair"],
            "zone": p["zone"],
            "price": p["price"],
            "change_pct": p["change_pct"],
            "hooked": p["hooked"],
            # Hide detailed indicators
            "tsi": None, "adapt_l1": None, "adapt_l2": None,
            "ce_line": None, "ce_cloud": None, "ce_level": None,
            "ce_distance_pct": None, "linreg": None,
        } for p in _store["monitored"]]

    return JSONResponse(content={
        "pairs": pairs_data,
        "updated": _store["last_scan"],
        "total_scanned": len(_store["ohlcv"]),
        "ws_streams": _store["ws_connected"],
        "bootstrapped": _store["bootstrapped"],
        "bootstrap_progress": _store["bootstrap_progress"],
        "tier": tier,
    })


@app.get("/api/chart/{pair}")
async def api_chart(pair: str, bars: int = 500, interval: str = "1h",
                    user: dict = Depends(require_tier("plus"))):
    """
    Multi-timeframe chart data endpoint.
    ?interval=  5m | 15m | 1h | 4h | 1d  (default 1h)
    ?bars=N     number of candles (capped per TF)

    Data source priority:
      1h  → in-memory WebSocket store (hot, zero-latency)
      *   → local SQLite OHLCV cache → Binance REST fallback (geo-IP safe)
    """
    p        = pair.upper()
    interval = interval if interval in _VALID_TF else "1h"
    bars     = max(50, min(bars, _TF_MAX_BARS.get(interval, 1000)))
    now      = time.time()
    ttl      = _TF_CACHE_TTL.get(interval, 4)
    cache_key = f"{p}:{interval}:{bars}"
    cached = _chart_cache.get(cache_key)
    if cached and (now - cached["ts"]) < ttl:
        return JSONResponse(content=cached["data"])
    data = await asyncio.to_thread(_compute_chart_data, p, bars, interval)
    if not data:
        return JSONResponse(content={"error": "No data"}, status_code=404)
    _chart_cache[cache_key] = {"data": data, "ts": now}
    # Evict oldest entries if cache exceeds 300 items (LRU-style, dict preserves insertion order)
    if len(_chart_cache) > 300:
        for _old_key in list(_chart_cache.keys())[:len(_chart_cache) - 300]:
            _chart_cache.pop(_old_key, None)
    return JSONResponse(content=data)


@app.get("/api/signals/live_pnl")
async def api_signals_live_pnl(user: Optional[dict] = Depends(get_current_user)):
    """Live leveraged PnL for all open/SENT signals (Pro+)."""
    tier = user.get('_effective_tier', 'free') if user else 'free'
    if TIERS.get(tier, 0) < TIERS.get('pro', 1):
        return JSONResponse({"error": "Pro+ required"}, status_code=403)

    if not _SIGNAL_DB_PATH.exists():
        return JSONResponse({"pnl": {}, "updated": time.time()})

    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT signal_id, pair, signal, price, stop_loss, leverage, targets_json, status "
            "FROM signals WHERE status IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT') "
            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
            "ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[live_pnl] DB error: {e}")
        return JSONResponse({"pnl": {}, "error": "Internal error", "updated": time.time()})

    if not rows:
        return JSONResponse({"pnl": {}, "updated": time.time()})

    pairs_needed = {r['pair'] for r in rows}
    prices = {}

    # ── Tier 0: shared PRICE_BROADCASTER (WebSocket, always fresh) ───────────
    # Zero-cost in-memory read populated by the single shared Binance WS
    # consumer. Eliminates per-request REST calls for the common case.
    try:
        _snap = PRICE_BROADCASTER.snapshot()
        for _p in pairs_needed:
            _v = _snap.get(_p)
            if _v and _v > 0:
                prices[_p] = _v
    except Exception as _be:
        print(f"[live_pnl] broadcaster snapshot failed: {_be}")

    # ── Tier 1: authenticated bulk ticker (fallback for cold-start) ──────────
    if pairs_needed - set(prices.keys()):
        try:
            tickers = await asyncio.to_thread(binance_client.futures_symbol_ticker)
            for t in tickers:
                if t['symbol'] in pairs_needed and t['symbol'] not in prices:
                    prices[t['symbol']] = float(t['price'])
        except Exception as _te:
            print(f"[live_pnl] bulk ticker failed: {_te}")

    # ── Tier 2: raw HTTP via proxy pool for any pairs still missing ──────────
    # Handles geo-restricted pairs the auth client refuses to serve.
    missing = pairs_needed - set(prices.keys())
    if missing:
        try:
            import requests as _req
            from proxy_config import get_proxy_dict as _gpd
            _resp = await asyncio.to_thread(
                lambda: _req.get(
                    'https://fapi.binance.com/fapi/v1/ticker/price',
                    proxies=_gpd(), timeout=6
                )
            )
            if _resp.ok:
                for t in _resp.json():
                    if t['symbol'] in missing:
                        prices[t['symbol']] = float(t['price'])
        except Exception as _re:
            print(f"[live_pnl] raw proxy ticker failed: {_re}")

    # ── Tier 3: last WebSocket close from in-memory OHLCV store ─────────────
    for pair in pairs_needed - set(prices.keys()):
        _df = _store["ohlcv"].get(pair)
        if _df is not None and not _df.empty:
            prices[pair] = float(_df['close'].iloc[-1])

    result = {}
    for r in rows:
        current = prices.get(r['pair'])
        entry    = float(r['price'] or 0)
        leverage = int(r['leverage'] or 1)
        direction = (r['signal'] or '').upper()
        targets  = json.loads(r['targets_json']) if r['targets_json'] else []
        sl       = float(r['stop_loss'] or 0)

        if current is None or entry <= 0:
            continue

        raw_pct = ((current - entry) / entry * 100) if direction == 'LONG' else ((entry - current) / entry * 100)
        leveraged_pct = round(raw_pct * leverage, 2)
        raw_pct = round(raw_pct, 2)

        sig_status = (r['status'] or 'SENT').upper()
        # targets_hit: check ALL TPs against current price
        targets_hit = 0
        for idx, tp in enumerate(targets):
            if (direction == 'LONG' and current >= tp) or \
               (direction == 'SHORT' and current <= tp):
                targets_hit = idx + 1
            else:
                break

        sl_hit = bool(sl and (
            (direction == 'LONG'  and current <= sl) or
            (direction == 'SHORT' and current >= sl)
        ))

        # ── Auto-close if max TP hit or SL hit ────────────────────
        # Writes closure back to DB and triggers feedback loops.
        if targets and (targets_hit == len(targets) or sl_hit):
            try:
                _close_signal_and_feedback(
                    r['signal_id'], r['pair'], direction, entry, sl, targets,
                    leverage, current, targets_hit, sl_hit
                )
            except Exception as _ce:
                print(f"[live_pnl] close error for {r['signal_id']}: {_ce}")

        result[r['signal_id']] = {
            'pair':          r['pair'],
            'current_price': current,
            'raw_pct':       raw_pct,
            'leveraged_pct': leveraged_pct,
            'leverage':      leverage,
            'targets_hit':   targets_hit,
            'tp1_hit':       targets_hit >= 1,
            'tp2_hit':       targets_hit >= 2,
            'tp3_hit':       targets_hit >= 3,
            'sl_hit':        sl_hit,
        }

    return JSONResponse({"pnl": result, "updated": time.time()})


# ══════════════════════════════════════════════════════════════════════
#  Shared SSE streams — single Binance WS upstream, fan-out to all users
# ══════════════════════════════════════════════════════════════════════

def _sse_resolve_user(request: Request, user: Optional[dict]) -> Optional[dict]:
    """
    EventSource in browsers cannot send Authorization headers. Fall back
    to a `?token=<jwt>` query param so authenticated users can open SSE
    streams directly from the client.
    """
    if user is not None:
        return user
    from auth import decode_token, get_user_by_id, get_effective_tier
    tok = request.query_params.get("token")
    if not tok:
        return None
    payload = decode_token(tok)
    if not payload:
        return None
    try:
        u = get_user_by_id(int(payload['sub']))
    except Exception:
        return None
    if not u:
        return None
    u['_effective_tier'] = get_effective_tier(u)
    return u


def _load_open_signals_for_pnl() -> list[dict]:
    """Read all open/SENT signals once (used by the SSE PnL stream)."""
    if not _SIGNAL_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT signal_id, pair, signal, price, stop_loss, leverage, targets_json, status "
            "FROM signals WHERE status IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT') "
            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
            "ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[sse_live_pnl] DB error: {e}")
        return []
    out = []
    for r in rows:
        try:
            out.append({
                "signal_id": r["signal_id"],
                "pair":      r["pair"],
                "direction": (r["signal"] or "").upper(),
                "entry":     float(r["price"] or 0),
                "leverage":  int(r["leverage"] or 1),
                "sl":        float(r["stop_loss"] or 0),
                "targets":   json.loads(r["targets_json"]) if r["targets_json"] else [],
            })
        except Exception:
            continue
    return out


@app.get("/api/stream/prices")
async def api_stream_prices(request: Request, user: Optional[dict] = Depends(get_current_user)):
    """
    Server-Sent Events stream of Binance mark prices.

    A single upstream WebSocket (PRICE_BROADCASTER) fans out to every
    connected browser. All users see identical ticks at the same moment.

    Events:
      snapshot  — full price dict on connect
      tick      — full price dict every ~2 s (when any price changed)
      ping      — keepalive comment (every 15 s)
    """
    user = _sse_resolve_user(request, user)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    tier = user.get('_effective_tier', 'free')
    if TIERS.get(tier, 0) < TIERS.get('pro', 1):
        return JSONResponse({"error": "Pro+ required"}, status_code=403)

    async def _gen():
        q = await PRICE_BROADCASTER.subscribe()
        try:
            # Tell browser to reconnect after 5 s if the stream drops
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: {msg.get('type','tick')}\n" \
                          f"data: {json.dumps(msg, separators=(',', ':'))}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            await PRICE_BROADCASTER.unsubscribe(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # disable nginx/proxy buffering
            "Connection":        "keep-alive",
        },
    )


@app.get("/api/stream/live_pnl")
async def api_stream_live_pnl(request: Request, user: Optional[dict] = Depends(get_current_user)):
    """
    SSE stream of live per-signal PnL. Computed server-side every ~2 s
    from the shared PRICE_BROADCASTER cache and the open-signals DB.

    Replaces per-user polling of /api/signals/live_pnl — same payload
    shape so the client can consume it identically.
    """
    user = _sse_resolve_user(request, user)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    tier = user.get('_effective_tier', 'free')
    if TIERS.get(tier, 0) < TIERS.get('pro', 1):
        return JSONResponse({"error": "Pro+ required"}, status_code=403)

    async def _gen():
        yield "retry: 5000\n\n"
        last_reload = 0.0
        signals: list[dict] = []
        closed_fired: set[str] = set()
        _partial_th: dict[str, int] = {}   # track highest targets_hit written per signal
        while True:
            if await request.is_disconnected():
                break
            now = time.time()
            # Reload signal list every 20 s (cheap; avoids stale set after new fires)
            if now - last_reload > 20:
                signals = await asyncio.to_thread(_load_open_signals_for_pnl)
                last_reload = now

            prices = PRICE_BROADCASTER.snapshot()
            pnl: dict = {}
            _partial_updates: list[tuple] = []   # (targets_hit, signal_id) for DB batch
            for s in signals:
                cur = prices.get(s["pair"])
                if not cur or s["entry"] <= 0:
                    continue
                direction = s["direction"]
                entry = s["entry"]
                raw_pct = ((cur - entry) / entry * 100) if direction == "LONG" \
                    else ((entry - cur) / entry * 100)
                leveraged_pct = round(raw_pct * s["leverage"], 2)
                raw_pct = round(raw_pct, 2)
                targets_hit = 0
                for idx, tp in enumerate(s["targets"]):
                    if (direction == "LONG" and cur >= tp) or \
                       (direction == "SHORT" and cur <= tp):
                        targets_hit = idx + 1
                    else:
                        break
                sl = s["sl"]
                sl_hit = bool(sl and (
                    (direction == "LONG"  and cur <= sl) or
                    (direction == "SHORT" and cur >= sl)
                ))
                # Auto-close once on terminal event — same logic as REST path
                if (s["targets"] and (targets_hit == len(s["targets"]) or sl_hit)
                        and s["signal_id"] not in closed_fired):
                    closed_fired.add(s["signal_id"])
                    try:
                        _close_signal_and_feedback(
                            s["signal_id"], s["pair"], direction, entry, sl,
                            s["targets"], s["leverage"], cur, targets_hit, sl_hit
                        )
                    except Exception as _ce:
                        print(f"[sse_live_pnl] close error {s['signal_id']}: {_ce}")
                # Persist partial TP progress to DB when it increases
                elif targets_hit > 0 and targets_hit > _partial_th.get(s["signal_id"], 0):
                    _partial_th[s["signal_id"]] = targets_hit
                    _partial_updates.append((targets_hit, s["signal_id"]))
                pnl[s["signal_id"]] = {
                    "pair":          s["pair"],
                    "current_price": cur,
                    "raw_pct":       raw_pct,
                    "leveraged_pct": leveraged_pct,
                    "leverage":      s["leverage"],
                    "targets_hit":   targets_hit,
                    "tp1_hit":       targets_hit >= 1,
                    "tp2_hit":       targets_hit >= 2,
                    "tp3_hit":       targets_hit >= 3,
                    "sl_hit":        sl_hit,
                }
            # Batch-write partial TP progress (non-blocking)
            if _partial_updates:
                try:
                    def _write_partial(updates):
                        _c = sqlite3.connect('signal_registry.db', timeout=3)
                        _c.executemany(
                            "UPDATE signals SET targets_hit=? WHERE signal_id=? AND COALESCE(targets_hit,0) < ?",
                            [(th, sid, th) for th, sid in updates]
                        )
                        _c.commit()
                        _c.close()
                    await asyncio.to_thread(_write_partial, _partial_updates)
                except Exception as _pe:
                    print(f"[sse_live_pnl] partial TP write error: {_pe}")
            payload = {"pnl": pnl, "updated": now}
            yield f"event: pnl\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@app.get("/api/stream/stats")
async def api_stream_stats(user: Optional[dict] = Depends(get_current_user)):
    """Diagnostic: current broadcaster state."""
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse(PRICE_BROADCASTER.stats())

@app.get("/api/signals/hit_stats")
async def api_signals_hit_stats(days: int = 30):
    """Return TP/SL hit percentages for the last N days (default 30)."""
    from analytics import get_signal_hit_stats
    return JSONResponse(get_signal_hit_stats(days))

@app.get("/api/signals/stats")
async def api_signals_stats():
    """Return high-level KPI counts for all signals."""
    import sqlite3, time
    DB = Path(__file__).resolve().parent.parent / "signal_registry.db"
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    open_cnt = cur.execute("SELECT COUNT(*) FROM signals WHERE upper(status) IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT')").fetchone()[0]
    closed_cnt = total - open_cnt
    cutoff = time.time() - 30*86400
    last30 = cur.execute("SELECT COUNT(*) FROM signals WHERE timestamp>?", (cutoff,)).fetchone()[0]
    conn.close()
    return {
        "total_signals": total,
        "open_signals": open_cnt,
        "closed_signals": closed_cnt,
        "signals_last_30d": last30,
    }

# ────────────────────────────────────────────────────────────────────
#  LIVE KPI + BACKTEST API
# ────────────────────────────────────────────────────────────────────

@app.get("/api/kpis")
async def api_kpis():
    """Landing-page KPI snapshot (real data)."""
    return JSONResponse(get_live_kpis())


@app.get("/api/public/stats")
async def api_public_stats():
    """Public unauthenticated stats for landing page (pairs + signals)."""
    total = get_live_kpis().get("total_signals", 0)
    try:
        from market_classifier import get_all_classifications
        pairs_monitored = len(get_all_classifications())
    except Exception:
        pairs_monitored = 0
    return JSONResponse({
        "total_signals": total,
        "pairs_monitored": pairs_monitored,
    })


@app.get("/api/backtest")
async def api_backtest(days: int = 365, capital: float = 1000.0, pos_pct: float = 1.0):
    """Equity-curve back-test based on realised signals."""
    res = run_backtest(days=days, starting_capital=capital, position_pct=pos_pct)
    return JSONResponse(res)



def _close_signal_and_feedback(signal_id, pair, direction, entry, sl, targets,
                               leverage, exit_price, targets_hit, sl_hit):
    """Persist closure to DB + trigger Circuit Breaker / Auto-Blacklist / RL / ML."""
    is_long = direction == 'LONG'
    if sl_hit:
        raw_pct = ((sl - entry) / entry * 100) if is_long else ((entry - sl) / entry * 100)
        reason  = 'SL_HIT'
        th      = 0
    else:
        tp_price = targets[targets_hit - 1]
        raw_pct  = ((tp_price - entry) / entry * 100) if is_long else ((entry - tp_price) / entry * 100)
        reason   = f'TP{targets_hit}_HIT'
        th       = targets_hit
    pnl = round(raw_pct * leverage, 2)

    # 1. SQLite update
    try:
        _con = sqlite3.connect('signal_registry.db', timeout=5)
        _con.execute(
            "UPDATE signals SET status='CLOSED', pnl=?, targets_hit=?, closed_timestamp=? "
            "WHERE signal_id=? AND status IN ('SENT','OPEN','ACTIVE')",
            (pnl, th, time.time(), signal_id)
        )
        _con.commit()
        _con.close()
    except Exception as e:
        print(f"[close] DB error for {signal_id}: {e}")
        return

    # 2. Circuit Breaker + Auto-Blacklist + RL feedback
    try:
        from performance_tracker import close_open_signal, track_signal_performance, OPEN_SIGNALS_TRACKER
        if signal_id in OPEN_SIGNALS_TRACKER:
            sig = OPEN_SIGNALS_TRACKER[signal_id]
            close_open_signal(signal_id, close_reason=reason, pnl=pnl)
            # 3. ML self-learning
            try:
                track_signal_performance(pair, sig, exit_price)
            except Exception as _te:
                print(f"[close] track_signal_performance error: {_te}")
    except Exception as e:
        print(f"[close] feedback error for {signal_id}: {e}")


@app.get("/api/signals")
async def api_signals(user: Optional[dict] = Depends(get_current_user)):
    """Signals — free tier gets 24h delayed with hidden prices."""
    tier = user.get('_effective_tier', 'free') if user else 'free'
    signals = await asyncio.to_thread(_read_signals, 50, tier)
    open_count = sum(1 for s in signals if s['status'] in ('SENT', 'OPEN', 'ACTIVE'))
    return JSONResponse(content={
        "signals": signals,
        "open_count": open_count,
        "total": len(signals),
        "tier": tier,
    })


@app.get("/api/signals/export")
async def api_signals_export(
    days: int = 30,
    user: dict = Depends(require_tier("pro"))
):
    """Pro only: export signals as JSON."""
    signals = await asyncio.to_thread(_read_signals, 500, "pro")
    return JSONResponse(content={"signals": signals, "exported_at": time.time()})


# ── Analytics Routes (Pro+) ──────────────────────────────────────────

@app.get("/api/analytics/summary")
async def api_analytics_summary(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_performance_summary, days)
    return JSONResponse(content=data)

@app.get("/api/analytics/equity")
async def api_analytics_equity(
    days: int = 30,
    capital: float = 1000,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_equity_curve, days, capital)
    return JSONResponse(content={"curve": data})

@app.get("/api/analytics/pairs")
async def api_analytics_pairs(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_pair_performance, days)
    return JSONResponse(content={"pairs": data})

@app.get("/api/analytics/heatmap")
async def api_analytics_heatmap(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_hourly_heatmap, days)
    return JSONResponse(content={"heatmap": data})

@app.get("/api/analytics/daily")
async def api_analytics_daily(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_daily_pnl, days)
    return JSONResponse(content={"daily": data})

@app.get("/api/analytics/breakdown")
async def api_analytics_breakdown(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_signal_breakdown, days)
    return JSONResponse(content={"signals": data})

@app.get("/api/analytics/attribution")
async def api_analytics_attribution(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_indicator_attribution, days)
    return JSONResponse(content=data)

@app.get("/api/analytics/regimes")
async def api_analytics_regimes(
    days: int = 30,
    user: dict = Depends(require_tier("plus"))
):
    data = await asyncio.to_thread(get_regime_performance, days)
    return JSONResponse(content=data)


# ── Pre-signal Alerts (Pro only) ─────────────────────────────────────

@app.get("/api/presignals")
async def api_presignals(user: dict = Depends(require_tier("pro"))):
    """Pro only: pairs that are close to triggering a signal."""
    presignals = []
    for p in _store["monitored"]:
        zone = p.get("zone", "")
        hooked = p.get("hooked", False)
        if not hooked:
            continue

        # L1 + L2 hooked pairs are potential pre-signals
        if zone in ("OS_L1", "OS_L2", "OB_L1", "OB_L2"):
            signal_type = "LONG" if zone.startswith("OS") else "SHORT"
            is_l2 = "L2" in zone
            ce_aligned = p.get("ce_line") == signal_type

            # Readiness: L2 + CE aligned = IMMINENT, L2 = HIGH, L1 + CE = MEDIUM, L1 = LOW
            if is_l2 and ce_aligned:
                readiness = "IMMINENT"
            elif is_l2:
                readiness = "HIGH"
            elif ce_aligned:
                readiness = "MEDIUM"
            else:
                readiness = "LOW"

            presignals.append({
                "pair": p["pair"],
                "zone": zone,
                "expected_signal": signal_type,
                "tsi": p["tsi"],
                "ce_line": p.get("ce_line"),
                "ce_cloud": p.get("ce_cloud"),
                "ce_dist": p.get("ce_dist"),
                "ce_distance_pct": p.get("ce_distance_pct"),
                "ce_level": p.get("ce_level"),
                "linreg": p.get("linreg"),
                "price": p["price"],
                "change_24h": p.get("change_pct"),
                "readiness": readiness,
            })

    # Sort: IMMINENT first, then HIGH, MEDIUM, LOW
    order = {"IMMINENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    presignals.sort(key=lambda x: order.get(x["readiness"], 9))

    return JSONResponse(content={"presignals": presignals})


@app.post("/api/presignals/quick-entry")
async def api_quick_entry(request: Request, user: dict = Depends(require_tier("ultra"))):
    """
    One-click manual trade entry from Pre-Signal Alerts (ULTRA tier only).
    Executes via the user's configured copy-trading Binance API keys.
    """
    body = await request.json()
    pair      = str(body.get('pair', '')).upper().strip()
    direction = str(body.get('direction', '')).upper().strip()
    sl_price  = float(body.get('sl_price', 0) or 0)
    tp_prices = [float(x) for x in body.get('tp_prices', []) if x]
    leverage  = int(body.get('leverage', 0) or 0)

    if not pair or not direction:
        return JSONResponse({"error": "pair and direction are required"}, status_code=400)
    if sl_price <= 0:
        return JSONResponse({"error": "sl_price must be > 0"}, status_code=400)
    if not tp_prices:
        return JSONResponse({"error": "tp_prices must not be empty"}, status_code=400)

    result = await asyncio.to_thread(
        ct_quick_entry, user['id'], pair, direction, sl_price, tp_prices, leverage
    )
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)

# ── Copy-Trading: UDS Stream Health ────────────────────────────────
@app.get("/api/copy-trading/uds-status")
async def api_ct_uds_status(user: dict = Depends(get_current_user)):
    """Return the current user's WebSocket User Data Stream health.

    Tells the frontend whether the zero-cost push-based balance path
    is live (connected=True) or whether the system is falling back to
    the REST API (connected=False). Includes staleness in seconds and
    reconnect count for diagnostic use.
    """
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    uid = user["id"]
    try:
        from binance_user_stream import (
            get_state  as _uds_state,
            is_fresh   as _uds_fresh,
            is_enabled as _uds_enabled,
        )
        if not _uds_enabled():
            return JSONResponse({"enabled": False, "connected": False,
                                 "message": "UDS disabled via BINANCE_WS_USER_STREAM env var"})
        state = _uds_state(uid) or {}
        fresh = _uds_fresh(uid)
        last_ts = state.get("server_time") or state.get("last_update") or 0
        staleness = round(time.time() - last_ts, 1) if last_ts else None
        return JSONResponse({
            "enabled":      True,
            "connected":    bool(state.get("connected", False)),
            "fresh":        fresh,
            "staleness_sec": staleness,
            "reconnects":   int(state.get("reconnects", 0)),
            "last_error":   state.get("last_error"),
            "balance_usdt": state.get("balance_usdt"),
        })
    except Exception as e:
        return JSONResponse({"enabled": False, "connected": False,
                             "error": str(e)[:200]})


# ── Liquidation Heatmap (Plus/Pro) ─────────────────────────────────

_LIQ_WINDOW_HOURS = {1: 1, 4: 4, 12: 12, 24: 24, 72: 72, 168: 168}

@app.get("/api/liq/heatmap/{symbol}")
async def api_liq_heatmap(
    symbol: str,
    window: int = 24,
    user: dict = Depends(require_tier("plus"))
):
    """Per-symbol liquidation heatmap with variable time window."""
    tier = user.get('_effective_tier', 'free')
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym = sym + "USDT"
    hours = _LIQ_WINDOW_HOURS.get(window, 24)
    # >24h windows need DB query; <=24h use fast in-memory data
    if hours <= 24:
        data = _LIQ_COLLECTOR.get_heatmap(sym)
        data["window_hours"] = hours
    else:
        data = await asyncio.to_thread(_LIQ_COLLECTOR.get_heatmap_window, sym, hours)
    # Plus-tier (rank 1) gets a lower-resolution heatmap; Pro+ gets full.
    from auth import canonicalize_tier as _canon
    if _canon(tier) == "plus" and data["has_data"]:
        data["buckets"] = data["buckets"][:20]
    return JSONResponse(content=data)


@app.get("/api/liq/summary")
async def api_liq_summary(
    top_n: int = 20,
    user: dict = Depends(require_tier("plus"))
):
    """Top symbols by liquidation volume in last 24h."""
    tier = user.get('_effective_tier', 'free')
    # Pro-tier (rank ≥ 2) and above get 50 rows; Plus/Free get 20.
    from auth import tier_rank, TIERS_CANONICAL as _TC
    max_n = 50 if tier_rank(tier) >= _TC['pro'] else 20
    top_n = max(1, min(top_n, max_n))
    return JSONResponse(content={
        "summary": _LIQ_COLLECTOR.get_summary(top_n),
        "stats": _LIQ_COLLECTOR.get_stats(),
    })


@app.get("/api/liq/pairs")
async def api_liq_pairs(user: dict = Depends(require_tier("plus"))):
    """All USDT perpetual symbols tracked by the collector (for autocomplete)."""
    all_symbols = [s['symbol'] for s in _LIQ_COLLECTOR.get_summary(top_n=500)]
    # Guarantee BTC and ETH are always present
    for sym in ('BTCUSDT', 'ETHUSDT'):
        if sym not in all_symbols:
            all_symbols.append(sym)
    return JSONResponse({"pairs": sorted(all_symbols)})


@app.get("/api/liq/stats")
async def api_liq_stats(
    user: dict = Depends(require_tier("plus"))
):
    """Collector health stats."""
    return JSONResponse(content=_LIQ_COLLECTOR.get_stats())


@app.get("/api/liq/vp/{symbol}")
async def api_liq_vp(
    symbol: str,
    window: int = 24,
    user: dict = Depends(require_tier("plus"))
):
    """Volume Profile (VPVR) — POC, VAH, VAL, and volume buckets by price."""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym = sym + "USDT"

    hours = _LIQ_WINDOW_HOURS.get(window, 24)
    if   hours <= 4:   interval, limit = '15m', hours * 4
    elif hours <= 24:  interval, limit = '1h',  hours
    elif hours <= 72:  interval, limit = '1h',  min(hours, 500)
    else:              interval, limit = '4h',  min(hours // 4, 500)

    try:
        klines = await asyncio.to_thread(
            binance_client.futures_klines, symbol=sym, interval=interval, limit=limit
        )
    except Exception as e:
        print(f"[vp] fetch error: {e}")
        return JSONResponse({"error": "Failed to fetch data", "has_data": False})

    if not klines:
        return JSONResponse({"has_data": False})

    # Build volume profile — distribute each candle's volume to its midpoint bucket
    from collections import defaultdict as _dd
    bucket_pct = 0.003  # 0.3% bands for VP (slightly wider than liq bands)
    vp: dict[float, float] = _dd(float)

    for k in klines:
        high   = float(k[2])
        low    = float(k[3])
        volume = float(k[5])
        mid    = (high + low) / 2
        if mid <= 0 or volume <= 0:
            continue
        band   = mid * bucket_pct
        bucket = round(round(mid / band) * band, 10)
        vp[bucket] += volume

    if not vp:
        return JSONResponse({"has_data": False})

    total_vol  = sum(vp.values())
    poc_price  = max(vp, key=lambda p: vp[p])

    # Value Area = 70% of total volume, built outward from POC
    sorted_by_vol = sorted(vp.items(), key=lambda x: x[1], reverse=True)
    va_vol   = 0.0
    va_prices: list[float] = []
    for price, vol in sorted_by_vol:
        va_vol  += vol
        va_prices.append(price)
        if va_vol >= total_vol * 0.70:
            break

    vah = max(va_prices) if va_prices else poc_price
    val = min(va_prices) if va_prices else poc_price
    max_v = max(vp.values())

    buckets_out = sorted(
        [{"price": p, "volume": round(v, 4), "ratio": round(v / max_v, 4)}
         for p, v in vp.items()],
        key=lambda x: x["price"]
    )

    return JSONResponse({
        "symbol":       sym,
        "poc":          poc_price,
        "vah":          round(vah, 10),
        "val":          round(val, 10),
        "total_volume": round(total_vol, 2),
        "interval":     interval,
        "window_hours": hours,
        "buckets":      buckets_out,
        "has_data":     True,
    })


@app.get("/api/liq/context/{symbol}")
async def api_liq_context(
    symbol: str,
    user: dict = Depends(require_tier("plus"))
):
    """Market context: funding rate, open interest, long/short ratio."""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym = sym + "USDT"

    result: dict = {"symbol": sym, "has_data": False}

    async def _fetch(fn, **kw):
        try:
            return await asyncio.to_thread(fn, **kw)
        except Exception:
            return None

    funding_raw, oi_raw, mark_raw, ls_raw = await asyncio.gather(
        _fetch(binance_client.futures_funding_rate,    symbol=sym, limit=3),
        _fetch(binance_client.futures_open_interest,   symbol=sym),
        _fetch(binance_client.futures_mark_price,      symbol=sym),
        _fetch(binance_client.futures_top_longshort_account_ratio, symbol=sym, period='1h', limit=2),
    )

    if mark_raw:
        mark_price  = float(mark_raw.get('markPrice', 0))
        result['mark_price'] = mark_price
        result['has_data']   = True
    else:
        mark_price = 0

    if funding_raw:
        rates = [float(f['fundingRate']) for f in funding_raw]
        result['funding_rate']     = round(rates[-1] * 100, 4)   # % per 8h
        result['funding_rate_24h'] = round(sum(rates) * 100, 4)  # 3 periods
        result['funding_bias']     = 'LONG_HEAVY' if rates[-1] > 0.0005 else \
                                     'SHORT_HEAVY' if rates[-1] < -0.0005 else 'NEUTRAL'

    if oi_raw and mark_price:
        oi_contracts = float(oi_raw.get('openInterest', 0))
        oi_usd       = oi_contracts * mark_price
        result['oi_usd'] = round(oi_usd, 0)

    if ls_raw and len(ls_raw) >= 1:
        latest = ls_raw[-1]
        result['long_ratio']  = round(float(latest.get('longAccount',  0)) * 100, 1)
        result['short_ratio'] = round(float(latest.get('shortAccount', 0)) * 100, 1)
        result['ls_ratio']    = round(float(latest.get('longShortRatio', 1)), 3)

    return JSONResponse(result)


# ── Liq Velocity ──────────────────────────────────────────────────────

@app.get("/api/liq/velocity/{symbol}")
async def api_liq_velocity(
    symbol: str,
    window: int = 10,
    user: dict = Depends(require_tier("plus"))
):
    """Per-minute liquidation event rate for last window minutes (max 30)."""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    data = await asyncio.to_thread(_LIQ_COLLECTOR.get_velocity, sym, min(window, 30))
    return JSONResponse(data)


# ── Liq-Based TP/SL Suggester ─────────────────────────────────────────

@app.get("/api/liq/suggest/{symbol}")
async def api_liq_suggest(
    symbol: str,
    direction: str = "auto",
    user: dict = Depends(require_tier("plus"))
):
    """
    Compute suggested TP and SL levels from liquidation clusters, VP, and funding.
    direction: 'LONG' | 'SHORT' | 'auto'
    """
    from collections import defaultdict as _dd2
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"

    # ── Fetch mark price and funding concurrently ──
    async def _fetch(fn, **kw):
        try:
            return await asyncio.to_thread(fn, **kw)
        except Exception:
            return None

    mark_raw, funding_raw, klines_raw = await asyncio.gather(
        _fetch(binance_client.futures_mark_price, symbol=sym),
        _fetch(binance_client.futures_funding_rate, symbol=sym, limit=1),
        _fetch(binance_client.futures_klines, symbol=sym, interval='1h', limit=24),
    )

    mark_price = float(mark_raw.get("markPrice", 0)) if mark_raw else 0
    if not mark_price:
        return JSONResponse({"has_data": False, "error": "No mark price"})

    funding_rate = float(funding_raw[0]["fundingRate"]) if funding_raw else 0
    funding_bias = ("LONG_HEAVY" if funding_rate > 0.0005 else
                    "SHORT_HEAVY" if funding_rate < -0.0005 else "NEUTRAL")

    # ── Heatmap clusters ──
    heat = _LIQ_COLLECTOR.get_heatmap(sym)
    buckets = heat.get("buckets", [])
    above = [b for b in buckets if b["price"] > mark_price]
    below = [b for b in buckets if b["price"] <= mark_price]

    # ── VP from 24h klines ──
    poc = vah = val = None
    if klines_raw:
        vp: dict[float, float] = _dd2(float)
        bp = 0.003
        for k in klines_raw:
            mid  = (float(k[2]) + float(k[3])) / 2
            vol  = float(k[5])
            if mid <= 0 or vol <= 0:
                continue
            band = mid * bp
            buck = round(round(mid / band) * band, 10)
            vp[buck] += vol
        if vp:
            poc = max(vp, key=lambda p: vp[p])
            tv  = sum(vp.values())
            svol = sorted(vp.items(), key=lambda x: x[1], reverse=True)
            va_v, va_p = 0.0, []
            for p, v in svol:
                va_v += v; va_p.append(p)
                if va_v >= tv * 0.70:
                    break
            vah = max(va_p) if va_p else None
            val = min(va_p) if va_p else None

    # ── Auto direction ──
    if direction == "auto":
        if funding_bias == "LONG_HEAVY":
            direction = "SHORT"
        elif funding_bias == "SHORT_HEAVY":
            direction = "LONG"
        else:
            long_usd  = heat.get("total_long_24h",  0)
            short_usd = heat.get("total_short_24h", 0)
            direction = "LONG" if long_usd > short_usd else "SHORT"

    # ── Build TP / SL candidates ──
    if direction == "LONG":
        tp_src = sorted(above, key=lambda b: b["short_liq_usd"], reverse=True)[:5]
        sl_src = sorted(below, key=lambda b: b["long_liq_usd"],  reverse=True)[:3]

        tp_prices = {b["price"]: b["short_liq_usd"] for b in tp_src if b["price"] > mark_price}
        if vah and vah > mark_price:
            tp_prices[round(vah, 8)] = tp_prices.get(round(vah, 8), 0)
        if poc and poc > mark_price:
            tp_prices[round(poc, 8)] = tp_prices.get(round(poc, 8), 0)

        tp_levels = sorted(
            [{"price": p, "usd": round(u, 2),
              "pct": round((p - mark_price) / mark_price * 100, 2)}
             for p, u in tp_prices.items()],
            key=lambda x: x["price"]
        )[:3]

        sl_base = sl_src[0]["price"] if sl_src else (val if val else mark_price * 0.97)
        sl_price = round(sl_base * 0.998, 8)

    else:  # SHORT
        tp_src = sorted(below, key=lambda b: b["long_liq_usd"],  reverse=True)[:5]
        sl_src = sorted(above, key=lambda b: b["short_liq_usd"], reverse=True)[:3]

        tp_prices = {b["price"]: b["long_liq_usd"] for b in tp_src if b["price"] < mark_price}
        if val and val < mark_price:
            tp_prices[round(val, 8)] = tp_prices.get(round(val, 8), 0)
        if poc and poc < mark_price:
            tp_prices[round(poc, 8)] = tp_prices.get(round(poc, 8), 0)

        tp_levels = sorted(
            [{"price": p, "usd": round(u, 2),
              "pct": round((p - mark_price) / mark_price * 100, 2)}
             for p, u in tp_prices.items()],
            key=lambda x: x["price"], reverse=True
        )[:3]

        sl_base = sl_src[0]["price"] if sl_src else (vah if vah else mark_price * 1.03)
        sl_price = round(sl_base * 1.002, 8)

    sl_pct = round((sl_price - mark_price) / mark_price * 100, 2)
    rr = (round(abs(tp_levels[0]["pct"]) / abs(sl_pct), 2)
          if tp_levels and sl_pct else 0)

    # ── POC distance / VA position ──
    poc_dist_pct = round((mark_price - poc) / poc * 100, 2) if poc else None
    in_va = bool(val and vah and val <= mark_price <= vah)

    return JSONResponse({
        "symbol":        sym,
        "mark_price":    mark_price,
        "direction":     direction,
        "tp_levels":     tp_levels,
        "sl_price":      sl_price,
        "sl_pct":        sl_pct,
        "risk_reward":   rr,
        "poc":           round(poc, 8) if poc else None,
        "vah":           round(vah, 8) if vah else None,
        "val":           round(val, 8) if val else None,
        "poc_dist_pct":  poc_dist_pct,
        "in_value_area": in_va,
        "funding_rate":  round(funding_rate * 100, 4),
        "funding_bias":  funding_bias,
        "has_data":      True,
    })


# ── Liquidation Watchlist & Alert Stream ────────────────────────────

_LIQ_WL_DB_PATH: str = str(Path(__file__).parent / "users.db")

_LIQ_WL_INIT_SQL = """
    CREATE TABLE IF NOT EXISTS liq_watchlist (
        user_id     INTEGER NOT NULL,
        symbol      TEXT    NOT NULL,
        min_usd     REAL    NOT NULL DEFAULT 100000,
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        PRIMARY KEY (user_id, symbol)
    )
"""

def _wl_get(user_id: int) -> list:
    """Thread-safe: open, query, close in one call."""
    import sqlite3 as _sq3
    conn = _sq3.connect(_LIQ_WL_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_LIQ_WL_INIT_SQL)
    conn.commit()
    rows = conn.execute(
        "SELECT symbol, min_usd FROM liq_watchlist WHERE user_id=? ORDER BY symbol",
        (user_id,)
    ).fetchall()
    conn.close()
    return [{"symbol": r[0], "min_usd": r[1]} for r in rows]

def _wl_add(user_id: int, sym: str, min_usd: float) -> dict:
    """Thread-safe: open, insert, close."""
    import sqlite3 as _sq3
    conn = _sq3.connect(_LIQ_WL_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_LIQ_WL_INIT_SQL)
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM liq_watchlist WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    if count >= 10:
        conn.close()
        return {"error": "Max 10 symbols per watchlist"}
    conn.execute(
        "INSERT OR REPLACE INTO liq_watchlist (user_id, symbol, min_usd) VALUES (?,?,?)",
        (user_id, sym, min_usd)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "symbol": sym, "min_usd": min_usd}

def _wl_remove(user_id: int, sym: str) -> None:
    """Thread-safe: open, delete, close."""
    import sqlite3 as _sq3
    conn = _sq3.connect(_LIQ_WL_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_LIQ_WL_INIT_SQL)
    conn.commit()
    conn.execute("DELETE FROM liq_watchlist WHERE user_id=? AND symbol=?", (user_id, sym))
    conn.commit()
    conn.close()

def _wl_fetch_for_sse(user_id: int) -> list:
    """Thread-safe watchlist fetch for SSE loop."""
    import sqlite3 as _sq3
    conn = _sq3.connect(_LIQ_WL_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    rows = conn.execute(
        "SELECT symbol, min_usd FROM liq_watchlist WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    return rows

@app.get("/api/liq/watchlist")
async def get_liq_watchlist(user: dict = Depends(require_tier("plus"))):
    """Get the current user's liquidation watchlist."""
    items = await asyncio.to_thread(_wl_get, user["id"])
    return JSONResponse({"watchlist": items})

@app.post("/api/liq/watchlist/{symbol}")
async def add_liq_watchlist(
    symbol: str,
    min_usd: float = 100_000,
    user: dict = Depends(require_tier("plus"))
):
    """Add a symbol to the liquidation watchlist (max 10 per user)."""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    min_usd = max(10_000, min(10_000_000, min_usd))
    result = await asyncio.to_thread(_wl_add, user["id"], sym, min_usd)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)

@app.delete("/api/liq/watchlist/{symbol}")
async def remove_liq_watchlist(symbol: str, user: dict = Depends(require_tier("plus"))):
    """Remove a symbol from the liquidation watchlist."""
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    await asyncio.to_thread(_wl_remove, user["id"], sym)
    return JSONResponse({"ok": True})

@app.get("/api/liq/alerts/stream")
async def liq_alerts_stream(request: Request):
    """
    SSE stream: pushes large liquidation alerts for the user's watchlist in real time.
    Accepts JWT via ?token= query param (EventSource cannot send Authorization headers).
    Checks every 2 seconds; yields 'data: {json}\\n\\n' for each new event.
    """
    from fastapi.responses import StreamingResponse as _SR
    from auth import decode_token, get_user_by_id, get_effective_tier, TIERS

    # Auth via query param (EventSource limitation)
    raw_token = request.query_params.get('token', '')
    payload   = decode_token(raw_token) if raw_token else None
    user      = get_user_by_id(int(payload['sub'])) if payload else None
    if not user:
        from fastapi.responses import JSONResponse as _JR
        return _JR({'error': 'Unauthorized'}, status_code=401)
    user['_effective_tier'] = get_effective_tier(user)
    if TIERS.get(user['_effective_tier'], 0) < TIERS.get('pro', 0):
        from fastapi.responses import JSONResponse as _JR
        return _JR({'error': 'Pro tier required'}, status_code=403)

    async def _generate():
        last_ts = time.time()
        # Send a heartbeat immediately so the browser knows the connection is alive
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                rows = await asyncio.to_thread(_wl_fetch_for_sse, user["id"])
                if rows:
                    symbols  = {r[0] for r in rows}
                    # Use the lowest threshold in the watchlist for the collector query
                    min_usd  = min(r[1] for r in rows)
                    thresh_map = {r[0]: r[1] for r in rows}
                    events = _LIQ_COLLECTOR.get_events_since(symbols, min_usd, last_ts)
                    for ev in events:
                        if ev['usd'] >= thresh_map.get(ev['symbol'], min_usd):
                            yield f"data: {json.dumps(ev)}\n\n"
                last_ts = time.time()
            except Exception as _e:
                logger.warning(f"[liq_alerts_stream] {_e}")
            await asyncio.sleep(2)

    return _SR(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ── Backtesting engine ───────────────────────────────────────────────
# Phase 3 · proposals/2026-04-24_backtesting-engine.md
# Historical-replay of signal_registry.db against cached OHLCV.
# Completely isolated — reads signal_registry.db + ohlcv_cache.db,
# writes only to backtests.db. No risk to the live pipeline.

@app.post("/api/backtest/run")
async def api_backtest_run(request: Request, user: dict = Depends(get_current_user)):
    """Kick off a backtest.

    Monthly quota (all tiers can access):
        free / plus : 3 runs / month
        pro         : 10 runs / month
        ultra       : 50 runs / month

    Runs synchronously in a worker thread — typical completion < 2 s.
    """
    if not user:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    from backtest_engine import run_backtest, get_backtest, check_quota
    # Quota check before we touch the DB. Admins are always allowed.
    tier     = str(user.get("tier", "free"))
    is_admin = bool(check_is_admin(user))
    quota    = await asyncio.to_thread(check_quota, int(user["id"]), tier, is_admin)
    if not quota["allowed"]:
        return JSONResponse({"error": quota["error"], "quota": quota}, status_code=429)
    try:
        params = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    if not isinstance(params, dict):
        return JSONResponse({"error": "params must be object"}, status_code=400)
    try:
        start = float(params.get("start"))
        end   = float(params.get("end"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "start and end (unix seconds) required"}, status_code=400)
    if end <= start or end - start < 3600:
        return JSONResponse({"error": "end must be > start by at least 1h"}, status_code=400)
    params["start"]    = start
    params["end"]      = end
    params["sim_mode"] = "actual"   # always use recorded outcomes; simulate mode removed from UI
    run_id = await asyncio.to_thread(run_backtest, int(user["id"]), params)
    data = await asyncio.to_thread(get_backtest, run_id)
    if data:
        data["quota"] = quota   # surface remaining runs to the frontend
    return JSONResponse(data or {"run_id": run_id, "status": "error",
                                  "error": "run disappeared"})


@app.get("/api/backtest/{run_id:int}")
async def api_backtest_get(run_id: int, user: dict = Depends(get_current_user)):
    """Fetch a full backtest payload (run + stats + every trade)."""
    if not user:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    from backtest_engine import get_backtest
    data = await asyncio.to_thread(get_backtest, run_id)
    if not data:
        return JSONResponse({"error": "not found"}, status_code=404)
    if data["user_id"] != user["id"] and not check_is_admin(user):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


@app.get("/api/backtest/list")
async def api_backtest_list(user: dict = Depends(get_current_user)):
    """The caller's last 25 runs + current quota status."""
    if not user:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    from backtest_engine import list_backtests, check_quota
    tier     = str(user.get("tier", "free"))
    is_admin = bool(check_is_admin(user))
    rows     = await asyncio.to_thread(list_backtests, int(user["id"]), 25)
    quota    = await asyncio.to_thread(check_quota, int(user["id"]), tier, is_admin)
    return JSONResponse({"runs": rows, "quota": quota})


# ── Web Push (VAPID) ─────────────────────────────────────────────────
# Phase 2 · proposals/2026-04-24_native-push-alerts.md
# Inert until VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are set in env.

@app.get("/api/push/vapid-public-key")
async def api_push_vapid_public_key():
    """Return the VAPID public key so the SW can subscribe.
    Empty payload (+200) if push is not configured — lets client hide UI."""
    from push_notifications import get_public_key, is_push_enabled
    return JSONResponse({
        "public_key": get_public_key() or "",
        "enabled":    is_push_enabled(),
    })


@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, user: dict = Depends(get_current_user)):
    """Register a browser PushSubscription for the current user."""
    from push_notifications import subscribe as _push_subscribe
    if not user:
        return JSONResponse({"ok": False, "error": "auth required"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
    sub = body.get("subscription") or {}
    ua  = body.get("user_agent") or request.headers.get("user-agent", "")[:256]
    result = _push_subscribe(int(user["id"]), sub, user_agent=ua)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/push/unsubscribe")
async def api_push_unsubscribe(request: Request, user: dict = Depends(get_current_user)):
    """Drop a subscription (typically called when the user disables push)."""
    from push_notifications import unsubscribe as _push_unsubscribe
    if not user:
        return JSONResponse({"ok": False, "error": "auth required"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
    endpoint = str(body.get("endpoint", "")).strip()
    ok = _push_unsubscribe(int(user["id"]), endpoint) if endpoint else False
    return JSONResponse({"ok": ok})


# ── TradingView Screener API ─────────────────────────────────────────

@app.get("/api/screener")
async def get_screener(user: dict = Depends(require_tier("plus"))):
    """Return TV screener priority pairs with scores (Pro+).

    Caching architecture (Phase 2, 2026-04-24):
      1. Redis cache (25 s TTL, shared across all worker processes &
         all concurrent users). Hit rate ~99%.
      2. On Redis miss OR Redis unavailable: fall through to the
         TradingView API, compute, then backfill Redis.
      3. The old in-process `_TV_CACHE` remains untouched so nothing
         else in the codebase breaks (tv_screener.py still uses it).
    """
    try:
        from tradingview_screener import Query, col
        from tv_screener import RSI_OS_MAX, RSI_OB_MIN, MIN_REL_VOL, _TV_CACHE
        from redis_cache import screener_cache_get, screener_cache_set

        # ── Redis fast-path ──────────────────────────────────────────
        cached = screener_cache_get()
        if cached is not None:
            # Surface a cache header so clients can reason about freshness.
            cached["cache_source"] = "redis"
            return JSONResponse(cached)

        # Return cached data if fresh
        cached_ts = _TV_CACHE.get("ts", 0)
        cache_age = int(time.time() - cached_ts)

        # Always fetch fresh data for the screener endpoint (cap to 300 pairs)
        _, df = (
            Query()
            .set_markets("crypto")
            .select("name", "close", "RSI", "MACD.macd", "MACD.signal",
                    "volume", "relative_volume_10d_calc", "change")
            .where(
                col("exchange").isin(["BINANCE", "BYBIT"]),
                col("relative_volume_10d_calc") >= MIN_REL_VOL,
            )
            .order_by("relative_volume_10d_calc", ascending=False)
            .limit(300)
            .get_scanner_data()
        )
        df = df[df["name"].str.endswith(".P", na=False)]

        def _safe(val, default=0.0):
            """Return default if val is None, NaN, or inf (NaN is truthy so 'or' fallback fails)."""
            try:
                v = float(val)
                import math as _m
                return default if (_m.isnan(v) or _m.isinf(v)) else v
            except (TypeError, ValueError):
                return default

        rows = []
        for _, row in df.iterrows():
            name = str(row.get("name", "")).upper()
            sym = name.replace(".P", "").replace("-PERP", "")
            rsi     = round(_safe(row.get("RSI"), 50), 1)
            rel_vol = round(_safe(row.get("relative_volume_10d_calc"), 1), 2)
            macd    = _safe(row.get("MACD.macd"), 0)
            macd_sig= _safe(row.get("MACD.signal"), 0)
            change  = round(_safe(row.get("change"), 0), 2)
            close   = _safe(row.get("close"), 0)

            # Determine bias
            if rsi <= RSI_OS_MAX:
                bias = "LONG"
            elif rsi >= RSI_OB_MIN:
                bias = "SHORT"
            else:
                bias = "NEUTRAL"

            # Score
            score = 0.0
            if rsi <= RSI_OS_MAX:
                score += (RSI_OS_MAX - rsi) * 2
            elif rsi >= RSI_OB_MIN:
                score += (rsi - RSI_OB_MIN) * 2
            score += min(rel_vol, 5.0) * 3
            if (macd > macd_sig and rsi < 50) or (macd < macd_sig and rsi > 50):
                score += 5
            score += abs(change) * 0.5
            macd_cross = "bullish" if macd > macd_sig else "bearish"

            rows.append({
                "symbol":   sym,
                "rsi":      rsi,
                "rel_vol":  rel_vol,
                "macd_cross": macd_cross,
                "change":   change,
                "close":    close,
                "bias":     bias,
                "score":    round(score, 1),
            })

        rows.sort(key=lambda r: -r["score"])
        payload = {
            "pairs":        rows,
            "total":        len(rows),
            "cache_age":    cache_age,
            "fetched_at":   int(time.time()),
            "cache_source": "live",
        }
        # Backfill Redis so the next N users within 25 s hit the fast path.
        # No-op if Redis is down; zero risk either way.
        screener_cache_set(payload, ttl_s=25)
        return JSONResponse(payload)
    except Exception as exc:
        print(f"[screener] error: {exc}")
        return JSONResponse({"error": "Screener unavailable", "pairs": [], "total": 0}, status_code=500)


# ── TradingView Webhook ──────────────────────────────────────────────

_TV_SECRET = os.getenv("TV_WEBHOOK_SECRET", "")
_TV_DB_PATH = Path(__file__).resolve().parent.parent / "tv_alerts.db"

def _init_tv_db():
    conn = sqlite3.connect(_TV_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tv_alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            received  REAL NOT NULL,
            symbol    TEXT,
            action    TEXT,
            price     REAL,
            strategy  TEXT,
            message   TEXT,
            raw_json  TEXT,
            processed INTEGER DEFAULT 0,
            result    TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_tv_db()

@app.post("/api/webhook/tradingview")
async def tv_webhook(request: Request):
    """
    Receives TradingView strategy alerts via webhook.

    TradingView alert message (JSON format):
    {
      "secret":   "YOUR_TV_WEBHOOK_SECRET",
      "symbol":   "{{ticker}}",
      "action":   "{{strategy.order.action}}",
      "price":    {{strategy.order.price}},
      "strategy": "My Strategy Name",
      "message":  "{{strategy.order.comment}}"
    }

    Validation: secret must match TV_WEBHOOK_SECRET in .env
    """
    try:
        body = await request.json()
    except Exception:
        raw = await request.body()
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Validate secret (body or header) — REQUIRED; reject all if not configured
    if not _TV_SECRET:
        return JSONResponse({"error": "Webhook not configured"}, status_code=503)
    incoming_secret = body.get("secret", "") or request.headers.get("X-TV-Secret", "")
    if incoming_secret != _TV_SECRET:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    symbol   = str(body.get("symbol", "UNKNOWN")).upper().replace(".P", "").replace("BINANCE:", "")
    action   = str(body.get("action", body.get("side", ""))).upper()
    price    = float(body.get("price", 0) or 0)
    strategy = str(body.get("strategy", "TradingView"))
    message  = str(body.get("message", body.get("comment", "")))
    received = time.time()

    # Persist to SQLite
    try:
        conn = sqlite3.connect(_TV_DB_PATH)
        conn.execute(
            "INSERT INTO tv_alerts (received, symbol, action, price, strategy, message, raw_json) VALUES (?,?,?,?,?,?,?)",
            (received, symbol, action, price, strategy, message, json.dumps(body))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        pass

    # Forward to Telegram ops channel
    action_emoji = "🚀" if action in ("BUY", "LONG", "BUY_LONG") else ("📉" if action in ("SELL", "SHORT", "SELL_SHORT") else "📡")
    tg_text = (
        f"📺 *TradingView Alert*\n"
        f"Strategy: `{strategy}`\n"
        f"Symbol: `{symbol}`\n"
        f"Action: {action_emoji} `{action}`\n"
        f"Price: `{price}`\n"
        + (f"Note: _{message}_\n" if message else "")
        + f"Time: {datetime.fromtimestamp(received, tz=timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    try:
        from telegram_handler import send_ops_message
        await send_ops_message(tg_text)
    except Exception:
        pass

    # ── Forward to bot's process_pair with tv_override ────────────────────────
    # Map TV action to bot direction
    tv_signal = None
    if action in ("BUY", "LONG", "BUY_LONG"):
        tv_signal = "LONG"
    elif action in ("SELL", "SHORT", "SELL_SHORT"):
        tv_signal = "SHORT"

    if tv_signal and symbol.endswith("USDT"):
        try:
            import sys as _sys
            # Import main module if bot is co-located in same process environment
            _main_mod = _sys.modules.get("__main__")
            _process_pair = None
            if _main_mod and hasattr(_main_mod, "process_pair"):
                _process_pair = _main_mod.process_pair
            else:
                # Try direct import (works if dashboard is started from bot dir)
                from main import process_pair as _process_pair
            if _process_pair:
                tv_override = {"signal": tv_signal, "strategy": strategy,
                               "price": price, "source": "tv_webhook"}
                asyncio.create_task(_process_pair(symbol, tv_override=tv_override))
        except Exception as _fw_err:
            pass  # Bot not co-located — alert is stored, Telegram notified

    return JSONResponse({"status": "ok", "symbol": symbol, "action": action,
                         "tv_signal": tv_signal, "received": received})


@app.get("/api/webhook/tradingview/alerts")
async def tv_alerts(
    limit: int = 50,
    user: dict = Depends(require_tier("plus"))
):
    """Recent TradingView alerts (Pro+)."""
    try:
        conn = sqlite3.connect(_TV_DB_PATH)
        rows = conn.execute(
            "SELECT id, received, symbol, action, price, strategy, message FROM tv_alerts ORDER BY received DESC LIMIT ?",
            (min(limit, 200),)
        ).fetchall()
        conn.close()
        alerts = [
            {"id": r[0], "time": r[1], "symbol": r[2], "action": r[3],
             "price": r[4], "strategy": r[5], "message": r[6]}
            for r in rows
        ]
        return JSONResponse({"alerts": alerts, "count": len(alerts)})
    except Exception as e:
        print(f"[tv_alerts] DB error: {e}")
        return JSONResponse({"alerts": [], "count": 0, "error": "Internal error"})

# ══════════════════════════════════════════════════════════════════════
#  COPY-TRADING API (Pro)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/copy-trading/server-ip")
async def ct_get_server_ip(request: Request, user: dict = Depends(require_tier("pro"))):
    """Return the server's current public IP for Binance API key whitelist setup."""
    force = request.query_params.get("refresh", "").lower() == "true"
    result = await asyncio.to_thread(force_refresh_ip if force else get_cached_server_ip)
    return JSONResponse(result)

@app.get("/api/copy-trading/config")
async def ct_get_config(user: dict = Depends(require_tier("pro"))):
    """Get user's copy-trading configuration."""
    cfg = get_ct_config(user['id'])
    stats = ct_stats(user['id'])
    return JSONResponse({"config": cfg, "stats": stats})


@app.post("/api/copy-trading/keys")
async def ct_save_keys(request: Request, user: dict = Depends(require_tier("pro"))):
    """Save encrypted Binance API keys."""
    body = await request.json()
    result = save_api_keys(
        user_id=user['id'],
        api_key=body.get('api_key', ''),
        api_secret=body.get('api_secret', ''),
        size_pct=float(body.get('size_pct', 2.0)),
        max_size_pct=float(body.get('max_size_pct', 5.0)),
        max_leverage=int(body.get('max_leverage', 20)),
        scale_with_sqi=bool(body.get('scale_with_sqi', True)),
        tp_mode=str(body.get('tp_mode', 'pyramid')),
        size_mode=str(body.get('size_mode', 'pct')),
        fixed_size_usd=float(body.get('fixed_size_usd', 5.0)),
        leverage_mode=str(body.get('leverage_mode', 'auto')),
        sl_mode=str(body.get('sl_mode', 'signal')),
        sl_pct=float(body.get('sl_pct', 3.0)),
        copy_experimental=bool(body.get('copy_experimental', False)),
    )
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    # Spawn / restart the user-stream for this user so the dashboard
    # starts receiving push updates immediately (no REST polling).
    try:
        import binance_user_stream as _uds
        await _uds.stop(user['id'])
        await _uds.start(user['id'])
    except Exception:
        pass
    return JSONResponse(result)


@app.post("/api/copy-trading/toggle")
async def ct_toggle_active(request: Request, user: dict = Depends(require_tier("pro"))):
    """Enable or disable copy-trading."""
    body = await request.json()
    active = bool(body.get('active', False))
    result = ct_toggle(user['id'], active)
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    # Start/stop the user-stream in lockstep with is_active.
    try:
        import binance_user_stream as _uds
        if active:
            await _uds.start(user['id'])
        else:
            await _uds.stop(user['id'])
    except Exception:
        pass
    return JSONResponse(result)


@app.post("/api/copy-trading/settings")
async def ct_update(request: Request, user: dict = Depends(require_tier("pro"))):
    """Update copy-trading settings."""
    body = await request.json()
    kwargs = {}
    if 'size_pct' in body: kwargs['size_pct'] = float(body['size_pct'])
    if 'max_size_pct' in body: kwargs['max_size_pct'] = float(body['max_size_pct'])
    if 'max_leverage' in body: kwargs['max_leverage'] = int(body['max_leverage'])
    if 'scale_with_sqi' in body: kwargs['scale_with_sqi'] = bool(body['scale_with_sqi'])
    if 'tp_mode' in body: kwargs['tp_mode'] = str(body['tp_mode'])
    if 'size_mode' in body: kwargs['size_mode'] = str(body['size_mode'])
    if 'fixed_size_usd' in body: kwargs['fixed_size_usd'] = float(body['fixed_size_usd'])
    if 'leverage_mode' in body: kwargs['leverage_mode'] = str(body['leverage_mode'])
    if 'sl_mode' in body: kwargs['sl_mode'] = str(body['sl_mode'])
    if 'sl_pct' in body: kwargs['sl_pct'] = float(body['sl_pct'])
    if 'copy_experimental' in body: kwargs['copy_experimental'] = bool(body['copy_experimental'])
    result = ct_update_settings(user['id'], **kwargs)
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.delete("/api/copy-trading/keys")
async def ct_delete_keys(user: dict = Depends(require_tier("pro"))):
    """Delete API keys and config."""
    # Stop the user-stream BEFORE deleting keys so the AsyncClient can
    # close cleanly while credentials are still valid.
    try:
        import binance_user_stream as _uds
        await _uds.stop(user['id'])
    except Exception:
        pass
    result = ct_delete_config(user['id'])
    return JSONResponse(result)


@app.get("/api/admin/ws-status")
async def admin_ws_status(user: dict = Depends(require_admin)):
    """Admin: per-user Binance WebSocket (User Data Stream) status."""
    try:
        import binance_user_stream as _uds
        return JSONResponse({
            "enabled": _uds.is_enabled(),
            "streams": _uds.status_all(),
        })
    except Exception as e:
        return JSONResponse({"enabled": False, "error": str(e), "streams": {}})


@app.get("/api/copy-trading/balance")
async def ct_get_balance(user: dict = Depends(require_tier("pro"))):
    """Fetch live Binance Futures USDT balance.

    Redis fast-path (Phase 2, 2026-04-24):
      1. 8 s TTL cache keyed on user_id — sufficient because the
         dashboard refresh rate is ~3 s, so a given user polls 3-4
         times within one TTL window. At 100 active users this
         collapses ~400 Binance REST calls/minute → ~15/minute.
      2. Cache is invalidated opportunistically on UDS ACCOUNT_UPDATE
         events (see binance_user_stream.py → bal_cache_del).
      3. If Redis is unavailable the call simply falls through to the
         existing synchronous Binance path; no degradation.
    """
    from redis_cache import bal_cache_get, bal_cache_set
    cached = bal_cache_get(user['id'])
    if cached is not None:
        cached["cache_source"] = "redis"
        return JSONResponse(cached)
    # The Binance client is synchronous and can block for up to 30 s on
    # timeout — run it in a worker thread so we don't stall the event loop.
    result = await asyncio.to_thread(ct_live_balance, user['id'])
    # Backfill only on success; failure payloads stay out of cache to
    # avoid pinning an error state on every subsequent poll.
    try:
        if isinstance(result, dict) and result.get("success", True) and not result.get("error"):
            bal_cache_set(user['id'], result, ttl_s=8)
    except Exception:
        pass
    return JSONResponse(result)  # always 200 — balance failure is non-fatal


@app.get("/api/copy-trading/live-pnl")
async def ct_live_pnl_endpoint(user: dict = Depends(require_tier("pro"))):
    """Ultra-cheap real-time unrealized PnL — zero Binance REST weight.

    Recomputes unrealized PnL every call from two WebSocket caches:
      1. UDS `binance_user_stream` state: per-position entry/amt/leverage
         (updated on ACCOUNT_UPDATE events and every 60 s via reconcile)
      2. `PRICE_BROADCASTER` snapshot: live mark prices for every USDT
         perp, pushed by Binance every 1 s

    Formula per position (signed amt: >0 LONG, <0 SHORT):
        pnl_usd = (mark - entry) * amt
        init_margin = |amt| * entry / leverage
        pnl_pct = pnl_usd / init_margin * 100  (ROI on margin, same as Binance UI)

    Safe to poll every 1 s from the client.
    """
    try:
        from binance_user_stream import get_state as _uds_state  # type: ignore
    except Exception:
        return JSONResponse({"error": "user stream unavailable", "positions": {}})
    st = _uds_state(user['id']) or {}
    positions_in = st.get("positions") or {}
    if not positions_in:
        return JSONResponse({
            "ok": True,
            "unrealized_pnl": 0.0,
            "unrealized_pnl_pct": 0.0,
            "total_invested_usd": float(st.get("total_invested_usd", 0) or 0),
            "positions": {},
            "price_age_s": None,
            "state_age_s": round(time.time() - float(st.get("last_event", 0) or 0), 2)
                           if st.get("last_event") else None,
        })

    prices = PRICE_BROADCASTER.snapshot() or {}
    price_stats = PRICE_BROADCASTER.stats() or {}
    price_age = price_stats.get("age")

    out_positions: Dict[str, Dict[str, float]] = {}
    total_pnl = 0.0
    total_margin = 0.0
    for sym, p in positions_in.items():
        try:
            amt = float(p.get("amt", 0) or 0)
            entry = float(p.get("entry", 0) or 0)
            lev = int(float(p.get("leverage", 1) or 1)) or 1
            if amt == 0 or entry <= 0:
                continue
            mark = prices.get(sym)
            if mark is None:
                # No live mark yet — fall back to the value UDS already stored
                pnl_u = float(p.get("pnl_usd", 0) or 0)
                pnl_p = float(p.get("pnl_pct", 0) or 0)
                mark = entry
                stale = True
            else:
                pnl_u = (mark - entry) * amt
                im = abs(amt) * entry / lev
                pnl_p = (pnl_u / im * 100) if im else 0.0
                stale = False
            im_total = abs(amt) * entry / lev
            total_pnl += pnl_u
            total_margin += im_total
            out_positions[sym] = {
                "pnl_usd": round(pnl_u, 4),
                "pnl_pct": round(pnl_p, 4),
                "mark": mark,
                "entry": entry,
                "amt": amt,
                "leverage": lev,
                "side": "LONG" if amt > 0 else "SHORT",
                "stale_mark": stale,
            }
        except Exception:
            continue

    total_pct = (total_pnl / total_margin * 100) if total_margin else 0.0
    return JSONResponse({
        "ok": True,
        "unrealized_pnl": round(total_pnl, 2),
        "unrealized_pnl_pct": round(total_pct, 2),
        "total_invested_usd": round(total_margin, 2),
        "positions": out_positions,
        "price_age_s": price_age,
        "state_age_s": round(time.time() - float(st.get("last_event", 0) or 0), 2)
                       if st.get("last_event") else None,
        "source": "ws",
    })


@app.post("/api/copy-trading/close-all")
async def ct_close_all_positions(user: dict = Depends(require_tier("pro"))):
    """Close all open Binance Futures positions at market price."""
    result = ct_close_all(user['id'])
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/copy-trading/close-position/{pair}")
async def ct_close_single_position_endpoint(pair: str, user: dict = Depends(require_tier("pro"))):
    """Close a specific open Binance Futures position at market price."""
    result = ct_close_single(user['id'], pair)
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/copy-trading/recalc-pnl")
async def ct_recalc_pnl(
    user: dict = Depends(require_tier("pro")),
    lookback_days: int = 90,
    only_missing: bool = False,
):
    """Recalculate realized PnL (USD + leverage-aware %) for every closed
    copy-trade in the last `lookback_days`. Pass `only_missing=true` to
    restrict to rows that still show $0.
    """
    result = await asyncio.to_thread(
        ct_backfill_pnl, user['id'], lookback_days, only_missing
    )
    return JSONResponse(result)


@app.get("/api/copy-trading/history")
async def ct_get_history(
    limit: int = 50,
    user: dict = Depends(require_tier("pro"))
):
    """Get copy-trade history with live unrealized PnL for open trades."""
    trades = ct_history(user['id'], min(limit, 200))
    stats  = ct_stats(user['id'])
    # Enrich open trades with live Binance unrealized PnL
    open_trades = [t for t in trades if t.get('status') == 'open']
    if open_trades:
        live_pnl = await asyncio.to_thread(ct_live_pnl, user['id'])
        for t in trades:
            if t.get('status') == 'open':
                lp = live_pnl.get(t.get('pair', ''), {})
                t['pnl_usd']    = lp.get('pnl_usd', 0)
                t['pnl_pct']    = lp.get('pnl_pct', 0)
                t['mark_price'] = lp.get('mark_price')
    return JSONResponse({"trades": trades, "stats": stats})


@app.post("/api/copy-trading/tradefi-signed")
async def ct_tradefi_signed(user: dict = Depends(require_tier("pro"))):
    """Mark TradFi-Perps agreement as signed — hides the warning banner."""
    result = ct_mark_tradefi_signed(user['id'])
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/copy-trading/filters")
async def ct_save_pair_filters(request: Request, user: dict = Depends(require_tier("pro"))):
    """Save pair tier/sector filter settings for copy-trading."""
    body = await request.json()
    allowed_tiers = body.get('allowed_tiers', 'blue_chip,large_cap,mid_cap,small_cap,high_risk')
    allowed_sectors = body.get('allowed_sectors', 'all')
    hot_only = bool(body.get('hot_only', False))
    result = ct_save_filters(user['id'], allowed_tiers, allowed_sectors, hot_only)
    if result.get('error'):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.get("/api/market/classifications")
async def market_classifications(user: dict = Depends(get_current_user)):
    """Return full pair → tier/sector/HOT classification map."""
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)
    data = get_all_classifications()
    return JSONResponse({
        "classifications": data,
        "tiers": get_tier_labels(),
        "sectors": get_sector_labels(),
        "count": len(data),
    })


# ── Macro Indicators (USDT.D + Per-Pair REVERSE HUNT) ─────────────────────
@app.get("/api/macro/state")
async def api_macro_state(pairs: str = "BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,XRPUSDT,BNBUSDT,AVAXUSDT,LINKUSDT",
                          timeframe: str = "1h"):
    """
    Return macro indicator state for USDT.D and the listed pairs.
    Public endpoint (no auth) so the overview panel works for all tiers.
    Query params:
      - pairs: comma-separated tickers (defaults to top 8)
      - timeframe: 15m|30m|1h|2h|4h (default 1h matches bot main loop)
    """
    import sys, os as _os
    _os.sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    try:
        from usdt_dominance import get_usdt_dominance_state, LEVEL_L1_UP as U_L1U, LEVEL_L1_DN as U_L1D, LEVEL_L2_UP as U_L2U, LEVEL_L2_DN as U_L2D
        from pair_macro_indicator import get_pair_macro_state, LEVEL_L1_UP as P_L1U, LEVEL_L1_DN as P_L1D, LEVEL_L2_UP as P_L2U, LEVEL_L2_DN as P_L2D
    except Exception as exc:
        return JSONResponse({"error": f"Macro modules unavailable: {exc}"}, status_code=503)

    # USDT.D
    try:
        ud = get_usdt_dominance_state(timeframe=timeframe)
        usdt_d = {
            "value_pct":      ud.value_pct,
            "tsi_scaled":     ud.tsi_scaled,
            "tsi_prev":       ud.tsi_prev,
            "linreg":         ud.linreg,
            "state":          ud.state,
            "is_ready":       ud.is_ready,
            "bars_available": ud.bars_available,
            "timeframe":      timeframe,
            "levels":         {"L1_UP": U_L1U, "L1_DN": U_L1D, "L2_UP": U_L2U, "L2_DN": U_L2D},
        }
    except Exception as exc:
        usdt_d = {"error": str(exc)}

    # Per-pair
    pair_list = [p.strip().upper() for p in pairs.split(",") if p.strip()][:20]
    pair_states = []
    for p in pair_list:
        try:
            ps = get_pair_macro_state(p, timeframe=timeframe)
            pair_states.append({
                "pair":           p,
                "tsi_scaled":     ps.tsi_scaled,
                "tsi_prev":       ps.tsi_prev,
                "linreg":         ps.linreg,
                "state":          ps.state,
                "lr_regime":      ps.lr_regime,
                "is_ready":       ps.is_ready,
                "bars_available": ps.bars_available,
            })
        except Exception as exc:
            pair_states.append({"pair": p, "error": str(exc)})

    return JSONResponse({
        "timeframe":    timeframe,
        "usdt_d":       usdt_d,
        "pairs":        pair_states,
        "pair_levels":  {"L1_UP": P_L1U, "L1_DN": P_L1D, "L2_UP": P_L2U, "L2_DN": P_L2D},
        "updated_at":   time.time(),
    })


_FNG_CACHE: dict = {'data': None, 'ts': 0}
_FNG_TTL = 3600  # 1 hour

def _fetch_fng_cmc(cmc_key: str) -> dict:
    """Fetch from CoinMarketCap v3 Fear & Greed API."""
    import requests as _req
    r = _req.get(
        'https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest',
        headers={'X-CMC_PRO_API_KEY': cmc_key, 'Accept': 'application/json'},
        timeout=8
    )
    r.raise_for_status()
    d = r.json()
    if str(d.get('status', {}).get('error_code', '0')) != '0':
        raise ValueError(d['status'].get('error_message', 'CMC API error'))
    item = d['data']
    return {
        'value':          int(item['value']),
        'classification': item['value_classification'],
        'timestamp':      int(time.time()),
        'source':         'coinmarketcap',
    }

def _fetch_fng_alternative() -> dict:
    """Fallback: fetch from Alternative.me."""
    import requests as _req
    r = _req.get('https://api.alternative.me/fng/?limit=1', timeout=8)
    r.raise_for_status()
    item = r.json()['data'][0]
    return {
        'value':          int(item['value']),
        'classification': item['value_classification'],
        'timestamp':      int(item['timestamp']),
        'source':         'alternative.me',
    }

@app.get("/api/macro/fear-greed")
async def api_fear_greed():
    """Fear & Greed Index — CoinMarketCap primary, Alternative.me fallback. 1h cache."""
    now = time.time()
    if _FNG_CACHE['data'] and now - _FNG_CACHE['ts'] < _FNG_TTL:
        return JSONResponse(_FNG_CACHE['data'])
    cmc_key = os.getenv('CMC_API_KEY', '')
    result = None
    try:
        if cmc_key:
            result = await asyncio.to_thread(_fetch_fng_cmc, cmc_key)
        else:
            result = await asyncio.to_thread(_fetch_fng_alternative)
    except Exception as _cmc_err:
        logger.warning(f"[fear-greed] primary fetch failed: {_cmc_err} — trying fallback")
        try:
            result = await asyncio.to_thread(_fetch_fng_alternative)
        except Exception as _alt_err:
            logger.warning(f"[fear-greed] fallback also failed: {_alt_err}")
    if result:
        result['cached_at'] = now
        _FNG_CACHE['data']  = result
        _FNG_CACHE['ts']    = now
        return JSONResponse(result)
    if _FNG_CACHE['data']:
        return JSONResponse({**_FNG_CACHE['data'], 'stale': True})
    return JSONResponse({'error': 'Fear & Greed data unavailable'}, status_code=503)


# ══════════════════════════════════════════════════════════════════════════════
# Order Flow & Money Flow endpoints — all data from Binance public APIs
# ══════════════════════════════════════════════════════════════════════════════

_FLOW_CACHE: dict = {}   # symbol → {data, ts}
_FLOW_TTL   = 60         # seconds

_BNFAPI = "https://fapi.binance.com"
_BNDATA = "https://fapi.binance.com/futures/data"


def _bnf_get(url: str, params: dict) -> dict | list:
    """Simple urllib GET to Binance fapi."""
    qs  = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={'User-Agent': 'AladdinBot/1.0', 'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def _fetch_binance_lsr(symbol: str) -> dict:
    """Global Long/Short Account Ratio from Binance (5m period, last 1 bar)."""
    try:
        rows = _bnf_get(f"{_BNDATA}/globalLongShortAccountRatio",
                        {'symbol': symbol, 'period': '5m', 'limit': 1})
        if not rows:
            return {}
        r = rows[-1]
        ls   = float(r.get('longShortRatio', 1.0))
        long_pct  = ls / (1 + ls) * 100
        short_pct = 100 - long_pct
        return {'long_pct': round(long_pct, 2), 'short_pct': round(short_pct, 2),
                'ls_ratio': round(ls, 4), 'source': 'binance'}
    except Exception:
        return {}


def _fetch_binance_top_lsr(symbol: str) -> dict:
    """Top Trader Long/Short Position Ratio from Binance."""
    try:
        rows = _bnf_get(f"{_BNDATA}/topLongShortPositionRatio",
                        {'symbol': symbol, 'period': '5m', 'limit': 1})
        if not rows:
            return {}
        r = rows[-1]
        return {'top_long_pct':  round(float(r.get('longAccount', 0)) * 100, 2),
                'top_short_pct': round(float(r.get('shortAccount', 0)) * 100, 2)}
    except Exception:
        return {}


def _fetch_binance_oi(symbol: str) -> dict:
    """Current OI snapshot + 24h history (hourly) from Binance."""
    try:
        snap = _bnf_get(f"{_BNFAPI}/fapi/v1/openInterest", {'symbol': symbol})
        oi_now = float(snap.get('openInterest', 0))
        price_snap = _bnf_get(f"{_BNFAPI}/fapi/v1/premiumIndex", {'symbol': symbol})
        mark  = float(price_snap.get('markPrice', 1))
        oi_usd = oi_now * mark

        hist = _bnf_get(f"{_BNDATA}/openInterestHist",
                        {'symbol': symbol, 'period': '1h', 'limit': 24})
        oi_hist = []
        for h in hist:
            oi_hist.append({
                'ts':     int(h.get('timestamp', 0)),
                'oi':     float(h.get('sumOpenInterest', 0)),
                'oi_usd': float(h.get('sumOpenInterestValue', 0)),
            })
        oi_change = 0.0
        if len(oi_hist) >= 2:
            first = oi_hist[0]['oi_usd']
            last  = oi_hist[-1]['oi_usd']
            oi_change = round((last - first) / first * 100, 2) if first > 0 else 0.0

        return {
            'oi_usd':    round(oi_usd, 0),
            'oi_change': oi_change,
            'oi_history': oi_hist,
            'source':    'binance',
        }
    except Exception:
        return {}


def _fetch_binance_funding(symbol: str) -> dict:
    """Current funding rate + next funding time from Binance."""
    try:
        r = _bnf_get(f"{_BNFAPI}/fapi/v1/premiumIndex", {'symbol': symbol})
        fr = float(r.get('lastFundingRate', 0))
        return {
            'funding_rate':      round(fr * 100, 6),   # in %
            'funding_rate_raw':  fr,
            'next_funding_time': int(r.get('nextFundingTime', 0)),
            'mark_price':        float(r.get('markPrice', 0)),
            'index_price':       float(r.get('indexPrice', 0)),
            'source':            'binance',
        }
    except Exception:
        return {}


def _fetch_binance_taker(symbol: str) -> dict:
    """Taker long/short ratio (last 12 × 5m bars) from Binance."""
    try:
        rows = _bnf_get(f"{_BNDATA}/takerlongshortRatio",
                        {'symbol': symbol, 'period': '5m', 'limit': 12})
        if not rows:
            return {}
        hist = [{'ts': int(r['timestamp']),
                 'buy_ratio':  round(float(r.get('buySellRatio', 1)), 4),
                 'buy_vol':    float(r.get('buyVol', 0)),
                 'sell_vol':   float(r.get('sellVol', 0))} for r in rows]
        latest = hist[-1] if hist else {}
        ratio = latest.get('buy_ratio', 1.0)
        bias  = ('buy_dominant' if ratio > 1.1
                 else 'sell_dominant' if ratio < 0.9
                 else 'neutral')
        return {'taker_ratio': ratio, 'taker_bias': bias,
                'taker_history': hist, 'source': 'binance'}
    except Exception:
        return {}


def _fetch_binance_all(symbol: str) -> dict:
    """Fetch all Binance flow data for one symbol in one thread call."""
    out: dict = {}
    out.update(_fetch_binance_lsr(symbol))
    out.update(_fetch_binance_top_lsr(symbol))
    out.update(_fetch_binance_oi(symbol))
    out.update(_fetch_binance_funding(symbol))
    out.update(_fetch_binance_taker(symbol))
    return out


@app.get("/api/flow/cvd/{symbol}")
async def api_flow_cvd(symbol: str, user: dict = Depends(require_tier("plus"))):
    """Real-time CVD (Cumulative Volume Delta) for a symbol from the aggTrade stream."""
    sym = symbol.upper()
    try:
        from cvd_stream_manager import CVD_FEED as _cvd
        data = _cvd.get(sym, max_age_s=60)
        if data is None:
            return JSONResponse({'symbol': sym, 'available': False, 'reason': 'no_data_or_stale'})
        return JSONResponse({'symbol': sym, 'available': True, **data})
    except Exception as exc:
        return JSONResponse({'symbol': sym, 'available': False, 'reason': str(exc)}, status_code=500)


@app.get("/api/flow/mfi/{symbol}")
async def api_flow_mfi(symbol: str, interval: str = "1h", user: dict = Depends(require_tier("plus"))):
    """Money Flow Index (MFI-14) for a symbol from OHLCV cache."""
    sym = symbol.upper()
    try:
        from data_fetcher import fetch_data as _fd
        import talib as _talib
        df = await asyncio.to_thread(_fd, sym, interval)
        if df is None or len(df) < 20:
            return JSONResponse({'symbol': sym, 'available': False, 'reason': 'insufficient_data'})
        hi = df['high'].values.astype(float)
        lo = df['low'].values.astype(float)
        cl = df['close'].values.astype(float)
        vo = df['volume'].values.astype(float)
        mfi14      = _talib.MFI(hi, lo, cl, vo, timeperiod=14)
        obv        = _talib.OBV(cl, vo)
        ad         = _talib.AD(hi, lo, cl, vo)
        latest_mfi = float(mfi14[-1]) if not np.isnan(mfi14[-1]) else None
        mfi_state  = ('oversold' if latest_mfi and latest_mfi <= 20
                      else 'overbought' if latest_mfi and latest_mfi >= 80 else 'neutral')
        return JSONResponse({
            'symbol':     sym, 'interval': interval, 'available': True,
            'mfi':        round(latest_mfi, 2) if latest_mfi else None,
            'mfi_state':  mfi_state,
            'obv_trend':  'rising' if obv[-1] > obv[-5] else 'falling',
            'ad_trend':   'accumulation' if ad[-1] > ad[-5] else 'distribution',
            'mfi_history': [round(float(v), 2) if not np.isnan(v) else None for v in mfi14[-20:]],
        })
    except Exception as exc:
        return JSONResponse({'symbol': sym, 'available': False, 'reason': str(exc)}, status_code=500)


@app.get("/api/flow/snapshot/{symbol}")
async def api_flow_snapshot(symbol: str, user: dict = Depends(require_tier("plus"))):
    """
    Unified order-flow snapshot:
    CVD (aggTrade stream) + MFI/OBV/AD (OHLCV) + L/S ratio + OI + funding + taker (all Binance).
    """
    sym = symbol.upper()
    now = time.time()
    result: dict = {'symbol': sym, 'fetched_at': now}

    # ── CVD ─────────────────────────────────────────────────────────
    try:
        from cvd_stream_manager import CVD_FEED as _cvd
        cvd = _cvd.get(sym, max_age_s=60)
        result['cvd'] = cvd if cvd else None
    except Exception:
        result['cvd'] = None

    # ── MFI / OBV / AD ──────────────────────────────────────────────
    try:
        from data_fetcher import fetch_data as _fd
        import talib as _talib
        df = await asyncio.to_thread(_fd, sym, '1h')
        if df is not None and len(df) >= 15:
            hi = df['high'].values.astype(float)
            lo = df['low'].values.astype(float)
            cl = df['close'].values.astype(float)
            vo = df['volume'].values.astype(float)
            mfi14 = _talib.MFI(hi, lo, cl, vo, timeperiod=14)
            obv   = _talib.OBV(cl, vo)
            ad    = _talib.AD(hi, lo, cl, vo)
            mv    = float(mfi14[-1]) if not np.isnan(mfi14[-1]) else None
            result['mfi'] = {
                'value':   round(mv, 2) if mv else None,
                'state':   ('oversold' if mv and mv <= 20 else 'overbought' if mv and mv >= 80 else 'neutral'),
                'obv_dir': ('rising' if obv[-1] > obv[-5] else 'falling'),
                'ad_dir':  ('accumulation' if ad[-1] > ad[-5] else 'distribution'),
                'history': [round(float(v), 2) if not np.isnan(v) else None for v in mfi14[-10:]],
            }
        else:
            result['mfi'] = None
    except Exception:
        result['mfi'] = None

    # ── Binance market data (L/S, OI, funding, taker) ───────────────
    cached = _FLOW_CACHE.get(sym)
    if cached and now - cached['ts'] < _FLOW_TTL:
        result['market'] = cached['data']
    else:
        try:
            market = await asyncio.to_thread(_fetch_binance_all, sym)
            _FLOW_CACHE[sym] = {'data': market, 'ts': now}
            result['market'] = market
        except Exception as exc:
            logger.warning(f"[flow/snapshot] Binance fetch failed for {sym}: {exc}")
            result['market'] = cached['data'] if cached else None

    return JSONResponse(result)


@app.get("/api/admin/copy-trading")
async def admin_ct_traders(user: dict = Depends(require_admin)):
    """Admin: list all copy-trading users."""
    traders = ct_admin_traders()
    return JSONResponse({"traders": traders})


@app.get("/api/admin/payments/config")
async def admin_payments_config(user: dict = Depends(require_admin)):
    """
    Admin: full NOWPayments diagnostic.
    Includes: config state, API health ping, available currencies,
    IPN URL to paste into NOWPayments dashboard.
    """
    import nowpayments as np_client
    cfg    = np_client.describe_config()
    health = np_client.get_api_status()
    currencies = np_client.get_currencies() if cfg["configured"] else []
    return JSONResponse({
        "config":     cfg,
        "health":     health,
        "currencies": currencies[:50],  # cap list for response size
        "currency_count": len(currencies),
    })


@app.get("/api/admin/payments/history")
async def admin_payments_history(limit: int = 100, user: dict = Depends(require_admin)):
    """Admin: recent payment history across all users."""
    from auth import _get_db
    conn = _get_db()
    rows = conn.execute(
        "SELECT ph.*, u.username, u.email "
        "FROM payment_history ph LEFT JOIN users u ON ph.user_id = u.id "
        "ORDER BY ph.created_at DESC LIMIT ?",
        (min(int(limit), 500),)
    ).fetchall()
    conn.close()
    return JSONResponse({"payments": [dict(r) for r in rows]})


@app.post("/api/admin/copy-trading/recover-sl-tp/{user_id}")
async def admin_recover_sl_tp(user_id: int, user: dict = Depends(require_admin)):
    """Admin: place missing SL/TP orders on open copy-trades for a user."""
    results = await ct_retry_sl_tp(user_id)
    return JSONResponse({"results": results, "processed": len(results)})


# ── Payment Return Pages (NOWPayments success/cancel) ────────────────

@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success_page(order: str = ""):
    """
    Shown when NOWPayments redirects the user after a successful checkout.
    The IPN webhook has (or will) activate the subscription — we just
    reassure the user and auto-redirect to the dashboard.
    """
    safe_order = "".join(c for c in order if c.isalnum() or c in "-_")[:64]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Received — Anunnaki World</title>
    <link rel="stylesheet" href="/static/css/main.css?v=3">
    <link rel="stylesheet" href="/static/css/premium.css?v=5">
    <style>
        body {{ margin:0; background:#05080F; color:#E1E7EF; font-family:Inter,sans-serif;
               min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px; }}
        .card {{ max-width:480px; width:100%; padding:48px 36px; text-align:center;
                 background:linear-gradient(180deg,rgba(15,21,34,0.85),rgba(8,12,22,0.88));
                 border:1px solid rgba(212,168,74,0.35); border-radius:20px;
                 backdrop-filter:blur(18px); box-shadow:0 24px 64px rgba(0,0,0,.55),0 0 48px rgba(212,168,74,.15); }}
        .logo {{ width:64px;height:64px;border-radius:14px;margin:0 auto 20px;
                 box-shadow:0 0 0 1px rgba(212,168,74,.5),0 0 24px rgba(212,168,74,.3); }}
        .ok {{ display:inline-flex;align-items:center;gap:8px;
               background:rgba(79,209,199,.12);color:#4FD1C7;
               font-size:12px;font-weight:800;letter-spacing:.2em;
               padding:6px 16px;border-radius:20px;margin-bottom:18px;
               border:1px solid rgba(79,209,199,.3); }}
        .ok .dot {{ width:6px;height:6px;border-radius:50%;background:#4FD1C7;
                     box-shadow:0 0 10px #4FD1C7;animation:pulse 1.6s ease-in-out infinite; }}
        @keyframes pulse {{ 50% {{ opacity:.35; transform:scale(.8); }} }}
        h1 {{ font-size:28px; font-weight:800; letter-spacing:-.02em; margin:0 0 12px;
              background:linear-gradient(135deg,#fff 0%,#E4C375 60%,#D4A84A 100%);
              -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent; }}
        p {{ font-size:14px; line-height:1.6; color:rgba(225,231,239,.7); margin:0 0 24px; }}
        code {{ background:rgba(255,255,255,.05);padding:2px 8px;border-radius:4px;
                font-size:11px;color:#E4C375;letter-spacing:.04em; }}
        a.btn {{ display:inline-block;background:linear-gradient(135deg,#E4C375,#D4A84A 50%,#9B7A2F);
                 color:#1a0f00;font-weight:700;font-size:14px;padding:14px 32px;
                 border-radius:10px;text-decoration:none;letter-spacing:.03em;
                 box-shadow:0 6px 18px rgba(212,168,74,.4),inset 0 1px 0 rgba(255,255,255,.25); }}
        .hint {{ font-size:11px;color:rgba(198,204,212,.45);margin-top:18px;letter-spacing:.04em; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/logo.jpeg" class="logo" alt="Anunnaki World">
        <div class="ok"><span class="dot"></span>PAYMENT RECEIVED</div>
        <h1>Welcome to the Club</h1>
        <p>Your crypto payment has been detected on-chain. We're waiting for the final confirmations — your subscription will be activated automatically within <strong style="color:#E4C375">a few minutes</strong>.</p>
        <p style="font-size:12px">Order reference: <code>{safe_order or 'pending'}</code></p>
        <a class="btn" href="/">Go to Dashboard</a>
        <div class="hint">This page will auto-redirect in 15 seconds…</div>
    </div>
    <script>setTimeout(function(){{window.location.href='/?payment=success';}}, 15000);</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel_page(order: str = ""):
    """Shown when user cancels or closes the NOWPayments checkout."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Cancelled — Anunnaki World</title>
    <style>
        body { margin:0; background:#05080F; color:#E1E7EF; font-family:Inter,sans-serif;
              min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px; }
        .card { max-width:440px; width:100%; padding:44px 36px; text-align:center;
                background:linear-gradient(180deg,rgba(15,21,34,.85),rgba(8,12,22,.88));
                border:1px solid rgba(255,255,255,.1); border-radius:20px;
                backdrop-filter:blur(18px); box-shadow:0 24px 64px rgba(0,0,0,.55); }
        .logo { width:56px;height:56px;border-radius:12px;margin:0 auto 16px;opacity:.85; }
        h1 { font-size:22px; font-weight:700; margin:0 0 10px; color:#fff; }
        p { font-size:14px; line-height:1.6; color:rgba(225,231,239,.68); margin:0 0 24px; }
        a.btn { display:inline-block;background:rgba(255,255,255,.06);color:#E1E7EF;
                font-weight:600;font-size:13px;padding:12px 24px;
                border-radius:10px;text-decoration:none;letter-spacing:.03em;
                border:1px solid rgba(255,255,255,.12); margin:4px; }
        a.btn.gold { background:linear-gradient(135deg,#E4C375,#D4A84A 50%,#9B7A2F);
                     color:#1a0f00;border:none;
                     box-shadow:0 6px 18px rgba(212,168,74,.35); }
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/logo.jpeg" class="logo" alt="Anunnaki World">
        <h1>Checkout Cancelled</h1>
        <p>No payment was taken. You can continue exploring the platform or start a new checkout whenever you're ready.</p>
        <a class="btn" href="/">Back to Dashboard</a>
        <a class="btn gold" href="/?page=pricing">Try Again</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Referral Landing Page ────────────────────────────────────────────

@app.get("/ref/{code}", response_class=HTMLResponse)
async def referral_landing(code: str):
    """
    Shareable referral URL with social OG preview cards.
    Shows the current referral offer, then redirects to /?ref=code.
    This route is a utility/share page and should not be indexed.
    """
    safe_code = code.strip().upper()[:12]
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex,nofollow">
    <title>You've been invited to Anunnaki World Signals</title>

    <meta property="og:type"        content="website">
    <meta property="og:url"         content="https://anunnakiworld.com/ref/{safe_code}">
    <meta property="og:title"       content="🎁 Get 7 Bonus Days — Anunnaki World Signals">
    <meta property="og:description" content="You've been personally invited. Create your account through this link and, after the first verified payment, both you and the referrer receive 7 bonus days.">
    <meta property="og:image"       content="https://anunnakiworld.com/static/logo.jpeg">
    <meta property="og:site_name"   content="Anunnaki World Signals">

    <meta name="twitter:card"        content="summary">
    <meta name="twitter:title"       content="🎁 Get 7 Bonus Days — Anunnaki World Signals">
    <meta name="twitter:description" content="Join through this invite link and both accounts receive 7 bonus days after the first verified payment.">
    <meta name="twitter:image"       content="https://anunnakiworld.com/static/logo.jpeg">

    <meta http-equiv="refresh" content="0;url=/?ref={safe_code}">
    <style>
        body {{ margin:0; background:#0d0d0f; color:#fff; font-family:Inter,sans-serif;
               display:flex; align-items:center; justify-content:center; height:100vh; }}
        .card {{ text-align:center; max-width:460px; padding:40px 32px;
                 background:#141416; border:1px solid #2a2a2e; border-radius:16px; }}
        .logo {{ width:72px; height:72px; border-radius:14px; margin-bottom:20px; }}
        h1 {{ font-size:22px; margin:0 0 10px; }}
        p {{ font-size:14px; color:#888; line-height:1.6; margin:0 0 24px; }}
        .badge {{ display:inline-block; background:rgba(0,200,83,.12);
                  color:#00c853; font-size:13px; font-weight:700;
                  padding:6px 16px; border-radius:20px; margin-bottom:20px; }}
        a {{ display:inline-block; background:#00c853; color:#000;
             font-weight:700; font-size:14px; padding:12px 28px;
             border-radius:10px; text-decoration:none; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/logo.jpeg" alt="Anunnaki World" class="logo">
        <div class="badge">🎁 Special Invite</div>
        <h1>You've been invited!</h1>
        <p>Join Anunnaki World through this invite link. After your <strong style="color:#fff">first verified payment</strong>, both you and the referrer receive <strong style="color:#fff">7 bonus days</strong>.</p>
        <a href="/?ref={safe_code}">Accept Invite →</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_doc)


# ── Referral Routes ──────────────────────────────────────────────────

@app.get("/api/referral/stats")
async def api_referral_stats(user: dict = Depends(get_current_user)):
    """Get current user's referral code, stats, and history."""
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)
    return JSONResponse(get_referral_stats(user['id']))


@app.get("/api/referral/code")
async def api_referral_code(user: dict = Depends(get_current_user)):
    """Get or generate the current user's referral code."""
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)
    code = get_or_create_code(user['id'])
    return JSONResponse({"code": code})


@app.get("/api/referral/validate/{code}")
async def api_referral_validate(code: str):
    """Validate a referral code before registration (public endpoint)."""
    referrer_id = resolve_code(code)
    return JSONResponse({"valid": referrer_id is not None})


@app.get("/api/admin/referrals")
async def api_admin_referrals(user: dict = Depends(require_admin)):
    """Admin: view all referral performance."""
    return JSONResponse({"referrers": get_admin_referral_stats()})


# ── Health Check ─────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    users = get_user_count()
    return JSONResponse(content={
        "bootstrapped": _store["bootstrapped"],
        "bootstrap_progress": _store["bootstrap_progress"],
        "total_pairs": len(_store["all_pairs"]),
        "loaded_pairs": len(_store["ohlcv"]),
        "monitored_count": len(_store["monitored"]),
        "ws_connections": _store["ws_connected"],
        "last_scan": _store["last_scan"],
        "users": users,
    })


# ── Public Landing Stats (no auth) ───────────────────────────────────
_PUBLIC_STATS_CACHE = {"ts": 0.0, "data": None}
# Short TTL so the landing-page "signals fired" counter visibly ticks up
# as new signals are generated by the main loop (~every 30 s). A 15 s
# cache protects the DB while still feeling live to a visitor.
_PUBLIC_STATS_TTL  = 15.0


def _count_all_signals_direct() -> int:
    """Authoritative all-time count: open + archived rows in the
    signal registry. Cheap COUNT(*) on indexed tables, ~1 ms."""
    if not _SIGNAL_DB_PATH.exists():
        return 0
    con = sqlite3.connect(str(_SIGNAL_DB_PATH), timeout=3)
    try:
        con.row_factory = sqlite3.Row
        n_open = con.execute("SELECT COUNT(*) FROM signals WHERE COALESCE(signal_tier,'production')='production'").fetchone()[0] or 0
        try:
            n_arch = con.execute("SELECT COUNT(*) FROM archived_signals WHERE COALESCE(signal_tier,'production')='production'").fetchone()[0] or 0
        except sqlite3.Error:
            n_arch = 0
        return int(n_open) + int(n_arch)
    finally:
        con.close()


@app.get("/api/public/stats")
async def api_public_stats():
    """
    Public aggregate stats for the landing page (no auth, cached 15 s).
    Returns real numbers: total signals fired, win rate, pairs monitored.
    The "total_signals" value comes straight from the signal_registry DB
    (open + archived rows) so the landing-page counter reflects every
    new signal within one poll window.
    """
    import time as _t
    now = _t.time()
    if _PUBLIC_STATS_CACHE["data"] and (now - _PUBLIC_STATS_CACHE["ts"]) < _PUBLIC_STATS_TTL:
        return JSONResponse(content=_PUBLIC_STATS_CACHE["data"])

    try:
        # Authoritative direct count — survives even if the perf summary
        # is misconfigured or its lookback window is too short.
        total_signals = await asyncio.to_thread(_count_all_signals_direct)

        # Everything else comes from the performance summary (all-time).
        summary = await asyncio.to_thread(get_performance_summary, 3650)
        # Live pair count from shared_state if bootstrapped, else static 200
        pairs_count = len(_store.get("all_pairs", []))
        if pairs_count < 50:
            pairs_count = 200
        data = {
            "pairs_monitored": pairs_count,
            "total_signals":   int(total_signals or summary.get("total_signals", 0) or 0),
            "closed_signals":  int(summary.get("closed_signals", 0) or 0),
            "win_rate":        float(summary.get("win_rate", 0) or 0),
            "profit_factor":   float(summary.get("profit_factor", 0) or 0),
            "wins":            int(summary.get("wins", 0) or 0),
            "losses":          int(summary.get("losses", 0) or 0),
            "server_time":     now,
        }
    except Exception as e:
        # Graceful degrade — never 500 on the landing page
        data = {
            "pairs_monitored": 200,
            "total_signals":   0,
            "closed_signals":  0,
            "win_rate":        0.0,
            "profit_factor":   0.0,
            "wins":            0,
            "losses":          0,
            "error":           str(e)[:80],
            "server_time":     now,
        }
    _PUBLIC_STATS_CACHE["data"] = data
    _PUBLIC_STATS_CACHE["ts"]   = now
    return JSONResponse(content=data)


# ══════════════════════════════════════════════════════════════════════
#  STREAM MODE — /stream route + /api/stream/* endpoints
#  Public, sanitized view for YouTube/OBS broadcast. Zones/macro live,
#  signal details embargoed by _STREAM_EMBARGO_SEC. See top of file for env config.
# ══════════════════════════════════════════════════════════════════════

def _stream_token_ok(request: Request) -> bool:
    """True if stream is open (no token set) or provided token matches."""
    if not _STREAM_TOKEN:
        return True
    provided = request.query_params.get("key", "")
    # Constant-time compare to resist timing attacks
    return hmac.compare_digest(provided, _STREAM_TOKEN)


def _stream_guard(request: Request):
    """Raise 403 if stream disabled or token invalid."""
    if not _STREAM_ENABLED:
        raise HTTPException(status_code=404, detail="Stream mode disabled")
    if not _stream_token_ok(request):
        raise HTTPException(status_code=403, detail="Invalid stream token")


@app.get("/stream", response_class=HTMLResponse)
async def stream_page(request: Request):
    """Serve the stream view HTML (OBS browser source target)."""
    _stream_guard(request)
    html_path = Path(__file__).parent / "stream.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Stream view not installed</h1>", status_code=500)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/api/stream/stats")
async def api_stream_stats(request: Request):
    """Aggregate performance — reuses cached /api/public/stats numbers."""
    _stream_guard(request)
    # Reuse public stats (5 min cached, already sanitized)
    now = time.time()
    if not _PUBLIC_STATS_CACHE["data"] or (now - _PUBLIC_STATS_CACHE["ts"]) >= _PUBLIC_STATS_TTL:
        try:
            summary = await asyncio.to_thread(get_performance_summary, 3650)
            pairs_count = len(_store.get("all_pairs", [])) or 200
            _PUBLIC_STATS_CACHE["data"] = {
                "pairs_monitored": pairs_count,
                "total_signals":   int(summary.get("total_signals", 0) or 0),
                "closed_signals":  int(summary.get("closed_signals", 0) or 0),
                "win_rate":        float(summary.get("win_rate", 0) or 0),
                "profit_factor":   float(summary.get("profit_factor", 0) or 0),
                "wins":            int(summary.get("wins", 0) or 0),
                "losses":          int(summary.get("losses", 0) or 0),
            }
            _PUBLIC_STATS_CACHE["ts"] = now
        except Exception:
            pass
    return JSONResponse(content=_PUBLIC_STATS_CACHE["data"] or {})


@app.get("/api/stream/monitored")
async def api_stream_monitored(request: Request):
    """Zone snapshot — pair + zone + tsi + linreg + ce flags. No trade params."""
    _stream_guard(request)
    safe = []
    for p in _store["monitored"]:
        safe.append({
            "pair":     p.get("pair"),
            "zone":     p.get("zone"),
            "tsi":      p.get("tsi"),
            "adapt_l1": p.get("adapt_l1"),
            "adapt_l2": p.get("adapt_l2"),
            "ce_line":  p.get("ce_line"),
            "ce_cloud": p.get("ce_cloud"),
            "linreg":   p.get("linreg"),
            "hooked":   bool(p.get("hooked", False)),
            # Deliberately omit: any entry/SL/TP-style fields
        })
    return JSONResponse({
        "pairs":   safe,
        "updated": _store.get("last_scan", 0),
    })


@app.get("/api/stream/presignals")
async def api_stream_presignals(request: Request):
    """Pre-signal pairs shown on stream — pair + zone + readiness only.
    Direction (LONG/SHORT) redacted unless STREAM_SHOW_DIRECTION=1."""
    _stream_guard(request)
    presignals = []
    for p in _store["monitored"]:
        zone = p.get("zone", "")
        hooked = p.get("hooked", False)
        if not hooked:
            continue
        # Readiness calc (same logic as /api/presignals but stripped)
        ce_line  = p.get("ce_line", "")
        ce_cloud = p.get("ce_cloud", "")
        # Simple readiness based on zone + hook + CE alignment
        if zone in ("OS_L2", "OB_L2"):
            readiness = "IMMINENT" if ce_line and ce_cloud else "HIGH"
        elif zone in ("OS_L1", "OB_L1"):
            readiness = "MEDIUM"
        else:
            readiness = "LOW"
        item = {
            "pair":      p.get("pair"),
            "zone":      zone,
            "readiness": readiness,
        }
        if _STREAM_SHOW_DIRECTION:
            # Optional: expose expected direction
            item["expected_signal"] = "LONG" if zone.startswith("OS") else "SHORT"
        presignals.append(item)
    # Order: IMMINENT > HIGH > MEDIUM > LOW
    order = {"IMMINENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    presignals.sort(key=lambda x: order.get(x["readiness"], 9))
    return JSONResponse({"presignals": presignals[:12]})


@app.get("/api/stream/signals")
async def api_stream_signals(request: Request):
    """Signal feed with embargo. Signals newer than _STREAM_EMBARGO_SEC are
    shown with pair + status + countdown only (locked). Older signals get
    full details just like any authenticated user would see."""
    _stream_guard(request)
    if not _SIGNAL_DB_PATH.exists():
        return JSONResponse({"signals": [], "embargo_sec": _STREAM_EMBARGO_SEC})
    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cutoff_old = time.time() - 7 * 86400  # show last 7 days on stream
        cur.execute(
            'SELECT signal_id, pair, signal, price, confidence, targets_json, '
            'stop_loss, leverage, timestamp, status, pnl, targets_hit, signal_tier, zone_used '
            "FROM signals WHERE timestamp > ? "
            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
            'ORDER BY timestamp DESC LIMIT 30',
            (cutoff_old,)
        )
        now = time.time()
        out = []
        for row in cur.fetchall():
            age = now - (row['timestamp'] or 0)
            locked = age < _STREAM_EMBARGO_SEC
            ts_utc = datetime.fromtimestamp(row['timestamp'], tz=timezone.utc)

            base = {
                "pair":      row['pair'],
                "status":    row['status'] or 'SENT',
                "time_utc":  ts_utc.isoformat(),
                "timestamp": row['timestamp'],
                "locked":    locked,
                "signal_tier": row['signal_tier'] or 'production',
                "zone_used": row['zone_used'],
            }
            if locked:
                # Redact EVERYTHING except pair + status + time
                base["reveal_in_sec"] = max(0, int(_STREAM_EMBARGO_SEC - age))
                base["direction"]     = "🔒"
            else:
                # Past embargo — reveal full details
                targets = []
                if row['targets_json']:
                    try:
                        targets = json.loads(row['targets_json'])
                    except Exception:
                        pass
                _th_raw = row['targets_hit']
                if isinstance(_th_raw, int):
                    th = _th_raw
                elif isinstance(_th_raw, str):
                    try:
                        _v = json.loads(_th_raw)
                        th = len(_v) if isinstance(_v, list) else int(_v)
                    except Exception:
                        th = 0
                else:
                    th = 0
                base.update({
                    "direction":    row['signal'],
                    "price":        row['price'],
                    "stop_loss":    row['stop_loss'],
                    "targets":      targets,
                    "leverage":     row['leverage'],
                    "targets_hit":  th,
                    "pnl":          round(row['pnl'], 2) if row['pnl'] else 0,
                    "confidence":   round(row['confidence'] * 100, 1) if row['confidence'] else 0,
                })
            out.append(base)
        conn.close()
        return JSONResponse({
            "signals":     out,
            "embargo_sec": _STREAM_EMBARGO_SEC,
            "server_time": now,
        })
    except Exception as e:
        return JSONResponse({"signals": [], "error": str(e)[:80]}, status_code=500)


@app.get("/api/stream/config")
async def api_stream_config(request: Request):
    """Static config the stream page needs at load time."""
    _stream_guard(request)
    return JSONResponse({
        "embargo_sec":     _STREAM_EMBARGO_SEC,
        "show_direction":  _STREAM_SHOW_DIRECTION,
        "server_time":     time.time(),
    })


# ── Backtest aggregate stats for the stream view ──────────────────────
# Cache: 5 min (data only changes when someone runs a new backtest)
_BT_STREAM_CACHE: dict = {"ts": 0.0, "data": None}
_BT_STREAM_TTL = 300.0


def _get_bt_stream_stats() -> dict:
    """Return the stats block from the single most-recent completed backtest
    run across ALL users, for public display on the stream view.

    Reads only `stats_json` from `backtests.db` — no user ID, no params,
    no trade-level data is ever exposed.
    """
    try:
        from backtest_engine import _bt_conn as _btc
        c = _btc()
        try:
            row = c.execute(
                "SELECT stats_json, created_at FROM backtest_runs "
                "WHERE status='done' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            c.close()
        if not row or not row["stats_json"]:
            return {}
        import json as _json
        stats = _json.loads(row["stats_json"])
        # Whitelist — only non-sensitive aggregate metrics
        return {
            "trades":           int(stats.get("trades", 0)),
            "wins":             int(stats.get("wins", 0)),
            "losses":           int(stats.get("losses", 0)),
            "win_rate":         float(stats.get("win_rate", 0)),
            "profit_factor":    float(stats.get("profit_factor", 0)),
            "net_pnl_pct":      float(stats.get("net_pnl_pct", 0)),
            "max_drawdown_pct": float(stats.get("max_drawdown_pct", 0)),
            "sharpe":           float(stats.get("sharpe", 0)),
            "sortino":          float(stats.get("sortino", 0)),
            "run_at":           float(row["created_at"] or 0),
        }
    except Exception:
        return {}


@app.get("/api/stream/backtest")
async def api_stream_backtest(request: Request):
    """Public aggregate backtest stats for the stream view.

    Returns stats from the most recently completed backtest run — no
    user-identifying data, no trade-level details, no parameters.
    Cached 5 min server-side; safe to call on every stream poll cycle.
    """
    _stream_guard(request)
    now = time.time()
    if _BT_STREAM_CACHE["data"] and (now - _BT_STREAM_CACHE["ts"]) < _BT_STREAM_TTL:
        return JSONResponse(_BT_STREAM_CACHE["data"])
    data = await asyncio.to_thread(_get_bt_stream_stats)
    _BT_STREAM_CACHE["data"] = data
    _BT_STREAM_CACHE["ts"]   = now
    return JSONResponse(data)


@app.get("/api/charts/ohlcv")
async def api_charts_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 120,
    user: Optional[dict] = Depends(get_current_user),
):
    """Proxy Binance spot klines for the mobile Charts page. Requires Plus+."""
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    if not (check_is_admin(user) or TIERS.get(user.get('_effective_tier', user.get('tier', 'free')), 0) >= TIERS.get('plus', 1)):
        return JSONResponse({"error": "Plus plan required"}, status_code=403)
    symbol = symbol.upper().strip()
    ALLOWED_INTERVALS = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w"}
    if interval not in ALLOWED_INTERVALS:
        interval = "1h"
    limit = max(10, min(500, limit))
    try:
        import requests as _req
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        resp = await asyncio.to_thread(_req.get, url, timeout=8)
        if resp.status_code != 200:
            return JSONResponse({"candles": [], "error": f"Binance {resp.status_code}"}, status_code=200)
        raw = resp.json()
        candles = [
            {
                "time":   int(k[0]),
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]
        return JSONResponse({"candles": candles, "symbol": symbol, "interval": interval})
    except Exception as exc:
        return JSONResponse({"candles": [], "error": str(exc)}, status_code=200)


@app.get("/mobile", response_class=HTMLResponse)
@app.get("/mobile/{path:path}", response_class=HTMLResponse)
async def mobile_app(path: str = ""):
    """Serve the React mobile app. All sub-routes return index.html (SPA)."""
    mobile_index = Path(__file__).parent.parent / "mobile" / "dist" / "index.html"
    if not mobile_index.exists():
        return HTMLResponse(content="<h1>Mobile app not built yet. Run: cd mobile && npm run build</h1>", status_code=503)
    html = mobile_index.read_text()
    if "<head>" in html:
        html = html.replace("<head>", '<head>\n    <meta name="robots" content="noindex,nofollow">')
    return HTMLResponse(content=html, status_code=200)


@app.get("/{path:path}")
async def catch_all_pairs(path: str):
    path_lower = path.lower()
    if path_lower.endswith("usdt") and "/" not in path:
        return RedirectResponse(url=f"/signals/{path_lower}")
    raise HTTPException(status_code=404, detail="Not Found")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="info")
