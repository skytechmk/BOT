# Dynamic Trailing Stop-Loss — Chandelier Exit (1h)

**Date:** 2026-04-22
**Status:** ✅ Implemented, live on the next reconciler tick (≤ 5 min after deploy)
**Feature flag:** `TRAILING_ENABLED=true` (default — set to `false` to disable at runtime)
**Tier gate:** 🌟 **ULTRA tier only** — copy-trade SL propagation runs solely for users with `users.tier = 'ultra'` and unexpired `tier_expires`. Elite-tier copy-traders keep their original signal SL (with the legacy breakeven-after-TP1 fallback still enforced by the reconciler).
**Communication:** Fully **active / platform-side**. The bot modifies each Ultra user's Binance `STOP_MARKET` directly — no Telegram chat messages are emitted per ratchet. The user sees the live `sl_price` in their dashboard trade history and on Binance itself.

---

## Summary

After the first take-profit (TP1) on a signal is hit, the bot now automatically
ratchets the stop-loss upward (LONG) or downward (SHORT) using the
**Chandelier Exit (22/3.0)** on the **1h** timeframe. Each time the trail SL
improves meaningfully, the bot:

1. **Persists** the new SL to `signal_registry.db` (`signals.trail_sl`).
2. **Re-positions** every copy-trader's Binance `STOP_MARKET` close-position
   order via cancel-and-replace (Binance does not support in-place stop-price
   modification on futures conditional orders).
3. **Updates** `copy_trades.sl_price` so the software SL monitor (fallback for
   Portfolio Margin accounts) is armed with the same level.
4. **Posts a Telegram reply** to the original signal message announcing the
   SL move, rate-limited by the `TRAIL_ANNOUNCE_MIN_PCT` move threshold so
   users don't get spammed by micro-adjustments.

The reconciler's SL-hit kline walk now uses `max(original_sl, entry, trail_sl)`
for LONGs (or `min(...)` for SHORTs) when `targets_hit >= 1`, so trailed
signals close with the correct PnL in statistics.

---

## Files changed

| File | Change |
|---|---|
| `trailing_engine.py` | **NEW** — core engine: CE computation, ratchet logic, Telegram + copy-trade fan-out. |
| `performance_tracker.py` | Reconciler now SELECTs `trail_sl`, ensures schema, and uses the best of `(original_sl, entry, trail_sl)` for SL-hit resolution after TP1. |
| `main.py` | After each reconcile tick, calls `trailing_engine.run_trailing_cycle()` to persist new trail values and fire async Telegram + copy-trade updates. |
| `dashboard/copy_trading.py` | Adds `update_copy_sl_for_signal()` + `_replace_exchange_sl_blocking()` — cancels old STOP_MARKET (legacy + algo endpoints), places new one, updates `copy_trades.sl_price`. |
| `signal_registry.db` | New columns on `signals`: `trail_sl`, `trail_last_announced`, `trail_activated_ts`. Migration is idempotent and runs on first reconciler tick after deploy. |

---

## Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `TRAILING_ENABLED` | `true` | Master on/off switch. |
| `TRAIL_CE_PERIOD` | `22` | Chandelier Exit ATR period. |
| `TRAIL_CE_MULT` | `3.0` | Chandelier Exit ATR multiplier. |
| `TRAIL_TF` | `1h` | Timeframe for CE calculation (uses `data_fetcher.fetch_data` cache). |
| `TRAIL_MIN_IMPROVE_PCT` | `0.10` | Ratchet is only applied if the new SL moves the stop by ≥ this %. |
| `TRAIL_ANNOUNCE_MIN_PCT` | `0.30` | Telegram reply is only posted on moves ≥ this % from the last announced SL. |
| `TRAIL_BREAKEVEN_BUFFER` | `0.0` | % above entry (LONG) / below entry (SHORT) as a floor/ceiling for the first trail. |

---

## End-to-end flow

