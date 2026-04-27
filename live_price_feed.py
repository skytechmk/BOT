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


# Binance split futures WS endpoints into /public and /market categories;
# !markPrice@arr@1s lives on /market, !bookTicker lives on /public, so we
# run two concurrent connections.
_WS_MARKPRICE_URL = "wss://fstream.binance.com/market/stream?streams=!markPrice@arr@1s"
_WS_BOOKTICKER_URL = "wss://fstream.binance.com/public/stream?streams=!bookTicker"
_RECONNECT_BASE  = 2
_RECONNECT_MAX   = 60
_DEFAULT_MAX_AGE = 10.0   # seconds — after this, a cached entry is "stale"


class LivePriceFeed:
    """Singleton — import LIVE_FEED, start once with asyncio.create_task(LIVE_FEED.run())."""

    def __init__(self):
        # mark dict carries: mark, index, funding_rate, next_funding_ts, ts.
        # The funding fields come for free in markPrice@arr@1s — capturing them
        # here eliminates a per-pair-per-cycle REST call to futures_funding_rate.
        self._mark: dict = {}      # pair → {mark, index, funding_rate, next_funding_ts, ts}
        self._book: dict = {}      # pair → {bid, ask, bid_qty, ask_qty, ts}
        # Per-pair funding-rate history (rolling deque). Appended when we
        # observe a new settlement (next_funding_ts advances). Deeper history
        # than this still falls back to REST.
        from collections import deque as _deque
        self._funding_history: dict = {}    # pair → deque[(ts, rate)]
        self._FUNDING_HIST_MAX = 30          # ~10 days @ 8h cadence
        self._deque = _deque
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

    def get_funding_rate(self, pair: str, max_age_s: float = 30.0):
        """Return (rate, next_funding_ts_ms) from WS markPrice@1s, or None if
        not yet observed / stale. Callers can fall back to REST on None."""
        m = self._mark.get(pair)
        if not m:
            return None
        if time.time() - m['ts'] > max_age_s:
            return None
        return (m.get('funding_rate', 0.0), m.get('next_funding_ts', 0))

    def get_funding_history(self, pair: str, limit: int = 10):
        """Return list[(funding_ts_ms, rate)] of the last `limit` settlements
        observed via WS. May be shorter than `limit` if uptime is short.
        Callers should fall back to REST when this returns fewer than `limit`."""
        hist = self._funding_history.get(pair)
        if not hist:
            return []
        # Most-recent last → return newest `limit` items
        return list(hist)[-limit:]

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
        """Main loop — spawns one task per WS endpoint (/market + /public).
        Cross-category subscriptions are no longer allowed on the new
        Binance futures WS endpoints, so markPrice and bookTicker run on
        separate connections."""
        self.running = True
        await asyncio.gather(
            self._run_one(_WS_MARKPRICE_URL,  "markPrice@arr@1s"),
            self._run_one(_WS_BOOKTICKER_URL, "!bookTicker"),
            return_exceptions=True,
        )

    async def _run_one(self, url: str, label: str):
        """Run a single WS connection with reconnect/backoff."""
        delay = _RECONNECT_BASE
        while self.running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**22,
                    compression=None,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message(f"✅ LivePriceFeed connected ({label})")
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
                                # Aggregate stream: data is a list of per-symbol dicts.
                                # Each item has: e, E, s, p (mark), i (index),
                                # P (estSettle), r (funding rate), T (next funding ms).
                                if isinstance(data, list):
                                    for d in data:
                                        s = d.get('s')
                                        if not s:
                                            continue
                                        try:
                                            new_funding = float(d.get('r') or 0)
                                        except Exception:
                                            new_funding = 0.0
                                        try:
                                            next_T = int(d.get('T') or 0)
                                        except Exception:
                                            next_T = 0

                                        prev = self._mark.get(s)
                                        # Detect funding settlement: next_funding_ts advanced
                                        # past the previously-known one → append the OLD rate
                                        # to history (it's now "the rate that just settled").
                                        if prev:
                                            prev_T = prev.get('next_funding_ts') or 0
                                            if next_T and prev_T and next_T > prev_T:
                                                hist = self._funding_history.get(s)
                                                if hist is None:
                                                    hist = self._deque(maxlen=self._FUNDING_HIST_MAX)
                                                    self._funding_history[s] = hist
                                                hist.append((prev_T, prev.get('funding_rate', 0.0)))

                                        self._mark[s] = {
                                            'mark':            float(d.get('p') or 0),
                                            'index':           float(d.get('i') or 0),
                                            'funding_rate':    new_funding,
                                            'next_funding_ts': next_T,
                                            'ts':              now,
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
