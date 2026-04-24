"""
Liquidation Collector — Real-time forced liquidation data from Binance

Subscribes to wss://fstream.binance.com/ws/!forceOrder@arr
ONE connection covers ALL USDT perpetual pairs (~700 symbols).

Data structure per symbol:
  buckets: dict[price_band -> {long_liq_usd, short_liq_usd, count, last_ts}]
  price_band = round(price to nearest BUCKET_PCT% of price)
  Rolling 24h window — events older than 24h are pruned hourly.

Usage (from app.py):
  from liquidation_collector import LiquidationCollector
  collector = LiquidationCollector()
  asyncio.create_task(collector.run())          # start background task
  data = collector.get_heatmap("BTCUSDT")       # get per-pair heatmap
  summary = collector.get_summary()             # top symbols by liquidation volume
"""

import asyncio
import json
import time
import sqlite3
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

try:
    import websockets
except ImportError:
    websockets = None

# ── Config ──────────────────────────────────────────────────────────────
_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
_BUCKET_PCT = 0.0025      # 0.25% price bands
_WINDOW_HOURS = 24        # Rolling window
_PRUNE_INTERVAL = 3600    # Prune old events every 1h
_PERSIST_INTERVAL = 300   # SQLite batch write every 5 min
_DB_PATH = Path(__file__).parent / "liquidation_history.db"
_MAX_EVENTS_PER_SYMBOL = 10000  # Safety cap per symbol in memory
_ALERT_MIN_USD = 50_000         # Minimum USD for the large-event ring buffer
_ALERT_RING_SIZE = 2000         # Max events kept in the alert ring buffer


def _price_bucket(price: float) -> float:
    """Round price to nearest BUCKET_PCT% band."""
    if price <= 0:
        return 0.0
    band = price * _BUCKET_PCT
    return round(round(price / band) * band, 10)


