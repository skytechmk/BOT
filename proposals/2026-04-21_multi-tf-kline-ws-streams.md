# Proposal: Multi-Timeframe Kline WebSocket Streams (15m / 1h / 4h) + Sub-Minute Scan Cycles

**Date**: 2026-04-21
**Author**: S.P.E.C.T.R.E.
**Status**: ✅ IMPLEMENTED 2026-04-21 — awaiting operator service restart

---

## IMPLEMENTATION NOTES (applied)

Final approach turned out to be **far more surgical** than the original draft.
The existing `KlineStreamManager` and `BATCH_PROCESSOR` already support
multi-TF caching per `(pair, timeframe)` key — no new module needed.

### Files changed

1. **`kline_stream_manager.py`**
   - `_KLINE_INTERVALS`: `['1h']` → `['15m', '1h', '4h']`
   - New `_TRIGGER_INTERVALS = {'1h'}` — only 1h closes fire `process_pair`
   - 15m and 4h closes silently update `BATCH_PROCESSOR` cache (parked)
   - Added 1.5s stagger between WS shard starts (avoids Binance 5-conn/300s limit)

2. **`main.py`**
   - New module globals: `_LAST_BAR_TS_EVALUATED`, `_BAR_DEDUP_LOCK`
   - `process_pair()` — 1h bar-timestamp dedup: skip if same bar already evaluated (TV overrides bypass)
   - `_bg_prefetch()` — now prefetches 1h, then 15m, then 4h sequentially
   - Main loop sleep: `max(0, 90 - elapsed)` → `max(0, 30 - elapsed)`

### What's cached now

- **All 629 pairs × 3 TFs** via WS streams in `BATCH_PROCESSOR._df_cache`
- Backfill depth: per `BATCH_PROCESSOR.prefetch` default (uses `fetch_data` which reads the per-TF `_OHLCV_MAX_CANDLES` cap — typically 800 bars per TF, deeper for longer TFs)
- WS shards: 629 × 3 = 1887 streams / 200 per-conn = ~10 WS connections, staggered 1.5s apart

### What did NOT change (per operator direction)

- TSI calculation logic
- Signal scoring / thresholds
- Indicator formulas
- Signal firing still exclusively on **1h closes** (enforced by `_TRIGGER_INTERVALS` + bar-ts dedup)
- 15m + 4h data is **parked** — ready for future entry-refinement (Phase 3) and regime-filter (Phase 4) without a redeploy

### Next step for operator

```bash
systemctl restart bot          # picks up new kline_stream_manager.py + main.py
```

Expected log lines on boot:
```
📡 KlineStream: 629 pairs × [15m, 1h, 4h] = 1887 streams (10 connection(s))
⏳ Background REST prefetch: 629 pairs × [1h,15m,4h] (non-blocking)...
✅ 1h prefetch complete — 629 pairs in ~15s
✅ 15m prefetch complete — 629 pairs in ~15s (parked)
✅ 4h prefetch complete — 629 pairs in ~15s (parked)
```

After first 1h close: cycle logs `📊 Cycle: …` should arrive every ~30s (was ~90s).

---

## ORIGINAL PROPOSAL (below, kept for reference)

---

## 1. Goal

Replace the REST `futures_klines` polling in the main scan loop with a **persistent WebSocket kline cache** covering **all ~629 USDT perps** on three timeframes:

- **15m** — fine-grained entry refinement (future work)
- **1h** — primary signal timeframe (TSI logic stays identical)
- **4h** — regime / higher-timeframe confirmation context

This unlocks **sub-minute scan cycles** (target 30–60s) without touching Binance REST rate limits, while **preserving today's signal semantics** (signals still fire on 1h TSI closures).

---

## 2. Current State

