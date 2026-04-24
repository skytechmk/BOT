# Proposal: Migrate copy-trading from Binance REST to WebSocket

**Date:** 2026-04-23
**Author:** S.P.E.C.T.R.E.
**Status:** Draft — awaiting operator review
**Risk:** Medium-High (architectural change; needs phased rollout + feature flag)
**Trigger:** `-1003` IP ban today (2026-04-23 21:54 CEST) caused by REST polling of `futures_account_balance` + `futures_account`. Binance's own error message: *"Please use the websocket for live updates to avoid bans."*

---

## TL;DR

Replace the REST-polling hot path in `copy_trading.py` with two parallel Binance WebSocket surfaces:

1. **User Data Stream (push)** — consume real-time `ACCOUNT_UPDATE`, `ORDER_TRADE_UPDATE`, `listenKeyExpired` events. Balance / positions / fills become **push-driven in-memory state**. No polling.
2. **WebSocket API (request/response)** — route order placement (`order.place`, `order.cancel`, `order.modify`, `algoOrder.place`, `algoOrder.cancel`) over `wss://ws-fapi.binance.com/ws-fapi/v1`. Separate rate-limit bucket from REST, lower latency.

REST stays only for (a) one-time snapshot on connect, (b) `listenKey` creation, (c) fallback when WS is down.

---

## Motivation

### Current problem

- `get_live_balance(user_id)` in `copy_trading.py` fires **2 signed REST calls** (`futures_account_balance` + `futures_account`) per invocation.
- Dashboard polls `/api/copy-trading/balance` every 5 s per open tab. With multiple users/tabs: 10–50 calls/min hitting Binance with signed weight.
- Binance's per-IP weight budget (~2400/min on `fapi`) gets eaten → **`-1003` IP ban**, which blocks **ALL** Binance calls from `185.6.20.65`, including `futures_create_order` → copy-trades silently fail even for users not polling.
- Today's caching patch (15 s TTL in `_BALANCE_CACHE`) reduces this by ~90% but doesn't eliminate the class of problem. Adding users → linear REST cost. Adding pages/views → linear REST cost.

### Why WebSocket wins

| Dimension | REST today | User Data Stream | WS API |
|---|---|---|---|
| Balance/position staleness | 5–15 s | **0 ms (push)** | n/a |
| Per-user REST calls/min (idle) | 24–120 | **0** | 0 |
| Order placement latency (p50) | ~300 ms | n/a | **~80 ms** |
| Rate-limit bucket | `fapi` per-IP weight | separate (connection + msg) | separate |
| `-1003` risk from polling | **High** | **Zero** | Low |
| Survives IP-level ban? | No | Yes (WS already connected) | Partial |

### Extra benefit: real-time UX

Push events mean the dashboard can update balance/PnL **the instant a position moves**, not on the next 5 s tick. The existing SSE `/api/stream/live_pnl` becomes a trivial re-emit of Binance's own events.

---

## Architecture

### New files

```
dashboard/
  binance_user_stream.py      NEW  — per-user UDS connection manager
  binance_ws_api.py           NEW  — request/response client for ws-fapi
  ws_account_state.py         NEW  — in-memory {user_id → {balance, positions, orders}}
```

### Modified files

```
dashboard/copy_trading.py     — get_live_balance() becomes state lookup
                              — _execute_single_trade_blocking() uses ws_api
                              — keep REST fallbacks behind feature flag
dashboard/app.py              — /api/copy-trading/balance serves from ws_account_state
                              — startup hook spawns UDS for each active user
                              — shutdown hook closes all WS connections
```

### Feature flag

```
# .env
BINANCE_WS_ENABLED=true        # master switch
BINANCE_WS_USER_STREAM=true    # enable User Data Stream (balance push)
BINANCE_WS_ORDER_API=false     # enable WS API for order placement (phase 2)
```

### User Data Stream lifecycle

```
┌────────────────────────────────────────────────────────────────┐
│  per user with is_active=1:                                    │
│                                                                │
│  1. POST /fapi/v1/listenKey       → listenKey (valid 60 min)   │
│  2. wss://fstream.binance.com/ws/<listenKey>                   │
│  3. on ACCOUNT_UPDATE       → update ws_account_state[uid]      │
│     on ORDER_TRADE_UPDATE   → update orders[]; trigger hooks    │
│     on listenKeyExpired     → restart from step 1               │
│  4. every 30 min: PUT /fapi/v1/listenKey  (keepalive)          │
│  5. on disconnect: exponential backoff reconnect               │
└────────────────────────────────────────────────────────────────┘
```

### WS API for orders (Phase 2)

Request shape:
```json
{
  "id": "<uuid>",
  "method": "order.place",
  "params": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quantity": "0.001",
    "apiKey": "<key>",
    "timestamp": 1776974000000,
    "signature": "<hmac>"
  }
}
```
Response correlated by `id`. `binance_ws_api.py` exposes a promise-based API:
```python
resp = await ws_api.call(user_id, "order.place", params)
```

