"""
mexc_kline_stream.py — WebSocket kline streams for MEXC Futures pairs.

MEXC Futures WS endpoint: wss://contract.mexc.com/edge
Per-symbol subscription:  {"method": "sub.kline", "param": {"symbol": "BTC_USDT", "interval": "Min60"}}
Push format:              {"channel": "push.kline", "data": {"a":..., "c":..., "h":..., "l":..., "o":..., "q":..., "symbol":"BTC_USDT", "t":...}, "symbol":"BTC_USDT"}

Unlike Binance, MEXC has no "x" (candle closed) flag — we detect closes
by tracking the last `t` (open-time) per symbol and firing when it advances.

Usage in main.py:
    manager = MexcKlineStreamManager(process_pair_callback, top_n=300)
    asyncio.create_task(manager.run(pairs))
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Set

import websockets

from utils_logger import log_message

_WS_URL = "wss://contract.mexc.com/edge"

# MEXC interval mapping (Binance → MEXC)
_INTERVAL_MAP = {
    '1h': 'Min60',
    '4h': 'Hour4',
    '15m': 'Min15',
}

# Only 1h closes trigger process_pair (same as Binance KlineStreamManager)
_TRIGGER_INTERVALS = {'Min60'}

_RECONNECT_DELAY_BASE = 5
_RECONNECT_DELAY_MAX = 60
_PING_INTERVAL = 15            # seconds between pings
_MAX_SUBS_PER_CONN = 100       # limit subscriptions per WS connection
_SUB_BATCH_DELAY = 0.05        # 50ms between subscription messages


def _to_mexc(binance_sym: str) -> str:
    """BTCUSDT → BTC_USDT"""
    s = binance_sym.upper().strip()
    if '_' in s:
        return s
    for quote in ('USDT', 'USDC', 'USD'):
        if s.endswith(quote):
            return s[:-len(quote)] + '_' + quote
    return s


def _to_binance(mexc_sym: str) -> str:
    """BTC_USDT → BTCUSDT"""
    return mexc_sym.replace('_', '')


class MexcKlineStreamManager:
    """
    Manages MEXC Futures WebSocket kline streams.
    Calls process_pair_fn(pair, exchange='mexc') when a 1h candle closes.
    Splits into multiple connections if pairs > MAX_SUBS_PER_CONN.
    REST fallback in main.py covers gaps if WS drops.
    """

    def __init__(self, process_pair_fn: Callable, top_n: int = 300):
        self.process_pair_fn = process_pair_fn
        self.top_n = top_n
        self.running = False
        self._active_pairs: List[str] = []      # Binance format
        self._last_kline_t: Dict[str, int] = {} # mexc_sym → last kline open timestamp
        self._debounce_secs = 30
        self._last_trigger: Dict[str, float] = {}

    def update_pairs(self, pairs: List[str]):
        """Update which pairs to stream (Binance format symbols)."""
        self._active_pairs = list(pairs[:self.top_n])

    def _chunk_pairs(self, pairs: List[str]) -> List[List[str]]:
        """Split pairs into chunks of MAX_SUBS_PER_CONN."""
        chunks = []
        for i in range(0, len(pairs), _MAX_SUBS_PER_CONN):
            chunks.append(pairs[i:i + _MAX_SUBS_PER_CONN])
        return chunks

    async def run(self, initial_pairs: List[str]):
        """Main entry — spawn one task per connection chunk."""
        self.running = True
        self._active_pairs = list(initial_pairs[:self.top_n])

        while self.running:
            if not self._active_pairs:
                await asyncio.sleep(5)
                continue

            chunks = self._chunk_pairs(self._active_pairs)
            intervals = list(_INTERVAL_MAP.values())
            log_message(
                f"🟡 MEXC KlineStream: {len(self._active_pairs)} pairs × "
                f"{intervals} = {len(chunks)} connection(s)"
            )

            tasks = [
                asyncio.create_task(self._run_one(chunk, idx))
                for idx, chunk in enumerate(chunks)
            ]
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                log_message(f"⚠️ MEXC KlineStream gather error: {e}")
            for t in tasks:
                t.cancel()
            await asyncio.sleep(_RECONNECT_DELAY_BASE)

        log_message("🛑 MEXC KlineStream stopped.")

    async def _run_one(self, pairs: List[str], conn_idx: int):
        """Maintain one MEXC WS connection with subscriptions for a chunk of pairs."""
        delay = _RECONNECT_DELAY_BASE
        while self.running:
            try:
                async with websockets.connect(
                    _WS_URL,
                    ping_interval=None,  # We handle pings manually
                    ping_timeout=None,
                    close_timeout=5,
                    max_size=2**20,
                    compression=None,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_DELAY_BASE
                    log_message(f"✅ MEXC KlineStream conn#{conn_idx} connected ({len(pairs)} pairs)")

                    # Subscribe to klines for all pairs × intervals
                    await self._subscribe_all(ws, pairs)

                    # Run ping loop and message handler concurrently
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    try:
                        async for raw in ws:
                            if not self.running:
                                return
                            try:
                                msg = json.loads(raw)
                                channel = msg.get('channel', '')

                                if channel == 'pong':
                                    continue

                                if channel == 'push.kline':
                                    await self._handle_kline(msg)
                            except Exception as e:
                                log_message(f"MEXC KlineStream msg error: {e}")
                    finally:
                        ping_task.cancel()

            except asyncio.CancelledError:
                return
            except Exception as e:
                log_message(f"⚠️ MEXC KlineStream conn#{conn_idx} dropped: {e} — retry in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_DELAY_MAX)

    async def _subscribe_all(self, ws, pairs: List[str]):
        """Send subscription messages for all pairs × intervals."""
        count = 0
        for pair in pairs:
            mexc_sym = _to_mexc(pair)
            for _binance_iv, mexc_iv in _INTERVAL_MAP.items():
                sub_msg = json.dumps({
                    "method": "sub.kline",
                    "param": {"symbol": mexc_sym, "interval": mexc_iv}
                })
                await ws.send(sub_msg)
                count += 1
                if count % 20 == 0:
                    await asyncio.sleep(_SUB_BATCH_DELAY)
        log_message(f"🟡 MEXC subscribed to {count} kline streams")

    async def _ping_loop(self, ws):
        """Send ping every PING_INTERVAL seconds to keep connection alive."""
        try:
            while self.running:
                await asyncio.sleep(_PING_INTERVAL)
                try:
                    await ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    return  # Connection dead, let outer loop reconnect
        except asyncio.CancelledError:
            return

    async def _handle_kline(self, msg: dict):
        """Process a push.kline message. Detect candle close by timestamp advance."""
        data = msg.get('data', {})
        mexc_sym = data.get('symbol') or msg.get('symbol', '')
        interval = data.get('interval', '')
        kline_t = data.get('t', 0)  # candle open timestamp (seconds)

        if not mexc_sym or not kline_t:
            return

        # Track candle open time per symbol+interval
        cache_key = f"{mexc_sym}:{interval}"
        prev_t = self._last_kline_t.get(cache_key, 0)

        if prev_t > 0 and kline_t > prev_t:
            # Candle closed — the timestamp advanced to a new candle
            self._last_kline_t[cache_key] = kline_t

            if interval in _TRIGGER_INTERVALS:
                binance_sym = _to_binance(mexc_sym)

                # Debounce: don't re-trigger same pair within 30s
                now = time.time()
                last = self._last_trigger.get(binance_sym, 0)
                if now - last < self._debounce_secs:
                    return
                self._last_trigger[binance_sym] = now

                log_message(f"🕯️ MEXC {binance_sym} {interval} candle closed → analysis triggered")
                asyncio.create_task(self._safe_process(binance_sym))
        else:
            # First observation or same candle — just update tracker
            self._last_kline_t[cache_key] = kline_t

    async def _safe_process(self, pair: str):
        """Wrap process_pair_fn with error isolation."""
        try:
            await self.process_pair_fn(pair, exchange='mexc')
        except Exception as e:
            log_message(f"MEXC KlineStream process error for {pair}: {e}")

    def stop(self):
        self.running = False
