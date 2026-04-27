"""
cvd_stream_manager.py — Real-time Cumulative Volume Delta (CVD) via Binance aggTrade.

Subscribes to {symbol}@aggTrade WebSocket streams for top-N pairs.
Tracks per-symbol rolling CVD in 1m / 5m / 15m / 1h buckets.

CVD = Σ(buyer_qty) - Σ(seller_qty)
  Positive → buy pressure dominating
  Negative → sell pressure dominating

Usage:
    from cvd_stream_manager import CVD_FEED
    asyncio.create_task(CVD_FEED.run(pairs))   # start once in main_async

Then in process_pair():
    flow = CVD_FEED.get('BTCUSDT')   # dict or None
      → {
          cvd_1m, cvd_5m, cvd_15m, cvd_1h,   # cumulative delta per window
          buy_vol_1m, sell_vol_1m,            # raw volumes for delta_pct
          delta_pct_5m,                       # (buy-sell)/total in last 5m  (-1.0 to +1.0)
          total_trades_1m,                    # trade count for quality check
          last_update,                        # unix timestamp of last trade
        }
Returns None if no data received yet for that symbol.

Connection management:
  - Binance limit: 200 streams per connection
  - aggTrade is high-frequency; limit to top-50 pairs to avoid saturation
  - Reconnects automatically with exponential back-off
"""

import asyncio
import json
import time
from collections import defaultdict, deque
from utils_logger import log_message
import websockets

_FUTURES_STREAM_URL = "wss://fstream.binance.com/market/stream?streams={streams}"
_MAX_STREAMS_PER_CONN = 180          # stay under 200 limit
_MAX_PAIRS = 220                     # cover all USDT perps Binance scans
_RECONNECT_BASE = 3
_RECONNECT_MAX = 60

# Rolling window buckets in seconds
_WINDOWS = {
    '1m':  60,
    '5m':  300,
    '15m': 900,
    '1h':  3600,
}


class _SymbolCVD:
    """Per-symbol rolling CVD state using timestamped trade ring."""

    __slots__ = ('_trades', '_lock')

    def __init__(self):
        # Each element: (timestamp_float, buy_qty_float, sell_qty_float)
        self._trades: deque = deque()

    def record(self, ts: float, buy_qty: float, sell_qty: float):
        self._trades.append((ts, buy_qty, sell_qty))
        # Prune everything older than 1h
        cutoff = ts - 3600
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    def snapshot(self) -> dict:
        now = time.time()
        result = {}
        for label, secs in _WINDOWS.items():
            cutoff = now - secs
            bvol = svol = 0.0
            n = 0
            for (ts, bq, sq) in self._trades:
                if ts < cutoff:
                    continue
                bvol += bq
                svol += sq
                n += 1
            total = bvol + svol
            result[f'cvd_{label}']   = round(bvol - svol, 4)
            result[f'buy_vol_{label}']  = round(bvol, 4)
            result[f'sell_vol_{label}'] = round(svol, 4)
            result[f'trades_{label}'] = n
            result[f'delta_pct_{label}'] = round((bvol - svol) / total, 4) if total > 0 else 0.0

        # Convenience aliases for the pipeline
        result['delta_pct'] = result['delta_pct_5m']
        result['total_trades_1m'] = result['trades_1m']
        result['buy_vol_1m']  = result['buy_vol_1m']
        result['sell_vol_1m'] = result['sell_vol_1m']
        return result


class CVDFeed:
    """Singleton — import CVD_FEED, start once with asyncio.create_task(CVD_FEED.run(pairs))."""

    def __init__(self):
        self._data: dict[str, _SymbolCVD] = {}
        self._last_update: dict[str, float] = {}
        self.running = False
        self._active_pairs: list[str] = []
        self._msgs_rx = 0
        self._last_log = 0.0

    # ── public API ──────────────────────────────────────────────────────────

    def update_pairs(self, pairs: list):
        """Refresh the pair list (call each scan cycle). Restarts streams on change."""
        new = list(dict.fromkeys(pairs))[:_MAX_PAIRS]   # dedup + limit
        if new != self._active_pairs:
            self._active_pairs = new
            log_message(f"📊 CVD: pair list updated ({len(new)} pairs)")

    def get(self, symbol: str, max_age_s: float = 30.0) -> dict | None:
        """Return CVD snapshot for symbol, or None if stale / no data."""
        ts = self._last_update.get(symbol, 0)
        if not ts or (time.time() - ts) > max_age_s:
            return None
        cvd = self._data.get(symbol)
        if cvd is None:
            return None
        snap = cvd.snapshot()
        snap['last_update'] = ts
        return snap

    def all_symbols(self) -> list[str]:
        return list(self._data.keys())

    def stats(self) -> dict:
        return {
            'tracked_symbols': len(self._data),
            'active_pairs': len(self._active_pairs),
            'msgs_rx': self._msgs_rx,
        }

    def stop(self):
        self.running = False

    # ── WebSocket loop ──────────────────────────────────────────────────────

    async def run(self, initial_pairs: list):
        """Main entry — spawn chunk connections, reconnect on drop."""
        self.running = True
        self._active_pairs = list(dict.fromkeys(initial_pairs))[:_MAX_PAIRS]
        log_message(f"📊 CVDFeed starting for {len(self._active_pairs)} pairs")

        while self.running:
            if not self._active_pairs:
                await asyncio.sleep(5)
                continue

            chunks = self._build_chunks(self._active_pairs)
            tasks = [asyncio.create_task(self._run_one(url)) for url in chunks]
            try:
                await asyncio.gather(*tasks)
            except Exception as exc:
                log_message(f"⚠️ CVDFeed gather error: {exc}")
            for t in tasks:
                t.cancel()
            await asyncio.sleep(_RECONNECT_BASE)

    def _build_chunks(self, pairs: list) -> list[str]:
        streams = [f"{p.lower()}@aggTrade" for p in pairs]
        urls = []
        for i in range(0, len(streams), _MAX_STREAMS_PER_CONN):
            chunk = streams[i:i + _MAX_STREAMS_PER_CONN]
            urls.append(_FUTURES_STREAM_URL.format(streams="/".join(chunk)))
        return urls

    async def _run_one(self, url: str):
        delay = _RECONNECT_BASE
        while self.running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                    compression=None,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message("✅ CVDFeed connection established")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg  = json.loads(raw)
                            data = msg.get('data', msg)
                            if data.get('e') != 'aggTrade':
                                continue
                            sym  = data['s']
                            qty  = float(data['q'])
                            # m=True → seller is market maker → SELL order
                            # m=False → buyer is market maker → BUY order
                            maker = data.get('m', False)
                            buy_qty  = 0.0 if maker else qty
                            sell_qty = qty if maker else 0.0

                            if sym not in self._data:
                                self._data[sym] = _SymbolCVD()
                            ts = time.time()
                            self._data[sym].record(ts, buy_qty, sell_qty)
                            self._last_update[sym] = ts
                            self._msgs_rx += 1

                            now = time.time()
                            if now - self._last_log > 300:
                                log_message(
                                    f"📊 CVDFeed: {len(self._data)} symbols | "
                                    f"{self._msgs_rx:,} msgs rx"
                                )
                                self._last_log = now
                        except Exception:
                            continue
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log_message(f"⚠️ CVDFeed conn dropped: {exc} — retry in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)


# Singleton
CVD_FEED = CVDFeed()
