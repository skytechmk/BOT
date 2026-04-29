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
from typing import Dict, Optional, Set, TypedDict

import websockets


_WS_URL          = "wss://fstream.binance.com/market/stream?streams=!markPrice@arr@1s"
_RECONNECT_BASE  = 2
_RECONNECT_MAX   = 60
_BROADCAST_HZ    = 1.0      # 1-second tick cadence for fan-out
_KEEPALIVE_SEC   = 15       # send `:ping` comment to SSE clients when idle
_QUEUE_MAXSIZE   = 32       # drop oldest if a slow client falls behind

# ── Circuit Breaker thresholds ──
_LATENCY_TRIP_MS       = 500   # delta_ms threshold to count as a spike
_LATENCY_CONSECUTIVE   = 3     # consecutive spikes required to trip breaker


class PriceBroadcaster:
    """Single WS consumer, multi-SSE fan-out."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {}
        self._last_ts: float = 0.0
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running = False
        # ── Circuit Breaker latency tracking ──
        self._latency_spike_count: int = 0
        self._breaker_tripped: bool = False

    # ─── public API ─────────────────────────────────────────────────────

    def get(self, pair: str) -> Optional[float]:
        return self._prices.get(pair)

    def snapshot(self) -> Dict[str, float]:
        """Return a shallow copy of the current price cache."""
        return dict(self._prices)

    class PriceBroadcasterStatsDict(TypedDict):
        pairs: int
        subscribers: int
        last_ts: float
        age: Optional[float]

    def stats(self) -> PriceBroadcasterStatsDict:
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
        asyncio.create_task(self._stale_watchdog())
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
                    self._breaker_tripped = False
                    self._latency_spike_count = 0
                    print("[price_broadcaster] ✅ connected (!markPrice@arr@1s)", flush=True)
                    async for raw in ws:
                        if not self._running:
                            return
                        self._last_ts = time.time()
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data")
                            if not isinstance(data, list):
                                continue
                            now = time.time()
                            now_ms = int(now * 1000)
                            event_times = []
                            for entry in data:
                                sym = entry.get("s")
                                mp  = entry.get("p")
                                et  = entry.get("E")
                                if not sym or mp is None:
                                    continue
                                if not isinstance(sym, str) or not sym.endswith('USDT'):
                                    continue
                                try:
                                    self._prices[sym] = float(mp)
                                except (TypeError, ValueError):
                                    continue
                                if et is not None:
                                    event_times.append(int(et))

                            if event_times:
                                earliest_event_ms = min(event_times)
                                delta_ms = abs(now_ms - earliest_event_ms)
                                await self._check_latency(delta_ms)
                        except Exception:
                            continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[price_broadcaster] ⚠️  disconnected: {e}; reconnect in {delay}s", flush=True)
                await self._trip_breaker_on_disconnect(str(e))
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)

    # ─── internal: broadcast loop (fan-out) ─────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Every ~1 s, push the full price snapshot to every subscriber queue."""
        interval = 1.0 / _BROADCAST_HZ
        while self._running:
            await asyncio.sleep(interval)
            if not self._prices or not self._subscribers:
                continue
            payload = {"type": "tick", "prices": self.snapshot(), "ts": self._last_ts}
            async with self._lock:
                subs = list(self._subscribers)
            for q in subs:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except Exception:
                        pass

    def stop(self) -> None:
        self._running = False

    # ─── Circuit Breaker triggers ────────────────────────────────────────

    async def _check_latency(self, delta_ms: int) -> None:
        """
        Non-blocking latency monitor integrated into the WS event loop.

        If delta_ms > 500 for three consecutive ticks, trips the circuit breaker
        to halt new trade entries during exchange latency spikes.
        Resets the counter on any healthy tick.
        """
        if delta_ms > _LATENCY_TRIP_MS:
            self._latency_spike_count += 1
            if self._latency_spike_count >= _LATENCY_CONSECUTIVE and not self._breaker_tripped:
                self._breaker_tripped = True
                asyncio.create_task(
                    self._trip_circuit_breaker(
                        f"Exchange latency {delta_ms}ms for {_LATENCY_CONSECUTIVE} consecutive ticks"
                    )
                )
        else:
            self._latency_spike_count = 0

    async def _trip_circuit_breaker(self, reason: str) -> None:
        """Set the distributed circuit breaker to OPEN state."""
        try:
            from dashboard.redis_cache import set_circuit_breaker
            await set_circuit_breaker(True, reason=reason)
            print(f"[price_broadcaster] 🚨 CIRCUIT BREAKER OPENED: {reason}", flush=True)
        except Exception as e:
            print(f"[price_broadcaster] ⚠️  Failed to trip circuit breaker: {e}", flush=True)

    async def _trip_breaker_on_disconnect(self, disconnect_reason: str) -> None:
        """Trip the circuit breaker on unexpected WS disconnection."""
        if not self._breaker_tripped:
            self._breaker_tripped = True
            asyncio.create_task(
                self._trip_circuit_breaker(
                    f"WebSocket disconnected: {disconnect_reason}"
                )
            )

    async def _stale_watchdog(self) -> None:
        """Background coroutine: if no WS tick arrives for 60s, log + trip breaker."""
        while self._running:
            await asyncio.sleep(30)
            if self._last_ts > 0 and time.time() - self._last_ts > 60:
                print("[price_broadcaster] ⚠️  STALL: >60s since last tick — tripping breaker", flush=True)
                if not self._breaker_tripped:
                    self._breaker_tripped = True
                    await self._trip_circuit_breaker("WS data stall (>60s no tick)")


# Global singleton
PRICE_BROADCASTER = PriceBroadcaster()
