# Proposal: Real Liquidity Heatmap for All Monitored Pairs

**Date:** 2026-04-13
**Status:** PROPOSED
**Risk Level:** LOW (read-only data collection, no signal changes)
**Effort:** ~6-8 hours across 3 phases

---

## Problem

The bot currently has:
- PREDATOR's `detect_liquidation_magnets()` — swing-based *estimates* of where liquidations cluster
- `smart_money_analyzer._detect_liquidity_zones()` — equal highs/lows detection (not wired to dashboard)
- `get_order_book_depth()` — bid/ask imbalance + wall detection

**None of these provide REAL liquidation data.** We're guessing where liquidations are; Binance tells us exactly where they happen in real time.

---

## Solution: 3-Layer Liquidation Heatmap

### Layer 1: Real Liquidation Stream (ground truth)

**Source:** Binance WebSocket `wss://fstream.binance.com/ws/!forceOrder@arr`

- **Single WebSocket connection** covers ALL USDT perpetual futures (~700 pairs)
- Pushes every forced liquidation within 1000ms
- Each event contains: symbol, side (BUY=short liq / SELL=long liq), price, quantity, timestamp
- **Zero API weight** — it's a WebSocket stream, no rate limits

**Collection:**
```python
# Each liquidation event:
{
    "symbol": "BTCUSDT",
    "side": "SELL",           # SELL = long got liquidated
    "price": 67234.50,
    "quantity": 0.014,        # BTC
    "notional": 941.28,       # USD value
    "timestamp": 1681234567890
}
```

**Storage:** In-memory rolling buffer per symbol, 24h window. SQLite for historical persistence.

**Data structure:**
```python
# Per-symbol heatmap bucket (0.25% price bands)
{
    "BTCUSDT": {
        "buckets": {
            67000: {"long_liq_usd": 45230, "short_liq_usd": 12100, "count": 23},
            67250: {"long_liq_usd": 0, "short_liq_usd": 89400, "count": 45},
            ...
        },
        "total_long_liq_24h": 1234567,    # USD
        "total_short_liq_24h": 987654,
        "last_update": 1681234567
    }
}
```

### Layer 2: Projected Liquidation Clusters (already built)

**Source:** PREDATOR `detect_liquidation_magnets()`

- Swing-based entry detection + 7 leverage tier projections
- Density-weighted clustering
- Already integrated into signal pipeline

**Dashboard overlay:** Show projected clusters as lighter/transparent zones on the heatmap, overlaid with real liquidation data to validate the model.

### Layer 3: Order Book Walls

**Source:** `get_order_book_depth()` (existing)

- Bid/ask walls (orders > 3× average size)
- Imbalance ratio
- Refreshed on-demand when user views a specific pair

**Dashboard overlay:** Show large resting orders as horizontal lines on the heatmap.

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │  Binance WebSocket           │
                    │  !forceOrder@arr             │
                    │  (all pairs, 1 connection)   │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  liquidation_collector.py     │
                    │  - Parse forceOrder events    │
                    │  - Bucket by price band       │
                    │  - Rolling 24h window         │
                    │  - SQLite persistence         │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
    │ Dashboard API  │  │ PREDATOR    │  │ Signal      │
    │ /api/heatmap/  │  │ Integration │  │ Pipeline    │
    │ {pair}         │  │ (validate   │  │ (liq near   │
    │                │  │  estimates) │  │  targets?)  │
    └────────────────┘  └─────────────┘  └─────────────┘
```

### New Files

| File | Purpose | Size Est. |
|------|---------|-----------|
| `liquidation_collector.py` | WebSocket listener + bucketing + SQLite | ~250 lines |
| Dashboard API endpoint | `/api/heatmap/{pair}` in `app.py` | ~50 lines |
| Dashboard UI component | Canvas/SVG heatmap in `index.html` | ~200 lines |

### Modified Files

| File | Changes |
|------|---------|
| `dashboard/app.py` | Import collector, start WS in background, add API route |
| `dashboard/index.html` | Add heatmap tab/visualization (Elite tier) |
| `predator.py` | Optional: cross-reference real liqs with projected clusters |

---

## Data Flow

### Collection (continuous, background)

1. Connect to `wss://fstream.binance.com/ws/!forceOrder@arr`
2. For each `forceOrder` event:
   - Parse symbol, side, price, quantity
   - Calculate notional value (price × quantity)
   - Determine price bucket (round to nearest 0.25% band of current price)
   - Add to in-memory rolling buffer
   - Persist to SQLite every 5 minutes (batch write)
3. Every hour: prune events older than 24h from memory

### Serving (on-demand)

