"""
MEXC Price Broadcaster — REST-polling equivalent of the Binance PriceBroadcaster.

MEXC has no broadcast markPrice@arr WebSocket stream. Instead, this module
polls the public ticker endpoint every 2 seconds to keep an in-memory cache
of all MEXC Futures mark prices.

Architecture:
    MEXC REST /api/v1/contract/ticker
           ↓  (every 2s, aiohttp)
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
import json
from typing import Dict, Optional, Set

import aiohttp

_TICKER_URL     = "https://api.mexc.com/api/v1/contract/ticker"
_POLL_INTERVAL  = 2.0        # seconds between REST polls
_BROADCAST_HZ   = 0.5        # 2-second tick cadence for SSE fan-out
_QUEUE_MAXSIZE  = 32
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=5)
_RECONNECT_BASE  = 2          # seconds — exponential backoff base
_RECONNECT_MAX   = 60         # seconds — backoff ceiling


def _to_binance(mexc_sym: str) -> str:
    """MEXC symbol → Binance-format symbol.  BTC_USDT → BTCUSDT."""
    s = mexc_sym.strip().upper().replace('_', '')
    return s if s.endswith('USDT') and len(s) > 4 else mexc_sym


class MexcPriceBroadcaster:
    """REST-polling price cache for all MEXC Futures pairs."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {}
        self._last_ts: float = 0.0
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None

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
        self._session = aiohttp.ClientSession(
            timeout=_REQUEST_TIMEOUT,
            connector=aiohttp.TCPConnector(limit=2, ttl_dns_cache=300, force_close=False),
        )
        backoff = _RECONNECT_BASE
        print("[mexc_price_broadcaster] 🟡 started (aiohttp poll every 2s)", flush=True)
        try:
            while self._running:
                try:
                    await self._fetch_prices()
                    backoff = _RECONNECT_BASE
                except asyncio.TimeoutError:
                    print(f"[mexc_price_broadcaster] ⚠️  poll timed out — backoff {backoff}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_MAX)
                except aiohttp.ClientError as e:
                    print(f"[mexc_price_broadcaster] ⚠️  HTTP error: {e} — backoff {backoff}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_MAX)
                except Exception as e:
                    print(f"[mexc_price_broadcaster] ⚠️  unexpected poll error: {type(e).__name__}: {e} — backoff {backoff}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_MAX)
                await asyncio.sleep(_POLL_INTERVAL)
        finally:
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None

    async def _fetch_prices(self) -> None:
        """Fetch all MEXC Futures tickers in one async REST call."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_REQUEST_TIMEOUT,
                connector=aiohttp.TCPConnector(limit=2, ttl_dns_cache=300, force_close=False),
            )
        async with self._session.get(_TICKER_URL) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
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
                fp_val = float(fp)
                if fp_val <= 0:
                    continue
                binance_sym = _to_binance(sym)
                if binance_sym.endswith('USDT') and len(binance_sym) > 4:
                    self._prices[binance_sym] = fp_val
            except (TypeError, ValueError):
                continue
        self._last_ts = now

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
