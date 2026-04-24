# Proposal: TimescaleDB Migration for Liquidations

## Context & Problem
`liquidation_collector.py` maintains an aggressively expanding, 10,000-event per symbol Python dictionary payload. Every hour, an `asyncio.to_thread` worker iterates through all entries to prune anything older than 24 hours. The Garbage Collection and deep iteration loops of dictionaries block the main Python event loop (GIL), causing micro-lag on parallel WebSocket execution.

## Proposed Architecture: TimescaleDB / QuestDB

Instead of maintaining a massive rolling window in volatile RAM, use a hyper-optimized Time-Series Database (TSDB). The Postgres extension `TimescaleDB` natively handles chunked arrays based on timestamps, meaning we never have to run a Python `_prune_old_events()` script again. The database engine natively drops chunks as they expire via `Continuous Aggregates`.

## Code Changes / Implementation Steps

### 1. Provision TimescaleDB
```yaml
# Add to docker-compose.yml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg14
    environment:
      POSTGRES_PASSWORD: mysecretpassword
    ports:
      - "5432:5432"
```

### 2. SQL Schema Setup
```sql
CREATE TABLE liquidations (
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  price DOUBLE PRECISION NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL
);

-- Convert to hypertable
SELECT create_hypertable('liquidations', 'timestamp');

-- Setup automated data retention policy (auto-deletes rows > 24 hours old)
SELECT add_retention_policy('liquidations', INTERVAL '24 hours');
```

### 3. Replace Persistence Logic in Collector
Modify `liquidation_collector.py` to push directly to TimescaleDB instead of SQLite, and remove the `_prune_old_events` loop completely since Postgres will natively purge the data in the background without affecting the Python runtime.

## Risk Assessment
**Medium Risk**: Moving from SQLite to a networked Postgres instance introduces network latency. We must ensure `asyncpg` is used to fire the inserts non-blockingly, rather than the synchronous `psycopg2`, to prevent stalling the forceOrder socket parser.
