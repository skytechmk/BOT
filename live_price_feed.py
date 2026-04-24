"""
Live Price Feed — subscribes to Binance Futures WebSocket streams for:

  !markPrice@arr@1s   — every 1 s per symbol: markPrice + indexPrice + funding
  !bookTicker         — every book update per symbol: best bid / ask + quantities

Provides always-fresh prices for every USDT perp symbol in memory, eliminating
per-pair REST calls in the signal pipeline and exposing the true tradable
top-of-book for entry-price validation.

Usage (in main_async):
    from live_price_feed import LIVE_FEED
    asyncio.create_task(LIVE_FEED.run())

Then in process_pair():
    px = LIVE_FEED.get('BTCUSDT')    # dict or None
        → {
            mark, index,             # from markPrice stream
            bid, ask, mid,           # from bookTicker stream
            bid_qty, ask_qty,
            spread_bps,              # (ask-bid)/mid * 10_000
            mark_ts, book_ts,        # unix-second timestamps of last update
          }

Returns None until both streams have delivered at least one update for that
symbol, or if either stream data is older than `max_age_s` (default 10 s).
Callers should treat None as "fall back to REST".
"""
import asyncio
import json
import time

import websockets

from utils_logger import log_message


_WS_URL          = "wss://fstream.binance.com/stream?streams=!markPrice@arr@1s/!bookTicker"
_RECONNECT_BASE  = 2
_RECONNECT_MAX   = 60
_DEFAULT_MAX_AGE = 10.0   # seconds — after this, a cached entry is "stale"


class LivePriceFeed:
    """Singleton — import LIVE_FEED, start once with asyncio.create_task(LIVE_FEED.run())."""

    def __init__(self):
        self._mark: dict = {}      # pair → {mark, index, ts}
        self._book: dict = {}      # pair → {bid, ask, bid_qty, ask_qty, ts}
        self.running = False
        self._msgs_rx = 0
        self._last_log = 0

    # ── public API ──────────────────────────────────────────────────────────

    def get(self, pair: str, max_age_s: float = _DEFAULT_MAX_AGE):
        """Return merged live-price dict for `pair`, or None if unavailable / stale."""
        m = self._mark.get(pair)
        b = self._book.get(pair)
        if not m or not b:
            return None
        now = time.time()
        if now - m['ts'] > max_age_s or now - b['ts'] > max_age_s:
            return None
        bid, ask = b['bid'], b['ask']
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
        spread_bps = ((ask - bid) / mid * 10_000) if mid > 0 else float('inf')
        return {
            'mark':       m['mark'],
            'index':      m['index'],
            'bid':        bid,
            'ask':        ask,
            'bid_qty':    b['bid_qty'],
            'ask_qty':    b['ask_qty'],
            'mid':        mid,
            'spread_bps': spread_bps,
            'mark_ts':    m['ts'],
            'book_ts':    b['ts'],
        }

    def is_fresh(self, pair: str, max_age_s: float = _DEFAULT_MAX_AGE) -> bool:
        return self.get(pair, max_age_s) is not None

    def stats(self) -> dict:
        return {
            'mark_symbols': len(self._mark),
            'book_symbols': len(self._book),
            'msgs_rx':      self._msgs_rx,
        }

    def stop(self):
        self.running = False

    # ── WebSocket loop ──────────────────────────────────────────────────────

    async def run(self):
        """Main loop — opens WS, updates caches, auto-reconnects on drop."""
        self.running = True
        delay = _RECONNECT_BASE
        while self.running:
            try:
                async with websockets.connect(
                    _WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**22,
                    compression=None,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message("✅ LivePriceFeed connected (markPrice@1s + bookTicker)")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg    = json.loads(raw)
                            stream = msg.get('stream', '')
                            data   = msg.get('data', msg)
                            now    = time.time()
                            self._msgs_rx += 1

                            if stream.startswith('!markPrice'):
                                # Aggregate stream: data is a list of per-symbol dicts
                                if isinstance(data, list):
                                    for d in data:
                                        s = d.get('s')
                                        if not s:
                                            continue
                                        self._mark[s] = {
                                            'mark':  float(d.get('p') or 0),
                                            'index': float(d.get('i') or 0),
                                            'ts':    now,
                                        }
                            else:
                                # !bookTicker: one symbol per message
                                s = data.get('s') if isinstance(data, dict) else None
                                if not s:
                                    continue
                                self._book[s] = {
                                    'bid':     float(data.get('b') or 0),
                                    'ask':     float(data.get('a') or 0),
                                    'bid_qty': float(data.get('B') or 0),
                                    'ask_qty': float(data.get('A') or 0),
                                    'ts':      now,
                                }

                            # Periodic heartbeat log (once every 5 min)
                            if now - self._last_log > 300:
                                log_message(
                                    f"📡 LivePriceFeed: {len(self._mark)} mark / "
                                    f"{len(self._book)} book symbols | "
                                    f"{self._msgs_rx:,} msgs rx"
                                )
                                self._last_log = now
                        except Exception:
                            # A single bad message must not kill the feed
                            continue
            except asyncio.CancelledError:
                self.running = False
                return
            except Exception as e:
                log_message(f"⚠️ LivePriceFeed conn dropped: {e} — retry in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)


# Singleton — import and use directly
LIVE_FEED = LivePriceFeed()
