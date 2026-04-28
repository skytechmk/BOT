# MEXC Futures Integration — Copy-Trading Multi-Exchange Support

**Date**: 2026-04-27
**Status**: Implementation complete, pending review
**Risk**: Medium — new exchange path is fully isolated; Binance path untouched

---

## Summary

Added MEXC Futures as a second supported exchange for the copy-trading system.
Users can now select Binance or MEXC from the dashboard, enter their API keys,
and receive automated trade execution on their chosen exchange.

## Files Changed

### New File
| File | Purpose |
|------|---------|
| `dashboard/mexc_futures_client.py` (693 lines) | MEXC Futures REST API client — auth, signing, orders, positions, balance, leverage, TP/SL, market data, Binance-format adapters |

### Modified Files
| File | Change |
|------|--------|
| `dashboard/copy_trading.py` | Exchange column migration, `_get_user_exchange()` helper, MEXC routing in `_get_futures_client_fresh`, `save_api_keys` accepts `exchange` param, `_execute_single_trade_mexc` (full MEXC order pipeline), `_close_all_positions_mexc`, `_close_single_position_mexc`, `get_open_trades_live_pnl` MEXC adapter, `_record_trade` persists exchange, `quick_entry_trade` MEXC mark price fetch |
| `dashboard/app.py` | `/api/copy-trading/keys` accepts `exchange` in body, conditionally starts Binance user stream (skip for MEXC) |
| `dashboard/static/js/copytrading.js` | Exchange selector UI: Binance + MEXC both "ACTIVE" and clickable, `_ctSelectExchange()` toggle function, exchange sent with key save payload |

## DB Schema Changes

Two ALTER TABLE migrations (auto-applied by `init_copy_trading_db`):
```sql
ALTER TABLE copy_trading_config ADD COLUMN exchange TEXT DEFAULT 'binance';
ALTER TABLE copy_trades ADD COLUMN exchange TEXT DEFAULT 'binance';
```

Backward compatible — all existing rows default to `'binance'`.

## Architecture

- **Routing**: `_execute_single_trade_blocking` checks `_get_user_exchange(user_id)` at entry and dispatches to `_execute_single_trade_mexc` or the existing Binance path
- **Client cache**: Single `_CLIENT_CACHE` stores both Binance Client and MexcFuturesClient instances (keyed by user_id)
- **Exchange cache**: `_USER_EXCHANGE_CACHE` avoids repeated DB lookups per trade
- **Close functions**: `close_all_positions` and `close_single_position` route to `_close_all_positions_mexc` / `_close_single_position_mexc` for MEXC users
- **Live PnL**: `get_open_trades_live_pnl` uses `client.get_position_as_binance_format()` for MEXC, returning Binance-compatible dicts so downstream code is unchanged

## MEXC API Differences Handled

| Aspect | Binance | MEXC |
|--------|---------|------|
| Symbol format | `BTCUSDT` | `BTC_USDT` (auto-converted) |
| Volume | Base asset qty | Contract count (vol) |
| Side values | `BUY`/`SELL` | 1/2/3/4 (open/close × long/short) |
| Order type | `MARKET` | 5 (market) |
| Hedge mode | Dual position side | positionType 1=long, 2=short |
| SL/TP | Algo orders | Stop orders + plan (trigger) orders |
| User stream | WebSocket push | REST polling (no persistent WS) |

## What's NOT Changed

- Binance execution path: zero modifications to existing Binance order logic
- Signal generation pipeline: signals are exchange-agnostic
- Telegram notifications: exchange field available for future enrichment
- SL monitor: software SL fallback works for both exchanges

## Testing Checklist

- [ ] Existing Binance users see no change in behavior
- [ ] New MEXC user can select MEXC, enter keys, save successfully
- [ ] MEXC key validation returns balance
- [ ] Trade executes on MEXC with correct contract volume
- [ ] SL and TP orders placed on MEXC
- [ ] Live PnL displays for MEXC positions
- [ ] Close single / close all works for MEXC
- [ ] Quick entry works for MEXC users
- [ ] Exchange selector UI toggles correctly
