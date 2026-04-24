import asyncio
import time
import json
import os
import sys
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

# Strategic & Shared State
from constants import *
from shared_state import *
from ai_auto_healer import exception_handler

# Set the global exception hook for self-healing
sys.excepthook = exception_handler

# Modular Components
from utils_logger import log_message, clear_console
from technical_indicators import *
# signal_generator.py — REMOVED: dead code, none of its functions are called
from data_fetcher import *
from performance_tracker import *
from performance_tracker import emergency_de_risk, _reconcile_sent_signals
from signal_cache_manager import *
from telegram_handler import (
    send_telegram_message, send_closed_signal_message, send_ops_message,
    register_signal, generate_signal_id,
    load_signal_registry,
    setup_telegram_listener
)
from trading_utilities import (
    is_prime_trading_session, check_btc_correlation,
    get_btc_htf_regime, assign_leverage,
    institutional_risk_adjust,
    is_equity_perp, is_us_equity_market_open,
    discover_equity_perps_from_exchange,
)
try:
    from dashboard.copy_trading import execute_copy_trades as _execute_copy_trades
    _COPY_TRADING_AVAILABLE = True
except ImportError:
    _COPY_TRADING_AVAILABLE = False
from signal_quality import calculate_sqi, sqi_to_leverage, sqi_to_size
from predator import (
    detect_regime, analyze_positioning, positioning_aligns,
    detect_stop_hunt, detect_liquidation_magnets, liquidation_aligns,
    REGIME_VOLATILE_CHOP
)
from data_fetcher import analyze_funding_rate_sentiment, get_open_interest_change
from rust_batch_processor import BATCH_PROCESSOR
from kline_stream_manager import KlineStreamManager
from live_price_feed import LIVE_FEED
from cvd_stream_manager import CVD_FEED
from news_monitor import NewsMonitor
from defi_filter import get_defi_tvl_filter, is_defi_token
import trade_memory as _trade_memory
try:
    from usdt_dominance import (
        get_usdt_dominance_state as _get_usdt_d_state,
        long_allowed as _usdt_d_long_allowed,
        short_allowed as _usdt_d_short_allowed,
    )
    _USDT_D_AVAILABLE = True
except Exception as _usdt_d_exc:  # pragma: no cover
    _USDT_D_AVAILABLE = False
    print(f'[main] usdt_dominance module unavailable: {_usdt_d_exc}')

try:
    from pair_macro_indicator import (
        get_pair_macro_state as _get_pair_macro_state,
        long_bias as _pair_macro_long_bias,
    )
    _PAIR_MACRO_AVAILABLE = True
except Exception as _pair_macro_exc:  # pragma: no cover
    _PAIR_MACRO_AVAILABLE = False
    print(f'[main] pair_macro_indicator module unavailable: {_pair_macro_exc}')

# Availability Flags are now managed in shared_state.py
realtime_monitor = None
_kline_manager = None   # WebSocket kline stream for top-20 pairs
_news_monitor = None    # RSS macro news monitor
_last_heartbeat = 0     # watchdog sync

# Global semaphore: 5 concurrent AI (OpenRouter) calls allowed simultaneously.
_AI_SEMAPHORE = asyncio.Semaphore(5)

# Per-pair in-flight guard: prevents duplicate signals from parallel coroutines
# racing through can_send_direction() before either has registered the signal.
_PAIR_IN_FLIGHT: set = set()

# Per-scan-cycle signal governor: max signals per 30s scan (prevents burst flooding)
# Resets at start of each main loop cycle. Does NOT penalise direction.
# IMPORTANT: must use _CYCLE_LOCK to atomically check+increment under async concurrency.
_CYCLE_SIGNALS_SENT: int = 0
CYCLE_SIGNAL_LIMIT: int  = 5
_CYCLE_LOCK = asyncio.Lock()

# Per-pair 1h-bar dedup: with the 30s scan cycle, process_pair() can be invoked
# ~120× per 1h candle. Record the last 1h bar-close timestamp we evaluated for
# each pair and short-circuit repeat calls — signals still fire at most once per
# 1h bar per pair. WS-driven calls on a fresh close naturally bump this forward.
_LAST_BAR_TS_EVALUATED: dict = {}   # pair -> int ms timestamp of last-evaluated 1h bar
_BAR_DEDUP_LOCK = asyncio.Lock()

