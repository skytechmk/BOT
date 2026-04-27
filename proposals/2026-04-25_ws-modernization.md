# Binance WS Modernization — P0 → P3

**Date:** 2026-04-25
**Author:** Cascade (S.P.E.C.T.R.E.)
**Scope:** Full alignment with the new Binance USDS-M Futures WebSocket
endpoints + adoption of streams that fix concrete known issues.

---

## Why now

Binance has split the futures WebSocket endpoints into three categories:

| Base URL | Streams |
|---|---|
| `wss://fstream.binance.com/public` | `@bookTicker`, `!bookTicker`, `@depth*`, `@rpiDepth` |
| `wss://fstream.binance.com/market` | `@kline`, `@aggTrade`, `@markPrice`, `@ticker`, `@miniTicker`, `@forceOrder`, `!contractInfo`, `tradingSession`, `@compositeIndex`, `!assetIndex` |
| `wss://fstream.binance.com/private` | listenKey + ORDER_TRADE_UPDATE / ACCOUNT_UPDATE |

Migration deadline (per Binance docs): **2026-04-23** — already passed,
currently in grace period. Legacy `/ws` and `/stream` paths will eventually
return errors.

We also discovered, while building the Lab tab, that **every loss in the
experimental tier this week is a TradFi perpetual** (TSLA, PAYP, VICI, AGLD,
ERA, CRCL, XAGU, COPPER, DODOX), all fired Friday after-hours / weekend when
the underlying equity market is closed. Binance now exposes a
`tradingSession` stream that lets us suppress these signals at source.

---

## Changes (in order of execution)

### P0a — URL Migration

**Files (all production-critical WS connections):**

| File | Current URL | New URL |
|---|---|---|
| `kline_stream_manager.py` | `fstream/stream` | `fstream/market/stream` |
| `cvd_stream_manager.py` | `fstream/stream` | `fstream/market/stream` |
| `liquidation_collector.py` | `fstream/ws` | `fstream/market/ws` |
| `realtime_signal_monitor.py` | `fstream/stream` | `fstream/market/stream` |
| `live_price_feed.py` | `fstream/stream` (mixed) | **split**: `/market` for `!markPrice@arr@1s`, `/public` for `!bookTicker` |
| `price_broadcaster.py` | `fstream/stream` | `fstream/market/stream` |
| `dashboard/app.py` | `fstream/stream` | `fstream/market/stream` |
| `enhanced_websocket_monitor.py` | `fstream/ws` | `fstream/market/ws` |
| `dashboard/binance_user_stream.py` | `fstream/ws/<key>` | `fstream/private/ws?listenKey=<key>` (if python-binance hardcodes legacy URL, monkey-patch via factory) |

**Constraint discovered:** `live_price_feed.py` currently combines
`!markPrice@arr@1s` (market category) and `!bookTicker` (public category) on
one connection. Cross-category subscriptions are not supported on the new
endpoints — must split into two connections.

**Risk:** python-binance's `BinanceSocketManager.futures_user_socket()` may
internally hardcode the legacy `wss://fstream.binance.com/ws/<listenKey>`
URL. If so, we override by constructing the WS connection manually with the
listenKey it manages. Worst case: stay on legacy until python-binance
releases an updated version (Binance has not given a hard cutoff date past
2026-04-23 yet).

### P0b — Trading Session Gate

**Stream:** `tradingSession` on `/market/ws`. Pushes session status every
1 second for U.S. equity (`PRE_MARKET` / `REGULAR` / `AFTER_MARKET` /
`OVERNIGHT` / `NO_TRADING`) and commodity (`REGULAR` / `NO_TRADING`)
underlyings.

**New file:** `trading_session_manager.py`
- One persistent connection
- In-memory state: `{"equity": {"session": "REGULAR", "until": ts}, "commodity": {...}}`
- Singleton getter `is_underlying_active(pair: str) -> bool` returns:
  - True for crypto (always tradeable)
  - True for TradFi pair if its market is `REGULAR`
  - False otherwise

**Pair classification:** maintain a hard-coded set of known TradFi tickers in
the manager (TSLAUSDT, AAPLUSDT, GOOGLUSDT, AMZNUSDT, METAUSDT, NVDAUSDT,
MSTRUSDT, COINUSDT, MSTRUSDT, PAYPUSDT, VICIUSDT, AGLDUSDT, ERAUSDT,
CRCLUSDT, XAGUSDT, COPPERUSDT, DODOXUSDT, SPYUSDT, QQQUSDT, EWJUSDT, NVDAUSDT,
XPTUSDT) plus commodity ones. Future enhancement: derive from `!contractInfo`.

