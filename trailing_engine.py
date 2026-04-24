"""
trailing_engine.py — Dynamic Trailing Stop-Loss Engine

Activates AFTER the first take-profit (TP1) is hit on a live signal and then
ratchets the stop-loss upward (LONG) / downward (SHORT) using the Chandelier
Exit (22/3.0) on the 1h timeframe as the trailing reference.

Integration points
------------------
1. `trail_open_signals()` — called every reconcile cycle (default 5 min) from
   `performance_tracker._reconcile_sent_signals`.  Computes a candidate new
   trail SL for every OPEN signal with targets_hit >= 1 and persists it to
   signal_registry.db in the new `trail_sl` column.

2. For every signal whose trail SL improved, we:
   a) fire an async task to re-position the exchange-side STOP_MARKET orders
      of every copy-trader on that signal (cancel + replace);
   b) post a Telegram reply to the original signal message announcing the
      new SL (rate-limited to TRAIL_ANNOUNCE_MIN_MOVE_PCT between updates).

Feature flag
------------
Controlled by env var `TRAILING_ENABLED` (default "true").  Set to "false" to
fully disable the engine — it then becomes a no-op in the reconciler.

Schema migration
----------------
`ensure_schema()` adds the following columns to `signals` idempotently:
    trail_sl             REAL DEFAULT 0
    trail_last_announced REAL DEFAULT 0
    trail_activated_ts   REAL DEFAULT 0
"""
from __future__ import annotations

import os
import time
import json
import sqlite3
import asyncio
import logging
from typing import Optional, List, Tuple

log = logging.getLogger("trailing_engine")

# ── Tunables (safe defaults; override via env) ────────────────────────────
TRAILING_ENABLED          = os.getenv("TRAILING_ENABLED", "true").lower() == "true"
TRAIL_CE_PERIOD           = int(os.getenv("TRAIL_CE_PERIOD", "22"))
TRAIL_CE_MULT             = float(os.getenv("TRAIL_CE_MULT", "3.0"))
TRAIL_TF                  = os.getenv("TRAIL_TF", "1h")
TRAIL_MIN_IMPROVE_PCT     = float(os.getenv("TRAIL_MIN_IMPROVE_PCT", "0.10"))   # must move ≥0.10% to ratchet
TRAIL_ANNOUNCE_MIN_PCT    = float(os.getenv("TRAIL_ANNOUNCE_MIN_PCT", "0.30")) # announce only on ≥0.30% move
TRAIL_BREAKEVEN_BUFFER    = float(os.getenv("TRAIL_BREAKEVEN_BUFFER", "0.0"))   # 0% above/below entry

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signal_registry.db')


# ── Schema migration ──────────────────────────────────────────────────────
def ensure_schema() -> None:
    """Add trailing-SL columns to signals table idempotently."""
    try:
        con = sqlite3.connect(_DB_PATH, timeout=5)
        for sql in (
            "ALTER TABLE signals ADD COLUMN trail_sl REAL DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN trail_last_announced REAL DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN trail_activated_ts REAL DEFAULT 0",
        ):
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        con.commit()
        con.close()
    except Exception as e:
        log.warning(f"[trailing] schema migration failed: {e}")


# ── Core computation ──────────────────────────────────────────────────────
def compute_ce_trailing_sl(pair: str, direction: str, entry: float,
                           current_sl: float) -> Optional[float]:
    """
    Return a candidate trailing-SL price for the given signal, or None if
    unavailable.  The candidate is the Chandelier Exit level on the 1h
    timeframe, floored at the breakeven price (+buffer).

    LONG:  max(entry * (1 + buffer),  CE_Long_Stop_latest)
    SHORT: min(entry * (1 - buffer),  CE_Short_Stop_latest)

    The ratchet rule (never move the stop backwards) is enforced by the
    caller comparing against the row's current trail_sl value.
    """
    try:
        from data_fetcher import fetch_data
        from technical_indicators import calculate_chandelier_exit
    except Exception as e:
        log.warning(f"[trailing] deps missing: {e}")
        return None

    try:
        df = fetch_data(pair, interval=TRAIL_TF)
    except Exception as e:
        log.debug(f"[trailing] fetch_data failed for {pair}: {e}")
        return None
    if df is None or len(df) < TRAIL_CE_PERIOD + 5:
        return None

    try:
        df = calculate_chandelier_exit(df, atr_period=TRAIL_CE_PERIOD, mult=TRAIL_CE_MULT)
    except Exception as e:
        log.warning(f"[trailing] CE calc failed for {pair}: {e}")
        return None

    # CE columns missing on degenerate data
    if 'CE_Long_Stop' not in df.columns or 'CE_Short_Stop' not in df.columns:
        return None

    try:
        ce_long  = float(df['CE_Long_Stop'].iloc[-1])
        ce_short = float(df['CE_Short_Stop'].iloc[-1])
    except Exception:
        return None

    is_long = direction.upper() in ('LONG', 'BUY')
    if is_long:
        floor_price = entry * (1.0 + TRAIL_BREAKEVEN_BUFFER / 100.0)
        candidate = max(floor_price, ce_long)
        # Never set SL above current mark (would close immediately). Caller
        # verifies mark price downstream via the reconciler kline walk.
        return candidate
    else:
        ceil_price = entry * (1.0 - TRAIL_BREAKEVEN_BUFFER / 100.0)
        candidate = min(ceil_price, ce_short)
        return candidate