| Component | Source | Notes |
|-----------|--------|-------|
| Main scan loop | `main.py:1444` → `sleep(max(0, 90-elapsed))` | ~90s cycle, bound by REST klines fetch of 629 pairs × 1h |
| 1h klines | `data_fetcher._fetch_klines_raw` (REST, raw HTTPS, thread pool) | ~2770 weight/cycle (~1846/min) |
| 15m / 4h klines | Fetched ad-hoc per pair in `signal_generator` / `technical_indicators` | Adds more REST load |
| Live mark price / book | `LivePriceFeed` (WS `markPrice@1s` + `bookTicker`) | Already all symbols |
| Live CVD | `CVDFeed` (WS `aggTrade`) | 218 symbols |
| Kline WS | `KlineStream` | **Top-N pairs only** (not full universe) |

**Bottleneck**: REST klines fetch. Running the scan faster than ~90s hits the 2400 wt/min limit.

---

## 3. Proposed Architecture

### 3.1 New module: `multi_tf_kline_feed.py`

A single class `MultiTFKlineFeed` that:

1. **On start**: Does a one-shot **REST backfill** for every `(pair, tf)` pair — fetches last N bars into an in-memory `deque` (sized per timeframe: e.g. 100 for 1h, 60 for 15m, 60 for 4h).
2. **Opens WebSocket streams**: Binance combined streams `<symbol>@kline_<tf>` for all pairs × 3 timeframes.
3. **Routes incoming messages**: On each kline tick, updates the appropriate deque (live bar = last element, replaced on each tick; closed bar = appended).
4. **Exposes accessors**:
   - `get_closed(pair, tf) -> pd.DataFrame` — last N closed bars only (safe for indicator calc)
   - `get_live(pair, tf) -> dict` — current forming bar (for entry refinement, later)
   - `is_ready(pair, tf) -> bool` — sufficient history loaded
5. **Auto-reconnect + gap detection**: If a WS disconnect lasted > 1 bar's duration, re-backfill gaps via REST.

### 3.2 Stream sharding

Binance limit: **200 streams per WS connection**. 629 pairs × 3 TFs = **1887 streams** → **10 WS connections** (shard by `hash(pair) % 10`).

### 3.3 Main loop changes (`main.py`)

- Replace `fetch_klines_batch(...)` calls with `MULTI_TF_FEED.get_closed(pair, '1h')`.
- Drop the 90s sleep floor → use **30s** (TSI on 1h barely changes, but regime/volatility/signal-confirmation gates use live data that *does* change).
- No change to signal firing cadence: **signals still only fire when a new 1h bar closes** (check `last_bar_close_ts` — dedupe by bar timestamp per pair, same as today).

### 3.4 TSI logic: **untouched**

Per your direction:
- TSI computation code stays exactly as-is.
- Signal generation gated on 1h timeframe.
- 15m and 4h data is **parked in the cache** for later:
  - 15m → used as entry-refinement layer (price drift check, micro-structure entry) in a future PR.
  - 4h → higher-TF regime filter (future PR).

Nothing in `signal_generator.py` or `technical_indicators.py` changes in this proposal. Only the **data source** (WS cache instead of REST) changes.

---

## 4. File-Level Changes

### 4.1 New file: `multi_tf_kline_feed.py` (new, ~350 lines)

```python
# Pseudocode sketch — full impl in follow-up
class MultiTFKlineFeed:
    TIMEFRAMES = {'15m': 60, '1h': 100, '4h': 60}
    MAX_STREAMS_PER_WS = 200

    def __init__(self, pairs: list[str], client):
        self._pairs = pairs
        self._client = client
        self._bars: dict[tuple[str,str], deque] = {}   # (pair, tf) -> deque of closed bars
        self._live: dict[tuple[str,str], dict] = {}    # current forming bar
        self._shards: list[list[str]] = self._shard_pairs()
        self._last_msg_ts = 0.0

    async def backfill(self):
        """Parallel REST backfill for all (pair, tf) — one-shot at startup."""
        ...

    async def run(self):
        """Start N WS connections (one per shard) in parallel."""
        await self.backfill()
        await asyncio.gather(*[self._run_shard(s) for s in self._shards])

    def get_closed(self, pair: str, tf: str) -> pd.DataFrame: ...
    def get_live(self, pair: str, tf: str) -> dict | None: ...
    def is_ready(self, pair: str, tf: str) -> bool: ...
```

