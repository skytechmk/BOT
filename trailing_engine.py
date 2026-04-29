"""
trailing_engine.py — Dynamic Trailing Stop-Loss Engine (v3)

Activates AFTER the first take-profit (TP1) is hit on a live signal and then
ratchets the stop-loss upward (LONG) / downward (SHORT) using a volatility-
adjusted Chandelier Exit on the 1h timeframe as the trailing reference.

Key upgrades over v2:
  - ML Confidence integration — trailing SL now ingests ML calibrated
    probabilities from the signal's feature snapshot:
      * High conviction (ml_confidence > 0.85) → widen ATR multiplier
        to prevent premature exits during strong trends.
      * Low conviction (ml_confidence < 0.60) → tighten ATR multiplier
        to lock in profits or minimize drawdown.
  - ML confidence persisted to Redis Signal Cache as trail_ml_confidence.

Key features retained from v2:
  - Dynamic ATR-based trailing (replaces static % stops → anti-stop-hunt)
  - "Funding Choke" — tightens ATR multiplier when funding flips aggressively
    against the trade direction (crowd-driven reversal signal)
  - All trailing state persisted asynchronously to Redis Signal Cache
  - Backward-compatible: sl_mode == "fixed" bypasses ATR logic entirely

Integration points
------------------
1. `trail_open_signals()` — called every reconcile cycle (default 5 min) from
   `performance_tracker._reconcile_sent_signals`.  Computes a candidate new
   trail SL for every OPEN signal with targets_hit >= 1 and persists it to
   the Redis Signal Cache via `set_signal`.

2. For every signal whose trail SL improved, we:
   a) fire an async task to re-position the exchange-side STOP_MARKET orders
      of every copy-trader on that signal (cancel + replace);
   b) post a Telegram reply to the original signal message announcing the
      new SL (rate-limited to TRAIL_ANNOUNCE_MIN_MOVE_PCT between updates).

Feature flag
------------
Controlled by env var `TRAILING_ENABLED` (default "true").  Set to "false" to
fully disable the engine — it then becomes a no-op in the reconciler.
"""
from __future__ import annotations

import os
import time
import json
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

from loguru import logger

# ── Internal imports (lazy where possible to avoid circular deps) ──────────

# ── Tunables (safe defaults; override via env) ────────────────────────────
TRAILING_ENABLED = os.getenv("TRAILING_ENABLED", "true").lower() == "true"
TRAIL_CE_PERIOD = int(os.getenv("TRAIL_CE_PERIOD", "22"))
TRAIL_CE_MULT = float(os.getenv("TRAIL_CE_MULT", "3.0"))
TRAIL_TF = os.getenv("TRAIL_TF", "1h")
TRAIL_MIN_IMPROVE_PCT = float(os.getenv("TRAIL_MIN_IMPROVE_PCT", "0.10"))
TRAIL_ANNOUNCE_MIN_PCT = float(os.getenv("TRAIL_ANNOUNCE_MIN_PCT", "0.30"))
TRAIL_BREAKEVEN_BUFFER = float(os.getenv("TRAIL_BREAKEVEN_BUFFER", "0.0"))

# Funding Choke thresholds
FUNDING_CHOKE_THRESHOLD = float(os.getenv("FUNDING_CHOKE_THRESHOLD", "0.0005"))
FUNDING_CHOKE_MULTIPLIER = float(os.getenv("FUNDING_CHOKE_MULTIPLIER", "1.0"))

# ── ML Confidence thresholds for ATR multiplier scaling ─────────────────
ML_CONF_HIGH     = float(os.getenv("TRAIL_ML_CONF_HIGH", "0.85"))
ML_CONF_LOW      = float(os.getenv("TRAIL_ML_CONF_LOW", "0.60"))
ML_WIDEN_MULT    = float(os.getenv("TRAIL_ML_WIDEN_MULT", "1.5"))
ML_TIGHTEN_MULT  = float(os.getenv("TRAIL_ML_TIGHTEN_MULT", "0.6"))

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signal_registry.db')


# ── Schema migration (SQLite read-path remains for signal discovery) ──────
def ensure_schema() -> None:
    """Add trailing-SL columns to signals table idempotently."""
    try:
        con = sqlite3.connect(_DB_PATH, timeout=5)
        for sql in (
            "ALTER TABLE signals ADD COLUMN trail_sl REAL DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN trail_last_announced REAL DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN trail_activated_ts REAL DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN sl_mode TEXT DEFAULT 'fixed'",
            "ALTER TABLE signals ADD COLUMN trail_atr_mult REAL DEFAULT 3.0",
            "ALTER TABLE signals ADD COLUMN trail_funding_choke REAL DEFAULT 0",
        ):
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass
        con.commit()
        con.close()
    except Exception as e:
        logger.warning(f"[PREDATOR-LOOP] trailing schema migration failed: {e}")