```
[T+0     SIGNAL]          LONG HYPER @ 0.09930, SL 0.09640
                          └─ Binance: MARKET entry + STOP_MARKET @ 0.09640
                          └─ sl_price column set = 0.09640 (software monitor armed)

[T+47m   TP1 HIT]         targets_hit=1 persisted via reconciler

[T+50m   RECONCILE TICK]  trailing_engine:
                          ├─ CE_Long_Stop(1h) = 0.09855
                          ├─ candidate = max(entry, CE) = 0.09930 (breakeven floor wins)
                          ├─ improvement: 0.09640 → 0.09930 (ratchet up)
                          ├─ persist signals.trail_sl = 0.09930
                          ├─ Telegram reply:
                          │    "🔒 Trailing SL updated — HYPERUSDT LONG
                          │     SL: 0.09640 → 0.09930  (CE-22/3.0 on 1h)"
                          └─ copy_trading.update_copy_sl_for_signal:
                                for each of N open copy-traders:
                                   ├─ cancel old STOP_MARKET (legacy + algo)
                                   ├─ place new STOP_MARKET @ 0.09930 closePosition=true
                                   ├─ UPDATE copy_trades SET sl_price=0.09930
                                   └─ 50 ms pacing between users

[T+2h    RECONCILE TICK]  CE climbs to 0.10050 → ratchet → users get 0.10050 stop + reply
[T+3h    RECONCILE TICK]  CE → 0.10180 → ratchet → users get 0.10180 stop + reply

[T+4h18m MARK BREACH]     Binance STOP_MARKET fires @ 0.10180 for every copy-trader
                          Position monitor detects empty position → copy_trades.status='closed'
                          Reconciler resolves signal: SL hit above entry → profit booked
```

---

## Why cancel-and-replace (not modify)?

Binance Futures **does not support modifying `stopPrice`** on an existing
`STOP_MARKET` / `TAKE_PROFIT_MARKET` conditional order. The only way to move
a stop is to cancel the old one and place a new one. We do this via two
endpoints to cover both legacy and migrated accounts:

- Legacy: `POST /fapi/v1/order` + `DELETE /fapi/v1/order`
- Algo (migrated / PM): `POST /fapi/v1/algoOrder` + `DELETE /fapi/v1/algoOrder`

Cancels are issued for **both** endpoints every cycle (cheap and idempotent)
because we cannot always tell from a single query which one the original
order was placed through. The placement retries algo first and falls back
to legacy on failure, matching the existing `_place_conditional` pattern in
`dashboard/copy_trading.py`.

---

## Safety characteristics

| Risk | Mitigation |
|---|---|
| Naked position during cancel→replace (~100 ms window) | Software SL monitor polls every 15 s and re-reads `sl_price` on each tick — it will fire a MARKET close if a breach happens in the window. |
| Rate-limit blowout with N copy-traders × M ratchets per signal | Sequential per-user with 50 ms pacing → 100 users trail = ~5 s of API activity per ratchet. Well under Binance's 2400 req/min ceiling. |
| User disabled copy-trading between signal and ratchet | `update_copy_sl_for_signal` JOINs `copy_trading_config.is_active` and skips inactive users automatically. |
| Trail SL that crosses current mark (would close instantly) | `_is_improvement` only ratchets relative to the previous SL; Binance itself rejects a stop that's already breached, so at worst the SL stays where it is and we see a logged warning. |
| TP already hit part-fills the qty (e.g. pyramid mode) | All STOP_MARKET orders are placed with `closePosition=true`, which auto-closes whatever position size remains — no qty math needed when trailing. |
| Telegram spam from micro-moves | `TRAIL_ANNOUNCE_MIN_PCT=0.30%` gate. Persists the last-announced SL in `trail_last_announced`, so consecutive sub-threshold ratchets accumulate silently until they cross the announcement floor. |
| Reconciler crash before fan-out | Schema migration is idempotent; the next reconciler tick re-evaluates from `trail_sl` and either re-ratchets or does nothing. No state is lost. |

---

## Rollback

Set `TRAILING_ENABLED=false` in `.env` and restart the bot. All trailing
functions become no-ops; existing `trail_sl` values stay in the DB but the
reconciler's breakeven-SL fallback (`sl = entry` after TP1) continues to
apply. To fully revert, drop the three `signals` columns manually.

---

## Verification

After the first reconciler tick post-deploy:

```bash
sqlite3 signal_registry.db \
  "SELECT signal_id, pair, signal, targets_hit, stop_loss, trail_sl \
   FROM signals WHERE status IN ('SENT','OPEN') AND targets_hit>=1;"
```

Look for `trail_sl > 0` rows. Then `debug_log10.txt` should show lines like:

```
[trailing] HYPERUSDT LONG sid=ab12cd34 SL 0.09640 → 0.09930 (+ratchet, announce=True)
[trail] user=7 HYPERUSDT SL → 0.0993
[trailing] 3 SL ratchet(s) applied this cycle
```

And subscribers should see a Telegram reply under the original signal message.
