"""
Batch Data Fetcher + Rust-accelerated Reverse Hunt indicators.

Prefetch fetches OHLCV for all pairs, then computes TSI + LinReg + CE (dual layer)
for 150+ pairs in ~30ms via Rust/Rayon (vs ~2400ms in Python).

Usage (in main_async, before the per-pair task loop):
    await BATCH_PROCESSOR.prefetch(pairs, '1h', fetch_data)
    # process_pair then calls BATCH_PROCESSOR.get_df(pair, tf)
    # and BATCH_PROCESSOR.get_rh(pair, tf) for pre-computed indicators
"""

import asyncio
import numpy as np
from utils_logger import log_message

try:
    import aladdin_core
    RUST_CORE_AVAILABLE = True
except ImportError:
    RUST_CORE_AVAILABLE = False


def _ce_params():
    """Read current CE Hybrid config from reverse_hunt.py (single source of truth).
    Lazy import to avoid circular-import risk at module load time."""
    from reverse_hunt import (
        CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT, CE_LINE_WAIT,
        CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, CE_CLOUD_MULT, CE_CLOUD_WAIT,
    )
    return (
        CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, float(CE_LINE_MULT), bool(CE_LINE_WAIT),
        CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, float(CE_CLOUD_MULT), bool(CE_CLOUD_WAIT),
    )