# ── ML Confidence extraction ─────────────────────────────────────────────

def _extract_ml_confidence(signal_data: Dict[str, Any]) -> Optional[float]:
    """
    Extract ML calibrated probability from the signal's feature snapshot.

    The ``features`` dict (stored as JSON in signal_registry.db) contains
    ``ml_prob_short``, ``ml_prob_neutral``, ``ml_prob_long`` — calibrated
    probabilities from the XGBoost ensemble in ml_ultra_surface.py.

    Returns the ML confidence aligned with the signal direction, or None
    if the ML payload was never persisted (pre-Phase 4 signal or feature
    capture failure).
    """
    features = signal_data.get('features')
    if not features:
        return None
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except json.JSONDecodeError:
            return None

    direction = (signal_data.get('signal') or signal_data.get('direction') or '').upper()
    is_long = direction in ('LONG', 'BUY')
    is_short = direction in ('SHORT', 'SELL')

    prob_long   = features.get('ml_prob_long')
    prob_short  = features.get('ml_prob_short')
    prob_neutral = features.get('ml_prob_neutral')

    if prob_long is None and prob_short is None and prob_neutral is None:
        return None

    try:
        if is_long and prob_long is not None:
            return float(prob_long)
        if is_short and prob_short is not None:
            return float(prob_short)
        # Fallback: use max(probs_calibrated) if direction-specific prob missing
        candidates = [float(v) for v in (prob_long, prob_short, prob_neutral) if v is not None]
        if candidates:
            return max(candidates)
    except (TypeError, ValueError):
        return None
    return None


def _apply_ml_confidence_to_atr_mult(
    base_mult: float,
    ml_confidence: Optional[float],
) -> float:
    """
    Scale the ATR multiplier based on ML conviction.

    High conviction (ml_confidence > ML_CONF_HIGH):
        Widen the trailing stop to prevent premature exits during strong
        trends the model is confident about.
        multiplier *= ML_WIDEN_MULT  (default 1.5×)

    Low conviction (ml_confidence < ML_CONF_LOW):
        Tighten the Chandelier Exit to lock in profits or minimize
        drawdown on trades the model is uncertain about.
        multiplier *= ML_TIGHTEN_MULT  (default 0.6×)

    Neutral: return base_mult unchanged.
    """
    if ml_confidence is None:
        return base_mult

    if ml_confidence >= ML_CONF_HIGH:
        return round(base_mult * ML_WIDEN_MULT, 2)
    if ml_confidence <= ML_CONF_LOW:
        return round(base_mult * ML_TIGHTEN_MULT, 2)
    return base_mult


