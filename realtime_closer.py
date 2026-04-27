"""
realtime_closer.py — 1 Hz SL/TP closer driven by LIVE_FEED.

Why this exists
---------------
Binance USDS-M REST is geo-blocked from this server (and the proxy fallback
also gets 418-banned), which means `_reconcile_sent_signals` in
`performance_tracker` regularly fails to fetch klines and silently skips
signals. Result: signals like PIPPINUSDT that have clearly pierced TP3 sit
at `targets_hit=0` for days.

But we *already* have markPrice@1s flowing via `LivePriceFeed` for every
USDT-perp pair. This module piggybacks on that feed and does the SL/TP
threshold checks at 1 Hz with zero extra network cost.

Design
------
- Runs as a single asyncio task at 1 Hz.
- Reads OPEN_SIGNALS_TRACKER (in-memory dict shared with main.py /
  performance_tracker).
- For each open signal, looks up live mark price from LIVE_FEED.
- Tracks the **highest TP pierced** (peak-price model) so a trailing-SL
  exit after TP2 records `targets_hit=2`, not 0.
- Writes outcomes to `signal_registry.db` directly.
- **Does NOT send Telegram.** Telegram closed-signal announcements are
  owned by `_reconcile_sent_signals` (5-min cycle, has its own flood
  control). Avoids the original "30 messages on restart" flood that got
  the previous RealTimeSignalMonitor disabled.
- Startup grace: for the first `_STARTUP_GRACE_S` seconds, the closer
  observes peak prices but does NOT close anything. Lets `OPEN_SIGNALS_TRACKER`
  load and prevents racing the periodic reconciler.

Public API
----------
    from realtime_closer import REALTIME_CLOSER
    asyncio.create_task(REALTIME_CLOSER.run())
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Optional

from utils_logger import log_message


_TICK_INTERVAL_S    = 1.0    # poll cadence
_STARTUP_GRACE_S    = 90     # observe-only window after startup (sec)
_DB_PATH            = "signal_registry.db"
_HEARTBEAT_EVERY_S  = 300    # log a heartbeat line this often


class RealtimeCloser:
    """Singleton — close OPEN signals the instant SL or TP is hit."""

    def __init__(self):
        self.running       = False
        self._started_at   = 0.0
        self._last_log     = 0.0
        # In-memory peak/trough per signal (sid → extreme price)
        self._extreme: dict[str, float] = {}
        # In-memory hits tracker per signal (sid → set[int])
        self._hits: dict[str, set] = {}
        # Counters
        self.stats = {
            'ticks':            0,
            'sl_closes':        0,
            'tp_closes':        0,
            'partial_tp_writes': 0,
            'errors':           0,
        }

    def stop(self):
        self.running = False

    async def run(self):
        """Main 1 Hz loop."""
        self.running     = True
        self._started_at = time.time()
        log_message(
            f"🚀 RealtimeCloser started (grace={_STARTUP_GRACE_S}s, tick={_TICK_INTERVAL_S}s, "
            f"DB-only — Telegram still owned by reconcile loop)"
        )
        while self.running:
            await asyncio.sleep(_TICK_INTERVAL_S)
            try:
                await self._tick()
            except Exception as e:
                self.stats['errors'] += 1
                log_message(f"⚠️ RealtimeCloser tick error: {e!r}")

    async def _tick(self):
        # Lazy-import to avoid circulars at module load
        try:
            from performance_tracker import OPEN_SIGNALS_TRACKER, save_open_signals_tracker
        except Exception:
            return
        try:
            from live_price_feed import LIVE_FEED
        except Exception:
            return

        self.stats['ticks'] += 1
        now = time.time()
        in_grace = (now - self._started_at) < _STARTUP_GRACE_S

        # Heartbeat
        if now - self._last_log > _HEARTBEAT_EVERY_S:
            n_open  = len(OPEN_SIGNALS_TRACKER)
            log_message(
                f"📡 RealtimeCloser heartbeat: {n_open} open signals, "
                f"{self.stats['tp_closes']} TP closes, {self.stats['sl_closes']} SL closes, "
                f"{self.stats['partial_tp_writes']} partial-TP writes, "
                f"{self.stats['errors']} errors"
                + ("  [GRACE]" if in_grace else "")
            )
            self._last_log = now

        if in_grace:
            # Observe-only: still update peaks so we don't miss a TP that
            # was hit during the grace window.
            for sid, sig in list(OPEN_SIGNALS_TRACKER.items()):
                self._update_extreme(sid, sig, LIVE_FEED)
            return

        any_close = False
        for sid, sig in list(OPEN_SIGNALS_TRACKER.items()):
            try:
                closed = await self._evaluate(sid, sig, LIVE_FEED)
                if closed:
                    any_close = True
            except Exception as e:
                self.stats['errors'] += 1
                log_message(f"⚠️ RealtimeCloser evaluate {sid} ({sig.get('pair')}) error: {e!r}")

        if any_close:
            try:
                save_open_signals_tracker()
            except Exception as e:
                log_message(f"⚠️ RealtimeCloser save_open_signals_tracker error: {e!r}")

    # ── helpers ─────────────────────────────────────────────────────────

    def _update_extreme(self, sid: str, sig: dict, LIVE_FEED) -> Optional[float]:
        """Track the most-favourable price reached. Returns the live mark or None."""
        pair = sig.get('pair')
        if not pair:
            return None
        px_pkg = LIVE_FEED.get(pair)
        if not px_pkg:
            return None
        mark = float(px_pkg.get('mark') or 0)
        if mark <= 0:
            return None
        is_long = sig.get('signal_type', 'LONG').upper() in ('LONG', 'BUY')
        cur = self._extreme.get(sid)
        if cur is None:
            self._extreme[sid] = mark
        elif is_long and mark > cur:
            self._extreme[sid] = mark
        elif (not is_long) and mark < cur:
            self._extreme[sid] = mark
        return mark

    async def _evaluate(self, sid: str, sig: dict, LIVE_FEED) -> bool:
        """Return True if this signal was closed in this tick."""
        mark = self._update_extreme(sid, sig, LIVE_FEED)
        if mark is None:
            return False

        entry  = float(sig.get('entry_price') or 0)
        sl     = float(sig.get('stop_loss')   or 0)
        tps    = sig.get('targets') or []
        if not entry or not sl or not tps:
            return False
        is_long = sig.get('signal_type', 'LONG').upper() in ('LONG', 'BUY')
        try:
            lev = int(sig.get('leverage') or 1)
        except Exception:
            lev = 1

        peak = self._extreme.get(sid, mark)

        # Highest TP pierced ever (1-indexed; 0 = none)
        highest_pierced = 0
        for i, tp in enumerate(tps):
            if (is_long and peak >= tp) or (not is_long and peak <= tp):
                highest_pierced = i + 1
            else:
                break  # ordered targets

        hits = self._hits.setdefault(sid, set())

        # ── SL hit? ─────────────────────────────────────────────────────
        sl_hit = (is_long and mark <= sl) or (not is_long and mark >= sl)
        if sl_hit:
            raw = ((sl - entry) / entry * 100) if is_long else ((entry - sl) / entry * 100)
            pnl = round(raw * lev, 2)
            self._db_close(sid, pnl=pnl, targets_hit=highest_pierced, reason='SL_HIT')
            self._cleanup_local(sid)
            self.stats['sl_closes'] += 1
            log_message(
                f"🛑 RealtimeCloser: {sig.get('pair')} SL_HIT @ {mark:.6f} "
                f"(SL={sl:.6f}) | targets_hit={highest_pierced} | PnL={pnl:+.2f}%"
            )
            self._remove_from_tracker(sid)
            return True

        # ── TP hits (write all newly pierced) ───────────────────────────
        for tn in range(1, highest_pierced + 1):
            if tn in hits:
                continue
            tp = tps[tn - 1]
            raw = ((tp - entry) / entry * 100) if is_long else ((entry - tp) / entry * 100)
            pnl = round(raw * lev, 2)
            is_final = (tn == len(tps))
            if is_final:
                self._db_close(sid, pnl=pnl, targets_hit=tn, reason=f'TP{tn}_HIT')
                self._cleanup_local(sid)
                self.stats['tp_closes'] += 1
                log_message(
                    f"🎯 RealtimeCloser: {sig.get('pair')} TP{tn}_HIT (final) @ {mark:.6f} "
                    f"| targets_hit={tn} | PnL={pnl:+.2f}%"
                )
                self._remove_from_tracker(sid)
                return True
            else:
                self._db_partial(sid, pnl=pnl, targets_hit=tn)
                hits.add(tn)
                self.stats['partial_tp_writes'] += 1
                log_message(
                    f"🎯 RealtimeCloser: {sig.get('pair')} TP{tn} hit @ {mark:.6f} "
                    f"(partial, signal stays open) | PnL={pnl:+.2f}%"
                )

        return False

    # ── DB helpers ──────────────────────────────────────────────────────

    def _db_close(self, sid: str, pnl: float, targets_hit: int, reason: str):
        try:
            con = sqlite3.connect(_DB_PATH, timeout=5)
            con.execute(
                "UPDATE signals SET status='CLOSED', pnl=?, targets_hit=?, "
                "closed_timestamp=?, close_reason=? WHERE signal_id=?",
                (pnl, targets_hit, time.time(), reason, sid),
            )
            con.commit()
            con.close()
        except Exception as e:
            log_message(f"⚠️ RealtimeCloser DB close error {sid}: {e!r}")

    def _db_partial(self, sid: str, pnl: float, targets_hit: int):
        try:
            con = sqlite3.connect(_DB_PATH, timeout=5)
            con.execute(
                "UPDATE signals SET pnl=?, targets_hit=? WHERE signal_id=?",
                (pnl, targets_hit, sid),
            )
            con.commit()
            con.close()
        except Exception as e:
            log_message(f"⚠️ RealtimeCloser DB partial error {sid}: {e!r}")

    def _cleanup_local(self, sid: str):
        self._extreme.pop(sid, None)
        self._hits.pop(sid, None)

    def _remove_from_tracker(self, sid: str):
        try:
            from performance_tracker import OPEN_SIGNALS_TRACKER
            OPEN_SIGNALS_TRACKER.pop(sid, None)
        except Exception:
            pass


# Module-level singleton
REALTIME_CLOSER = RealtimeCloser()
