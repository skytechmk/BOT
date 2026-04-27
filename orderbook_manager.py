"""
orderbook_manager.py — Live top-20 order book + derived features.

Subscribes to `<symbol>@depth20@500ms` on /public/stream for the top-N
pairs by volume. Maintains a snapshot of the top 20 bid/ask levels per
symbol and exposes derived features useful for signal quality and
execution gating:

  • bid_ask_imbalance  ∈ [-1, +1]   (positive = bid-heavy)
  • spread_bps          (best ask − best bid) / mid × 10000
  • top_depth_usd_bid   Σ first-10-levels notional on bid side
  • top_depth_usd_ask   Σ first-10-levels notional on ask side
  • mid                 mid price (helper)

These are EXPOSED for use as features in feature_snapshot or future SQI
components — they are NOT used as gates yet. Collect data first, study
correlation with outcomes, then promote the strongest signal to a gate.

Notes
-----
- We use Partial Book Depth (full top-20 snapshot every 500 ms), not
  Diff Depth. Simpler — no local-book maintenance, no `pu` chaining.
- Streams are batched per /public/stream endpoint, ≤200 streams per
  connection (Binance limit).
- Stays well under the per-IP connection limit even at 100+ pairs.

Usage
-----
    from orderbook_manager import ORDERBOOK
    asyncio.create_task(ORDERBOOK.run(top_pairs))   # list[str]

    feats = ORDERBOOK.features_for("BTCUSDT")
    if feats and feats['spread_bps'] > 5:
        # too thin — reject signal
        ...
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import websockets

from utils_logger import log_message


_FUTURES_STREAM_URL    = "wss://fstream.binance.com/public/stream?streams={streams}"
_DEPTH_LEVELS          = 20            # @depth20@500ms — full top-20 snapshot
_DEPTH_INTERVAL        = "500ms"
_MAX_STREAMS_PER_CONN  = 180           # well under 200 limit
_RECONNECT_BASE        = 3
_RECONNECT_MAX         = 60
_TOP_FEATURE_LEVELS    = 10            # imbalance / depth aggregated over top-10


class OrderBookManager:
    """Singleton — top-N order books, derived features in O(1)."""

    def __init__(self):
        # symbol → {"b": [[price, qty], …], "a": [[price, qty], …], "ts": float}
        self._books: dict[str, dict] = {}
        # symbol → cached features dict, recomputed on each push
        self._features: dict[str, dict] = {}
        self._pairs: list[str] = []
        self.running = False
        self._msgs_rx = 0
        self._last_log = 0.0

    # ── public API ──────────────────────────────────────────────────────

    def features_for(self, pair: str, max_age_s: float = 5.0) -> Optional[dict]:
        """Return latest derived features dict for `pair`, or None if stale/absent."""
        f = self._features.get(pair)
        if not f:
            return None
        if time.time() - f.get('ts', 0) > max_age_s:
            return None
        return f

    def book_for(self, pair: str) -> Optional[dict]:
        """Return raw top-20 book snapshot — bids/asks/ts."""
        return self._books.get(pair)

    def stats(self) -> dict:
        return {
            "tracked_pairs": len(self._books),
            "msgs_rx":       self._msgs_rx,
        }

    def stop(self):
        self.running = False

    # ── feature computation ────────────────────────────────────────────

    def _compute_features(self, sym: str, bids: list, asks: list) -> Optional[dict]:
        """Compute imbalance, spread, depth USD from a fresh top-20 snapshot."""
        if not bids or not asks:
            return None
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
                return None
            mid        = (best_bid + best_ask) * 0.5
            spread_bps = (best_ask - best_bid) / mid * 10_000.0

            # Top-N aggregated quantities and USD notional
            n = min(_TOP_FEATURE_LEVELS, len(bids), len(asks))
            bid_qty_sum = 0.0
            ask_qty_sum = 0.0
            bid_usd     = 0.0
            ask_usd     = 0.0
            for i in range(n):
                bp, bq = float(bids[i][0]), float(bids[i][1])
                ap, aq = float(asks[i][0]), float(asks[i][1])
                bid_qty_sum += bq
                ask_qty_sum += aq
                bid_usd     += bp * bq
                ask_usd     += ap * aq

            denom = bid_qty_sum + ask_qty_sum
            imbalance = (bid_qty_sum - ask_qty_sum) / denom if denom > 0 else 0.0

            return {
                'symbol':         sym,
                'best_bid':       best_bid,
                'best_ask':       best_ask,
                'mid':            mid,
                'spread_bps':     round(spread_bps, 3),
                'imbalance':      round(imbalance, 4),    # [-1, +1]
                'bid_depth_usd':  round(bid_usd, 2),
                'ask_depth_usd':  round(ask_usd, 2),
                'ts':             time.time(),
            }
        except (ValueError, IndexError, ZeroDivisionError):
            return None

    # ── WebSocket loop ──────────────────────────────────────────────────

    async def run(self, pairs: list[str]):
        self.running = True
        self._pairs  = list(pairs)
        if not self._pairs:
            log_message("⚠️ OrderBookManager: no pairs supplied — idle")
            return

        # Build stream chunks under the 180-per-conn limit
        all_streams = [f"{p.lower()}@depth{_DEPTH_LEVELS}@{_DEPTH_INTERVAL}" for p in self._pairs]
        chunks = []
        for i in range(0, len(all_streams), _MAX_STREAMS_PER_CONN):
            chunk = all_streams[i:i + _MAX_STREAMS_PER_CONN]
            chunks.append(_FUTURES_STREAM_URL.format(streams="/".join(chunk)))

        log_message(
            f"📚 OrderBookManager: {len(self._pairs)} pairs across {len(chunks)} WS connection(s) "
            f"(@depth{_DEPTH_LEVELS}@{_DEPTH_INTERVAL})"
        )

        # Spawn one task per chunk
        await asyncio.gather(
            *(self._run_chunk(url, idx) for idx, url in enumerate(chunks)),
            return_exceptions=True,
        )

    async def _run_chunk(self, url: str, idx: int):
        delay = _RECONNECT_BASE
        while self.running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    open_timeout=15,
                    max_size=2**22,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message(f"✅ OrderBookManager chunk #{idx} connected")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data", msg)
                            sym  = data.get("s")
                            bids = data.get("b") or []
                            asks = data.get("a") or []
                            if not sym or not bids or not asks:
                                continue
                            now = time.time()
                            self._books[sym] = {"b": bids, "a": asks, "ts": now}
                            feat = self._compute_features(sym, bids, asks)
                            if feat:
                                self._features[sym] = feat
                            self._msgs_rx += 1
                            # heartbeat
                            if now - self._last_log > 300:
                                log_message(
                                    f"📚 OrderBookManager heartbeat: {len(self._books)} pairs, "
                                    f"{self._msgs_rx:,} msgs rx"
                                )
                                self._last_log = now
                        except Exception:
                            continue
            except asyncio.CancelledError:
                return
            except Exception as e:
                log_message(f"⚠️ OrderBookManager chunk #{idx} error: {e!r} — reconnecting in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)


# Module-level singleton
ORDERBOOK = OrderBookManager()