# ── Volatility & Chandelier Exit computation ─────────────────────────────
def _compute_atr_trailing_sl(
    pair: str,
    direction: str,
    entry: float,
    current_sl: float,
    atr_multiplier: float = TRAIL_CE_MULT,
    df=None,  # pre-fetched DataFrame from parallel‑fetch phase
) -> Optional[Dict[str, Any]]:
    """
    Compute a volatility-adjusted trailing stop-loss using Chandelier Exit
    logic on the specified timeframe.

    **df** — when supplied (from the parallel‑fetch phase), the synchronous
    ``fetch_data()`` call is skipped entirely.  When ``None``, the legacy
    on‑demand path is used (for callers that don't batch).

    Returns dict with:
        candidate_sl: the new trailing stop price
        atr_value: current ATR value
        highest_high: highest high over lookback (for LONG)
        lowest_low: lowest low over lookback (for SHORT)
        atr_mult_used: effective ATR multiplier (may be choked)
    or None if unavailable.

    Longs:  Highest High (lookback) - (Multiplier * ATR)
    Shorts: Lowest Low (lookback) + (Multiplier * ATR)

    High Water Mark principle: the trailing stop only moves in the direction
    of the trade (up for LONG, down for SHORT).
    """
    if df is None:
        try:
            from data_fetcher import fetch_data
            df = fetch_data(pair, interval=TRAIL_TF)
        except Exception as e:
            logger.debug(f"[PREDATOR-LOOP] fetch_data failed for {pair}: {e}")
            return None
    else:
        # use supplied DataFrame directly — already validated by caller
        pass

    try:
        from technical_indicators import calculate_chandelier_exit
    except Exception as e:
        logger.warning(f"[PREDATOR-LOOP] deps missing for {pair}: {e}")
        return None

    if df is None or len(df) < TRAIL_CE_PERIOD + 5:
        return None

    try:
        df = calculate_chandelier_exit(df, atr_period=TRAIL_CE_PERIOD, mult=atr_multiplier)
    except Exception as e:
        logger.warning(f"[PREDATOR-LOOP] CE calc failed for {pair}: {e}")
        return None

    if 'CE_Long_Stop' not in df.columns or 'CE_Short_Stop' not in df.columns:
        return None

    try:
        ce_long = float(df['CE_Long_Stop'].iloc[-1])
        ce_short = float(df['CE_Short_Stop'].iloc[-1])
        atr_val = float(df['atr'].iloc[-1]) if 'atr' in df.columns else 0.0
    except Exception:
        return None

    is_long = direction.upper() in ('LONG', 'BUY')

    if is_long:
        floor_price = entry * (1.0 + TRAIL_BREAKEVEN_BUFFER / 100.0)
        candidate = max(floor_price, ce_long)
        highest_high = float(df['high'].rolling(TRAIL_CE_PERIOD, min_periods=1).max().iloc[-1])
        return {
            'candidate_sl': candidate,
            'atr_value': atr_val,
            'highest_high': highest_high,
            'lowest_low': None,
            'atr_mult_used': atr_multiplier,
        }
    else:
        ceil_price = entry * (1.0 - TRAIL_BREAKEVEN_BUFFER / 100.0)
        candidate = min(ceil_price, ce_short)
        lowest_low = float(df['low'].rolling(TRAIL_CE_PERIOD, min_periods=1).min().iloc[-1])
        return {
            'candidate_sl': candidate,
            'atr_value': atr_val,
            'highest_high': None,
            'lowest_low': lowest_low,
            'atr_mult_used': atr_multiplier,
        }


# ── Funding Choke mechanism ──────────────────────────────────────────────
async def _get_effective_atr_multiplier(
    symbol: str,
    direction: str,
    base_mult: float = TRAIL_CE_MULT,
) -> float:
    """
    Fetch real-time funding and Open Interest via Redis cache.

    If the funding rate flips aggressively against the trade direction,
    programmatically "choke" the ATR multiplier (reduce from 3.0x to 1.0x)
    to force a tighter exit and lock in profits.

    Aggressive funding against position = crowd is positioned for reversal.
    - LONG position + high positive funding = longs paying shorts = crowd long = reversal risk
    - SHORT position + high negative funding = shorts paying longs = crowd short = reversal risk
    """
    try:
        from dashboard.redis_cache import get_funding_oi
        funding_oi = await get_funding_oi(symbol)
        if funding_oi is None:
            return base_mult

        funding_rate = funding_oi.get('funding_rate', 0.0)
        if isinstance(funding_rate, str):
            funding_rate = float(funding_rate)

        is_long = direction.upper() in ('LONG', 'BUY')

        choke_triggered = False
        if is_long and funding_rate > FUNDING_CHOKE_THRESHOLD:
            choke_triggered = True
        elif not is_long and funding_rate < -FUNDING_CHOKE_THRESHOLD:
            choke_triggered = True

        if choke_triggered:
            logger.info(
                f"[PREDATOR-LOOP] 🪝 FUNDING CHOKE [{symbol}]: "
                f"funding_rate={funding_rate:.6f} | mult {base_mult}x → {FUNDING_CHOKE_MULTIPLIER}x"
            )
            return FUNDING_CHOKE_MULTIPLIER

        return base_mult

    except Exception as e:
        logger.warning(f"[PREDATOR-LOOP] funding choke check failed for {symbol}: {e}")
        return base_mult


# ── High Water Mark ratchet logic ────────────────────────────────────────
def _is_improvement(is_long: bool, old_sl: float, new_sl: float, min_improve_pct: float) -> bool:
    """Returns True if new_sl is a meaningful ratchet over old_sl."""
    if new_sl <= 0 or old_sl <= 0:
        return new_sl > 0 and old_sl == 0
    move_pct = abs(new_sl - old_sl) / old_sl * 100.0
    if move_pct < min_improve_pct:
        return False
    return (is_long and new_sl > old_sl) or ((not is_long) and new_sl < old_sl)


