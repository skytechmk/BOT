"""
kline_stream_manager.py — Event-driven WebSocket kline streams for top-N pairs.

Binance Futures combined stream: wss://fstream.binance.com/stream?streams=...
Streams all 3 execution timeframes: 15m, 1h, 4h.
When ANY candle closes (x=True), process_pair() fires immediately.

Usage in main.py:
    manager = KlineStreamManager(process_pair_callback, top_n=20)
    asyncio.create_task(manager.run(pairs))
"""

import asyncio
import json
import time
import websockets
from utils_logger import log_message

_FUTURES_STREAM_URL = "wss://fstream.binance.com/stream?streams={streams}"
# All 3 execution timeframes — 15m/4h are cached for entry-refinement &
# regime context; only 1h closes trigger process_pair() (signals stay 1h-gated).
_KLINE_INTERVALS    = ['15m', '1h', '4h']
# Timeframes that actually fire process_pair on close. 15m/4h are "parked":
# data flows into BATCH_PROCESSOR but no signal re-evaluation happens on close.
_TRIGGER_INTERVALS  = {'1h'}
_MAX_STREAMS_PER_CONNECTION = 200   # Binance hard limit per WS connection
_RECONNECT_DELAY_BASE = 5           # seconds
_RECONNECT_DELAY_MAX  = 60
_CONN_STAGGER_SECS    = 1.5         # delay between opening successive WS shards


class KlineStreamManager:
    """
    Manages combined WebSocket streams for top-N pairs across 15m, 1h, 4h.
    Calls process_pair_fn(pair) immediately when any candle closes.
    Splits into multiple connections if streams > 200 (Binance limit).
    Falls back gracefully — if WS dies, polling loop in main.py covers it.
    """

    def __init__(self, process_pair_fn, top_n: int = 200):
        self.process_pair_fn = process_pair_fn
        self.top_n           = top_n
        self.running         = False
        self._active_pairs   = []
        self._last_trigger   = {}   # pair → last trigger timestamp (debounce)
        self._debounce_secs  = 30   # don't re-trigger same pair within 30s

    def update_pairs(self, pairs: list):
        """Update which pairs are being streamed (call each cycle)."""
        self._active_pairs = list(pairs[:self.top_n])

    def _build_stream_chunks(self, pairs: list) -> list:
        """Build URL chunks, splitting at 200 streams per connection."""
        all_streams = [
            f"{p.lower()}@kline_{tf}"
            for p in pairs
            for tf in _KLINE_INTERVALS
        ]
        # Split into groups of max 200
        chunks = []
        for i in range(0, len(all_streams), _MAX_STREAMS_PER_CONNECTION):
            group = all_streams[i:i + _MAX_STREAMS_PER_CONNECTION]
            chunks.append(_FUTURES_STREAM_URL.format(streams="/".join(group)))
        return chunks

    async def run(self, initial_pairs: list):
        """Main entry point — spawns one task per connection chunk, restarts on drop."""
        self.running = True
        self._active_pairs = list(initial_pairs[:self.top_n])

        while self.running:
            if not self._active_pairs:
                await asyncio.sleep(5)
                continue
            urls = self._build_stream_chunks(self._active_pairs)
            tfs  = ", ".join(_KLINE_INTERVALS)
            log_message(f"📡 KlineStream: {len(self._active_pairs)} pairs × [{tfs}] = {len(self._active_pairs)*len(_KLINE_INTERVALS)} streams ({len(urls)} connection(s))")
            # Run all chunks concurrently; stagger starts to avoid Binance
            # connect-rate limit (5 new conns per 300s per IP).
            async def _staggered_start(u, idx):
                await asyncio.sleep(idx * _CONN_STAGGER_SECS)
                await self._run_one(u)
            tasks = [asyncio.create_task(_staggered_start(url, i)) for i, url in enumerate(urls)]
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                log_message(f"⚠️ KlineStream gather error: {e}")
            for t in tasks:
                t.cancel()
            await asyncio.sleep(_RECONNECT_DELAY_BASE)

        log_message("🛑 KlineStream stopped.")

    async def _run_one(self, url: str):
        """Maintain a single WebSocket connection, reconnect on drop."""
        delay = _RECONNECT_DELAY_BASE
        while self.running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                    compression=None,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_DELAY_BASE
                    log_message(f"✅ KlineStream connection established")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg  = json.loads(raw)
                            data = msg.get("data", msg)
                            if data.get("e") != "kline":
                                continue
                            k = data["k"]
                            if not k.get("x", False):
                                continue  # candle still open
                            pair = k["s"]
                            tf   = k["i"]   # e.g. "15m", "1h", "4h"
                            
                            import pandas as pd
                            # Construct single row dataframe
                            df_new_row = pd.DataFrame([{
                                'timestamp': k['t'],
                                'open': float(k['o']),
                                'high': float(k['h']),
                                'low': float(k['l']),
                                'close': float(k['c']),
                                'volume': float(k['v'])
                            }])
                            df_new_row['timestamp'] = pd.to_datetime(df_new_row['timestamp'], unit='ms')
                            df_new_row.set_index('timestamp', inplace=True)
                            
                            from rust_batch_processor import BATCH_PROCESSOR
                            updated = BATCH_PROCESSOR.update_single(pair, df_new_row, tf)
                            if updated and tf in _TRIGGER_INTERVALS:
                                log_message(f"🕯️ {pair} {tf} candle closed → analysis triggered")
                                asyncio.create_task(self._safe_process(pair))
                            elif not updated:
                                log_message(f"⚠️ {pair} {tf} candle closed BUT cache update failed.")
                            # else: 15m/4h close — cache updated silently, no trigger
                        except Exception as e:
                            log_message(f"KlineStream msg error: {e}")
            except asyncio.CancelledError:
                return
            except Exception as e:
                log_message(f"⚠️ KlineStream conn dropped: {e} — retry in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_DELAY_MAX)

    async def _safe_process(self, pair: str):
        """Wrap process_pair_fn with error isolation."""
        try:
            await self.process_pair_fn(pair)
        except Exception as e:
            log_message(f"KlineStream process error for {pair}: {e}")

    def stop(self):
        self.running = False
