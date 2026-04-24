# Proposal: Enable Taker Volume Persistence & Real-time Integration

## Problem Description
The PREDATOR Layer 2 (Positioning Analysis) relies on `taker_buy_base_asset_volume` to calculate institutional buyer/seller delta:
```python
if df is not None and 'taker_buy_base_asset_volume' in df.columns and len(df) >= 12:
    taker_buy = df['taker_buy_base_asset_volume'].astype(float).iloc[-12:].sum()
```
However, this feature is currently broken across the entire pipeline:
1.  **Data Fetcher**: The SQLite schema in `data_fetcher.py` only stores `timestamp, open, high, low, close, volume`. Taker volume is discarded.
2.  **WebSocket**: `kline_stream_manager.py` does not extract the `V` field (Taker buy base asset volume) from the Binance WebSocket message.
3.  **Result**: Taker Delta always calculates as `0.0`, resulting in a systematic 0/5 score for that SQI component for every trade.

## Proposed Changes

### 1. Update SQLite Schema in `data_fetcher.py`
**File:** `data_fetcher.py`
Add `taker_buy_base_asset_volume` to the table creation and selection logic.

```diff
 def _ohlcv_ensure_table(conn, table):
     conn.execute(f'''
         CREATE TABLE IF NOT EXISTS "{table}" (
             timestamp INTEGER PRIMARY KEY,
-            open REAL, high REAL, low REAL, close REAL, volume REAL
+            open REAL, high REAL, low REAL, close REAL, volume REAL,
+            taker_buy_base_asset_volume REAL
         )
     ''')
```

### 2. Include Taker Volume in WebSocket Updates
**File:** `kline_stream_manager.py`
Extract the `V` field from the WebSocket kline message.

```diff
                             df_new_row = pd.DataFrame([{
                                 'timestamp': k['t'],
                                 'open': float(k['o']),
                                 'high': float(k['h']),
                                 'low': float(k['l']),
                                 'close': float(k['c']),
-                                'volume': float(k['v'])
+                                'volume': float(k['v']),
+                                'taker_buy_base_asset_volume': float(k['V'])
                             }])
```

### 3. Graceful Fallback in `predator.py`
**File:** `predator.py`
If the column is missing (e.g., during the transition period or on symbols with corrupt history), default to neutral rather than generating errors. (Already partially implemented, but we'll ensure it remains robust).

## Risk Assessment
**Low Risk.**
- **Database**: Migration is handled automatically by `INSERT OR REPLACE` after the table schema is updated.
- **Performance**: Negligible increase in SQLite storage and WebSocket payload processing.
- **Integrity**: Significantly improves the accuracy of the Signal Quality Index (SQI) by enabling the positioning factor.
