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
from utils_logger import log_message, set_context
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


_RECENT_WINDOW = 300     # 5 min — raw tick retention
_BUCKET_SPAN   = 60      # 1-min bucket granularity for historical data
_MAX_HISTORY   = 3600    # 1 hour total coverage


def _bucket_key(ts: float) -> int:
    """Floor a unix timestamp to its 1-minute bucket (integer seconds)."""
    return int(ts) // _BUCKET_SPAN * _BUCKET_SPAN


class _SymbolCVD:
    """Per-symbol rolling CVD state — hybrid storage architecture.

    Raw ticks are kept only for the last 5 minutes (_recent_trades) to
    serve the 1m and 5m windows at full fidelity.  As ticks age past
    the 5-min mark they are compressed into 1-minute aggregated buckets
    (_hist_buckets) keyed by floored minute-timestamp.  The 15m and 1h
    windows sum across relevant buckets + the raw recent window.

    Memory per symbol drops from O(trades_per_hour) to O(recent_5m + 55
    bucket structs), eliminating the OOM risk on high-volume pairs.
    """

    __slots__ = ('symbol', '_recent_trades', '_hist_buckets')

    def __init__(self, symbol: str):
        self.symbol = symbol
        # Raw ticks: (ts_float, buy_qty_float, sell_qty_float)
        self._recent_trades: deque = deque()
        # 1-minute buckets: bucket_key_int → [buy_vol, sell_vol, trade_count]
        self._hist_buckets: dict[int, list] = {}

    def record(self, ts: float, buy_qty: float, sell_qty: float):
        self._recent_trades.append((ts, buy_qty, sell_qty))

        # ── Compress: migrate trades older than 5 min into buckets ────
        recent_cutoff = ts - _RECENT_WINDOW
        while self._recent_trades and self._recent_trades[0][0] < recent_cutoff:
            old_ts, old_bq, old_sq = self._recent_trades.popleft()
            bk = _bucket_key(old_ts)
            bucket = self._hist_buckets.get(bk)
            if bucket is None:
                self._hist_buckets[bk] = [old_bq, old_sq, 1]
            else:
                bucket[0] += old_bq
                bucket[1] += old_sq
                bucket[2] += 1

        # ── Prune buckets older than 1 hour ───────────────────────────
        hist_cutoff = _bucket_key(ts - _MAX_HISTORY)
        stale = [k for k in self._hist_buckets if k < hist_cutoff]
        for k in stale:
            del self._hist_buckets[k]

    def snapshot(self) -> dict:
        now = time.time()
        result = {}

        # Pre-compute bucket sums for each window that needs them (15m, 1h).
        # Buckets cover data >5min old; recent trades cover ≤5min.
        for label, secs in _WINDOWS.items():
            cutoff = now - secs
            bvol = svol = 0.0
            n = 0

            # 1) Sum from recent raw trades (covers last 5 min)
            for (ts, bq, sq) in self._recent_trades:
                if ts < cutoff:
                    continue
                bvol += bq
                svol += sq
                n += 1

            # 2) For windows > 5 min, also sum from historical buckets
            if secs > _RECENT_WINDOW:
                bucket_cutoff = _bucket_key(cutoff)
                for bk, (bbuy, bsell, bcount) in self._hist_buckets.items():
                    if bk >= bucket_cutoff:
                        bvol += bbuy
                        svol += bsell
                        n += bcount

            total = bvol + svol
            result[f'cvd_{label}']       = round(bvol - svol, 4)
            result[f'buy_vol_{label}']   = round(bvol, 4)
            result[f'sell_vol_{label}']  = round(svol, 4)
            result[f'trades_{label}']    = n
            result[f'delta_pct_{label}'] = round((bvol - svol) / total, 4) if total > 0 else 0.0

        # Convenience aliases for the pipeline
        result['delta_pct'] = result['delta_pct_5m']
        result['total_trades_1m'] = result['trades_1m']
        result['buy_vol_1m']  = result['buy_vol_1m']
        result['sell_vol_1m'] = result['sell_vol_1m']
        
        # Async push to Redis cache
        try:
            from dashboard.redis_cache import set_cvd_bucket
            # We push the full snapshot to the 'latest' window key for this symbol
            asyncio.create_task(set_cvd_bucket(self.symbol, "latest", result))
        except Exception as e:
            log_message(f"Failed to dispatch Redis task: {e}")
            
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
        set_context("CVD-MAIN")
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
        set_context("CVD-TICK")
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
                                self._data[sym] = _SymbolCVD(sym)
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