async def process_pair(pair, timeframe='1h', tv_override=None):
    """
    REVERSE HUNT Strategy — TSI + CE signal pipeline.
    Exclusively uses 1h timeframe for signal generation.
    tv_override: if provided, skip RH engine and use TV's signal direction.
                 dict with keys: 'signal' (LONG|SHORT), 'strategy' (str)
    """
    # Guard: if this pair is already being processed (parallel coroutines),
    # skip immediately to prevent duplicate signals.
    if pair in _PAIR_IN_FLIGHT:
        return

    # ── Permanent Manual Blacklist ─────────────────────────────────────
    if pair in MANUAL_BLACKLIST:
        return

    # ── Equity-Perp Market-Hours Gate ──────────────────────────────────
    # Binance lists perps for US stocks / ETFs whose underlying market is
    # closed on weekends. 1h candles go stale, ATR collapses, and signals
    # placed during the closure use price from days ago. Skip silently.
    if is_equity_perp(pair) and not is_us_equity_market_open():
        return

    _PAIR_IN_FLIGHT.add(pair)
    try:
        # 0. Yield control to event loop at start
        await asyncio.sleep(0.01)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 1: Fetch 1h data — sole timeframe for Reverse Hunt
        # ══════════════════════════════════════════════════════════════════
        df_1h = BATCH_PROCESSOR.get_df(pair, '1h')
        if df_1h is None:
            try:
                df_1h = await asyncio.wait_for(
                    asyncio.to_thread(fetch_data, pair, '1h'), timeout=10.0
                )
            except asyncio.TimeoutError:
                log_message(f"⏱️ fetch_data timeout (10s) for {pair}")
                return
        if df_1h is None or df_1h.empty or len(df_1h) < 200:
            return  # Silent — insufficient data is normal for new listings

        # ── 1h bar-close dedup ────────────────────────────────────────────
        # With a 30s scan cycle the same pair gets re-evaluated ~120× per 1h
        # candle. A TV override always gets through (operator-forced); for
        # normal scans, skip if we've already evaluated this exact 1h bar.
        if tv_override is None:
            try:
                _bar_ts_ms = int(df_1h.index[-1].timestamp() * 1000)
            except Exception:
                _bar_ts_ms = 0
            if _bar_ts_ms and _LAST_BAR_TS_EVALUATED.get(pair) == _bar_ts_ms:
                return  # already evaluated this 1h bar
            if _bar_ts_ms:
                _LAST_BAR_TS_EVALUATED[pair] = _bar_ts_ms

        candle_close  = float(df_1h['close'].iloc[-1])

        # ── Live price via WebSocket feed (markPrice@1s + bookTicker) ────────
        # Primary path: in-memory push feed — zero latency, always-fresh for every
        # symbol. REST fallback covers cold-start (first ~5s) and stream drops.
        # CRITICAL: `has_live_price` MUST be True to fire a signal. Falling back
        # silently to candle_close defeats the drift guard (drift=0 by construction)
        # and has caused multiple stale-entry fake signals (BAKE 1.5985 vs live 0.025).
        live_bid = live_ask = live_spread_bps = None
        live_price = None
        has_live_price = False
        _live_px = LIVE_FEED.get(pair)
        if _live_px is not None:
            live_price      = _live_px['mark']
            _idx            = _live_px['index']
            live_bid        = _live_px['bid']
            live_ask        = _live_px['ask']
            live_spread_bps = _live_px['spread_bps']
            has_live_price  = live_price > 0
            # Mark/Index divergence override (stock tokens off-hours)
            if _idx > 0 and live_price > 0 and abs(_idx - live_price) / live_price > 0.02:
                log_message(f"⚡ Mark/Index Divergence [{pair}]: mark={live_price:.5g} "
                            f"index={_idx:.5g} drift={(abs(_idx-live_price)/live_price*100):.1f}% "
                            f"— overriding with index price")
                live_price = _idx
        else:
            # Fallback: REST mark-price (used only during startup warm-up / WS reconnect)
            try:
                _live = await asyncio.wait_for(
                    asyncio.to_thread(client.futures_mark_price, symbol=pair), timeout=5.0
                )
                _mp = None
                _idx = 0.0
                if isinstance(_live, dict):
                    _mp  = float(_live.get('markPrice') or 0)
                    _idx = float(_live.get('indexPrice') or 0)
                elif isinstance(_live, list) and _live:
                    _mp  = float(_live[0].get('markPrice') or 0)
                    _idx = float(_live[0].get('indexPrice') or 0)
                if _mp and _mp > 0:
                    live_price = _mp
                    has_live_price = True
                    if _idx > 0 and abs(_idx - live_price) / live_price > 0.02:
                        live_price = _idx
            except (Exception, asyncio.TimeoutError):
                pass

        # Hard gate: if we have no real live price, we cannot trust the 1H candle
        # close as entry geometry (it may be days stale on delisted / illiquid pairs).
        # Silently using candle_close would make drift=0 and defeat every guard.
        if not has_live_price or live_price is None or live_price <= 0:
            log_message(f"🚫 {pair}: no live price available (WS+REST both failed) — skipping")
            return

        # ── Spread filter (P1) ── reject when top-of-book is too wide to get a fill.
        # Stock / TradFi perps are more permissive (30 bps) since they’re thinner.
        if live_spread_bps is not None and live_spread_bps > 0:
            _spread_limit = 30.0 if is_equity_perp(pair) else 15.0
            if live_spread_bps > _spread_limit:
                log_message(f"🚫 Wide Spread [{pair}]: {live_spread_bps:.1f} bps > "
                            f"{_spread_limit:.0f} bps limit — skipping (illiquid book)")
                return

        current_price = live_price
        drift_pct = abs(live_price - candle_close) / candle_close * 100 if candle_close > 0 else 0
        if drift_pct > 2.0:
            log_message(f"⚡ Price Drift [{pair}]: candle={candle_close:.5g} live={live_price:.5g} drift={drift_pct:.1f}% — using live price for entry geometry")
        # Entry drift alert: flag signals where the candle close is far from live
        # price so traders can decide — CE hybrid flip still has value even if price
        # moved. Alert shown on Telegram + stored in dashboard features.
        entry_drift_alert = drift_pct > 5.0
        if entry_drift_alert:
            log_message(f"⚠️ Entry Drift Alert [{pair}]: {drift_pct:.1f}% drift (candle={candle_close:.5g} vs live={live_price:.5g}) — signal fires with caution flag")

        precision = await asyncio.to_thread(get_precision, pair)


        # ══════════════════════════════════════════════════════════════════
        #  STEP 2: Reverse Hunt Signal — TSI watch + CE confirmation
        # ══════════════════════════════════════════════════════════════════
        if tv_override is not None:
            # ── TradingView Override: TV confirmed the signal, skip RH engine ──
            final_signal = tv_override['signal'].upper()
            rh_conviction = 0.67  # equivalent to 4/6 RH conviction
            rh_components = {
                'ce_line_flip': True, 'ce_cloud_agree': True,
                'linreg_zero_cross': False, 'extreme_mode': False,
                'tsi_l2_trigger': False, 'tv_signal': True,
            }
            # Compute CE for stop level + SQI inputs
            from reverse_hunt import (
                calculate_tsi, calculate_chandelier_exit,
                CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT, CE_LINE_ATR_LEN,
                CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT,
                CE_CLOUD_SRC, CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK,
                CE_CLOUD_MULT, CE_CLOUD_SMOOTH, CE_CLOUD_WAIT,
            )
            _tsi_s = await asyncio.to_thread(calculate_tsi, df_1h)
            _ce_l  = await asyncio.to_thread(
                calculate_chandelier_exit, df_1h,
                CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT, CE_LINE_ATR_LEN,
                CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT)
            _ce_c  = await asyncio.to_thread(
                calculate_chandelier_exit, df_1h,
                CE_CLOUD_SRC, CE_CLOUD_SRC, CE_CLOUD_ATR_LEN,
                CE_CLOUD_LOOKBACK, CE_CLOUD_MULT, CE_CLOUD_SMOOTH, CE_CLOUD_WAIT)
            _ce_line_dir  = int(_ce_l['direction'].iloc[-1])
            _ce_cloud_dir = int(_ce_c['direction'].iloc[-1])
            _ce_stop = float(_ce_l['long_stop'].iloc[-1] if final_signal == 'LONG' else _ce_l['short_stop'].iloc[-1])
            rh_indicators = {
                'tsi':          float(_tsi_s.iloc[-1]),
                'tsi_zone':     'TV_SIGNAL',
                'ce_line_dir':  _ce_line_dir,
                'ce_cloud_dir': _ce_cloud_dir,
                'linreg':       0.0,
            }
            _tv_ce_stop = _ce_stop  # used below to replace rh_result['levels']
            log_message(
                f"📺 TV SIGNAL [{pair}]: {final_signal} | "
                f"Strategy: {tv_override.get('strategy', 'TradingView')} | "
                f"CE Line: {'LONG' if _ce_line_dir==1 else 'SHORT'} | "
                f"TSI: {rh_indicators['tsi']:.3f}"
            )
        else:
            from reverse_hunt import process_pair as rh_process_pair
            rust_rh = BATCH_PROCESSOR.get_rh(pair, '1h')
            rh_result = await asyncio.to_thread(rh_process_pair, pair, df_1h, rust_rh)

            if rh_result is None:
                return  # No signal — TSI not in extreme or CE hasn't confirmed

            final_signal = rh_result['signal']  # 'LONG' or 'SHORT'
            rh_conviction = rh_result['conviction_pct']
            rh_components = rh_result['components']
            rh_indicators = rh_result['indicators']
            _tv_ce_stop   = None  # not used in normal path

            log_message(
                f"🎯 REVERSE HUNT [{pair}] {final_signal} | "
                f"Conviction: {rh_result['conviction']}/6 ({rh_conviction:.0%}) | "
                f"TSI Zone: {rh_indicators.get('tsi_zone', 'N/A')} | "
                f"CE Line: {'✅' if rh_components.get('ce_line_flip') else '❌'} | "
                f"CE Cloud: {'✅' if rh_components.get('ce_cloud_agree') else '❌'} | "
                f"LR Cross: {'✅' if rh_components.get('linreg_zero_cross') else '❌'} | "
                f"Extreme: {'⚡' if rh_components.get('extreme_mode') else '—'}"
            )

        # ══════════════════════════════════════════════════════════════════
        #  STEP 3: Risk Filters (kept from original pipeline)
        # ══════════════════════════════════════════════════════════════════
        risk_level = MACRO_RISK_ENGINE.state
        _allow_trade, _reason = MACRO_RISK_ENGINE.should_allow_trading()
        if not _allow_trade:
            log_message(f"⚪ No Trade: {pair} — Macro Risk Engine blocked: {_reason}")
            return

        # Circuit Breaker DISABLED — copy trading users share the same global counter.
        # A 3-loss sequence in one session silently blocks signals for ALL subscribers.
        # Risk is managed per-signal via SQI soft floor, institutional_risk_adjust, and Auto-Blacklist.

        is_blacklisted_bl, bl_reason = AUTO_BLACKLIST.is_blacklisted(pair)
        if is_blacklisted_bl:
            log_message(f"⚪ No Trade: {pair} — Blacklisted: {bl_reason}")
            return

        can_trade_cd, cd_reason = PAIR_COOLDOWN.can_send_signal(pair)
        if not can_trade_cd:
            log_message(f"⚪ No Trade: {pair} — Cooldown active: {cd_reason}")
            return

        # ══════════════════════════════════════════════════════════════════
        #  STEP 4: PREDATOR — Regime + Positioning + Stop Hunt
        #
        #  Replaces the old confidence destruction chain.
        #  RH conviction is preserved for logging. SQI v2 drives sizing.
        # ══════════════════════════════════════════════════════════════════

        # ── Layer 1: Regime Detection ──
        pred_regime = detect_regime(df_1h)
        regime_name = pred_regime['regime']
        regime_params = pred_regime['params']

        if not regime_params['allow_entry']:
            log_message(f"🚫 Signal Rejected for {pair}: {regime_params['skip_reason']} "
                        f"(ATR ratio={pred_regime['atr_ratio']}, clarity={pred_regime['trend_clarity']})")
            return

        log_message(
            f"🌍 REGIME [{pair}]: {regime_name} | ATR_ratio={pred_regime['atr_ratio']} | "
            f"Clarity={pred_regime['trend_clarity']} | {pred_regime['vol_state']}/{pred_regime['trend_state']}"
        )

        # ── Layer 2: Positioning (crypto-native) ──
        try:
            funding_analysis = await asyncio.wait_for(
                asyncio.to_thread(analyze_funding_rate_sentiment, pair), timeout=5.0
            )
        except asyncio.TimeoutError:
            funding_analysis = {}
        try:
            oi_data = await asyncio.wait_for(
                asyncio.to_thread(get_open_interest_change, pair), timeout=5.0
            )
        except asyncio.TimeoutError:
            oi_data = None
        positioning = analyze_positioning(funding_analysis, oi_data, df_1h)
        pos_aligned, pos_sqi_score = positioning_aligns(positioning, final_signal)

        _cvd_log = CVD_FEED.get(pair)
        _cvd_str = (f" | cvd_5m={_cvd_log['delta_pct_5m']:+.3f} cvd_1h={_cvd_log['cvd_1h']:+.0f}"
                    if _cvd_log else " | cvd=N/A")
        log_message(
            f"📡 POSITIONING [{pair}]: bias={positioning['positioning_bias']} | "
            f"crowd={positioning['crowd_direction']} | OI={positioning['oi_divergence']} | "
            f"funding={positioning['funding_momentum']:+.2f} | taker_delta={positioning['taker_delta']:+.4f}"
            f"{_cvd_str} | aligned={'✅' if pos_aligned else '❌'} score={pos_sqi_score}/20"
        )

        # ── Layer 3: Stop Hunt Detection ──
        hunt_result = detect_stop_hunt(df_1h)
        if hunt_result['hunt_detected']:
            log_message(
                f"🎯 STOP HUNT [{pair}]: {hunt_result['hunt_type']} | "
                f"wick={hunt_result['wick_ratio']}x | vol={hunt_result['vol_ratio']}x | "
                f"swept={hunt_result['swept_level']}"
            )

        # ── Layer 2b: Liquidation Magnet Detection ──
        liq_magnets = detect_liquidation_magnets(df_1h, current_price)
        liq_aligned, liq_score = liquidation_aligns(liq_magnets, final_signal)

        # Boost positioning score with liquidation magnet data
        pos_sqi_score = min(20, pos_sqi_score + liq_score)

        nearest_above = liq_magnets.get('nearest_above')
        nearest_below = liq_magnets.get('nearest_below')
        if nearest_above or nearest_below:
            above_str = f"↑{nearest_above['distance_pct']}% (d={nearest_above['density']})" if nearest_above else '—'
            below_str = f"↓{nearest_below['distance_pct']}% (d={nearest_below['density']})" if nearest_below else '—'
            log_message(
                f"🧲 LIQ MAGNETS [{pair}]: bias={liq_magnets['magnet_bias']} | "
                f"above={above_str} | below={below_str} | "
                f"aligned={'✅' if liq_aligned else '❌'} boost={liq_score}/10"
            )

        # ── Counter-Flow Trap Gate ────────────────────────────────────────
        # Veto signals where taker flow OPPOSES the signal AND liquidity is
        # misaligned — the combination is a reliable false-positive pattern.
        # Example: LONG with negative taker delta (-0.40) + liq biased SHORT
        # → price hunts the nearby liquidity below before any upside move.
        taker_delta_val = positioning.get('taker_delta', 0.0)
        _is_long = final_signal.upper() == 'LONG'
        _counter_flow = (
            (_is_long and taker_delta_val <= -0.20) or
            (not _is_long and taker_delta_val >= 0.20)
        )
        if _counter_flow and not liq_aligned:
            _liq_below_pct = nearest_below['distance_pct'] if nearest_below else 99.0
            _liq_above_pct = nearest_above['distance_pct'] if nearest_above else 99.0
            _close_liq = (
                (_is_long and _liq_below_pct < 0.5) or
                (not _is_long and _liq_above_pct < 0.5)
            )
            _reason = (
                f"counter-flow trap: taker_delta={taker_delta_val:+.3f} opposes {final_signal} | "
                f"liq_aligned=False | liq_bias={liq_magnets.get('magnet_bias')}"
            )
            if _close_liq:
                _reason += f" | close liq {'below' if _is_long else 'above'} {_liq_below_pct if _is_long else _liq_above_pct:.2f}% — sweep risk"
            log_message(f"🚫 Signal Rejected for {pair}: {_reason}")
            return

        # ── Hard Gates (kept — structural safety) ──
        btc_match, pearson_corr = check_btc_correlation(client, final_signal, pair)
        is_corr_blocked, corr_reason = PORTFOLIO_MANAGER.get_correlation_risk(pair, OPEN_SIGNALS_TRACKER, btc_correlation=pearson_corr)
        if is_corr_blocked:
            log_message(f"🚫 Signal Rejected for {pair}: {corr_reason}")
            return

        # ── Extreme Fear SHORT Gate ───────────────────────────────────────
        # When F&G < 25 (Extreme Fear) the market is at statistical bounce risk.
        # Allow SHORTs only if BTC 1h HTF independently confirms a downtrend.
        # This gate prevented 4 SL hits on 2026-04-13 when all SHORTs fired
        # into a strong bounce from Extreme Fear lows.
        if final_signal.upper() == 'SHORT':
            fear_greed = MACRO_RISK_ENGINE.state.get('fear_greed', 50)
            if fear_greed < 25:
                btc_htf = get_btc_htf_regime(client)
                if btc_htf != 'bearish':
                    log_message(
                        f"🚫 Signal Rejected for {pair}: SHORT suppressed — "
                        f"Extreme Fear (F&G={fear_greed}) without BTC HTF bearish confirmation "
                        f"(BTC HTF={btc_htf.upper()})"
                    )
                    return

        # ── Extreme Greed LONG Gate ───────────────────────────────────────
        # [UPGRADE 2026-04-19 — Directional Symmetry]
        # Mirror of the Extreme Fear SHORT gate to fix the LONG-bias
        # discovered at 9:1 fire ratio. When F&G > 75 (Extreme Greed)
        # the market is at statistical reversion risk. Allow LONGs only
        # if BTC 1h HTF independently confirms an uptrend.
        if final_signal.upper() == 'LONG':
            fear_greed = MACRO_RISK_ENGINE.state.get('fear_greed', 50)
            if fear_greed > 75:
                btc_htf = get_btc_htf_regime(client)
                if btc_htf != 'bullish':
                    log_message(
                        f"🚫 Signal Rejected for {pair}: LONG suppressed — "
                        f"Extreme Greed (F&G={fear_greed}) without BTC HTF bullish confirmation "
                        f"(BTC HTF={btc_htf.upper()})"
                    )
                    return

        # ── 4H HTF Chandelier Exit Direction Gate ─────────────────────────
        # The Apr-18 massacre (-70% to -93% LONGs) all fired against a clear
        # 4H bearish CE. This single gate would have prevented all of them.
        # Uses local SQLite cache first (zero latency), falls back to REST.
        # Fail-open: if 4H data unavailable, don't block signal.
        try:
            from reverse_hunt import calculate_chandelier_exit, CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT, CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT
            _df_4h = await asyncio.wait_for(
                asyncio.to_thread(fetch_data, pair, '4h'), timeout=8.0
            )
            if _df_4h is not None and len(_df_4h) >= 50:
                _ce_4h = await asyncio.to_thread(
                    calculate_chandelier_exit, _df_4h,
                    CE_LINE_SRC_LONG, CE_LINE_SRC_SHORT, CE_LINE_ATR_LEN,
                    CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_SMOOTH, CE_LINE_WAIT
                )
                _ce_4h_dir = int(_ce_4h['direction'].iloc[-1])
                if final_signal.upper() == 'LONG' and _ce_4h_dir != 1:
                    log_message(
                        f"🚫 Signal Rejected for {pair}: 4H CE BEARISH — "
                        f"LONG signal against 4H trend (HTF CE dir={_ce_4h_dir})"
                    )
                    return
                if final_signal.upper() == 'SHORT' and _ce_4h_dir != -1:
                    log_message(
                        f"🚫 Signal Rejected for {pair}: 4H CE BULLISH — "
                        f"SHORT signal against 4H trend (HTF CE dir={_ce_4h_dir})"
                    )
                    return
                log_message(f"✅ 4H CE Gate [{pair}]: dir={_ce_4h_dir} aligns with {final_signal}")
        except (asyncio.TimeoutError, Exception) as _4h_e:
            log_message(f"[4H CE gate] fail-open for {pair}: {_4h_e}")

        # ── Session Gate ──────────────────────────────────────────────────
        # small_cap / high_risk pairs are blocked outside London/NY sessions.
        # mid_cap blocked in dead zone. blue_chip / large_cap always allowed.
        try:
            from trading_sessions import can_trade_session
            from dashboard.market_classifier import get_pair_info as _gpi
            _pair_info = _gpi(pair)
            _pair_tier = _pair_info.get('tier', 'high_risk')
            _sess_ok, _sess_reason = can_trade_session(_pair_tier)
            if not _sess_ok:
                log_message(f"🚫 Signal Rejected for {pair}: Session gate — {_sess_reason}")
                return
        except Exception as _sess_e:
            _pair_tier = 'high_risk'   # conservative fallback
            log_message(f"[session gate] degraded for {pair}: {_sess_e}")

        # ── USDT.D Macro Gate (Systemic Dominance Vector) ─────────────────
        # Pine REVERSE HUNT [MTF reg] on CRYPTOCAP:USDT.D at 1H.
        # TSI(69,9)/14 inverted, LinReg(270,69,39) not inverted.
        # Block LONGs when TSI > +2.1 (GREED_MAX_PAIN — alts already overheated).
        # Block SHORTs when TSI < -1.8 (FEAR_MAX_PAIN — capitulation imminent).
        # Fail-open if module unavailable or not enough history yet.
        if _USDT_D_AVAILABLE:
            try:
                _usdt_d = _get_usdt_d_state()
                if _usdt_d.is_ready:
                    if final_signal.upper() == 'LONG' and _usdt_d.state == 'GREED_MAX_PAIN':
                        log_message(
                            f"🚫 Signal Rejected for {pair}: USDT.D veto LONG — "
                            f"TSI={_usdt_d.tsi_scaled:.2f} > +2.1 (alts overheated, "
                            f"USDT.D={_usdt_d.value_pct:.2f}%)"
                        )
                        return
                    if final_signal.upper() == 'SHORT' and _usdt_d.state == 'FEAR_MAX_PAIN':
                        log_message(
                            f"🚫 Signal Rejected for {pair}: USDT.D veto SHORT — "
                            f"TSI={_usdt_d.tsi_scaled:.2f} < -1.8 (fear peaking, "
                            f"USDT.D={_usdt_d.value_pct:.2f}%)"
                        )
                        return
            except Exception as _usdt_exc:
                log_message(f"[usdt_dominance] gate check degraded: {_usdt_exc}")

        # ── Per-Pair Macro Gate (pair's own 1H TSI/LinReg) ───────────────
        # Pine REVERSE HUNT on the pair itself at 1H.
        # TSI(69,9)/14 NOT inverted, LinReg(278,69,39) INVERTED.
        # Block LONGs when TSI ≥ +2.2 (pair locally overbought → SHORT_MAX_PAIN).
        # Block SHORTs when TSI ≤ -2.2 (pair locally oversold → LONG_MAX_PAIN).
        # This is a "don't fight the local extreme" gate — lets USDT.D handle macro.
        if _PAIR_MACRO_AVAILABLE:
            try:
                _pm = _get_pair_macro_state(pair)
                if _pm.is_ready:
                    if final_signal.upper() == 'LONG' and _pm.state == 'SHORT_MAX_PAIN':
                        log_message(
                            f"🚫 Signal Rejected for {pair}: PAIR macro veto LONG — "
                            f"TSI={_pm.tsi_scaled:.2f} ≥ +2.2 (pair at local top, regime={_pm.lr_regime})"
                        )
                        return
                    if final_signal.upper() == 'SHORT' and _pm.state == 'LONG_MAX_PAIN':
                        log_message(
                            f"🚫 Signal Rejected for {pair}: PAIR macro veto SHORT — "
                            f"TSI={_pm.tsi_scaled:.2f} ≤ -2.2 (pair at local bottom, regime={_pm.lr_regime})"
                        )
                        return
            except Exception as _pm_exc:
                log_message(f"[pair_macro] gate check degraded: {_pm_exc}")

        conviction = rh_conviction  # RH conviction score (0.5–1.0), drives leverage

        # 5. Risk Engines & Liquidity Mapping (Phase 8)
        # Calculate ATR on 1h data for targets
        from technical_indicators import calculate_atr
        df_1h = calculate_atr(df_1h)
        vp_data = await asyncio.to_thread(calculate_volume_profile, df_1h)
        fvg_data = await asyncio.to_thread(calculate_fair_value_gaps, df_1h)
        
        # Use CE stop levels from Reverse Hunt (or TV-computed CE) as primary stop loss
        ce_stop = _tv_ce_stop if _tv_ce_stop is not None else rh_result['levels']['ce_line_stop']
        targets, _default_sl = calculate_technical_targets(df_1h, current_price, final_signal, precision, vp=vp_data, fvg_data=fvg_data)
        atr_val = float(df_1h['ATR'].iloc[-1]) if 'ATR' in df_1h.columns else current_price * 0.02
        atr_pct = atr_val / current_price

        # ── Institutional Risk Adjustment (5-layer hybrid) ────────────────
        # Caps SL, scales TPs for R:R ≥ 2.5:1, penalizes size/leverage on wide stops
        adx_val = float(df_1h['ADX'].iloc[-1]) if 'ADX' in df_1h.columns else 20.0
        risk_adj = institutional_risk_adjust(
            entry=current_price, ce_stop=ce_stop, targets=targets,
            atr=atr_val, signal_direction=final_signal,
            precision=precision, adx=adx_val, df=df_1h
        )
        if risk_adj is None:
            log_message(f"🚫 Signal Rejected for {pair}: R:R < 1.0 after risk adjustment (CE SL={ce_stop:.{precision}f}, entry={current_price:.{precision}f})")
            return

        stop_loss = risk_adj['stop_loss']
        targets = risk_adj['targets']
        _risk_size_mult = risk_adj['size_multiplier']
        _risk_lev_damp = risk_adj['leverage_dampener']

        if risk_adj['sl_capped']:
            log_message(
                f"⚠️ SL Capped [{pair}]: CE={ce_stop:.{precision}f} ({risk_adj['raw_risk_pct']:.1f}%) → "
                f"Adj={stop_loss:.{precision}f} ({risk_adj['adj_risk_pct']:.1f}%) | "
                f"R:R={risk_adj['rr']}:1 | Size×{_risk_size_mult} Lev×{_risk_lev_damp}"
            )
            # ── SL-Capped + Low Volume Gate ───────────────────────────────
            # CE stop was too wide AND volume is below 0.60× average →
            # low-liquidity consolidation; CE signal is noise, not edge.
            if len(df_1h) >= 21 and 'volume' in df_1h.columns:
                _avg_vol_sl = df_1h['volume'].iloc[-21:-1].mean()
                _curr_vol_sl = df_1h['volume'].iloc[-2]
                if _avg_vol_sl > 0 and _curr_vol_sl < 0.60 * _avg_vol_sl:
                    log_message(
                        f"🚫 Signal Rejected for {pair}: SL capped + low volume "
                        f"({_curr_vol_sl:.0f} = {_curr_vol_sl/_avg_vol_sl:.2f}x avg) — noise trap"
                    )
                    return
        else:
            log_message(f"✅ Risk OK [{pair}]: SL={stop_loss:.{precision}f} ({risk_adj['adj_risk_pct']:.1f}%) | R:R={risk_adj['rr']}:1")

        # BUG-2 FIX: Guard against degenerate targets (all targets ≈ entry price)
        if all(abs(t - current_price) / current_price < 0.001 for t in targets):
            log_message(f"🚫 Signal Rejected for {pair}: Degenerate targets (too close to entry)")
            return

        # BUG-3 FIX: Pre-flight TP geometry guard
        # If the live price has already breached ANY target, the signal is structurally
        # invalid: entry is stale and the reconciler will fake-close it immediately.
        if final_signal == 'LONG':
            _pre_hit = [(i+1, tp) for i, tp in enumerate(targets) if current_price >= tp]
        else:
            _pre_hit = [(i+1, tp) for i, tp in enumerate(targets) if current_price <= tp]
        if _pre_hit:
            _tn, _tp = _pre_hit[0]
            log_message(
                f"🚫 Signal Rejected for {pair}: Live price {current_price:.{precision}f} already "
                f"breaches TP{_tn} ({_tp:.{precision}f}) — stale entry, inverted geometry"
            )
            return

        # ── Extension Filter — reject parabolic entries ───────────────
        # Data shows: entries >15% from EMA21 have near-zero win rate
        ema21_val = df_1h['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        ext_pct = abs(current_price - ema21_val) / ema21_val * 100 if ema21_val > 0 else 0
        if ext_pct > 20.0:
            log_message(f"🚫 Signal Rejected for {pair}: Parabolic extension ({ext_pct:.1f}% from EMA21)")
            return
        elif ext_pct > 15.0:
            log_message(f"⚠️ High extension [{pair}]: {ext_pct:.1f}% from EMA21 — SQI will penalize")

        # S4: Volume filter — use previous completed candle on 1h
        if len(df_1h) >= 21 and 'volume' in df_1h.columns:
            avg_vol = df_1h['volume'].iloc[-21:-1].mean()
            curr_vol = df_1h['volume'].iloc[-2]
            if avg_vol > 0 and curr_vol < 0.40 * avg_vol:
                log_message(f"🚫 Signal Rejected for {pair}: Low volume ({curr_vol:.0f} < 40% of avg {avg_vol:.0f})")
                return

        conviction = min(1.0, max(0.0, conviction))

        # AI Robustness Filter — DISABLED
        # Rule-based pipeline (TSI + CE + SQI + PREDATOR) provides sufficient validation.
        deepseek_verdict = 'PROCEED'
        ai_sentiment = {}

        # 6. Signal Execution & Registration
        can_send_lim, remaining = check_daily_signal_limit()
        if not can_send_lim: 
            log_message(f"🚫 Signal Rejected for {pair}: Daily Signal Limit Reached")
            return
            
        can_dir = can_send_direction(pair, final_signal)
        if not can_dir:
            log_message(f"🚫 Signal Rejected for {pair}: Direction already sent recently")
            return

        # S3: Per-cycle signal governor — optimistic fast-fail check (non-authoritative).
        # The authoritative atomic reserve happens just before send_telegram_message below.
        global _CYCLE_SIGNALS_SENT
        if _CYCLE_SIGNALS_SENT >= CYCLE_SIGNAL_LIMIT:
            log_message(f"🚫 Cycle cap reached ({CYCLE_SIGNAL_LIMIT} signals this scan) — {pair} queued for next cycle")
            return

        signal_id = generate_signal_id()
        adj_confidence = adaptive_confidence_adjustment(pair, final_signal, conviction)

        # ── SQI v2: Signal Quality Index + PREDATOR layers ──
        ce_line_str = 'LONG' if rh_indicators.get('ce_line_dir') == 1 else 'SHORT' if rh_indicators.get('ce_line_dir') == -1 else None
        ce_cloud_str = 'LONG' if rh_indicators.get('ce_cloud_dir') == 1 else 'SHORT' if rh_indicators.get('ce_cloud_dir') == -1 else None
        _cvd_data = CVD_FEED.get(pair)
        sqi_result = calculate_sqi(
            df_1h, current_price, stop_loss, targets, final_signal,
            ce_line_dir=ce_line_str, ce_cloud_dir=ce_cloud_str,
            positioning_score=pos_sqi_score, positioning_aligned=pos_aligned,
            regime=regime_name, stop_hunt=hunt_result, pair=pair,
            cvd_data=_cvd_data
        )
        sqi_score = sqi_result['sqi']
        sqi_grade = sqi_result['grade']

        # ── Minimum SQI Gate (Soft Floor) ────────────────────────────────
        # [2026-04-22] SQI v6 rescale: max 182 → 134. D-floor 50 → 37
        # (proportional). Blocks outright garbage signals; allows V-bottoms.
        if sqi_score < 37:
            log_message(
                f"🚫 Signal Rejected for {pair}: SQI below D-floor ({sqi_score}/134, grade={sqi_grade}). "
                f"Flags: [{', '.join(sqi_result['flags'])}]"
            )
            return

        # Base leverage from RH conviction, then SQI + regime + risk adjust
        regime_mult = REGIME_SIZER.calculate_multiplier(risk_level, ai_sentiment)
        base_leverage = assign_leverage(adj_confidence, final_signal, pair)
        base_size = 100

        # SQI-driven leverage and size
        leverage_val = sqi_to_leverage(sqi_score, base_leverage)
        final_size = sqi_to_size(sqi_score, int(base_size * regime_mult))

        # Apply PREDATOR regime size multiplier
        final_size = max(1, int(final_size * regime_params['size_mult']))

        # Apply institutional risk adjustments on top
        final_size = max(1, int(final_size * _risk_size_mult))
        leverage_val = max(2, int(leverage_val * _risk_lev_damp))

        # ── DefiLlama TVL filter (DeFi tokens only) ─────────────────
        # Applied AFTER leverage/size are computed so the dampener actually fires.
        defi_mult = 1.0
        if is_defi_token(pair):
            try:
                defi_result = await get_defi_tvl_filter(pair)
                defi_mult   = defi_result['multiplier']
                if defi_mult < 1.0:
                    leverage_val = max(2, int(leverage_val * defi_mult))
                    final_size   = max(1, int(final_size   * defi_mult))
                    log_message(
                        f"🏦 DeFi TVL filter [{pair}]: {defi_result['verdict']} "
                        f"TVL=${defi_result.get('tvl_now_m',0):.0f}M "
                        f"30d={defi_result.get('pct_30d',0):+.1f}% → size×{defi_mult:.2f}"
                    )
            except Exception as _defi_exc:
                log_message(f"[defi_filter] {pair}: {_defi_exc}")

        sqi_flags = ', '.join(sqi_result['flags']) if sqi_result['flags'] else 'clean'
        log_message(
            f"📊 SQI [{pair}]: {sqi_score}/134 ({sqi_grade}) → {leverage_val}x lev | "
            f"size={final_size}% | regime={regime_name}(×{regime_params['size_mult']}) | "
            f"pos={pos_sqi_score}/20 | hunt={'✅' if hunt_result.get('hunt_detected') else '—'} | "
            f"flags=[{sqi_flags}]"
        )

        
        # ── Cornix-compatible signal format ──────────────────────────────
        # Root-cause fixes for 497 Cornix parse errors:
        #  C1: direction word (LONG/SHORT) must appear explicitly
        #  C2: entry keyword must be Buy: (LONG) or Sell: (SHORT)
        #  C3: targets must be "Target N:" not TP1/TP2
        #  C4: stop must be "Stop:" not SL
        #  C5: max 3 targets — 5 targets cause "prices too far" errors
        #  C6: ATR range ±0.1×ATR (not ±0.3) to keep spread tight
        #  C7: no markdown backticks/bold on price lines — breaks parser

        direction_word  = 'LONG' if final_signal.upper() in ('LONG', 'BUY') else 'SHORT'
        entry_keyword   = 'Buy'  if direction_word == 'LONG' else 'Sell'
        pair_cornix     = pair.replace('USDT', '/USDT')          # SPELLUSDT → SPELL/USDT

        # Entry base = live WebSocket mark price.
        entry_base = current_price

        # Entry zone: ±0.1×ATR (tight enough for Cornix spread check)
        atr_abs    = df_1h['ATR'].iloc[-1] if 'ATR' in df_1h.columns else current_price * 0.003
        entry_low  = round(entry_base - 0.1 * atr_abs, precision)
        entry_high = round(entry_base + 0.1 * atr_abs, precision)

        # 3 targets only
        targets_3    = targets[:3] if len(targets) >= 3 else targets
        target_lines = "\n".join([f"Target {i+1}: {t:.{precision}f}" for i, t in enumerate(targets_3)])

        direction_emoji = '🚀' if direction_word == 'LONG' else '📉'
        # Cornix price sanity check: for SHORT → stop > entry > targets
        # for LONG → targets > entry > stop
        if direction_word == 'SHORT':
            targets_3 = sorted(targets_3, reverse=True)  # highest first for SHORT
            if not (stop_loss > entry_high and entry_low > targets_3[-1]):
                log_message(f"⚠️ Price order fix for {pair} SHORT: SL={stop_loss} entry={entry_low}-{entry_high} T={targets_3}")
                if stop_loss <= entry_high:
                    stop_loss = round(entry_high + 0.2 * atr_abs, precision)
            # HARD REJECT: entry is below all TPs — signal is upside-down
            if targets_3 and entry_high < targets_3[-1]:
                log_message(
                    f"🚫 Signal Rejected for {pair}: Entry zone ({entry_low:.{precision}f}-{entry_high:.{precision}f}) "
                    f"is below all TPs [{', '.join(f'{t:.{precision}f}' for t in targets_3)}] — "
                    f"price moved past targets before signal fired."
                )
                return
        else:
            targets_3 = sorted(targets_3)  # lowest first for LONG
            if not (targets_3[-1] > entry_low and entry_low > stop_loss):
                log_message(f"⚠️ Price order fix for {pair} LONG: SL={stop_loss} entry={entry_low}-{entry_high} T={targets_3}")
                if stop_loss >= entry_low:
                    stop_loss = round(entry_low - 0.2 * atr_abs, precision)
            # HARD REJECT: entry is above all TPs — price already blew through targets
            if targets_3 and entry_low > targets_3[-1]:
                log_message(
                    f"🚫 Signal Rejected for {pair}: Entry zone ({entry_low:.{precision}f}-{entry_high:.{precision}f}) "
                    f"is above all TPs [{', '.join(f'{t:.{precision}f}' for t in targets_3)}] — "
                    f"price moved past targets before signal fired."
                )
                return


        target_lines = "\n".join([f"Target {i+1}: {t:.{precision}f}" for i, t in enumerate(targets_3)])

        # ── Tradable-entry guard (P1) ─────────────────────────────
        # Compare our computed entry against the *tradable* top-of-book price:
        #   LONG  fills at ASK (market buy)
        #   SHORT fills at BID (market sell)
        # 30 bps deviation → alert flag (not rejection). TP1 already blown → still reject.
        if live_bid is not None and live_ask is not None and live_bid > 0 and live_ask > 0:
            tradable = live_ask if final_signal == 'LONG' else live_bid
            entry_dev_bps = abs(tradable - current_price) / current_price * 10_000
            if entry_dev_bps > 30.0:
                log_message(
                    f"⚠️ Entry Deviation [{pair}]: computed={current_price:.{precision}f} "
                    f"tradable_{('ask' if final_signal == 'LONG' else 'bid')}={tradable:.{precision}f} "
                    f"({entry_dev_bps:.0f} bps) — CE signal valid, firing with deviation alert"
                )
                # Fold into drift alert so the banner picks it up below
                if not entry_drift_alert:
                    entry_drift_alert = True
                    drift_pct = entry_dev_bps / 100  # convert bps→% for banner
            if targets_3:
                _tp1 = targets_3[0]
                if final_signal == 'LONG' and tradable >= _tp1:
                    log_message(
                        f"🚫 Signal Rejected for {pair}: ask {tradable:.{precision}f} "
                        f"≥ TP1 {_tp1:.{precision}f} — already past target"
                    )
                    return
                if final_signal == 'SHORT' and tradable <= _tp1:
                    log_message(
                        f"🚫 Signal Rejected for {pair}: bid {tradable:.{precision}f} "
                        f"≤ TP1 {_tp1:.{precision}f} — already past target"
                    )
                    return
        else:
            # Live feed unavailable for this symbol — use legacy 1m-kline guard.
            try:
                _fk = await asyncio.wait_for(
                    asyncio.to_thread(client.futures_klines, symbol=pair, interval='1m', limit=3),
                    timeout=5.0
                )
                if _fk and targets_3:
                    _fk_hi = max(float(k[2]) for k in _fk)
                    _fk_lo = min(float(k[3]) for k in _fk)
                    _tp1   = targets_3[0]
                    if final_signal == 'LONG' and _fk_hi >= _tp1:
                        log_message(f"🚫 {pair}: 1m high {_fk_hi:.{precision}f} ≥ TP1 {_tp1:.{precision}f}")
                        return
                    if final_signal == 'SHORT' and _fk_lo <= _tp1:
                        log_message(f"🚫 {pair}: 1m low {_fk_lo:.{precision}f} ≤ TP1 {_tp1:.{precision}f}")
                        return
            except Exception as _fk_err:
                log_message(f"[entry_guard] 1m fallback check skipped for {pair}: {_fk_err}")

        # ── Build Telegram message (after all guards so drift flag is final) ──
        _drift_banner = (
            f"\n⚠️ ENTRY DRIFT ALERT: Price moved {drift_pct:.1f}% from candle close."
            f"\n   Candle close: {candle_close:.{precision}f} → Live: {current_price:.{precision}f}"
            f"\n   CE signal is valid but entry zone has shifted. Manual review advised.\n"
        ) if entry_drift_alert else ""

        msg = (
            f"{direction_word} #{pair_cornix} {direction_emoji}\n"
            f"Exchanges: Binance Futures\n"
            f"Leverage: Cross {leverage_val}x\n"
            f"{entry_keyword}: {entry_low:.{precision}f} - {entry_high:.{precision}f}\n\n"
            f"{target_lines}\n\n"
            f"Stop: {stop_loss:.{precision}f}\n\n"
            f"— ALADDIN INSIGHTS —\n"
            f"🆔 {signal_id[:8]} | SQI: {sqi_score}/134 ({sqi_grade}) | Size: {final_size}%\n"
            f" {regime_name} | Corr: {pearson_corr:.2f}\n"
            f"📊 TSI: {rh_indicators.get('tsi', 0):.2f} | CE: {'🟢' if rh_indicators.get('ce_line_dir') == 1 else '🔴'} | OI: {positioning['oi_divergence']}\n"
            f"⚖️ R:R {risk_adj['rr']}:1 | Risk: {risk_adj['adj_risk_pct']:.1f}%{' (capped)' if risk_adj['sl_capped'] else ''}"
            f"{_drift_banner}"
            f"\n\nDeveloped & hosted by skytech.mk"
        )

        # ── Atomic cycle-cap reservation (race-safe) ──────────────────
        # Under async concurrency with Semaphore(15), multiple pairs can pass the
        # optimistic pre-check simultaneously. Serialize the commit path with a lock.
        async with _CYCLE_LOCK:
            if _CYCLE_SIGNALS_SENT >= CYCLE_SIGNAL_LIMIT:
                log_message(f"🚫 Cycle cap reached ({CYCLE_SIGNAL_LIMIT} signals this scan) — {pair} dropped at commit gate")
                return
            _CYCLE_SIGNALS_SENT += 1  # Reserve slot BEFORE send to prevent burst

        # Re-enabled: Automatic signal broadcasts to Telegram
        try:
            msg_id = await asyncio.wait_for(send_telegram_message(msg), timeout=15.0)
        except asyncio.TimeoutError:
            async with _CYCLE_LOCK:
                _CYCLE_SIGNALS_SENT = max(0, _CYCLE_SIGNALS_SENT - 1)  # release reserved slot
            log_message(f"⏱️ Telegram send timeout (15s) for {pair} — signal slot released")
            return

        # Post-send Housekeeping
        increment_daily_signal_count()
        PAIR_COOLDOWN.record_signal(pair)  # P0 Fix: was never called, cooldown was broken
        
        # Capture features for learning
        # BUG FIX: numpy.float64/int64 fail isinstance(v,(int,float)) → features_json was always empty.
        # Convert numpy scalars to native Python types before filtering.
        feature_snapshot = {}
        for k, v in df_1h.iloc[-1].to_dict().items():
            if isinstance(v, (np.integer, np.floating)):
                v = float(v)
            if isinstance(v, (int, float, bool, str)) and len(str(v)) < 100:
                feature_snapshot[k] = v

        # Enrich with SQI v2 + PREDATOR data for analytics attribution
        feature_snapshot['sqi_score'] = sqi_score
        feature_snapshot['sqi_grade'] = sqi_grade
        feature_snapshot['rr_ratio'] = risk_adj['rr']
        feature_snapshot['sl_capped'] = risk_adj['sl_capped']
        feature_snapshot['risk_pct'] = risk_adj['adj_risk_pct']
        feature_snapshot['ext_from_ema21'] = round(ext_pct, 2)
        for fname, fdata in sqi_result['factors'].items():
            feature_snapshot[f'sqi_{fname}'] = fdata['score']
            feature_snapshot[f'sqi_{fname}_val'] = fdata['value']

        # Entry drift metadata — for dashboard alert badge and post-mortem attribution
        feature_snapshot['entry_drift_pct']   = round(drift_pct, 2)
        feature_snapshot['entry_drift_alert']  = entry_drift_alert
        feature_snapshot['candle_close_price'] = round(float(candle_close), 8)

        # [Phase 6] Persist ML Ultra payload for /explain + Ultra dashboard widget.
        # Strings kept short (<100 chars) to pass the snapshot filter above.
        _ml_factor = sqi_result['factors'].get('ml_ensemble', {}) or {}
        if _ml_factor.get('probs_calibrated') is not None:
            try:
                _pc = _ml_factor['probs_calibrated']
                feature_snapshot['ml_prob_short']    = round(float(_pc[0]), 4)
                feature_snapshot['ml_prob_neutral']  = round(float(_pc[1]), 4)
                feature_snapshot['ml_prob_long']     = round(float(_pc[2]), 4)
                _ci_lo = _ml_factor.get('ci_low'); _ci_hi = _ml_factor.get('ci_high')
                if _ci_lo is not None and _ci_hi is not None:
                    feature_snapshot['ml_ci_low']  = round(float(_ci_lo), 4)
                    feature_snapshot['ml_ci_high'] = round(float(_ci_hi), 4)
                feature_snapshot['ml_prediction_set'] = ','.join(_ml_factor.get('prediction_set') or [])
                _shap = _ml_factor.get('shap_top') or []
                if _shap:
                    feature_snapshot['ml_shap_top'] = ';'.join(
                        f"{s['feature']}:{s['contribution']:+.3f}" for s in _shap[:3]
                    )[:95]
                _txt = _ml_factor.get('text_explanation', '') or ''
                if _txt:
                    # Trim markdown for safe storage; keep compact.
                    feature_snapshot['ml_explain'] = _txt.replace('*', '').replace('`', '')[:95]
            except Exception:
                pass

        # PREDATOR data
        feature_snapshot['pred_regime'] = regime_name
        feature_snapshot['pred_atr_ratio'] = pred_regime['atr_ratio']
        feature_snapshot['pred_trend_clarity'] = pred_regime['trend_clarity']
        feature_snapshot['pred_oi_divergence'] = positioning['oi_divergence']
        feature_snapshot['pred_funding_mom'] = positioning['funding_momentum']
        feature_snapshot['pred_taker_delta'] = positioning['taker_delta']
        feature_snapshot['pred_crowd_dir'] = positioning['crowd_direction']
        feature_snapshot['pred_pos_aligned'] = pos_aligned
        feature_snapshot['pred_pos_score'] = pos_sqi_score
        feature_snapshot['pred_hunt'] = hunt_result.get('hunt_type')
        feature_snapshot['pred_hunt_wick'] = hunt_result.get('wick_ratio', 0)
        feature_snapshot['pred_regime_size_mult'] = regime_params['size_mult']
        feature_snapshot['pred_liq_bias'] = liq_magnets.get('magnet_bias')
        feature_snapshot['pred_liq_score'] = liq_score
        feature_snapshot['pred_liq_aligned'] = liq_aligned
        feature_snapshot['pred_liq_nearest_above'] = nearest_above['distance_pct'] if nearest_above else None
        feature_snapshot['pred_liq_nearest_below'] = nearest_below['distance_pct'] if nearest_below else None

        # USDT.D macro state attribution (for analytics and post-mortem)
        if _USDT_D_AVAILABLE:
            try:
                _usdt_d_snap = _get_usdt_d_state()
                feature_snapshot['usdt_d_value']  = _usdt_d_snap.value_pct
                feature_snapshot['usdt_d_tsi']    = _usdt_d_snap.tsi_scaled
                feature_snapshot['usdt_d_linreg'] = _usdt_d_snap.linreg
                feature_snapshot['usdt_d_state']  = _usdt_d_snap.state
                feature_snapshot['usdt_d_ready']  = _usdt_d_snap.is_ready
            except Exception:
                pass

        # Per-pair macro state (2H, Pine REVERSE HUNT with pair-side params)
        # Used alongside USDT.D for two-layer macro confirmation.
        if _PAIR_MACRO_AVAILABLE:
            try:
                _pm = _get_pair_macro_state(pair)
                feature_snapshot['pair_macro_tsi']    = _pm.tsi_scaled
                feature_snapshot['pair_macro_linreg'] = _pm.linreg
                feature_snapshot['pair_macro_state']  = _pm.state
                feature_snapshot['pair_macro_regime'] = _pm.lr_regime
                feature_snapshot['pair_macro_ready']  = _pm.is_ready
                feature_snapshot['pair_macro_long_bias'] = _pair_macro_long_bias(pair)
            except Exception:
                pass

        register_signal(signal_id, pair, final_signal, current_price, adj_confidence, targets, stop_loss, leverage_val, features=feature_snapshot, telegram_message_id=msg_id)

        # ── Copy-Trading: Execute for all active Pro+ users ────────────
        if _COPY_TRADING_AVAILABLE:
            try:
                await _execute_copy_trades({
                    'signal_id': signal_id, 'pair': pair,
                    'direction': final_signal, 'price': current_price,
                    'targets': targets, 'stop_loss': stop_loss,
                    'leverage': leverage_val,
                    'sqi_score': sqi_score,
                    'sqi_grade': sqi_grade,
                })
            except Exception as _ct_exc:
                log_message(f"[copy_trading] execution error: {_ct_exc}")

        # ── Store signal in ChromaDB trade memory ─────────────────────────
        try:
            _trade_memory.store_signal(
                signal_id=signal_id, pair=pair, signal=final_signal,
                regime=regime_name,
                rsi=float(df_1h['RSI_14'].iloc[-1]) if 'RSI_14' in df_1h.columns else 50.0,
                tsi=float(rh_indicators.get('tsi', 0)),
                atr_pct=float(feature_snapshot.get('atr_pct', 0)),
                sqi=sqi_score, ce_dir=ce_line_str or 'UNKNOWN',
                entry=current_price, targets=targets, stop=stop_loss,
                extra={'leverage': leverage_val, 'size': final_size,
                       'pearson': round(pearson_corr, 2)}
            )
        except Exception as _mem_exc:
            log_message(f"[trade_memory] store error: {_mem_exc}")

        add_open_signal(signal_id, pair, final_signal, current_price,
                         stop_loss=stop_loss, targets=targets, leverage=leverage_val)
        
        # realtime_monitor disabled — reconciler handles signal closures
            
    except Exception as e:
        log_message(f"Error in process_pair for {pair}: {e}")
    finally:
        _PAIR_IN_FLIGHT.discard(pair)

# emergency_de_risk is imported from performance_tracker (the real implementation
# that actually closes positions via Binance API). The stub that was here before
# only sent a Telegram message and set regime state, which is now handled
# inside the performance_tracker version.

async def main_async():
    """Central Automation Engine"""
    import concurrent.futures
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=100))
    clear_console()
    log_message("Initializing Aladdin Modular Architecture...")
    
    # 1. Boot up modules
    load_signal_registry()
    load_performance_data()
    load_open_signals_tracker()
    initialize_cache_system()

    # Expand the equity-perp gate set from Binance exchangeInfo so any
    # newly-listed stock/ETF perp is skipped on weekends/holidays too.
    try:
        await asyncio.to_thread(discover_equity_perps_from_exchange, client)
    except Exception as _exc:
        log_message(f"[equity-gate] startup discovery skipped: {_exc}")
    
    # Note: Telegram Listener has been decoupled to telegram_service.py
    
    # RealTimeSignalMonitor DISABLED — caused Telegram floods on restart
    # (sent 30+ TP/SL notifications simultaneously for all backlogged signals).
    # Signal closures are handled by _reconcile_sent_signals (DB + feedback loops).
    # Per-pair WS connections it opened are also redundant with KlineStreamManager.
    global realtime_monitor
    realtime_monitor = None

    log_message("System Online. Starting Market Surveillance...")
    
    last_status_report = time.time()
    last_phase7_check = time.time()
    last_reconcile    = 0.0   # reconcile signals every 5 min
    _last_ml_retrain = time.time() - 82800   # trigger ~1h after startup (not immediately)
    
    # Concurrency primitives — 30 concurrent pairs (proxy pool distributes IP load)
    semaphore = asyncio.Semaphore(30)
    _pair_error_tracker = {}
    _pair_suspended_until = {}
    
    global _last_heartbeat
    _last_heartbeat = time.time()
    
    async def watchdog_task():
        global _last_heartbeat
        while True:
            await asyncio.sleep(60)
            if time.time() - _last_heartbeat > 900: # 15 mins
                log_message("⚠️ WARNING: Main loop heartbeat stale >15 mins!")
                try:
                    await send_ops_message("⚠️ **SYSTEM ALERT**\nMain loop may be stuck. Last heartbeat >15 minutes ago.")
                except:
                    pass
                _last_heartbeat = time.time()
                
    asyncio.create_task(watchdog_task())

    # ── ML Autotraining coroutine ──────────────────────────────────────────
    async def _run_ml_autotraining():
        """
        Launch ml_engine_archive/train.py as a background subprocess every 24h.
        Uses --skip-download so it reuses cached Binance data, --epochs 25 for
        speed. Runs non-blocking so the main scan loop is never paused.
        """
        nonlocal _last_ml_retrain
        _last_ml_retrain = time.time()   # stamp BEFORE to avoid re-trigger on error
        try:
            log_message("🤖 ML Auto-Retrain: starting background training...")
            await send_ops_message("🤖 **ML Auto-Retrain Started**\nTraining BiLSTM+TFT+XGBoost+LightGBM ensemble in background (this takes ~20min).")
            proc = await asyncio.create_subprocess_exec(
                "/root/miniconda3/bin/python3", "-m", "ml_engine_archive.train",
                "--skip-download", "--epochs", "25", "--pairs", "20",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA",
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=7200)  # 2h max
            if proc.returncode == 0:
                log_message("✅ ML Auto-Retrain: completed successfully")
                await send_ops_message("✅ **ML Auto-Retrain Complete**\nModels updated. New weights will be used on next signal.")
            else:
                tail = stdout[-2000:].decode(errors='replace') if stdout else ''
                log_message(f"⚠️ ML Auto-Retrain: non-zero exit {proc.returncode}\n{tail}")
                await send_ops_message(f"⚠️ **ML Auto-Retrain Warning**\nExit code {proc.returncode}. Check logs.")
        except asyncio.TimeoutError:
            log_message("⚠️ ML Auto-Retrain: exceeded 2h timeout, killed")
        except Exception as _mle:
            log_message(f"⚠️ ML Auto-Retrain error: {_mle}")

    # ── TradingView Signal Queue Processor ─────────────────────────────────────
    _TV_ALERTS_DB = os.path.join(os.path.dirname(__file__), 'tv_alerts.db')

    _tv_last_cleanup = 0  # track last row-pruning time

    async def tv_queue_processor():
        """Poll tv_alerts.db every 60s for unprocessed TradingView alerts."""
        nonlocal _tv_last_cleanup
        await asyncio.sleep(15)  # let boot settle first
        while True:
            try:
                if os.path.exists(_TV_ALERTS_DB):
                    # ── Read pending rows (connection guarded) ──────────────
                    conn = sqlite3.connect(_TV_ALERTS_DB)
                    try:
                        rows = conn.execute(
                            "SELECT id, symbol, action, strategy FROM tv_alerts "
                            "WHERE processed=0 ORDER BY received ASC LIMIT 10"
                        ).fetchall()
                    finally:
                        conn.close()

                    for row_id, symbol, action, strategy in rows:
                        direction = None
                        if action.upper() in ('BUY', 'LONG', 'BUY_LONG'):
                            direction = 'LONG'
                        elif action.upper() in ('SELL', 'SHORT', 'SELL_SHORT'):
                            direction = 'SHORT'
                        result_str = 'SKIP: unknown action'
                        if direction:
                            try:
                                await process_pair(
                                    symbol.upper(),
                                    tv_override={'signal': direction, 'strategy': strategy or 'TradingView'}
                                )
                                result_str = 'PROCESSED'
                            except Exception as _tv_e:
                                result_str = f'ERROR: {_tv_e}'
                                log_message(f'⚠️ TV queue error for {symbol}: {_tv_e}')
                        # ── Write result (guarded) ──────────────────────────
                        conn2 = sqlite3.connect(_TV_ALERTS_DB)
                        try:
                            conn2.execute(
                                "UPDATE tv_alerts SET processed=1, result=? WHERE id=?",
                                (result_str, row_id)
                            )
                            conn2.commit()
                        finally:
                            conn2.close()
                        await asyncio.sleep(2)

                    # ── Periodic cleanup: delete processed rows >7 days ─────
                    now_t = time.time()
                    if now_t - _tv_last_cleanup > 86400:  # once per day
                        _tv_last_cleanup = now_t
                        conn3 = sqlite3.connect(_TV_ALERTS_DB)
                        try:
                            deleted = conn3.execute(
                                "DELETE FROM tv_alerts WHERE processed=1 "
                                "AND received < datetime('now', '-7 days')"
                            ).rowcount
                            conn3.commit()
                            if deleted:
                                log_message(f"[tv_queue] Pruned {deleted} old processed alerts from DB")
                        finally:
                            conn3.close()

            except Exception as _tv_loop_e:
                log_message(f'TV queue processor error: {_tv_loop_e}')
            await asyncio.sleep(60)

    asyncio.create_task(tv_queue_processor())

    # ── WebSocket kline stream for ALL pairs ────────────────────────────
    global _kline_manager
    _kline_manager = KlineStreamManager(process_pair, top_n=1500)  # stream ALL pairs via WS
    _kline_stream_started = False

    # ── NEWS MONITOR: RSS macro surveillance ─────────────────────────────
    global _news_monitor
    _news_monitor = NewsMonitor(send_ops_message)
    asyncio.create_task(_news_monitor.run())

    # ── Funding rate + OI cache refresh (Phase 1 ML feature feed) ────────
    try:
        from funding_oi_cache import periodic_refresh as _funding_oi_refresh
        from data_fetcher import fetch_trading_pairs as _fto_pairs
        asyncio.create_task(_funding_oi_refresh(_fto_pairs, interval_sec=600))
        log_message("📊 Funding/OI cache refresher started (10min interval)")
    except Exception as _fo_err:
        log_message(f"Funding/OI refresher not started: {_fo_err}")

    async def semaphore_process(p, current_time):
        if _pair_suspended_until.get(p, 0) > current_time:
            return
            
        async with semaphore:
            try:
                await process_pair(p)
                _pair_error_tracker[p] = 0 # reset on success
            except Exception as e:
                _pair_error_tracker[p] = _pair_error_tracker.get(p, 0) + 1
                if _pair_error_tracker[p] >= 3:
                    log_message(f"🚨 Suspending pair {p} for 30m due to repeated errors: {e}")
                    asyncio.create_task(send_ops_message(f"🚨 **Auto-Suspension**\nPair `{p}` suspended for 30m (3 consecutive errors).\nLast error: `{e}`"))
                    _pair_suspended_until[p] = current_time + 1800
                    _pair_error_tracker[p] = 0
                else:
                    log_message(f"Error in parallel processing of {p} (strike {_pair_error_tracker[p]}): {e}")
    
    while True:
        try:
            global _CYCLE_SIGNALS_SENT
            cycle_start = time.time()
            current_time = time.time()
            _last_heartbeat = current_time
            _CYCLE_SIGNALS_SENT = 0  # Reset per-cycle signal counter
            
            # Phase 7: Black Swan Surveillance (Every 30m)
            if current_time - last_phase7_check >= 1800:
                log_message("🔎 Running Systemic Fragility Tests...")
                
                # AI Surveillance
                try:
                    fragility = OPENROUTER_INTEL.analyze_systemic_fragility("Recent market trends and high-volatility events")
                except Exception as e:
                    log_message(f"Systemic fragility check failed: {e}")
                    fragility = {"severity": "MODERATE", "fragility_score": 0.5, "risk_level": "moderate"}
                
                if fragility.get('severity') == 'CRITICAL':
                    await emergency_de_risk(severity="CRITICAL")
                elif fragility.get('severity') == 'HIGH':
                    await emergency_de_risk(severity="HIGH")

                last_phase7_check = current_time

            # Signal Reconciliation — runs every 5 min (independent of Phase 7)
            # Uses kline HIGH/LOW since signal open to catch any SL/TP hits the
            # real-time monitor might have missed (e.g. before monitor started).
            if current_time - last_reconcile >= 300:  # 5 min
                try:
                    await asyncio.to_thread(_reconcile_sent_signals)
                except Exception as _re:
                    log_message(f"Signal reconciliation error: {_re}")
                # Dynamic Trailing SL — compute + persist + fan-out
                # (Telegram announcements + copy-trade SL propagation on Binance)
                try:
                    from trailing_engine import run_trailing_cycle
                    _n_trailed = await run_trailing_cycle()
                    if _n_trailed:
                        log_message(f"[trailing] {_n_trailed} SL ratchet(s) applied this cycle")
                except Exception as _te:
                    log_message(f"[trailing] cycle error: {_te}")
                last_reconcile = current_time

            # Periodic Reporting & Maintenance
            if cycle_start - last_status_report >= 21600: # 6h
                # DISABLED: Automatic daily summary broadcasts to Telegram
                # daily_summary = generate_daily_summary(DAILY_SIGNAL_COUNTER['count'], CIRCUIT_BREAKER, AUTO_BLACKLIST, MACRO_RISK_ENGINE)
                # await send_closed_signal_message(daily_summary) # Move from main to closed channel
                last_status_report = cycle_start

            # ── ML Auto-Retrain (every 24h, runs as background subprocess) ──
            if cycle_start - _last_ml_retrain >= 86400:
                asyncio.create_task(_run_ml_autotraining())
            
            # 1. Market Scanning (Non-blocking Parallelism)
            pairs = await asyncio.to_thread(fetch_trading_pairs)
            # Update macro risk metrics ONCE per cycle (not inside each process_pair)
            MACRO_RISK_ENGINE.update_risk_metrics(client)

            # ── Start / update kline stream after first pair fetch ────────
            if not _kline_stream_started and pairs:
                active_pairs = [p for p in pairs if _pair_suspended_until.get(p, 0) <= current_time]

                # Start WS and LiveFeed FIRST — they connect in ~5s.
                # The blocking REST prefetch used to take ~90s here; we now run
                # it in the background so the first scan cycle starts immediately.
                # process_pair's `len(df) < 200` guard silently skips pairs with
                # no cache yet — they'll be ready within 1-2 min.
                _kline_manager.update_pairs(pairs)
                asyncio.create_task(_kline_manager.run(pairs))
                log_message(f"🚀 KlineStream started for top {_kline_manager.top_n} pairs")

                asyncio.create_task(LIVE_FEED.run())
                log_message("🚀 LivePriceFeed started (markPrice@1s + bookTicker) — all symbols")

                asyncio.create_task(CVD_FEED.run(pairs))
                log_message(f"🚀 CVDFeed started (aggTrade CVD) — {len(pairs)} pairs")

                # Background REST prefetch — fills historical candle cache for
                # all 3 execution timeframes (15m, 1h, 4h) while WS is already
                # streaming live closes. 1h is loaded first (primary signal TF);
                # 15m and 4h are loaded after as "parked" data ready for future
                # entry-refinement and regime-filter work.
                async def _bg_prefetch(ap):
                    log_message(f"⏳ Background REST prefetch: {len(ap)} pairs × [1h,15m,4h] (non-blocking)...")
                    _t0 = time.time()
                    await BATCH_PROCESSOR.prefetch(ap, '1h', fetch_data)
                    log_message(f"✅ 1h prefetch complete — {len(ap)} pairs in {time.time()-_t0:.1f}s")
                    _t0 = time.time()
                    await BATCH_PROCESSOR.prefetch(ap, '15m', fetch_data)
                    log_message(f"✅ 15m prefetch complete — {len(ap)} pairs in {time.time()-_t0:.1f}s (parked)")
                    _t0 = time.time()
                    await BATCH_PROCESSOR.prefetch(ap, '4h',  fetch_data)
                    log_message(f"✅ 4h prefetch complete — {len(ap)} pairs in {time.time()-_t0:.1f}s (parked)")
                asyncio.create_task(_bg_prefetch(active_pairs))

                _kline_stream_started = True
            elif pairs:
                _kline_manager.update_pairs(pairs)
                CVD_FEED.update_pairs(pairs)

            # Filter suspended pairs
            active_pairs = [p for p in pairs if _pair_suspended_until.get(p, 0) <= current_time]
            ws_pairs = set(_kline_manager._active_pairs) if _kline_manager else set()
            suspended_count = len(pairs) - len(active_pairs)

            # ── TV Screener pre-sort: priority pairs (RSI extremes / vol spike) first ──
            try:
                from tv_screener import get_tv_priority_pairs
                active_pairs = get_tv_priority_pairs(active_pairs)
            except Exception as _tv_err:
                pass  # TV unavailable — scan all pairs in default order

            if suspended_count > 0:
                log_message(f"📡 {len(active_pairs)} pairs scanning (WS={len(ws_pairs)} active, {suspended_count} suspended)")
            
            # NOTE: We no longer call BATCH_PROCESSOR.prefetch() in this loop.
            # WebSockets (kline_stream_manager) handle data ingestion and Rust calculation dynamically.

            # ── Proxy-pool batch prefetch: parallel HTTP for pairs missing WS data ───────
            # Pairs on WebSocket already have fresh data in BATCH_PROCESSOR — skip those.
            # For the rest, fire 30 parallel raw HTTP requests (each on a different proxy IP)
            # so ALL pairs have fresh klines before signal processing begins.
            try:
                from data_fetcher import fetch_data_batch as _fetch_batch
                import pandas as _pd
                # Re-fetch pairs that either have NO cached data OR whose last
                # candle is > 2 h old.  Pairs outside the WebSocket top-N never
                # receive live updates, so without this they retain the initial
                # prefetched data forever — causing signals to fire on 5-day-old
                # prices (root cause of CAKE 1.59 / TSLA 367 fake-entry bugs).
                _now_ts = _pd.Timestamp.utcnow().tz_localize(None)
                _stale_delta = _pd.Timedelta(hours=2)
                _pairs_need_http = []
                for p in active_pairs:
                    _df = BATCH_PROCESSOR.get_df(p, '1h')
                    if _df is None or _df.empty:
                        _pairs_need_http.append(p); continue
                    _last = _df.index[-1]
                    if getattr(_last, 'tzinfo', None) is not None:
                        _last = _last.tz_localize(None)
                    if _now_ts - _last > _stale_delta:
                        _pairs_need_http.append(p)
                if _pairs_need_http:
                    _t0 = time.time()
                    # Use BATCH_PROCESSOR.prefetch so both the DB cache AND the
                    # in-memory _df_cache / Rust _rh_cache are refreshed. A raw
                    # _fetch_batch only updates the DB — leaving process_pair
                    # reading stale data from memory.
                    await BATCH_PROCESSOR.prefetch(_pairs_need_http, '1h', fetch_data)
                    log_message(
                        f"⚡ Stale refresh: {len(_pairs_need_http)} pairs "
                        f"in {time.time()-_t0:.1f}s (BATCH_PROCESSOR updated)"
                    )
            except Exception as _pf_err:
                log_message(f"Batch prefetch skipped: {_pf_err}")

            # Process ALL active pairs every cycle using CACHED data
            tasks = [semaphore_process(p, current_time) for p in active_pairs]
            await asyncio.gather(*tasks)
            
            # ── Cycle Summary: show what the bot sees ──
            from reverse_hunt import get_pair_status, get_tsi_zone, compute_adaptive_levels, calculate_tsi, LEVEL_OB_L1, LEVEL_OB_L2
            zone_counts = {'OB_L2': [], 'OB_L1': [], 'OS_L1': [], 'OS_L2': [], 'neutral': []}
            ce_long = 0
            ce_short = 0
            _seen_zone = set()
            for p in active_pairs:
                if p in _seen_zone:
                    continue
                _seen_zone.add(p)
                df_p = BATCH_PROCESSOR.get_df(p, '1h')
                rust_rh = BATCH_PROCESSOR.get_rh(p, '1h')
                st = get_pair_status(p, df_p, rust_rh)
                tsi_val = st.get('tsi', 0)
                # Use adaptive thresholds per pair (not hardcoded)
                try:
                    if rust_rh and 'tsi' in rust_rh:
                        tsi_arr = np.array(rust_rh['tsi'])
                    elif df_p is not None and len(df_p) >= 50:
                        tsi_arr = calculate_tsi(df_p).values
                    else:
                        tsi_arr = None
                    if tsi_arr is not None and len(tsi_arr) >= 50:
                        adapt_l1, adapt_l2 = compute_adaptive_levels(tsi_arr)
                    else:
                        adapt_l1, adapt_l2 = LEVEL_OB_L1, LEVEL_OB_L2
                except Exception:
                    adapt_l1, adapt_l2 = LEVEL_OB_L1, LEVEL_OB_L2
                z = get_tsi_zone(tsi_val, adapt_l1, adapt_l2) or 'neutral'
                zone_counts.setdefault(z, []).append(st.get('pair', p))
                if st.get('ce_line') == 'LONG':
                    ce_long += 1
                else:
                    ce_short += 1
            
            ob2 = zone_counts.get('OB_L2', [])
            ob1 = zone_counts.get('OB_L1', [])
            os1 = zone_counts.get('OS_L1', [])
            os2 = zone_counts.get('OS_L2', [])
            n_zone = len(ob2) + len(ob1) + len(os1) + len(os2)
            
            summary = (
                f"📊 Cycle: {len(active_pairs)} pairs | "
                f"TSI zones: {n_zone} ({len(ob2)} OB2, {len(ob1)} OB1, {len(os1)} OS1, {len(os2)} OS2) | "
                f"CE: {ce_long}L/{ce_short}S"
            )
            if ob2:
                summary += f"\n   🔴 OB_L2 (extreme short): {', '.join(ob2[:8])}"
            if os2:
                summary += f"\n   🟢 OS_L2 (extreme long): {', '.join(os2[:8])}"
            if ob1:
                summary += f"\n   🟠 OB_L1 (watch short): {', '.join(ob1[:8])}"
            if os1:
                summary += f"\n   🔵 OS_L1 (watch long): {', '.join(os1[:8])}"
            log_message(summary)
            
            cycle_errors = sum(1 for err_count in _pair_error_tracker.values() if err_count > 0)
            if cycle_errors > 0:
                log_message(f"⚠️ {cycle_errors} pairs with recent errors")
                
            # Cycle Synchronization — 90s scan cycle (550+ pairs)
            # API budget: with WS-driven candle updates across 15m/1h/4h,
            # REST klines are only used for boot prefetch + occasional stale
            # refresh. The 30s cycle is safe: it's CPU/iteration-bound, not
            # REST-bound. The WS kline stream pushes 1h closes the instant
            # they fire, so signal latency is ≤ 1s after candle close.
            elapsed = time.time() - cycle_start
            await asyncio.sleep(max(0, 30 - elapsed))
            
        except Exception as e:
            log_message(f"Critical error in main loop: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log_message("System terminated by operator.")
    except Exception as e:
        log_message(f"FATAL SYSTEM ERROR: {e}")
