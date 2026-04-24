# Proposal: Copy-Trading Scalability Roadmap

**Date:** 2026-04-16  
**Author:** Cascade  
**Priority:** Low (no action needed until ~100+ active copy-traders)  
**Status:** Draft — for future reference

---

## Current Architecture (baseline)

- **Database:** SQLite (`users.db`) — single-writer, file-based
- **API calls:** Binance REST via `python-binance`, per-user HTTP sessions (now cached, TTL=10min)
- **Order placement:** `asyncio.to_thread` — all users fire in parallel per signal
- **Conditional orders:** `POST /fapi/v1/algoOrder` (Binance Algo API, migrated Dec 2025)
- **SL protection:** Exchange-native `STOP_MARKET` algo order + software monitor fallback (15s poll)
- **Concurrency model:** Single process, asyncio + thread pool

---

## Scaling Thresholds & Bottlenecks

### Tier 1: 0–100 users ✅ (current)

**Status: No action needed.**

- All users execute in parallel — wall time per signal ~500ms regardless of N
- Client cache (TTL=10min) eliminates TCP/TLS overhead
- Hedge mode cache eliminates redundant position mode API calls
- Exchange info cache (TTL=5min) is global — only 1 call per 5 min regardless of users
- SQLite handles concurrent reads fine; writes are serialized but fast (<5ms each)
- Binance rate limits are per API key — no cross-user interference

**Estimated capacity:** 100 users, ~5 API calls each = 500 calls/signal, all parallel ≈ 500ms total

---

### Tier 2: 100–500 users ⚠️ (near-future)

**Primary bottleneck: SQLite write contention**

When 500 users execute simultaneously, `_record_trade()` fires 500 concurrent DB writes.
SQLite's single-writer model serializes these, adding ~2.5 seconds of DB wait time.

**Fix: Write queue**

Replace direct `conn.execute(INSERT)` with an async write queue:

```python
# In copy_trading.py — replace _record_trade DB write with:
_DB_WRITE_QUEUE: asyncio.Queue = asyncio.Queue()

async def _db_writer_loop():
    """Drain the write queue in batches — single writer, no contention."""
    conn = _get_db()
    while True:
        batch = []
        item = await _DB_WRITE_QUEUE.get()
        batch.append(item)
        # Drain any immediately available items (batch up to 50)
        while not _DB_WRITE_QUEUE.empty() and len(batch) < 50:
            batch.append(_DB_WRITE_QUEUE.get_nowait())
        try:
            for sql, params in batch:
                conn.execute(sql, params)
            conn.commit()
        except Exception as e:
            log.error(f"[db_writer] batch write failed: {e}")
```

**Secondary bottleneck: Thread pool exhaustion**

Python's default `asyncio.to_thread` pool has 32-64 threads. With 500 users, the pool
fills and later users wait. Fix: set `max_workers` explicitly:

```python
# In app.py lifespan startup:
import concurrent.futures
loop = asyncio.get_event_loop()
loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=200))
```

**Estimated effort:** 2–3 days  
**When to implement:** When active copy-traders consistently exceed 100

---

### Tier 3: 500–2000 users 🔴 (medium-term)

**Primary bottleneck: Binance IP-level rate limits**

All users share the same server IP (`185.6.20.65`). Binance applies global IP-level
rate limits in addition to per-key limits. With 1000+ users firing simultaneously,
the IP may hit the global order rate limit.

**Fix A: WebSocket Trading API**

Replace REST calls with the Binance WebSocket Trading API (`wss://ws-fapi.binance.com`):
- **0 IP rate limit weight** per order (vs 1 for REST)
- Persistent connection per user — no TCP overhead
- Identical parameters to REST (`order.place`, `algoOrder.place`)

Implementation:
```python
# Per-user WebSocket trading session (replaces REST client)
class BinanceWSTrader:
    def __init__(self, api_key, api_secret):
        self.ws_url = "wss://ws-fapi.binance.com/ws-fapi/v1"
        self.pending: dict = {}  # request_id → asyncio.Future

    async def place_order(self, params: dict) -> dict:
        request_id = str(uuid.uuid4())
        params.update({'apiKey': self.api_key, 'timestamp': int(time.time()*1000)})
        params['signature'] = hmac_sign(params, self.api_secret)
        future = asyncio.get_event_loop().create_future()
        self.pending[request_id] = future
        await self.ws.send(json.dumps({'id': request_id, 'method': 'order.place', 'params': params}))
        return await asyncio.wait_for(future, timeout=5.0)
```

**Fix B: Multiple server IPs / horizontal scaling**

Distribute users across multiple server instances behind a load balancer.
Each instance handles a shard of users. Requires:
- Shared database (PostgreSQL or Redis for session state)
- Message broker (Redis pub/sub or RabbitMQ) for signal distribution

**Estimated effort:** 1–2 weeks  
**When to implement:** When active copy-traders exceed 500

---

### Tier 4: 2000+ users 🏗️ (long-term)

**Primary bottleneck: Single-process architecture**

A single Python process with asyncio + threads cannot efficiently handle thousands of
concurrent Binance connections.

**Recommended architecture: Microservices**

```
Signal Generator (main.py)
        │
        ▼ (Redis pub/sub)
Signal Router Service
        │
    ┌───┴───┬───────┬───────┐
    ▼       ▼       ▼       ▼
Worker-1  Worker-2  Worker-3  Worker-N
(users    (users    (users    (users
1-500)   501-1000) 1001-1500) ...)
    │       │       │       │
    └───────┴───────┴───────┘
                │
          PostgreSQL
          (shared state)
```

Each Worker:
- Manages its shard of users
- Maintains persistent WebSocket connections to Binance per user
- Reports execution status to PostgreSQL

**Database migration: SQLite → PostgreSQL**

```sql
-- Same schema, just different driver
-- In copy_trading.py:
import asyncpg  # async PostgreSQL driver

async def _get_db():
    return await asyncpg.connect(os.getenv('DATABASE_URL'))
```

**Signal distribution: Redis pub/sub**

```python
# Signal Generator publishes:
await redis.publish('signals', json.dumps(signal_data))

# Each Worker subscribes:
async for message in redis.subscribe('signals'):
    await execute_for_my_users(json.loads(message))
```

**Estimated effort:** 4–6 weeks  
**When to implement:** When active copy-traders exceed 2000

---

## Summary Table

| Users | Bottleneck | Fix | Effort |
|-------|-----------|-----|--------|
| 0–100 | None | ✅ Current implementation sufficient | Done |
| 100–500 | SQLite writes, thread pool | Write queue + executor sizing | 2–3 days |
| 500–2000 | Binance IP rate limits | WebSocket Trading API | 1–2 weeks |
| 2000+ | Single-process limits | Microservices + PostgreSQL + Redis | 4–6 weeks |

---

## Immediate Low-Hanging Fruit (already done)

- ✅ Per-user Binance client cache (TTL=10min) — eliminates TCP/TLS overhead
- ✅ Hedge mode cache per user — eliminates 1 API call per trade
- ✅ Exchange info cache (global, TTL=5min) — eliminates 1 API call per trade
- ✅ Parallel execution via `asyncio.to_thread` — all users fire simultaneously
- ✅ Binance Algo API for conditional orders — correct endpoint post-Dec-2025 migration

---

## Notes

- Each scaling tier is independent — implement only when the threshold is reached
- Monitor with: `grep "Copy-trade EXECUTED" debug_log*.txt | wc -l` per day for volume estimates
- Current SQLite DB is at `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/users.db`
- WebSocket Trading API docs: `https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/websocket-api`