---

## Compatibility with IP whitelisting

User Data Stream connects from **the server's direct IP** (same as REST today) → **zero impact** on users who IP-whitelisted their key. This is important: UDS does NOT go through Webshare proxies. It's a single long-lived WS per user, not a per-request rotation.

WS API (phase 2) likewise connects from direct IP. Same whitelist compatibility as current REST.

If we ever want to remove the single-IP dependency, that's a separate "rotate server IP via proxy" discussion, orthogonal to this proposal.

---

## Rollout plan

### Phase 1 — User Data Stream for reads (highest ROI)
**Effort:** ~1 day
**Risk:** Low — purely additive. REST stays as fallback.

Steps:
1. Build `binance_user_stream.py` with listenKey + WS client + reconnect.
2. Build `ws_account_state.py` in-memory store. Hydrate with one REST snapshot on connect.
3. Wire startup hook in `app.py` to spawn one UDS task per `is_active=1` user.
4. Modify `get_live_balance()`: if `ws_account_state[uid]` is fresh (<30 s), serve from state; else fall back to REST (current code).
5. Add `/api/admin/ws-status` diagnostic endpoint showing connection state per user.
6. Deploy behind `BINANCE_WS_USER_STREAM=false` first; flip to `true` after 24 h of admin-only testing.

**Acceptance criteria:**
- `/api/copy-trading/balance` served from UDS state in <5 ms (vs ~300 ms REST).
- Zero `-1003` errors in 48 h post-rollout.
- Balance updates visible in dashboard within 1 s of a Binance fill.
- Auto-reconnect within 10 s of any WS drop.

### Phase 2 — WebSocket API for order placement
**Effort:** ~1 day
**Risk:** Medium — touches order hot path.

Steps:
1. Build `binance_ws_api.py` with request/response correlation, timeout, ed25519 signing (if we want to upgrade from HMAC).
2. Add `_place_market_order_ws(client_ctx, ...)` alongside existing REST path.
3. In `_execute_single_trade_blocking`, if `BINANCE_WS_ORDER_API=true`, try WS first, fall back to REST on timeout/error.
4. Shadow mode for 48 h: send order via REST AND via WS, log discrepancies, don't act on WS. Validate identical behavior.
5. Flip `BINANCE_WS_ORDER_API=true` for admin only, then all users.

**Acceptance criteria:**
- Order placement p50 <120 ms (vs ~300 ms REST).
- Error-rate parity with REST over 1000+ orders.
- Clean fallback to REST if WS API unreachable.

### Phase 3 — Retire REST for reads (cleanup)
**Effort:** ~2 h
**Risk:** Low.

After Phase 1 has 2+ weeks of zero incidents, remove the REST fallback in `get_live_balance()`. Delete `_BALANCE_CACHE`. Keep REST as emergency break-glass only (flag-gated).

---

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WS connection drops | **High** (normal for long-lived WS) | Low | Exponential backoff + REST fallback + health monitor |
| listenKey expires silently | Medium | High (stale state) | 30-min keepalive + `listenKeyExpired` handler → force reconnect |
| State divergence (WS missed an event) | Low | Medium | Periodic REST snapshot reconciliation every 5 min |
| Binance deprecates an endpoint | Low | Medium | Feature flag allows instant rollback |
| Per-user memory footprint | Low | Low | ~50 KB/user state + 1 connection. At 1000 users: ~50 MB, acceptable |
| Auth changes (HMAC → Ed25519) | Low | Low | Current HMAC works for both REST and WS; Ed25519 is optional upgrade |

---

## Out of scope (explicitly NOT in this proposal)

- Market-data WebSocket migration (already handled by `data_fetcher.py` / Webshare).
- Multi-IP / proxy rotation for signed endpoints. Orthogonal concern.
- SSE → WS upgrade for dashboard → browser (different layer).
- Migration of non-copy-trading REST calls (bot's own signal scanning).

---

## Decision needed from operator

1. Approve Phase 1 (UDS for reads) to start immediately? **[y/n]**
2. Approve Phase 2 (WS API for orders) pending Phase 1 success? **[y/n]**
3. Any users you want excluded from the rollout (e.g., keep a control cohort on REST)?
4. Do you want real-time balance/PnL pushed to the browser too (SSE → Binance event stream bridge), or keep the 5 s poll loop on the frontend?

---

## Estimated impact on the current incident

If Phase 1 had been live today:
- The `-1003` ban would **not** have occurred — the 50–100 REST calls/min from balance polling would have been zero.
- Copy-trade order placement during the ban window would have **still failed** (because all REST from the banned IP fails). Phase 2 would fix that too.

Caching patch deployed today (`_BALANCE_CACHE`, 15 s TTL) reduces the probability of recurrence by ~90% and is a sufficient stopgap. This migration is the durable fix.
