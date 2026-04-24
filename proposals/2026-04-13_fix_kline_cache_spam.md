# Proposal: Fix Kline Cache Update Spam

## Problem Description

The `debug_log10.txt` reveals constant log spam with the message:
`⚠️ SNDKUSDT 1h candle closed BUT cache update failed.`
`⚠️ QQQUSDT 1h candle closed BUT cache update failed.`
`⚠️ MUUSDT 1h candle closed BUT cache update failed.`
`⚠️ SPYUSDT 1h candle closed BUT cache update failed.`

**Root Cause:**
1. These symbols (recently listed stock tokens on Binance) lack sufficient historical data.
2. During initialization, `fetch_top_volume_pairs()` correctly fetches these symbols because they meet the volume threshold.
3. However, `BATCH_PROCESSOR.prefetch()` explicitly ignores pairs with `< 200` candles:
   ```python
   valid = [ (pair, df) for pair, df in fetched if df is not None and not df.empty and len(df) >= 200 ]
   ```
4. Even though they are rejected by the batch processor, `main.py` blindly passes the *entire* raw `pairs` list to `KlineStreamManager`:
   ```python
   _kline_manager.update_pairs(pairs)
   asyncio.create_task(_kline_manager.run(pairs))
   ```
5. Consequently, the WebSocket streams data for these invalid pairs. When their 1h candle closes, `kline_stream_manager.py` attempts to update the pair in the `BATCH_PROCESSOR`. Because the pair was never added to the cache, it returns `False`, generating the warning spam.

This not only pollutes the logs but also wastes Binance stream bandwidth and connection limits on pairs the bot literally cannot trade.

## Proposed Changes

We need to filter the pairs fed into `KlineStreamManager` ensuring it only opens streams for pairs that successfully initialized in the `BATCH_PROCESSOR`.

### 1. Filter Invalid Pairs in `main.py`
**File:** `main.py`
```diff
             if not _kline_stream_started and pairs:
                 # Initial warm up of cache via prefetch before starting WebSocket
                 active_pairs = [p for p in pairs if _pair_suspended_until.get(p, 0) <= current_time]
                 log_message(f"Initial warm-up: Prefetching {len(active_pairs)} pairs via REST...")
                 await BATCH_PROCESSOR.prefetch(active_pairs, '1h', fetch_data)
                 
-                _kline_manager.update_pairs(pairs)
-                asyncio.create_task(_kline_manager.run(pairs))
+                # Filter out pairs that failed to load into cache (e.g. newly listed, lack 200 candles)
+                valid_ws_pairs = [p for p in pairs if BATCH_PROCESSOR.get_df(p, '1h') is not None]
+                
+                _kline_manager.update_pairs(valid_ws_pairs)
+                asyncio.create_task(_kline_manager.run(valid_ws_pairs))
                 log_message(f"🚀 KlineStream started for top {_kline_manager.top_n} pairs")
                 _kline_stream_started = True
             elif pairs:
-                _kline_manager.update_pairs(pairs)
+                valid_ws_pairs = [p for p in pairs if BATCH_PROCESSOR.get_df(p, '1h') is not None]
+                _kline_manager.update_pairs(valid_ws_pairs)
```

## Risk Assessment
**Low Risk.** This optimizes the WebSocket connection allowance, preventing unnecessary load on the server and removing log pollution without altering any trading logic.