1. User opens heatmap for BTCUSDT
2. API returns:
   - Real liquidation buckets (24h, from collector)
   - Projected liquidation clusters (from PREDATOR, computed live)
   - Order book walls (fetched on-demand, cached 60s)
3. Frontend renders 3-layer heatmap:
   - **Red bars** = long liquidations (longs got rekt)
   - **Green bars** = short liquidations (shorts got rekt)
   - **Yellow zones** = PREDATOR projected clusters
   - **Blue lines** = order book walls
   - **White line** = current price

### Dashboard Visualization

```
Price Level  │ Long Liqs (red) ◄──── Price ────► Short Liqs (green) │
─────────────┼──────────────────────────────────────────────────────┤
  $68,500    │ ██                        *                    ████  │ ← short liq cluster
  $68,250    │ █                                              ███   │
  $68,000    │ ████████████████████████████████████████████████████  │ ← MASSIVE cluster
  $67,750    │ ████                  ──CURRENT──              █     │
  $67,500    │ ██████████            PRICE                          │ ← PREDATOR projected
  $67,250    │ ██████                                         █     │
  $67,000    │ ████████████████████                                 │ ← long liq cluster
  $66,750    │ ███                                                  │
─────────────┼──────────────────────────────────────────────────────┤
```

---

## Tier Gating

| Feature | Free | Pro ($49) | Elite ($99) |
|---------|------|-----------|-------------|
| Liquidation heatmap | ❌ | Top 5 pairs only | All pairs |
| Real-time updates | ❌ | 5-min delay | Live |
| Historical depth | ❌ | 6h | 24h |
| Order book overlay | ❌ | ❌ | ✅ |
| PREDATOR projection overlay | ❌ | ❌ | ✅ |

---

## Resource Impact

| Resource | Impact |
|----------|--------|
| **WebSocket connections** | +1 (currently using N for kline streams) |
| **Memory** | ~50-100MB for 24h rolling buffer across all pairs |
| **SQLite writes** | ~1 batch/5min (low I/O) |
| **API latency** | <50ms per heatmap request (in-memory) |
| **Binance rate limit** | Zero (WebSocket stream is free) |

---

## Implementation Plan

### Phase 1: Liquidation Collector (~3 hours)
- [ ] Build `liquidation_collector.py` with forceOrder WebSocket listener
- [ ] In-memory bucketing by symbol + price band
- [ ] SQLite persistence for historical data
- [ ] Rolling 24h window with hourly pruning
- [ ] Start collector as background task in dashboard `app.py`
- [ ] Log summary stats every 10 minutes (total liqs, top symbols)

### Phase 2: Dashboard API + Visualization (~3 hours)
- [ ] Add `/api/heatmap/{pair}` endpoint returning 3-layer data
- [ ] Build heatmap UI component (canvas-based, responsive)
- [ ] Tier gating (Elite = full, Pro = limited, Free = locked)
- [ ] Pair selector dropdown for heatmap view
- [ ] Auto-refresh every 30s for Elite, 5min for Pro

### Phase 3: PREDATOR Integration (~1-2 hours)
- [ ] Cross-reference real liquidation clusters with PREDATOR projections
- [ ] Score accuracy: do our projected magnets match real liquidation clusters?
- [ ] If accuracy > 70%, add real liquidation density as a signal quality factor
- [ ] Log divergences for model tuning

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| WebSocket disconnects | LOW | Auto-reconnect with exponential backoff (same pattern as kline WS) |
| Memory overflow (too many events) | LOW | 24h rolling window + hourly pruning, 0.25% bucket granularity |
| Low liquidation volume on small pairs | LOW | Show "insufficient data" for pairs with <10 events/24h |
| Binance deprecates forceOrder stream | VERY LOW | Stream has been stable since 2020, widely used |
| Dashboard rendering performance | MEDIUM | Limit to 100 price buckets per pair, use canvas not DOM |

---

## Expected Value

1. **Signal quality:** Real liquidation data validates PREDATOR's projected clusters — if our estimates are accurate, positioning confidence increases. If not, we recalibrate.

2. **Trade management:** Knowing exactly where liquidation cascades happen helps set better targets (place TP just before a liq cluster = price magnet pulls toward it).

3. **Premium feature:** Liquidation heatmaps are the #1 paid feature on Coinglass ($40/mo) and Hyblock ($60/mo). This gives Elite subscribers institutional-grade data.

4. **Direction filtering:** If we see massive long liquidations building up below current price, a SHORT signal has extra cascade fuel. This directly improves positioning scoring.

---

## Decision Required

**Proceed with Phase 1 (collector)?** The WebSocket listener is read-only, zero risk to live signals, and starts accumulating data immediately. Visualization can be built once we have 24h of data to render.