class LiquidationCollector:
    """
    Collects real liquidation events from Binance forceOrder stream.
    Maintains an in-memory rolling 24h heatmap per symbol.
    """

    def __init__(self):
        # symbol -> {bucket_price -> {long_liq_usd, short_liq_usd, count, last_ts}}
        self._buckets: dict[str, dict[float, dict]] = defaultdict(lambda: defaultdict(
            lambda: {"long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0, "last_ts": 0}
        ))

        # Raw event log for 24h window pruning: symbol -> [(ts, bucket, side, usd)]
        self._events: dict[str, list] = defaultdict(list)

        # Summary stats
        self._total_events = 0
        self._total_usd = 0.0
        self._connected = False

        # Ring buffer of large liquidation events for watchlist alerts
        from collections import deque as _deque
        self._large_events: _deque = _deque(maxlen=_ALERT_RING_SIZE)
        self._last_prune = time.time()
        self._last_persist = time.time()
        self._start_time = time.time()

        self._init_db()

    # ── SQLite Persistence ───────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                notional_usd REAL NOT NULL,
                timestamp INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_symbol_ts ON liquidations(symbol, timestamp)")
        conn.commit()
        conn.close()

    def _persist_recent(self, batch: list):
        """Write a batch of events to SQLite."""
        if not batch:
            return
        try:
            conn = sqlite3.connect(_DB_PATH)
            conn.executemany(
                "INSERT INTO liquidations (symbol, side, price, quantity, notional_usd, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[liq_collector] DB write error: {e}")

    def load_from_db(self, hours: int = 24):
        """Bootstrap in-memory buckets from SQLite on startup."""
        cutoff = int(time.time() * 1000) - (hours * 3600 * 1000)
        try:
            conn = sqlite3.connect(_DB_PATH)
            rows = conn.execute(
                "SELECT symbol, side, price, notional_usd, timestamp FROM liquidations WHERE timestamp > ?",
                (cutoff,)
            ).fetchall()
            conn.close()

            for symbol, side, price, notional, ts in rows:
                bucket = _price_bucket(price)
                ts_sec = ts / 1000
                self._events[symbol].append((ts_sec, bucket, side, notional))
                if side == "SELL":  # SELL = long got liquidated
                    self._buckets[symbol][bucket]["long_liq_usd"] += notional
                else:               # BUY = short got liquidated
                    self._buckets[symbol][bucket]["short_liq_usd"] += notional
                self._buckets[symbol][bucket]["count"] += 1
                self._buckets[symbol][bucket]["last_ts"] = max(
                    self._buckets[symbol][bucket]["last_ts"], ts_sec
                )

            print(f"[liq_collector] Loaded {len(rows)} events from DB ({len(self._buckets)} symbols)")
        except Exception as e:
            print(f"[liq_collector] DB load error: {e}")

    # ── Event Processing ─────────────────────────────────────────────────

    def _process_event(self, msg: dict) -> Optional[tuple]:
        """
        Parse a forceOrder event. Returns (symbol, side, price, qty, notional, ts_ms) or None.

        Event structure:
          e: "forceOrder"
          o.s: symbol (e.g. "BTCUSDT")
          o.S: side ("SELL" = long liq, "BUY" = short liq)
          o.ap: average fill price
          o.q: original quantity
          o.T: trade timestamp (ms)
        """
        try:
            if msg.get("e") != "forceOrder":
                return None
            order = msg.get("o", {})
            symbol = order.get("s", "")
            if not symbol.endswith("USDT"):
                return None
            side = order.get("S", "")
            price = float(order.get("ap", order.get("p", 0)))
            qty = float(order.get("z", order.get("q", 0)))
            ts_ms = int(order.get("T", time.time() * 1000))

            if price <= 0 or qty <= 0:
                return None

            notional = price * qty
            return symbol, side, price, qty, notional, ts_ms
        except Exception:
            return None

    def _add_event(self, symbol: str, side: str, price: float,
                   qty: float, notional: float, ts_ms: int):
        """Add a parsed event to in-memory buckets."""
        bucket = _price_bucket(price)
        ts_sec = ts_ms / 1000

        self._events[symbol].append((ts_sec, bucket, side, notional))

        b = self._buckets[symbol][bucket]
        if side == "SELL":   # long liquidated
            b["long_liq_usd"] += notional
        else:                # short liquidated
            b["short_liq_usd"] += notional
        b["count"] += 1
        b["last_ts"] = max(b["last_ts"], ts_sec)

        self._total_events += 1
        self._total_usd += notional

        # Buffer large events for watchlist alert delivery
        if notional >= _ALERT_MIN_USD:
            self._large_events.append({
                'symbol':   symbol,
                'type':     'LONG_LIQ' if side == 'SELL' else 'SHORT_LIQ',
                'price':    round(price, 8),
                'qty':      round(qty, 6),
                'usd':      round(notional, 2),
                'ts':       ts_sec,
            })

        # Safety cap
        if len(self._events[symbol]) > _MAX_EVENTS_PER_SYMBOL:
            self._events[symbol] = self._events[symbol][-_MAX_EVENTS_PER_SYMBOL:]

    # ── Rolling Window Pruning ────────────────────────────────────────────

    def _prune_old_events(self):
        """Remove events older than 24h from memory and rebuild buckets."""
        cutoff = time.time() - (_WINDOW_HOURS * 3600)
        pruned_symbols = 0

        for symbol in list(self._events.keys()):
            events = self._events[symbol]
            fresh = [(ts, b, side, usd) for ts, b, side, usd in events if ts >= cutoff]

            if len(fresh) == len(events):
                continue  # Nothing to prune

            # Rebuild buckets for this symbol
            pruned_symbols += 1
            self._events[symbol] = fresh
            self._buckets[symbol] = defaultdict(
                lambda: {"long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0, "last_ts": 0}
            )
            for ts, bucket, side, notional in fresh:
                b = self._buckets[symbol][bucket]
                if side == "SELL":
                    b["long_liq_usd"] += notional
                else:
                    b["short_liq_usd"] += notional
                b["count"] += 1
                b["last_ts"] = max(b["last_ts"], ts)

        if pruned_symbols:
            print(f"[liq_collector] Pruned {pruned_symbols} symbols (24h window)")

    # ── Public API ───────────────────────────────────────────────────────

    def get_heatmap(self, symbol: str, max_buckets: int = 100) -> dict:
        """
        Return liquidation heatmap for a symbol.

        Returns:
          symbol: str
          buckets: list of {price, long_liq_usd, short_liq_usd, count, last_ts}
            sorted by price ascending
          total_long_24h: float (USD)
          total_short_24h: float (USD)
          total_events_24h: int
          window_hours: int
          has_data: bool
        """
        buckets_raw = self._buckets.get(symbol, {})

        if not buckets_raw:
            return {
                "symbol": symbol,
                "buckets": [],
                "total_long_24h": 0,
                "total_short_24h": 0,
                "total_events_24h": 0,
                "window_hours": _WINDOW_HOURS,
                "has_data": False,
            }

        total_long = sum(b["long_liq_usd"] for b in buckets_raw.values())
        total_short = sum(b["short_liq_usd"] for b in buckets_raw.values())
        total_events = sum(b["count"] for b in buckets_raw.values())

        # Sort by price, keep top max_buckets by total volume
        all_buckets = [
            {
                "price": price,
                "long_liq_usd": round(b["long_liq_usd"], 2),
                "short_liq_usd": round(b["short_liq_usd"], 2),
                "total_usd": round(b["long_liq_usd"] + b["short_liq_usd"], 2),
                "count": b["count"],
                "last_ts": b["last_ts"],
            }
            for price, b in buckets_raw.items()
        ]

        # Sort by total volume desc, take top N, then sort by price for display
        all_buckets.sort(key=lambda x: x["total_usd"], reverse=True)
        top_buckets = all_buckets[:max_buckets]
        top_buckets.sort(key=lambda x: x["price"])

        return {
            "symbol": symbol,
            "buckets": top_buckets,
            "total_long_24h": round(total_long, 2),
            "total_short_24h": round(total_short, 2),
            "total_events_24h": total_events,
            "window_hours": _WINDOW_HOURS,
            "has_data": True,
        }

    def get_events_since(self, symbols: set, min_usd: float, since_ts: float) -> list:
        """Return large events matching symbols/threshold since a timestamp."""
        return [
            e for e in self._large_events
            if e['symbol'] in symbols
            and e['usd'] >= min_usd
            and e['ts'] > since_ts
        ]

    def get_summary(self, top_n: int = 20) -> list:
        """Return top N symbols by total liquidation volume in last 24h."""
        result = []
        for symbol, buckets_raw in self._buckets.items():
            if not buckets_raw:
                continue
            total_long = sum(b["long_liq_usd"] for b in buckets_raw.values())
            total_short = sum(b["short_liq_usd"] for b in buckets_raw.values())
            total = total_long + total_short
            if total <= 0:
                continue
            result.append({
                "symbol": symbol,
                "total_usd": round(total, 2),
                "long_liq_usd": round(total_long, 2),
                "short_liq_usd": round(total_short, 2),
                "events": sum(b["count"] for b in buckets_raw.values()),
                "dominant": "LONG" if total_long > total_short else "SHORT",
            })

        result.sort(key=lambda x: x["total_usd"], reverse=True)
        return result[:top_n]

    def get_heatmap_window(self, symbol: str, hours: int, max_buckets: int = 100) -> dict:
        """
        Return liquidation heatmap for any time window using SQLite.
        For windows <= 24h this supplements in-memory data.
        For windows > 24h this is the only source.
        """
        cutoff = int((time.time() - hours * 3600) * 1000)
        try:
            conn = sqlite3.connect(_DB_PATH)
            rows = conn.execute(
                "SELECT side, price, notional_usd FROM liquidations WHERE symbol=? AND timestamp > ?",
                (symbol, cutoff)
            ).fetchall()
            conn.close()
        except Exception as e:
            return {"symbol": symbol, "buckets": [], "total_long_24h": 0,
                    "total_short_24h": 0, "total_events_24h": 0,
                    "window_hours": hours, "has_data": False}

        if not rows:
            return {"symbol": symbol, "buckets": [], "total_long_24h": 0,
                    "total_short_24h": 0, "total_events_24h": 0,
                    "window_hours": hours, "has_data": False}

        buckets_raw: dict[float, dict] = defaultdict(
            lambda: {"long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0}
        )
        for side, price, notional in rows:
            bucket = _price_bucket(price)
            if side == "SELL":
                buckets_raw[bucket]["long_liq_usd"] += notional
            else:
                buckets_raw[bucket]["short_liq_usd"] += notional
            buckets_raw[bucket]["count"] += 1

        total_long  = sum(b["long_liq_usd"]  for b in buckets_raw.values())
        total_short = sum(b["short_liq_usd"] for b in buckets_raw.values())
        total_events = sum(b["count"]         for b in buckets_raw.values())

        all_buckets = [
            {"price": price,
             "long_liq_usd":  round(b["long_liq_usd"],  2),
             "short_liq_usd": round(b["short_liq_usd"], 2),
             "total_usd": round(b["long_liq_usd"] + b["short_liq_usd"], 2),
             "count": b["count"], "last_ts": 0}
            for price, b in buckets_raw.items()
        ]
        all_buckets.sort(key=lambda x: x["total_usd"], reverse=True)
        top_buckets = all_buckets[:max_buckets]
        top_buckets.sort(key=lambda x: x["price"])

        return {
            "symbol": symbol,
            "buckets": top_buckets,
            "total_long_24h":   round(total_long,   2),
            "total_short_24h":  round(total_short,  2),
            "total_events_24h": total_events,
            "window_hours": hours,
            "has_data": True,
        }

    def get_velocity(self, symbol: str, window_minutes: int = 10) -> dict:
        """
        Return per-minute liquidation rate for the last window_minutes.
        Uses in-memory events — fast, no DB query.
        """
        now = time.time()
        cutoff = now - window_minutes * 60
        events = self._events.get(symbol, [])

        by_minute: dict[int, dict] = {}
        for ts, bucket, side, notional in events:
            if ts < cutoff:
                continue
            mkey = int(ts // 60)
            if mkey not in by_minute:
                by_minute[mkey] = {"count": 0, "long_usd": 0.0, "short_usd": 0.0}
            by_minute[mkey]["count"] += 1
            if side == "SELL":
                by_minute[mkey]["long_usd"] += notional
            else:
                by_minute[mkey]["short_usd"] += notional

        result = []
        for i in range(window_minutes):
            mkey = int((now - (window_minutes - 1 - i) * 60) // 60)
            d = by_minute.get(mkey, {"count": 0, "long_usd": 0.0, "short_usd": 0.0})
            result.append({
                "minute": i,
                "count": d["count"],
                "long_usd": round(d["long_usd"], 2),
                "short_usd": round(d["short_usd"], 2),
            })

        counts = [r["count"] for r in result]
        current_rate = counts[-1] if counts else 0
        avg_rate = sum(counts) / len(counts) if counts else 0
        max_rate  = max(counts) if counts else 0
        spike = (current_rate > avg_rate * 2.5) and current_rate >= 3

        return {
            "symbol":       symbol,
            "window_min":   window_minutes,
            "by_minute":    result,
            "current_rate": current_rate,
            "avg_rate":     round(avg_rate, 2),
            "max_rate":     max_rate,
            "spike":        spike,
        }

    def get_stats(self) -> dict:
        """Return collector statistics."""
        uptime = time.time() - self._start_time
        return {
            "connected": self._connected,
            "total_events": self._total_events,
            "total_usd": round(self._total_usd, 2),
            "symbols_tracked": len(self._buckets),
            "uptime_hours": round(uptime / 3600, 2),
            "events_per_hour": round(self._total_events / max(uptime / 3600, 0.01), 1),
        }

    # ── WebSocket Runner ─────────────────────────────────────────────────

    async def run(self):
        """Main async loop — connects to forceOrder stream and processes events."""
        if websockets is None:
            print("[liq_collector] websockets package not installed, skipping")
            return

        # Bootstrap from DB on startup
        self.load_from_db()

        persist_batch = []
        backoff = 1

        while True:
            try:
                print(f"[liq_collector] Connecting to {_WS_URL}")
                async with websockets.connect(
                    _WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=2 * 1024 * 1024,
                    close_timeout=5,
                ) as ws:
                    self._connected = True
                    backoff = 1
                    print("[liq_collector] ✅ Connected to !forceOrder@arr stream")

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            parsed = self._process_event(msg)
                            if parsed:
                                symbol, side, price, qty, notional, ts_ms = parsed
                                self._add_event(symbol, side, price, qty, notional, ts_ms)
                                persist_batch.append((symbol, side, price, qty, notional, ts_ms))
                        except Exception:
                            pass

                        now = time.time()

                        # Batch persist to SQLite
                        if now - self._last_persist >= _PERSIST_INTERVAL and persist_batch:
                            await asyncio.to_thread(self._persist_recent, persist_batch.copy())
                            persist_batch.clear()
                            self._last_persist = now

                        # Prune old events
                        if now - self._last_prune >= _PRUNE_INTERVAL:
                            await asyncio.to_thread(self._prune_old_events)
                            self._last_prune = now
                            stats = self.get_stats()
                            summary = self.get_summary(5)
                            top = ", ".join(f"{s['symbol']}=${s['total_usd']/1e6:.1f}M" for s in summary)
                            print(f"[liq_collector] Stats: {stats['total_events']} events | "
                                  f"${stats['total_usd']/1e6:.1f}M | {stats['symbols_tracked']} symbols | "
                                  f"Top: {top}")

            except Exception as e:
                self._connected = False
                print(f"[liq_collector] Disconnected: {e} — reconnecting in {backoff}s")
                if persist_batch:
                    await asyncio.to_thread(self._persist_recent, persist_batch.copy())
                    persist_batch.clear()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


# ── Singleton ─────────────────────────────────────────────────────────
_collector: Optional[LiquidationCollector] = None


def get_collector() -> LiquidationCollector:
    global _collector
    if _collector is None:
        _collector = LiquidationCollector()
    return _collector