class BatchIndicatorCache:
    """Cache of OHLCV DataFrames + Rust-computed RH indicator arrays."""

    def __init__(self):
        self._cache: dict = {}          # (pair, tf) -> {col: list}
        self._df_cache: dict = {}       # (pair, tf) -> raw DataFrame
        self._rh_cache: dict = {}       # (pair, tf) -> dict of RH indicators

    # ── public API ──────────────────────────────────────────────────────────

    async def prefetch(
        self,
        pairs: list,
        timeframe: str,
        fetch_fn,
        **kwargs,
    ) -> bool:
        """
        1. Concurrent OHLCV fetch for all pairs.
        2. Single Rust call computes TSI + LinReg + CE (dual layer) for ALL pairs
           in parallel via Rayon (~30ms for 150 pairs).
        3. Results cached for get_df() and get_rh().
        """
        _BATCH_SIZE = 15  # throttle concurrency to flatten API bursts

        async def _fetch(pair):
            try:
                df = await asyncio.to_thread(fetch_fn, pair, timeframe)
                return pair, df
            except Exception:
                return pair, None

        # Fetch in batches to stay under Binance rate limits
        fetched = []
        for i in range(0, len(pairs), _BATCH_SIZE):
            batch = pairs[i:i + _BATCH_SIZE]
            batch_results = await asyncio.gather(*[_fetch(p) for p in batch])
            fetched.extend(batch_results)
            if i + _BATCH_SIZE < len(pairs):
                await asyncio.sleep(0.8)  # 0.8s total pause between 15-pair batches to perfectly flatten standard API request limits

        valid = [
            (pair, df) for pair, df in fetched
            if df is not None and not df.empty and len(df) >= 200
        ]
        if not valid:
            return False

        for pair, df in valid:
            self._df_cache[(pair, timeframe)] = df

        # Rust batch: compute all RH indicators in one Rayon call
        if RUST_CORE_AVAILABLE:
            import time
            batch_input = [
                (
                    df['high'].ffill().tolist(),
                    df['low'].ffill().tolist(),
                    df['close'].ffill().tolist(),
                )
                for _, df in valid
            ]
            try:
                t0 = time.perf_counter()
                results = aladdin_core.batch_reverse_hunt_rust(batch_input, *_ce_params())
                elapsed_ms = (time.perf_counter() - t0) * 1000

                for idx, (pair, df) in enumerate(valid):
                    tsi, linreg, ce_ll, ce_ls, ce_ld, ce_cl, ce_cs, ce_cd = results[idx]
                    self._rh_cache[(pair, timeframe)] = {
                        'tsi': tsi,
                        'linreg': linreg,
                        'ce_line_long': ce_ll,
                        'ce_line_short': ce_ls,
                        'ce_line_dir': ce_ld,
                        'ce_cloud_long': ce_cl,
                        'ce_cloud_short': ce_cs,
                        'ce_cloud_dir': ce_cd,
                    }

                log_message(
                    f"Batch RH indicators (Rust): {len(valid)}/{len(pairs)} pairs "
                    f"({timeframe}) — TSI+LinReg+CE computed in {elapsed_ms:.0f}ms"
                )
            except Exception as e:
                log_message(f"Rust batch RH failed ({e}), falling back to Python")
        else:
            log_message(
                f"Batch OHLCV fetch: {len(valid)}/{len(pairs)} pairs "
                f"({timeframe}) — Python fallback (no Rust)"
            )

        return True

    def update_single(self, pair: str, df_new_row, timeframe: str):
        """Update a single pair dynamically from WebSocket candle event."""
        if df_new_row is None or df_new_row.empty:
            return False
            
        key = (pair, timeframe)
        existing_df = self._df_cache.get(key)
        
        if existing_df is None or existing_df.empty:
            # If no history exists, we can't reliably calculate indicators like LinReg or TSI
            return False
            
        import pandas as pd
        # Update or append the new candle
        # Convert index to matching type (usually int64 if from sqlite, or datetime if fetched from ccxt)
        # Assuming df_new_row has the same index type (datetime)
        
        # Merge new row into existing df, overwriting if the timestamp matches
        updated_df = pd.concat([existing_df, df_new_row])
        # Group by index to keep the latest row for each timestamp
        updated_df = updated_df[~updated_df.index.duplicated(keep='last')].sort_index()
        
        # Keep recent 800
        updated_df = updated_df.tail(800)
        
        self._df_cache[key] = updated_df
        
        if RUST_CORE_AVAILABLE:
            try:
                batch_input = [(
                    updated_df['high'].ffill().tolist(),
                    updated_df['low'].ffill().tolist(),
                    updated_df['close'].ffill().tolist(),
                )]
                results = aladdin_core.batch_reverse_hunt_rust(batch_input, *_ce_params())
                tsi, linreg, ce_ll, ce_ls, ce_ld, ce_cl, ce_cs, ce_cd = results[0]
                self._rh_cache[key] = {
                    'tsi': tsi,
                    'linreg': linreg,
                    'ce_line_long': ce_ll,
                    'ce_line_short': ce_ls,
                    'ce_line_dir': ce_ld,
                    'ce_cloud_long': ce_cl,
                    'ce_cloud_short': ce_cs,
                    'ce_cloud_dir': ce_cd,
                }
                return True
            except Exception as e:
                return False
        return True

    def apply(self, df, pair: str, timeframe: str):
        """
        Inject pre-computed Rust indicator columns into df.
        Returns the enriched df, or df unchanged if no cached data.
        """
        key = (pair, timeframe)
        cached = self._cache.get(key)
        if not cached:
            return df

        n = len(df)
        for col, values in cached.items():
            if len(values) == n:
                df[col] = values
        return df

    def get_df(self, pair: str, timeframe: str):
        """Return the cached raw DataFrame (or None)."""
        return self._df_cache.get((pair, timeframe))

    def has(self, pair: str, timeframe: str) -> bool:
        return (pair, timeframe) in self._cache

    def evict(self, pair: str, timeframe: str):
        key = (pair, timeframe)
        self._cache.pop(key, None)
        self._df_cache.pop(key, None)

    def get_rh(self, pair: str, timeframe: str) -> dict:
        """Return pre-computed RH indicators (or empty dict for Python fallback)."""
        return self._rh_cache.get((pair, timeframe), {})

    def clear(self):
        self._cache.clear()
        self._df_cache.clear()
        self._rh_cache.clear()



# Global singleton — import and use directly
BATCH_PROCESSOR = BatchIndicatorCache()
