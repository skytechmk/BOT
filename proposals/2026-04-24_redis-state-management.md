# Proposal: Redis State Management Migration

## Context & Problem
Currently, the application relies on SQLite (even in WAL mode) for reading high-frequency state data (like live Binance balances and Screener permutations) in `dashboard/app.py`. When 50+ users request Screener data simultaneously via the frontend `fetch` calls, SQLite locking creates a bottleneck. Additionally, `liquidation_collector.py` maintains massive state in Python dictionaries via memory.

## Proposed Architecture: Redis In-Memory Cache

1. **Deployment**: Add a `redis-alpine` docker container to the stack.
2. **Global Heatmap Object**: Rather than storing 10,000 liquidation events per symbol in a Python dict inside `liquidation_collector.py`, we push the compiled `top_buckets` payload into a Redis key `heatmap:BTCUSDT` on every 1-second WebSocket message.
3. **Dashboard API Reads**: `dashboard/app.py` `loadScreener` and `get_heatmap` endpoints will fetch directly from Redis via `redis-py` `GET heatmap:BTCUSDT`, completely bypassing SQLite and Python ThreadPool calculations.

## Code Changes / Implementation Steps

### 1. `docker-compose.yml` (New Service)
```yaml
services:
  redis:
    image: redis:7-alpine
    restart: always
    ports:
      - "6379:6379"
    command: redis-server --save 60 1 --loglevel warning
```

### 2. `dashboard/app.py` (Read from Redis)
```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=0)

@app.get("/api/heatmap/{symbol}")
async def api_heatmap(symbol: str):
    cached = redis_client.get(f"heatmap:{symbol.upper()}")
    if cached:
        return Response(content=cached, media_type="application/json")
    
    # Fallback to current SQLite query
    # ...
```

## Risk Assessment
**Low Risk**: Redis fails gracefully. If the Redis server is uncontactable, `dashboard/app.py` can automatically catch the `redis.ConnectionError` and fall back to the existing SQLite `get_collector().get_heatmap()` path.
