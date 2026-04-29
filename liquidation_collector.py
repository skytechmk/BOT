"""
Liquidation Collector — Real-time forced liquidation data from Binance → TimescaleDB

Subscribes to wss://fstream.binance.com/ws/!forceOrder@arr
ONE connection covers ALL USDT perpetual pairs (~700 symbols).

Storage: asyncpg → TimescaleDB hypertable with automatic 24h retention policy.
In-memory hot cache (defaultdict buckets) is kept for fast reads by the
dashboard API; it is rebuilt from DB on startup and updated live on each
incoming WebSocket event.

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
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

import asyncpg

try:
    import websockets
except ImportError:
    websockets = None

# ── Config ──────────────────────────────────────────────────────────────
_WS_URL = "wss://fstream.binance.com/market/ws/!forceOrder@arr"
_BUCKET_PCT = 0.0025       # 0.25% price bands
_WINDOW_HOURS = 24         # Rolling window
_ALERT_MIN_USD = 50_000    # Minimum USD for the large-event ring buffer
_ALERT_RING_SIZE = 2000    # Max events kept in the alert ring buffer
_INSERT_BATCH_SIZE = 50    # Flush to DB every N events (or every _FLUSH_INTERVAL)
_FLUSH_INTERVAL = 5.0      # Max seconds between DB flushes
_LOG_INTERVAL = 3600       # Stats log every 1h

# Postgres connection — reads from env or falls back to local dev defaults
_PG_DSN = os.getenv(
    "TIMESCALE_DSN",
    "postgresql://aladdin:aladdin_ts_2026@localhost:5432/aladdin"
)
_PG_MIN_POOL = 2
_PG_MAX_POOL = 10

# ── SQL ─────────────────────────────────────────────────────────────────
_SQL_CREATE = """
CREATE TABLE IF NOT EXISTS liquidations (
    symbol      TEXT             NOT NULL,
    side        TEXT             NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    qty         DOUBLE PRECISION NOT NULL,
    notional    DOUBLE PRECISION NOT NULL,
    timestamp   TIMESTAMPTZ      NOT NULL
);
"""
_SQL_HYPERTABLE = """
SELECT create_hypertable('liquidations', 'timestamp', if_not_exists => TRUE);
"""
_SQL_RETENTION = """
SELECT add_retention_policy('liquidations', INTERVAL '24 hours', if_not_exists => TRUE);
"""
_SQL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_liq_sym_ts ON liquidations (symbol, timestamp DESC);
"""
_SQL_INSERT = """
INSERT INTO liquidations (symbol, side, price, qty, notional, timestamp)
VALUES ($1, $2, $3, $4, $5, $6);
"""


def _price_bucket(price: float) -> float:
    """Round price to nearest BUCKET_PCT% band."""
    if price <= 0:
        return 0.0
    band = price * _BUCKET_PCT
    return round(round(price / band) * band, 10)