### 4.2 `main.py`

- **Line ~1301** (near existing `LIVE_FEED.run()` boot): add
  ```python
  from multi_tf_kline_feed import MULTI_TF_FEED
  await MULTI_TF_FEED.backfill()          # block boot until ready
  asyncio.create_task(MULTI_TF_FEED.run())
  log_message(f"🚀 MultiTFKlineFeed started (15m/1h/4h × {len(pairs)} pairs)")
  ```
- **Line ~1444**: change `await asyncio.sleep(max(0, 90 - elapsed))` → `max(0, 30 - elapsed)`.
- **Pair processing**: replace REST klines lookup with `MULTI_TF_FEED.get_closed(pair, '1h')`.

### 4.3 `data_fetcher.py`

- Keep `_fetch_klines_raw` as fallback (used by backfill + gap-fill).
- Mark the existing `fetch_klines_batch` as "legacy / backfill only" — no removal this PR.

### 4.4 Signal firing gate (`signal_generator.py` or `main.py` scan wrapper)

Add a dedup check:
```python
last_bar_ts = df_1h.iloc[-1]['timestamp']
if _last_fired_bar_ts.get(pair) == last_bar_ts:
    return None   # already evaluated this 1h bar
_last_fired_bar_ts[pair] = last_bar_ts
```
This ensures **signals fire at most once per 1h bar per pair**, even though the scanner runs every 30s.

---

## 5. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| WS connection drops lose bars | Medium | Reconnect + gap-fill via REST; `is_ready()` gate |
| Memory footprint (629×3×100 bars ≈ 190k OHLCV rows) | Low | ~30 MB — trivial |
| Initial backfill takes long | Medium | Parallelize by 20 workers; ~30–60s one-time cost at boot |
| Stream ordering / race conditions on deque | Low | Single-writer per (pair,tf) — asyncio is single-threaded |
| Binance WS limit: 200 streams/conn, 5 conn/300s rate | Low | 10 shards × 190 streams; stagger connect by 1s |
| Signal firing more than once per 1h bar | High if dedup omitted | Explicit `_last_fired_bar_ts` dedup per-pair |
| Regression to existing TSI/indicator outputs | Low | Data shape identical — same OHLCV DataFrame, just different source |

---

## 6. Rollout Plan

1. **Phase 1** (this PR): Build `MultiTFKlineFeed`, wire into main loop for **1h only**. Keep scan at 90s. Verify TSI output identical to REST baseline for 24h.
2. **Phase 2**: Drop scan interval to **30s** with dedup gate. Measure latency improvement.
3. **Phase 3** (future): Add 15m entry refinement (price drift + micro-structure check on 15m close).
4. **Phase 4** (future): Add 4h regime filter (gate TSI signals against 4h trend).

---

## 7. Success Metrics

- [ ] Main scan cycle: 90s → **≤30s** sustained for 24h without WS drops
- [ ] REST `futures_klines` calls in main loop: ~2770/cycle → **~0/cycle** (only backfill + gap-fill)
- [ ] Zero duplicate 1h-bar signals (verified via `_last_fired_bar_ts` dedup)
- [ ] TSI zone counts match REST baseline to ±1 pair across 10 consecutive 1h closes

---

## 8. Operator Decision Points

1. **Backfill bar counts** — proposed 100×1h, 60×15m, 60×4h. Enough for TSI (needs ~25)? Increase 1h to 200 to match current?
2. **Scan interval target** — 30s? 15s? Faster = more CPU but no API pressure.
3. **15m + 4h activation** — subscribe now (ready for future work) or defer to Phase 3/4?
4. **Go/No-Go on Phase 1** — approve building `multi_tf_kline_feed.py` first?

---

## 9. Out of Scope

- Changes to TSI, Ichimoku, ATR, or any indicator formula
- Changes to signal scoring, thresholds, or leverage rules
- ML model retraining
- Dashboard changes

This PR is **purely a data-source swap** + scan-cadence unlock.