**Integration:** in `main.py::_classify_signal_tier()`, if the pair is
TradFi and `is_underlying_active(pair)` is False, force tier =
`'experimental'` regardless of zone — the signal goes to Lab, not public.
Crypto pairs are unaffected.

### P1 — Contract Info Stream

**Stream:** `!contractInfo` on `/market/ws`. Real-time push when:
- New symbol listed (status `TRADING`, `ot` = onboard time)
- Symbol settled / delisted (status `SETTLING` or `CLOSE`)
- Leverage brackets updated (`bks` field)

**New file:** `contract_info_listener.py`
- Subscribes to `!contractInfo`
- On status `SETTLING`/`CLOSE`: removes pair from active scanner set
  (signals `kline_stream_manager.remove_pair()` and `data_fetcher`)
- On status flip to `TRADING` from PRE_TRADING for an unknown symbol: log so
  we can review for inclusion next refresh
- Stores latest leverage brackets in `bracket_cache` (used by position-sizing
  to respect Binance's max leverage at our notional)

**Killed pain:** the `Invalid symbol PAYPUSDT` REST errors we saw in main.log
go away — we drop delisted symbols immediately from the WS stream chunks.

### P2 — Live SUBSCRIBE / UNSUBSCRIBE in Signal Monitor

**Current behavior:** `realtime_signal_monitor.py` rebuilds the entire
`?streams=...` URL and reconnects every time a signal opens or closes.
~5–10 reconnects per day, each with a brief blind spot during which a
TP/SL print could be missed.

**Fix:** open one persistent connection at boot. On signal change, send:
```json
{"method":"SUBSCRIBE","params":["btcusdt@markPrice@1s"],"id":<n>}
{"method":"UNSUBSCRIBE","params":["btcusdt@markPrice@1s"],"id":<n>}
```
Track outstanding `id`s for ACK. Zero reconnects, zero blind spots.

### P3 — Order Book Manager (foundation)

**Stream:** `<symbol>@depth20@500ms` on `/public/ws` for the top-50 pairs by
volume. (RPI variant `@rpiDepth@500ms` is a v2 upgrade — uses diff format
and requires local book maintenance.)

**New file:** `orderbook_manager.py`
- Maintains live top-20 levels for top-50 pairs
- Computes per pair every push:
  - `bid_ask_imbalance` = (Σtop10_bid_qty − Σtop10_ask_qty) / (Σtop10_bid_qty + Σtop10_ask_qty), range [-1, +1]
  - `spread_bps` = (best_ask − best_bid) / mid × 10000
  - `top_depth_usd_bid`, `top_depth_usd_ask` (Σ first-10-levels notional)
- Singleton getter `get_orderbook_features(pair: str) -> dict | None`

**Integration in this PR:** features are exposed and added to the
`feature_snapshot` saved in `signal_registry.db` (new columns or just inside
features_json). They are NOT used as signal gates yet — that's the next
research milestone, after we have ~2 weeks of data to study correlation
with signal outcomes.

---

## Risk assessment

| Item | Risk | Mitigation |
|---|---|---|
| URL migration breaks copy-trading | Medium — python-binance internals | Test on staging first; keep legacy fallback URL as env-flag for 1 week |
| `tradingSession` not yet available on all clusters | Low | Default to "always active" if stream unavailable, log warning |
| Order-book streams add ~50 connections | Low | Stays well under per-IP connection limit |
| Feature extraction in hot path | Low | Computation is O(20), runs in WS callback thread |

## Rollout

Single deployment, all five phases. Each phase is independently committed
and tested in `python3 -c 'import ast; ast.parse(...)'` before moving on.
Final smoke test: restart `anunnaki-dashboard.service` + bot, watch
`main.log` for 5 minutes for clean WS connections on all new URLs.

## Verification

- `lsof -i | grep python.*fstream` shows new URL paths
- `_count_all_signals_direct` query keeps returning sane numbers
- Lab tab shows new TradFi signals tagged experimental during weekend
- `realtime_signal_monitor` shows ZERO reconnect events for a 24h window
- New columns / features visible in `signal_registry.db`