# ── Core trailing evaluation ─────────────────────────────────────────────
async def _evaluate_trailing_stop(
    signal_data: Dict[str, Any],
    df_map: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Evaluate a single signal for trailing stop update.

    **df_map** — when supplied, a dict mapping pair → pre‑fetched DataFrame.
    The per‑pair ``fetch_data()`` call is skipped; the DataFrame is
    looked up in O(1) from this map.

    Returns update dict if trailing SL should be updated, None otherwise.
    """
    try:
        sid = signal_data.get('signal_id')
        pair = signal_data.get('pair')
        direction = (signal_data.get('signal') or '').upper()
        entry = float(signal_data.get('price') or 0)
        sig_sl = float(signal_data.get('stop_loss') or 0)
        trail_sl = float(signal_data.get('trail_sl') or 0)
        last_ann = float(signal_data.get('trail_last_announced') or 0)
        msg_id = signal_data.get('telegram_message_id')
        sl_mode = signal_data.get('sl_mode', 'fixed')
        targets_hit = signal_data.get('targets_hit', [])

        if not entry or direction not in ('LONG', 'SHORT', 'BUY', 'SELL'):
            return None

        if not targets_hit or (isinstance(targets_hit, list) and len(targets_hit) == 0):
            return None

        is_long = direction in ('LONG', 'BUY')

        if sl_mode == 'fixed':
            return None

        cur_eff_sl = max(sig_sl, trail_sl) if trail_sl > 0 else sig_sl

        atr_mult = await _get_effective_atr_multiplier(pair, direction)

        # ── ML Confidence scaling ──
        ml_conf = _extract_ml_confidence(signal_data)
        atr_mult = _apply_ml_confidence_to_atr_mult(atr_mult, ml_conf)

        df_prefetched = df_map.get(pair) if df_map else None
        result = _compute_atr_trailing_sl(pair, direction, entry, cur_eff_sl, atr_mult, df=df_prefetched)
        if result is None:
            return None

        candidate = result['candidate_sl']

        if not _is_improvement(is_long, cur_eff_sl, candidate, TRAIL_MIN_IMPROVE_PCT):
            return None

        should_announce = False
        if last_ann <= 0:
            should_announce = True
        else:
            ann_move = abs(candidate - last_ann) / last_ann * 100.0
            should_announce = ann_move >= TRAIL_ANNOUNCE_MIN_PCT

        return {
            'signal_id': sid,
            'pair': pair,
            'direction': 'LONG' if is_long else 'SHORT',
            'entry': entry,
            'old_sl': cur_eff_sl,
            'new_sl': candidate,
            'telegram_message_id': msg_id,
            'should_announce': should_announce,
            'atr_value': result['atr_value'],
            'atr_mult_used': result['atr_mult_used'],
            'ml_confidence': ml_conf,
            'funding_choke_active': result['atr_mult_used'] < TRAIL_CE_MULT and ml_conf is None,
        }

    except Exception as e:
        logger.warning(f"[PREDATOR-LOOP] per-signal evaluation error: {e}")
        return None


# ── Async orchestration ──────────────────────────────────────────────────
async def trail_open_signals() -> List[dict]:
    """
    Iterate all OPEN signals with targets_hit >= 1, compute candidate trail
    SL, and persist improvements to Redis Signal Cache.

    Returns a list of dicts describing each update actually applied.
    """
    if not TRAILING_ENABLED:
        return []

    ensure_schema()

    updates: List[dict] = []

    try:
        con = sqlite3.connect(_DB_PATH, timeout=5)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT signal_id, pair, signal, price, stop_loss, targets_hit, "
            "trail_sl, trail_last_announced, telegram_message_id, sl_mode, features "
            "FROM signals WHERE status IN ('SENT','OPEN') AND targets_hit >= 1"
        ).fetchall()
        con.close()
    except Exception as e:
        logger.error(f"[PREDATOR-LOOP] DB read failed: {e}")
        return []

    signal_data_list = []
    for r in rows:
        signal_data_list.append({
            'signal_id': r['signal_id'],
            'pair': r['pair'],
            'signal': r['signal'],
            'price': r['price'],
            'stop_loss': r['stop_loss'],
            'targets_hit': r['targets_hit'],
            'trail_sl': r['trail_sl'],
            'trail_last_announced': r['trail_last_announced'],
            'telegram_message_id': r['telegram_message_id'],
            'sl_mode': r['sl_mode'] or 'fixed',
            'features': r['features'],
        })

    # ── Phase 1: parallel DataFrame pre-fetch ─────────────────────────
    # Deduplicate pairs and fetch all needed DataFrames concurrently in
    # a thread pool so that per-signal evaluation never waits on I/O.
    unique_pairs = list({sd['pair'] for sd in signal_data_list})
    df_map: Dict[str, Any] = {}
    if unique_pairs:
        loop = asyncio.get_running_loop()

        async def _fetch_df(pair: str):
            try:
                from data_fetcher import fetch_data
                return pair, await loop.run_in_executor(
                    _fetch_executor, fetch_data, pair, TRAIL_TF,
                )
            except Exception as e:
                logger.debug(f"[PREDATOR-LOOP] parallel fetch failed for {pair}: {e}")
                return pair, None

        with ThreadPoolExecutor(max_workers=min(len(unique_pairs), 8)) as _fetch_executor:
            _fetched = await asyncio.gather(*[_fetch_df(p) for p in unique_pairs])
            for _p, _df in _fetched:
                df_map[_p] = _df

    # ── Phase 2: per-signal evaluation (zero I/O — data from df_map) ──
    tasks = [_evaluate_trailing_stop(sd, df_map=df_map) for sd in signal_data_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    now = time.time()
    for result in results:
        if isinstance(result, Exception) or result is None:
            continue

        try:
            from dashboard.redis_cache import set_signal
            from signal_registry_db import SignalRegistryDB

            sig_id = result['signal_id']
            db = SignalRegistryDB(_DB_PATH)
            current_signal = db.get_signal(sig_id)
            if current_signal is None:
                continue

            current_signal['trail_sl'] = result['new_sl']
            current_signal['trail_activated_ts'] = current_signal.get('trail_activated_ts') or now
            current_signal['trail_atr_mult'] = result['atr_mult_used']
            current_signal['trail_funding_choke'] = 1.0 if result['funding_choke_active'] else 0.0
            current_signal['trail_ml_confidence'] = result.get('ml_confidence') or 0.0
            current_signal['trail_last_updated'] = now

            await set_signal(sig_id, current_signal)

            try:
                con = sqlite3.connect(_DB_PATH, timeout=5)
                con.execute(
                    "UPDATE signals SET trail_sl=?, trail_activated_ts=COALESCE(NULLIF(trail_activated_ts,0), ?) "
                    "WHERE signal_id=?",
                    (result['new_sl'], now, sig_id)
                )
                if result['should_announce']:
                    con.execute(
                        "UPDATE signals SET trail_last_announced=? WHERE signal_id=?",
                        (result['new_sl'], sig_id)
                    )
                con.commit()
                con.close()
            except Exception as e:
                logger.error(f"[PREDATOR-LOOP] SQLite persist failed sid={sig_id[:8]}: {e}")

            if result['should_announce']:
                current_signal['trail_last_announced'] = result['new_sl']
                await set_signal(sig_id, current_signal)

            updates.append(result)

            ml_label = f"{ml_val:.2f}" if (ml_val := result.get('ml_confidence')) else 'N/A'
            logger.info(
                f"[PREDATOR-LOOP] {result['pair']} {result['direction']} sid={sig_id[:8]} "
                f"SL {result['old_sl']:.6g} → {result['new_sl']:.6g} "
                f"(ATR mult={result['atr_mult_used']}x, "
                f"ML={ml_label}, "
                f"choke={'ON' if result['funding_choke_active'] else 'OFF'}, "
                f"announce={result['should_announce']})"
            )

        except Exception as e:
            logger.warning(f"[PREDATOR-LOOP] persist error for sid={result.get('signal_id', 'unknown')}: {e}")
            continue

    return updates


# ── Async fan-out ─────────────────────────────────────────────────────────
async def _update_copy_trades(upd: dict) -> None:
    """Propagate the new SL to every copy-trader's Binance position."""
    try:
        from dashboard.copy_trading import update_copy_sl_for_signal
    except Exception as e:
        logger.debug(f"[PREDATOR-LOOP] copy_trading import skipped: {e}")
        return
    try:
        await update_copy_sl_for_signal(upd['signal_id'], upd['new_sl'])
    except Exception as e:
        logger.warning(
            f"[PREDATOR-LOOP] copy-trade SL update failed sid={upd['signal_id'][:8]}: {e}"
        )


async def fan_out_updates(updates: List[dict]) -> None:
    """
    Concurrently propagate each ratchet to every Ultra copy-trader's Binance
    account (cancel + replace STOP_MARKET).
    """
    if not updates:
        return
    tasks = [_update_copy_trades(upd) for upd in updates]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_trailing_cycle() -> int:
    """
    Convenience wrapper: compute + fan-out in one call. Returns the number
    of SL improvements applied this cycle.
    """
    if not TRAILING_ENABLED:
        return 0
    updates = await trail_open_signals()
    await fan_out_updates(updates)
    return len(updates)