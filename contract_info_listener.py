"""
contract_info_listener.py — Track Binance futures contract lifecycle events.

Subscribes to `!contractInfo` on /market/ws. Pushes:
  • New listing      (contract status TRADING with onboard date)
  • Delisting        (status SETTLING / CLOSE)
  • Leverage bracket (`bks` field) updates

Why we care:
  - We get "Invalid symbol" REST 400s when scanning recently-delisted pairs.
    With this stream, we drop them from the active set the moment Binance
    flips status, eliminating noisy errors.
  - When new pairs list, we get an event so the next scan cycle can pick
    them up without manual config.
  - Leverage bracket updates affect position sizing — we cache the current
    max leverage per notional bracket so the trader never asks for more than
    Binance currently allows for the pair.

Usage
-----
    from contract_info_listener import CONTRACT_INFO
    asyncio.create_task(CONTRACT_INFO.run())

    if CONTRACT_INFO.is_delisted(pair):
        # skip this pair this cycle
        continue

    max_lev = CONTRACT_INFO.max_leverage_for(pair, notional_usd) or 50
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import websockets

from utils_logger import log_message


_WS_URL = "wss://fstream.binance.com/market/ws/!contractInfo"
_RECONNECT_BASE = 3
_RECONNECT_MAX  = 60

# Status flags Binance uses (cs field).
_DELISTED_STATES = {"SETTLING", "CLOSE", "BREAK", "PENDING_TRADING_OFFLINE"}


class ContractInfoListener:
    """Singleton — owns the WS connection and exposes contract state."""

    def __init__(self):
        # pair → latest contract status string
        self._status: dict[str, str] = {}
        # pair → (event time, list of brackets) — bracket = dict per Binance spec
        self._brackets: dict[str, tuple[float, list]] = {}
        # pair → onboard ts (ms) for newly-listed contracts we haven't seen before
        self._onboard: dict[str, int] = {}
        self.running = False
        self._msgs_rx = 0

    # ── public API ──────────────────────────────────────────────────────

    def is_delisted(self, pair: str) -> bool:
        return self._status.get(pair) in _DELISTED_STATES

    def status_for(self, pair: str) -> Optional[str]:
        return self._status.get(pair)

    def max_leverage_for(self, pair: str, notional_usd: float) -> Optional[int]:
        """Return the max leverage allowed for `notional_usd` on `pair`,
        or None if we don't have bracket data for this pair."""
        entry = self._brackets.get(pair)
        if not entry:
            return None
        _, brackets = entry
        for b in brackets:
            try:
                floor = float(b.get("bnf", 0))
                cap   = float(b.get("bnc", 0))
                if floor <= notional_usd < cap:
                    return int(b.get("ma", 0))
            except Exception:
                continue
        # fall through: notional is above the largest bracket → use last bracket's ma
        try:
            return int(brackets[-1].get("ma", 0))
        except Exception:
            return None

    def stats(self) -> dict:
        return {
            "tracked_pairs":   len(self._status),
            "delisted":        sum(1 for s in self._status.values() if s in _DELISTED_STATES),
            "with_brackets":   len(self._brackets),
            "msgs_rx":         self._msgs_rx,
        }

    def stop(self):
        self.running = False

    # ── WebSocket loop ──────────────────────────────────────────────────

    async def run(self):
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
                    max_size=2**22,
                ) as ws:
                    delay = _RECONNECT_BASE
                    log_message("✅ ContractInfoListener connected")
                    async for raw in ws:
                        if not self.running:
                            return
                        try:
                            msg = json.loads(raw)
                            self._msgs_rx += 1
                            if msg.get("e") != "contractInfo":
                                continue
                            sym = msg.get("s")
                            if not sym:
                                continue
                            status = msg.get("cs")
                            old_status = self._status.get(sym)
                            if status:
                                self._status[sym] = status
                                if old_status and old_status != status:
                                    log_message(f"📋 ContractInfo [{sym}] status: {old_status} → {status}")
                                    if status in _DELISTED_STATES:
                                        log_message(f"🛑 [{sym}] now delisted — will be skipped by scanner")
                                elif old_status is None:
                                    # first time we hear about this pair
                                    self._onboard[sym] = int(msg.get("ot", 0) or 0)
                            # bracket update arrives only on bracket changes
                            bks = msg.get("bks")
                            if bks:
                                self._brackets[sym] = (time.time(), list(bks))
                                try:
                                    max_lev = max(int(b.get("ma", 0)) for b in bks)
                                    log_message(f"📋 ContractInfo [{sym}] bracket update — max leverage now {max_lev}x")
                                except Exception:
                                    pass
                        except Exception:
                            continue
            except asyncio.CancelledError:
                return
            except Exception as e:
                log_message(f"⚠️ ContractInfoListener WS error: {e!r} — reconnecting in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX)


# Module-level singleton
CONTRACT_INFO = ContractInfoListener()
