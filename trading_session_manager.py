"""
trading_session_manager.py — Track session status of TradFi-perp underlyings.

Binance now exposes a `tradingSession` stream on /market/ws that pushes
session status for the U.S. equity and commodity markets every second.

Session types:
  • Equity:    PRE_MARKET / REGULAR / AFTER_MARKET / OVERNIGHT / NO_TRADING
  • Commodity: REGULAR / NO_TRADING

Why we care:
    Several USDS-M futures pairs are perpetuals on TradFi underlyings
    (TSLAUSDT, AAPLUSDT, AMZNUSDT, COPPERUSDT, XAGUSDT, ...). When the
    underlying market is closed, signal quality on these perps collapses
    — they trade on synthetic liquidity only and our TSI/CE indicators
    read noise instead of price discovery. The Lab tab data confirms this:
    every losing PERSISTENT_OS_L2 from Apr 18 evening was a TradFi pair
    fired during NO_TRADING.

Usage
-----
    from trading_session_manager import SESSION
    asyncio.create_task(SESSION.run())
    ...
    if not SESSION.is_underlying_active(pair):
        # underlying closed — route to experimental tier
        ...
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import websockets

from utils_logger import log_message


_WS_URL          = "wss://fstream.binance.com/market/ws/tradingSession"
_RECONNECT_BASE  = 3
_RECONNECT_MAX   = 60

# ── Pair → market-category mapping ───────────────────────────────────────
# Hard-coded for now; can be derived from !contractInfo once that listener
# is live. Keep this list in sync with newly listed TradFi perps.
_EQUITY_TICKERS = {
    'TSLAUSDT', 'AAPLUSDT', 'GOOGLUSDT', 'AMZNUSDT', 'METAUSDT', 'NVDAUSDT',
    'MSTRUSDT', 'COINUSDT', 'PAYPUSDT', 'VICIUSDT', 'AGLDUSDT', 'ERAUSDT',
    'CRCLUSDT', 'DODOXUSDT', 'SPYUSDT', 'QQQUSDT', 'EWJUSDT', 'IWMUSDT',
    'GLDUSDT',
}
_COMMODITY_TICKERS = {
    'XAGUSDT', 'COPPERUSDT', 'XAUUSDT', 'XPTUSDT', 'XPDUSDT', 'WTIUSDT',
}


class TradingSessionManager:
    """Singleton — owns the WS connection and exposes session state."""

    def __init__(self):
        # Defaults: assume regular until we hear otherwise (fail-open).
        self._equity_session    = "REGULAR"
        self._commodity_session = "REGULAR"
        self._equity_ts         = 0.0
        self._commodity_ts      = 0.0
        self.running = False
        self._msgs_rx = 0

    # ── public API ──────────────────────────────────────────────────────

    def session_for(self, pair: str) -> Optional[str]:
        """Return the relevant session string for `pair`, or None for crypto."""
        if pair in _EQUITY_TICKERS:
            return self._equity_session
        if pair in _COMMODITY_TICKERS:
            return self._commodity_session
        return None  # crypto — no underlying market

    def is_underlying_active(self, pair: str) -> bool:
        """Return True if pair is crypto OR its underlying is in REGULAR session.

        Fail-open: if we have no data yet (haven't received first message),
        assume active. This avoids false-positive blocking during boot.
        """
        s = self.session_for(pair)
        if s is None:
            return True            # crypto pair — always active
        # If we never received any session data, fail-open.
        if pair in _EQUITY_TICKERS    and self._equity_ts    == 0.0: return True
        if pair in _COMMODITY_TICKERS and self._commodity_ts == 0.0: return True
        return s == "REGULAR"

    def is_tradfi(self, pair: str) -> bool:
        return pair in _EQUITY_TICKERS or pair in _COMMODITY_TICKERS

    def stats(self) -> dict:
        return {
            "equity_session":    self._equity_session,
            "equity_ts":         self._equity_ts,
            "commodity_session": self._commodity_session,
            "commodity_ts":      self._commodity_ts,
            "msgs_rx":           self._msgs_rx,
        }

    def stop(self):
        self.running = False

    # ── WebSocket loop ──────────────────────────────────────────────────

    async def run(self):
        """Open WS, update session state, auto-reconnect on drop."""
        self.running = True
        delay = _RECONNECT_BASE
        while self.running:
            try:
                async with websockets.connect(
                    _WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    open_timeout=15,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message("✅ TradingSessionManager connected")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg = json.loads(raw)
                            self._msgs_rx += 1
                            evt = msg.get("e")
                            sess = msg.get("S")
                            now = time.time()
                            if evt == "EquityUpdate" and sess:
                                if sess != self._equity_session:
                                    log_message(f"📊 Equity session: {self._equity_session} → {sess}")
                                self._equity_session = sess
                                self._equity_ts      = now
                            elif evt == "CommodityUpdate" and sess:
                                if sess != self._commodity_session:
                                    log_message(f"📊 Commodity session: {self._commodity_session} → {sess}")
                                self._commodity_session = sess
                                self._commodity_ts      = now
                        except Exception:
                            continue
            except asyncio.CancelledError:
                return
            except Exception as e:
                log_message(f"⚠️ TradingSessionManager WS error: {e!r} — reconnecting in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)


# Module-level singleton
SESSION = TradingSessionManager()
