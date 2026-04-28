"""
MEXC Price Broadcaster — REST-polling equivalent of the Binance PriceBroadcaster.

MEXC has no broadcast markPrice@arr WebSocket stream. Instead, this module
polls the public ticker endpoint every 2 seconds to keep an in-memory cache
of all MEXC Futures mark prices.

Architecture:
    MEXC REST /api/v1/contract/ticker
           ↓  (every 2s)
      MexcPriceBroadcaster  ──►  asyncio.Queue (per SSE client)
             │                        │
             └ in-memory prices       ├─► SSE client 1
                                      └─► SSE client N

Usage in app.py:
    from mexc_price_broadcaster import MEXC_PRICE_BROADCASTER
    asyncio.create_task(MEXC_PRICE_BROADCASTER.run())
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional, Set

import requests

_TICKER_URL     = "https://api.mexc.com/api/v1/contract/ticker"
_POLL_INTERVAL  = 2.0        # seconds between REST polls
_BROADCAST_HZ   = 0.5        # 2-second tick cadence for SSE fan-out
_QUEUE_MAXSIZE  = 32
_REQUEST_TIMEOUT = 5


def _to_binance(mexc_sym: str) -> str:
    """BTC_USDT → BTCUSDT"""
    return mexc_sym.replace('_', '')


class MexcPriceBroadcaster:
    """REST-polling price cache for all MEXC Futures pairs."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {}   # Binance-format symbol → mark price
        self._last_ts: float = 0.0
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running = False

    # ─── public API (mirrors PriceBroadcaster interface) ──────────────

    def get(self, pair: str) -> Optional[float]:
        """Get mark price for a pair (Binance-format symbol, e.g. BTCUSDT)."""
        return self._prices.get(pair)

    def snapshot(self) -> Dict[str, float]:
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
        try:
            q.put_nowait({"type": "snapshot", "prices": self.snapshot(), "ts": self._last_ts})
        except asyncio.QueueFull:
            pass
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    # ─── internal: REST poll loop ─────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        asyncio.create_task(self._broadcast_loop())
        print("[mexc_price_broadcaster] 🟡 started (REST poll every 2s)", flush=True)
        while self._running:
            try:
                await asyncio.to_thread(self._fetch_prices)
            except Exception as e:
                print(f"[mexc_price_broadcaster] ⚠️  poll error: {e}", flush=True)
            await asyncio.sleep(_POLL_INTERVAL)

    def _fetch_prices(self) -> None:
        """Fetch all MEXC Futures tickers in one REST call (runs in thread)."""
        try:
            r = requests.get(_TICKER_URL, timeout=_REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            tickers = data.get('data', data) if isinstance(data, dict) else data
            if not isinstance(tickers, list):
                return
            now = time.time()
            for t in tickers:
                sym = t.get('symbol', '')
                fp = t.get('fairPrice') or t.get('lastPrice') or t.get('last', 0)
                if not sym or not fp:
                    continue
                try:
                    binance_sym = _to_binance(sym)
                    self._prices[binance_sym] = float(fp)
                except (TypeError, ValueError):
                    continue
            self._last_ts = now
        except Exception:
            raise

    # ─── internal: broadcast loop (SSE fan-out) ───────────────────────

    async def _broadcast_loop(self) -> None:
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


# Global singleton
MEXC_PRICE_BROADCASTER = MexcPriceBroadcaster()
