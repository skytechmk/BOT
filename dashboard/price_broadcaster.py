"""
Price Broadcaster — single Binance WebSocket consumer that fans out mark
prices to all connected dashboard SSE clients.

Architecture:

    Binance !markPrice@arr@1s  ──►  PriceBroadcaster  ──►  asyncio.Queue (per client)
                                         │                     │
                                         │                     ├─► SSE client 1 (user A)
                                         │                     ├─► SSE client 2 (user B)
                                         └ in-memory prices     └─► SSE client N

Benefits over per-user polling:
  • One upstream WS instead of N REST calls
  • All users see the same tick at the same moment
  • Backend CPU + network drops linearly with user count
  • Identical prices across the whole platform (no drift between users)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, Optional, Set

import websockets


_WS_URL          = "wss://fstream.binance.com/market/stream?streams=!markPrice@arr@1s"
_RECONNECT_BASE  = 2
_RECONNECT_MAX   = 60
_BROADCAST_HZ    = 0.5      # 2-second tick cadence for fan-out
_KEEPALIVE_SEC   = 15       # send `:ping` comment to SSE clients when idle
_QUEUE_MAXSIZE   = 32       # drop oldest if a slow client falls behind


class PriceBroadcaster:
    """Single WS consumer, multi-SSE fan-out."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {}
        self._last_ts: float = 0.0
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running = False

    # ─── public API ─────────────────────────────────────────────────────

    def get(self, pair: str) -> Optional[float]:
        return self._prices.get(pair)

    def snapshot(self) -> Dict[str, float]:
        """Return a shallow copy of the current price cache."""
        return dict(self._prices)

    def stats(self) -> dict:
        return {
            "pairs":       len(self._prices),
            "subscribers": len(self._subscribers),
            "last_ts":     self._last_ts,
            "age":         round(time.time() - self._last_ts, 2) if self._last_ts else None,
        }

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.add(q)
        # Prime the new subscriber with the full snapshot so it can render
        # immediately without waiting for the next broadcast tick.
        try:
            q.put_nowait({"type": "snapshot", "prices": self.snapshot(), "ts": self._last_ts})
        except asyncio.QueueFull:
            pass
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    # ─── internal: Binance WS consumer ──────────────────────────────────

    async def run(self) -> None:
        self._running = True
        asyncio.create_task(self._broadcast_loop())
        delay = _RECONNECT_BASE
        while self._running:
            try:
                async with websockets.connect(
                    _WS_URL,
                    ping_interval=20,
                    ping_timeout=15,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_BASE
                    print("[price_broadcaster] ✅ connected (!markPrice@arr@1s)", flush=True)
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data")
                            if not isinstance(data, list):
                                continue
                            now = time.time()
                            for entry in data:
                                sym = entry.get("s")
                                mp  = entry.get("p")
                                if not sym or mp is None:
                                    continue
                                try:
                                    self._prices[sym] = float(mp)
                                except (TypeError, ValueError):
                                    continue
                            self._last_ts = now
                        except Exception:
                            continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[price_broadcaster] ⚠️  disconnected: {e}; reconnect in {delay}s", flush=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)

    # ─── internal: broadcast loop (fan-out) ─────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Every ~2 s, push the full price snapshot to every subscriber queue."""
        interval = 1.0 / _BROADCAST_HZ
        while self._running:
            await asyncio.sleep(interval)
            if not self._prices or not self._subscribers:
                continue
            payload = {"type": "tick", "prices": self.snapshot(), "ts": self._last_ts}
            # Copy to avoid mutation during iteration
            async with self._lock:
                subs = list(self._subscribers)
            for q in subs:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    # Slow client: drop oldest, enqueue newest
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except Exception:
                        pass

    def stop(self) -> None:
        self._running = False


# Global singleton
PRICE_BROADCASTER = PriceBroadcaster()
