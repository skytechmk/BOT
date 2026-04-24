"""
binance_ws_api.py — Binance Futures WebSocket API client (signed req/resp).

PURPOSE
    Route ALL signed Binance Futures calls (order placement, cancellation,
    order query, position query, account balance) over the persistent
    ws-fapi WebSocket, eliminating REST weight consumption on the hot path.

    Complementary to binance_user_stream.py which owns the PUSH-based
    User Data Stream.  This module owns the REQUEST/RESPONSE surface.

RATIONALE
    Binance's -1003 "Too many requests" ban is per-IP weight, counted
    against the REST fapi endpoint.  The ws-fapi endpoint has a SEPARATE
    rate-limit bucket (messages/min + connections), so routing orders
    over WS means a REST ban can't block order placement.

    Per python-binance 1.0.29, AsyncClient exposes:
        ws_futures_create_order
        ws_futures_cancel_order
        ws_futures_edit_order           (modify)
        ws_futures_get_order            (query)
        ws_futures_account_balance
        ws_futures_account_position     (v2)
        ws_futures_account_status
        ws_futures_get_order_book
        ws_futures_get_all_tickers

    Each call reuses a persistent wss://ws-fapi.binance.com/ws-fapi/v1
    connection managed internally by the library.

CONNECTION SHARING
    We reuse the AsyncClient instance that binance_user_stream creates
    for each user.  This means one AsyncClient per user, with TWO
    underlying WS connections:
      • wss://fstream.binance.com/ws/<listenKey>  (UDS, push)
      • wss://ws-fapi.binance.com/ws-fapi/v1      (WS API, req/resp)

FEATURE FLAG
    BINANCE_WS_ORDERS=true (default)  — send orders via WS
    BINANCE_WS_ORDERS=false           — every call raises WSAPIDisabled,
                                        caller must fall back to REST.

ERROR HANDLING
    Every method raises WSAPIError on Binance-reported failures.  -1003
    IP bans are captured via copy_trading._note_binance_ip_ban so the
    REST gate picks them up too (ws-fapi and REST share the underlying
    IP weight bucket for SOME operations).
"""

from __future__ import annotations

import os
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List

log = logging.getLogger("binance_ws_api")
if not log.handlers:
    from pathlib import Path
    _log_path = Path(__file__).resolve().parent.parent / "debug_log10.txt"
    _fh = logging.FileHandler(str(_log_path), encoding='utf-8')
    _fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - [ws_api] %(message)s'))
    log.addHandler(_fh)
    log.setLevel(logging.INFO)
    log.propagate = False


# ── Feature flag ─────────────────────────────────────────────────────────
def is_enabled() -> bool:
    """Master switch for WS-API routing of signed calls."""
    return os.getenv("BINANCE_WS_ORDERS", "true").strip().lower() in ("1", "true", "yes")


class WSAPIDisabled(Exception):
    """Raised when BINANCE_WS_ORDERS=false; caller should fall back to REST."""


class WSAPIError(Exception):
    """Wrapper for Binance errors returned over the WS API."""
    def __init__(self, code: int, msg: str, raw: Any = None):
        super().__init__(f"[{code}] {msg}")
        self.code = code
        self.msg  = msg
        self.raw  = raw


# ── Internal helpers ─────────────────────────────────────────────────────
async def _client(user_id: int):
    """Return (or lazily create) the per-user AsyncClient."""
    from binance_user_stream import UserStreamManager
    return await UserStreamManager.instance().get_or_create_client(user_id)


def _note_ip_ban_if_needed(raw_err: str) -> None:
    """Mirror -1003 detection from copy_trading so both gates stay aligned."""
    try:
        from copy_trading import _note_binance_ip_ban  # type: ignore
        _note_binance_ip_ban(raw_err)
    except Exception:
        pass


async def _call(user_id: int, method_name: str, **params) -> Dict[str, Any]:
    """
    Invoke a python-binance ws_futures_* method with unified error wrapping.

    Raises WSAPIDisabled if the feature flag is off — caller MUST handle.
    Raises WSAPIError on any Binance-reported failure.
    """
    if not is_enabled():
        raise WSAPIDisabled("BINANCE_WS_ORDERS=false")

    client = await _client(user_id)
    method = getattr(client, method_name, None)
    if method is None:
        raise WSAPIError(-1, f"method {method_name} not available on AsyncClient")

    t0 = time.time()
    try:
        result = await method(**params)
    except Exception as e:
        raw = str(e)
        _note_ip_ban_if_needed(raw)
        # python-binance raises BinanceAPIException w/ .code + .message
        code = getattr(e, "code", -2)
        msg  = getattr(e, "message", raw[:200])
        log.warning(f"user {user_id}: {method_name} FAILED [{code}] {msg}")
        raise WSAPIError(code, msg, raw) from e

    elapsed_ms = round((time.time() - t0) * 1000, 1)
    # python-binance returns the response directly (without the ws envelope).
    # Some builds return {"status": 200, "result": {...}} — unwrap if needed.
    if isinstance(result, dict) and "result" in result and "status" in result:
        if result["status"] != 200:
            err = result.get("error") or {}
            raise WSAPIError(err.get("code", result["status"]),
                             err.get("msg", "unknown"), raw=result)
        result = result["result"]
    log.info(f"user {user_id}: {method_name} OK ({elapsed_ms} ms)")
    return result


# ── Public API ───────────────────────────────────────────────────────────
async def create_order(user_id: int, **params) -> Dict[str, Any]:
    """
    Place a futures order via ws-fapi.  Params mirror REST:
      symbol, side, type, quantity, price, stopPrice, closePosition,
      positionSide, reduceOnly, workingType, timeInForce, newClientOrderId, ...
    Returns the order object (orderId, avgPrice, executedQty, ...).
    """
    return await _call(user_id, "ws_futures_create_order", **params)


async def cancel_order(user_id: int, symbol: str,
                       orderId: Optional[int] = None,
                       origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"symbol": symbol}
    if orderId is not None:          kwargs["orderId"] = orderId
    if origClientOrderId is not None: kwargs["origClientOrderId"] = origClientOrderId
    return await _call(user_id, "ws_futures_cancel_order", **kwargs)


async def edit_order(user_id: int, **params) -> Dict[str, Any]:
    """Modify an existing order in place (price/quantity)."""
    return await _call(user_id, "ws_futures_edit_order", **params)


async def get_order(user_id: int, symbol: str,
                    orderId: Optional[int] = None,
                    origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"symbol": symbol}
    if orderId is not None:          kwargs["orderId"] = orderId
    if origClientOrderId is not None: kwargs["origClientOrderId"] = origClientOrderId
    return await _call(user_id, "ws_futures_get_order", **kwargs)


async def account_balance(user_id: int) -> List[Dict[str, Any]]:
    return await _call(user_id, "ws_futures_account_balance")


async def account_position(user_id: int,
                           symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    kwargs: Dict[str, Any] = {}
    if symbol is not None:
        kwargs["symbol"] = symbol
    return await _call(user_id, "ws_futures_account_position", **kwargs)


async def account_status(user_id: int) -> Dict[str, Any]:
    return await _call(user_id, "ws_futures_account_status")