def _is_improvement(is_long: bool, old_sl: float, new_sl: float,
                    min_improve_pct: float) -> bool:
    """Returns True if new_sl is a meaningful ratchet over old_sl."""
    if new_sl <= 0 or old_sl <= 0:
        return new_sl > 0 and old_sl == 0
    move_pct = abs(new_sl - old_sl) / old_sl * 100.0
    if move_pct < min_improve_pct:
        return False
    return (is_long and new_sl > old_sl) or ((not is_long) and new_sl < old_sl)


# ── Orchestration ─────────────────────────────────────────────────────────
def trail_open_signals() -> List[dict]:
    """
    Iterate all OPEN signals with targets_hit >= 1, compute candidate trail
    SL, and persist improvements.  Returns a list of dicts describing each
    update actually applied (suitable for async fan-out).

    Each update dict contains:
        signal_id, pair, direction, entry, old_sl, new_sl,
        telegram_message_id, should_announce
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
            "trail_sl, trail_last_announced, telegram_message_id "
            "FROM signals WHERE status IN ('SENT','OPEN') AND targets_hit >= 1"
        ).fetchall()
    except Exception as e:
        log.error(f"[trailing] DB read failed: {e}")
        return []

    now = time.time()
    for r in rows:
        try:
            sid       = r['signal_id']
            pair      = r['pair']
            direction = (r['signal'] or '').upper()
            entry     = float(r['price'] or 0)
            sig_sl    = float(r['stop_loss'] or 0)
            trail_sl  = float(r['trail_sl'] or 0)
            last_ann  = float(r['trail_last_announced'] or 0)
            msg_id    = r['telegram_message_id']
            if not entry or direction not in ('LONG', 'SHORT', 'BUY', 'SELL'):
                continue
            is_long = direction in ('LONG', 'BUY')

            # Effective current SL = best of original SL and any prior trail
            if is_long:
                cur_eff_sl = max(sig_sl, trail_sl) if trail_sl > 0 else sig_sl
            else:
                cur_eff_sl = min(sig_sl, trail_sl) if trail_sl > 0 else sig_sl

            candidate = compute_ce_trailing_sl(pair, direction, entry, cur_eff_sl)
            if candidate is None:
                continue

            if not _is_improvement(is_long, cur_eff_sl, candidate, TRAIL_MIN_IMPROVE_PCT):
                continue

            # Persist
            try:
                con.execute(
                    "UPDATE signals SET trail_sl=?, "
                    "trail_activated_ts=COALESCE(NULLIF(trail_activated_ts,0), ?) "
                    "WHERE signal_id=?",
                    (candidate, now, sid)
                )
                con.commit()
            except Exception as e:
                log.error(f"[trailing] persist failed sid={sid}: {e}")
                continue

            # Decide if we should announce (rate-limited by %-move from last announced)
            if last_ann <= 0:
                should_announce = True
            else:
                ann_move = abs(candidate - last_ann) / last_ann * 100.0
                should_announce = ann_move >= TRAIL_ANNOUNCE_MIN_PCT

            updates.append({
                'signal_id': sid,
                'pair': pair,
                'direction': 'LONG' if is_long else 'SHORT',
                'entry': entry,
                'old_sl': cur_eff_sl,
                'new_sl': candidate,
                'telegram_message_id': msg_id,
                'should_announce': should_announce,
            })

            if should_announce:
                try:
                    con.execute(
                        "UPDATE signals SET trail_last_announced=? WHERE signal_id=?",
                        (candidate, sid)
                    )
                    con.commit()
                except Exception:
                    pass

            log.info(
                f"[trailing] {pair} {direction} sid={sid[:8]} "
                f"SL {cur_eff_sl:.6g} → {candidate:.6g} "
                f"({'+' if is_long else '-'}ratchet, announce={should_announce})"
            )
        except Exception as e:
            log.warning(f"[trailing] per-row error: {e}")
            continue

    try:
        con.close()
    except Exception:
        pass
    return updates


# ── Async fan-out (active trailing — platform-side only) ──────────────────
# No Telegram announces: trailing is fully executed on each Ultra user's
# Binance account via cancel+replace of STOP_MARKET orders.  Subscribers do
# not receive chat noise for every SL ratchet — the move is visible in each
# user's own dashboard (trade history shows the live sl_price) and on
# Binance directly.
async def _update_copy_trades(upd: dict) -> None:
    """Propagate the new SL to every copy-trader's Binance position."""
    try:
        from dashboard.copy_trading import update_copy_sl_for_signal
    except Exception as e:
        log.debug(f"[trailing] copy_trading import skipped: {e}")
        return
    try:
        await update_copy_sl_for_signal(upd['signal_id'], upd['new_sl'])
    except Exception as e:
        log.warning(
            f"[trailing] copy-trade SL update failed sid={upd['signal_id'][:8]}: {e}"
        )


async def fan_out_updates(updates: List[dict]) -> None:
    """
    Concurrently propagate each ratchet to every Ultra copy-trader's Binance
    account (cancel + replace STOP_MARKET).  Platform-side only — no Telegram
    chat noise is generated per ratchet.
    """
    if not updates:
        return
    tasks = [_update_copy_trades(upd) for upd in updates]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_trailing_cycle() -> int:
    """
    Convenience wrapper: compute + fan-out in one call.  Returns the number
    of SL improvements applied this cycle.
    """
    if not TRAILING_ENABLED:
        return 0
    updates = await asyncio.to_thread(trail_open_signals)
    await fan_out_updates(updates)
    return len(updates)