class LiquidationCollector:
    """
    Collects real liquidation events from Binance forceOrder stream.
    Persists to TimescaleDB via asyncpg.  In-memory cache for fast reads.
    """

    def __init__(self):
        # In-memory hot cache: symbol -> {bucket_price -> {long_liq_usd, short_liq_usd, count, last_ts}}
        self._buckets: dict[str, dict[float, dict]] = defaultdict(lambda: defaultdict(
            lambda: {"long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0, "last_ts": 0}
        ))

        # Summary stats
        self._total_events = 0
        self._total_usd = 0.0
        self._connected = False

        # Ring buffer of large liquidation events for watchlist alerts
        self._large_events: deque = deque(maxlen=_ALERT_RING_SIZE)

        # Recent events kept in memory for velocity calculations (last 30 min)
        self._recent_events: deque = deque(maxlen=50_000)

        self._start_time = time.time()
        self._last_log = 0.0

        # asyncpg pool (initialized in run())
        self._pool: Optional[asyncpg.Pool] = None

        # Write buffer
        self._write_buf: list = []
        self._last_flush = time.time()

    # ── AsyncPG Pool & Schema ────────────────────────────────────────────

    async def _ensure_pool(self):
        """Create or reconnect the asyncpg connection pool."""
        if self._pool is not None:
            try:
                async with self._pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                return  # pool is alive
            except Exception:
                try:
                    await self._pool.close()
                except Exception:
                    pass
                self._pool = None

        for attempt in range(5):
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=_PG_DSN,
                    min_size=_PG_MIN_POOL,
                    max_size=_PG_MAX_POOL,
                    command_timeout=15,
                )
                print(f"[liq_collector] ✅ asyncpg pool created ({_PG_MIN_POOL}-{_PG_MAX_POOL} conns)")
                return
            except Exception as e:
                wait = 2 ** attempt
                print(f"[liq_collector] Pool create failed (attempt {attempt+1}): {e} — retry in {wait}s")
                await asyncio.sleep(wait)

        print("[liq_collector] ❌ Could not create asyncpg pool after 5 attempts")

    async def _init_schema(self):
        """Create table, hypertable, retention policy, and index."""
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_SQL_CREATE)
                await conn.execute(_SQL_HYPERTABLE)
                await conn.execute(_SQL_RETENTION)
                await conn.execute(_SQL_INDEX)
            print("[liq_collector] ✅ TimescaleDB schema initialized (24h retention)")
        except Exception as e:
            print(f"[liq_collector] Schema init error: {e}")

    async def _load_from_db(self):
        """Bootstrap in-memory cache from TimescaleDB on startup."""
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT symbol, side, price, notional, timestamp "
                    "FROM liquidations WHERE timestamp > NOW() - INTERVAL '24 hours'"
                )

            for row in rows:
                symbol = row['symbol']
                side = row['side']
                price = row['price']
                notional = row['notional']
                ts_sec = row['timestamp'].timestamp()
                bucket = _price_bucket(price)

                if side == "SELL":
                    self._buckets[symbol][bucket]["long_liq_usd"] += notional
                else:
                    self._buckets[symbol][bucket]["short_liq_usd"] += notional
                self._buckets[symbol][bucket]["count"] += 1
                self._buckets[symbol][bucket]["last_ts"] = max(
                    self._buckets[symbol][bucket]["last_ts"], ts_sec
                )
                self._total_events += 1
                self._total_usd += notional

                # Populate recent events for velocity
                self._recent_events.append((ts_sec, bucket, side, notional, symbol))

            print(f"[liq_collector] Loaded {len(rows)} events from TimescaleDB ({len(self._buckets)} symbols)")
        except Exception as e:
            print(f"[liq_collector] DB load error: {e}")

    # ── Async DB Writer ──────────────────────────────────────────────────

    async def _flush_writes(self):
        """Flush the write buffer to TimescaleDB."""
        if not self._write_buf or not self._pool:
            return
        batch = self._write_buf.copy()
        self._write_buf.clear()
        self._last_flush = time.time()
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(_SQL_INSERT, batch)
        except Exception as e:
            print(f"[liq_collector] DB write error ({len(batch)} rows): {e}")
            # Re-enqueue on failure (cap to prevent infinite growth)
            if len(self._write_buf) < 10_000:
                self._write_buf.extend(batch)

    async def _record_to_db(self, symbol: str, side: str, price: float,
                            qty: float, notional: float, ts_ms: int):
        """Buffer an event for async batch INSERT."""
        ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        self._write_buf.append((symbol, side, price, qty, notional, ts_dt))

        now = time.time()
        if len(self._write_buf) >= _INSERT_BATCH_SIZE or (now - self._last_flush) >= _FLUSH_INTERVAL:
            await self._flush_writes()

    # ── Event Processing ─────────────────────────────────────────────────

    def _process_event(self, msg: dict) -> Optional[tuple]:
        """
        Parse a forceOrder event. Returns (symbol, side, price, qty, notional, ts_ms) or None.
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
        """Add a parsed event to in-memory cache (hot path — no I/O)."""
        bucket = _price_bucket(price)
        ts_sec = ts_ms / 1000

        b = self._buckets[symbol][bucket]
        if side == "SELL":
            b["long_liq_usd"] += notional
        else:
            b["short_liq_usd"] += notional
        b["count"] += 1
        b["last_ts"] = max(b["last_ts"], ts_sec)

        self._total_events += 1
        self._total_usd += notional

        # Recent events for velocity
        self._recent_events.append((ts_sec, bucket, side, notional, symbol))

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

    # ── Public API (unchanged signatures & return schemas) ───────────────

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

    async def get_heatmap_window(self, symbol: str, hours: int, max_buckets: int = 100) -> dict:
        """
        Return liquidation heatmap for any time window using TimescaleDB.
        """
        if not self._pool:
            return {"symbol": symbol, "buckets": [], "total_long_24h": 0,
                    "total_short_24h": 0, "total_events_24h": 0,
                    "window_hours": hours, "has_data": False}
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT side, price, notional FROM liquidations "
                    "WHERE symbol=$1 AND timestamp > NOW() - $2::INTERVAL",
                    symbol, f"{hours} hours"
                )
        except Exception as e:
            print(f"[liq_collector] heatmap_window query error: {e}")
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
        for row in rows:
            bucket = _price_bucket(row['price'])
            if row['side'] == "SELL":
                buckets_raw[bucket]["long_liq_usd"] += row['notional']
            else:
                buckets_raw[bucket]["short_liq_usd"] += row['notional']
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
        Uses in-memory recent events deque — fast, no DB query.
        """
        now = time.time()
        cutoff = now - window_minutes * 60

        by_minute: dict[int, dict] = {}
        for ts, bucket, side, notional, sym in self._recent_events:
            if sym != symbol or ts < cutoff:
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

        # Initialize asyncpg pool & schema
        await self._ensure_pool()
        await self._init_schema()

        # Bootstrap hot cache from DB
        await self._load_from_db()

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
                                # Update hot cache (sync, fast)
                                self._add_event(symbol, side, price, qty, notional, ts_ms)
                                # Async write to TimescaleDB
                                await self._record_to_db(symbol, side, price, qty, notional, ts_ms)
                        except Exception:
                            pass

                        # Periodic stats log
                        now = time.time()
                        if now - self._last_log >= _LOG_INTERVAL:
                            self._last_log = now
                            stats = self.get_stats()
                            summary = self.get_summary(5)
                            top = ", ".join(f"{s['symbol']}=${s['total_usd']/1e6:.1f}M" for s in summary)
                            print(f"[liq_collector] Stats: {stats['total_events']} events | "
                                  f"${stats['total_usd']/1e6:.1f}M | {stats['symbols_tracked']} symbols | "
                                  f"Top: {top}")

            except Exception as e:
                self._connected = False
                print(f"[liq_collector] Disconnected: {e} — reconnecting in {backoff}s")
                # Flush any remaining writes
                await self._flush_writes()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                # Re-check pool health on reconnect
                await self._ensure_pool()


# ── Singleton ─────────────────────────────────────────────────────────
_collector: Optional[LiquidationCollector] = None


def get_collector() -> LiquidationCollector:
    global _collector
    if _collector is None:
        _collector = LiquidationCollector()
    return _collector
