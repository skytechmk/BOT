"""
MEXC Futures API Client
=======================
Thin wrapper around the MEXC Futures REST API (https://api.mexc.com).
Covers: authentication, order placement, position management, balance,
leverage, TP/SL, and market data.

Used by the copy-trading module as a drop-in alternative to the Binance
python-binance client.

Symbol format: MEXC uses underscores (BTC_USDT), Binance uses none (BTCUSDT).
Volume model : MEXC Futures trades in *contracts*; each symbol has a
               `contractSize` (e.g. BTC_USDT = 0.0001 BTC per contract).

Side values:
    1 = Open Long    (buy to open)
    2 = Close Short  (buy to close)
    3 = Open Short   (sell to open)
    4 = Close Long   (sell to close)

Order types:
    1 = Limit price
    2 = Post-only maker
    3 = IOC (fill or cancel immediately)
    4 = FOK (fill all or cancel)
    5 = Market
    6 = Convert market to current price

Open types:
    1 = Isolated
    2 = Cross
"""

import hashlib
import hmac
import json
import logging
import math
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

log = logging.getLogger("mexc_futures")

BASE_URL = "https://api.mexc.com"
TIMEOUT = 30


# ── Symbol conversion helpers ─────────────────────────────────────────
def to_mexc_symbol(binance_symbol: str) -> str:
    """Convert Binance-style 'BTCUSDT' to MEXC-style 'BTC_USDT'."""
    s = binance_symbol.upper().strip()
    if "_" in s:
        return s
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote):
            return s[:-len(quote)] + "_" + quote
    return s


def to_binance_symbol(mexc_symbol: str) -> str:
    """Convert MEXC-style 'BTC_USDT' to Binance-style 'BTCUSDT'."""
    return mexc_symbol.replace("_", "")


# ── Signing ────────────────────────────────────────────────────────────
def _sign(access_key: str, secret_key: str, timestamp: int,
          param_str: str = "") -> str:
    """HMAC-SHA256 signature per MEXC docs: sign(accessKey + timestamp + paramStr)."""
    payload = f"{access_key}{timestamp}{param_str}"
    return hmac.new(
        secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class MexcFuturesClient:
    """Synchronous MEXC Futures REST API client."""

    def __init__(self, api_key: str, api_secret: str,
                 timeout: int = TIMEOUT, recv_window: int = 5000):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.timeout = timeout
        self.recv_window = recv_window
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        # Contract detail cache {symbol: detail_dict}
        self._contract_cache: Dict[str, Dict] = {}
        self._contract_cache_ts: float = 0.0
        self._contract_cache_ttl: float = 300.0  # 5 min

    # ── Low-level request helpers ──────────────────────────────────────
    def _headers(self, timestamp: int, signature: str) -> Dict[str, str]:
        return {
            "ApiKey": self.api_key,
            "Request-Time": str(timestamp),
            "Signature": signature,
            "Content-Type": "application/json",
        }

    def _public_get(self, path: str, params: Optional[Dict] = None) -> Any:
        """Unauthenticated GET request."""
        url = f"{BASE_URL}{path}"
        r = self._session.get(url, params=params, timeout=self.timeout)
        return self._parse(r)

    def _private_get(self, path: str, params: Optional[Dict] = None) -> Any:
        """Authenticated GET — params sorted alphabetically for signature."""
        params = params or {}
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        # Sort and build query string for signature
        sorted_params = sorted(params.items())
        param_str = urlencode(sorted_params) if sorted_params else ""
        ts = int(time.time() * 1000)
        sig = _sign(self.api_key, self.api_secret, ts, param_str)
        url = f"{BASE_URL}{path}"
        r = self._session.get(
            url, params=params, headers=self._headers(ts, sig),
            timeout=self.timeout,
        )
        return self._parse(r)

    def _private_post(self, path: str, body: Optional[Dict] = None) -> Any:
        """Authenticated POST — body is JSON string (not sorted) for signature."""
        body = body or {}
        # Remove None values
        body = {k: v for k, v in body.items() if v is not None}
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        ts = int(time.time() * 1000)
        sig = _sign(self.api_key, self.api_secret, ts, body_str)
        url = f"{BASE_URL}{path}"
        r = self._session.post(
            url, data=body_str, headers=self._headers(ts, sig),
            timeout=self.timeout,
        )
        return self._parse(r)

    def _private_delete(self, path: str, params: Optional[Dict] = None) -> Any:
        """Authenticated DELETE."""
        params = params or {}
        params = {k: v for k, v in params.items() if v is not None}
        sorted_params = sorted(params.items())
        param_str = urlencode(sorted_params) if sorted_params else ""
        ts = int(time.time() * 1000)
        sig = _sign(self.api_key, self.api_secret, ts, param_str)
        url = f"{BASE_URL}{path}"
        r = self._session.delete(
            url, params=params, headers=self._headers(ts, sig),
            timeout=self.timeout,
        )
        return self._parse(r)

    @staticmethod
    def _parse(r: requests.Response) -> Any:
        """Parse MEXC JSON response; raise on error."""
        try:
            j = r.json()
        except Exception:
            r.raise_for_status()
            return r.text
        if not j.get("success", True) or j.get("code", 0) != 0:
            code = j.get("code", "?")
            msg = j.get("message", j.get("msg", "Unknown error"))
            raise MexcAPIError(code, msg)
        return j.get("data")

    # ══════════════════════════════════════════════════════════════════
    # PUBLIC / MARKET ENDPOINTS
    # ══════════════════════════════════════════════════════════════════

    def ping(self) -> int:
        """Server time (ms)."""
        return self._public_get("/api/v1/contract/ping")

    def get_contract_detail(self, symbol: Optional[str] = None) -> Any:
        """Get contract specifications. If symbol given, returns single dict."""
        path = f"/api/v1/contract/detail"
        if symbol:
            data = self._public_get(path, {"symbol": to_mexc_symbol(symbol)})
        else:
            data = self._public_get(path)
        return data

    def get_all_contracts(self, force: bool = False) -> Dict[str, Dict]:
        """Return cached dict of {symbol: contract_detail}. Refreshes every 5 min."""
        now = time.time()
        if not force and self._contract_cache and (now - self._contract_cache_ts) < self._contract_cache_ttl:
            return self._contract_cache
        raw = self._public_get("/api/v1/contract/detail")
        if isinstance(raw, list):
            self._contract_cache = {c["symbol"]: c for c in raw}
        elif isinstance(raw, dict) and "symbol" in raw:
            self._contract_cache[raw["symbol"]] = raw
        self._contract_cache_ts = now
        return self._contract_cache

    def get_contract_info(self, symbol: str) -> Optional[Dict]:
        """Get contract info for a single symbol (cached)."""
        contracts = self.get_all_contracts()
        mexc_sym = to_mexc_symbol(symbol)
        return contracts.get(mexc_sym)

    def get_fair_price(self, symbol: str) -> float:
        """Get current fair/mark price."""
        data = self._public_get(f"/api/v1/contract/fair_price/{to_mexc_symbol(symbol)}")
        return float(data.get("fairPrice", 0))

    def get_index_price(self, symbol: str) -> float:
        data = self._public_get(f"/api/v1/contract/index_price/{to_mexc_symbol(symbol)}")
        return float(data.get("indexPrice", 0))

    def get_ticker(self, symbol: Optional[str] = None) -> Any:
        """Get ticker. If symbol given, returns single-symbol ticker."""
        data = self._public_get("/api/v1/contract/ticker")
        if symbol:
            mexc_sym = to_mexc_symbol(symbol)
            if isinstance(data, list):
                return next((t for t in data if t.get("symbol") == mexc_sym), None)
            if isinstance(data, dict) and data.get("symbol") == mexc_sym:
                return data
        return data

    def get_depth(self, symbol: str) -> Dict:
        return self._public_get(f"/api/v1/contract/depth/{to_mexc_symbol(symbol)}")

    def get_klines(self, symbol: str, interval: str = "Min60",
                   start: Optional[int] = None, end: Optional[int] = None) -> Dict:
        """Kline intervals: Min1, Min5, Min15, Min30, Min60, Hour4, Hour8, Day1, Week1, Month1."""
        params = {"interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._public_get(f"/api/v1/contract/kline/{to_mexc_symbol(symbol)}", params)

    def get_funding_rate(self, symbol: str) -> Dict:
        return self._public_get(f"/api/v1/contract/funding_rate/{to_mexc_symbol(symbol)}")

    # ══════════════════════════════════════════════════════════════════
    # ACCOUNT ENDPOINTS
    # ══════════════════════════════════════════════════════════════════

    def get_account_assets(self) -> List[Dict]:
        """Get all account asset balances."""
        return self._private_get("/api/v1/private/account/assets") or []

    def get_asset(self, currency: str = "USDT") -> Optional[Dict]:
        """Get single currency asset info."""
        return self._private_get(f"/api/v1/private/account/asset/{currency}")

    def get_usdt_balance(self) -> float:
        """Convenience: available USDT balance."""
        data = self.get_asset("USDT")
        if data:
            return float(data.get("availableBalance", 0))
        return 0.0

    def get_usdt_equity(self) -> float:
        """Convenience: total USDT equity."""
        data = self.get_asset("USDT")
        if data:
            return float(data.get("equity", 0))
        return 0.0

    # ══════════════════════════════════════════════════════════════════
    # POSITION ENDPOINTS
    # ══════════════════════════════════════════════════════════════════

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all open positions (optionally filtered by symbol)."""
        params = {}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/position/open_positions", params) or []

    def get_history_positions(self, symbol: Optional[str] = None,
                              page_num: int = 1, page_size: int = 20) -> List[Dict]:
        params = {"page_num": page_num, "page_size": page_size}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/position/list/history_positions", params) or []

    def get_position_leverage(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get current leverage multipliers for a symbol."""
        params = {}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/position/leverage", params) or []

    def change_leverage(self, symbol: str, leverage: int,
                        open_type: int = 2, position_type: Optional[int] = None) -> bool:
        """
        Set leverage for a symbol.
        open_type: 1=isolated, 2=cross
        position_type: 1=long, 2=short (for hedge mode; omit for one-way)
        """
        body = {
            "symbol": to_mexc_symbol(symbol),
            "leverage": leverage,
            "openType": open_type,
        }
        if position_type is not None:
            body["positionType"] = position_type
        self._private_post("/api/v1/private/position/change_leverage", body)
        return True

    def get_position_mode(self) -> List[Dict]:
        """Get user position mode (hedge vs one-way)."""
        return self._private_get("/api/v1/private/position/position_mode") or []

    def change_position_mode(self, position_mode: int) -> bool:
        """Set position mode: 1=hedge, 2=one-way."""
        self._private_post("/api/v1/private/position/change_position_mode",
                           {"positionMode": position_mode})
        return True

    def change_margin(self, symbol: str, amount: float,
                      position_type: int, margin_type: str = "ADD") -> bool:
        """Modify position margin. margin_type: 'ADD' or 'SUB'."""
        body = {
            "symbol": to_mexc_symbol(symbol),
            "amount": amount,
            "positionType": position_type,
            "type": margin_type,
        }
        self._private_post("/api/v1/private/position/change_margin", body)
        return True

    # ══════════════════════════════════════════════════════════════════
    # ORDER ENDPOINTS
    # ══════════════════════════════════════════════════════════════════

    def place_order(self, symbol: str, side: int, vol: int,
                    order_type: int = 5, price: Optional[float] = None,
                    leverage: Optional[int] = None,
                    open_type: int = 2,
                    external_oid: Optional[str] = None,
                    position_mode: Optional[int] = None,
                    reduce_only: bool = False) -> Dict:
        """
        Place a single order.

        Parameters
        ----------
        symbol      : e.g. 'BTC_USDT' or 'BTCUSDT' (auto-converted)
        side        : 1=open long, 2=close short, 3=open short, 4=close long
        vol         : number of contracts
        order_type  : 1=limit, 5=market (default)
        price       : required for limit orders
        leverage    : leverage multiplier
        open_type   : 1=isolated, 2=cross (default)
        external_oid: optional external order ID for tracking
        position_mode: 1=hedge, 2=one-way
        reduce_only : if True, set reduceOnly flag
        """
        body: Dict[str, Any] = {
            "symbol": to_mexc_symbol(symbol),
            "side": side,
            "vol": vol,
            "type": order_type,
            "openType": open_type,
        }
        if price is not None and order_type != 5:
            body["price"] = price
        if leverage is not None:
            body["leverage"] = leverage
        if external_oid:
            body["externalOid"] = external_oid
        if position_mode is not None:
            body["positionMode"] = position_mode
        if reduce_only:
            body["reduceOnly"] = True

        return self._private_post("/api/v1/private/order/create", body)

    def place_market_open_long(self, symbol: str, vol: int,
                               leverage: Optional[int] = None,
                               open_type: int = 2,
                               external_oid: Optional[str] = None) -> Dict:
        """Convenience: market buy to open long."""
        return self.place_order(symbol, side=1, vol=vol, order_type=5,
                                leverage=leverage, open_type=open_type,
                                external_oid=external_oid)

    def place_market_open_short(self, symbol: str, vol: int,
                                leverage: Optional[int] = None,
                                open_type: int = 2,
                                external_oid: Optional[str] = None) -> Dict:
        """Convenience: market sell to open short."""
        return self.place_order(symbol, side=3, vol=vol, order_type=5,
                                leverage=leverage, open_type=open_type,
                                external_oid=external_oid)

    def place_market_close_long(self, symbol: str, vol: int,
                                external_oid: Optional[str] = None) -> Dict:
        """Convenience: market sell to close long."""
        return self.place_order(symbol, side=4, vol=vol, order_type=5,
                                external_oid=external_oid)

    def place_market_close_short(self, symbol: str, vol: int,
                                 external_oid: Optional[str] = None) -> Dict:
        """Convenience: market buy to close short."""
        return self.place_order(symbol, side=2, vol=vol, order_type=5,
                                external_oid=external_oid)

    def cancel_orders(self, order_ids: List[int]) -> List[Dict]:
        """Cancel orders by ID (up to 50)."""
        return self._private_post("/api/v1/private/order/cancel", order_ids) or []

    def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol."""
        self._private_post("/api/v1/private/order/cancel_all",
                           {"symbol": to_mexc_symbol(symbol)})
        return True

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get current open/unfilled orders."""
        params = {}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/order/list/open_orders", params) or []

    def get_order(self, order_id: str) -> Optional[Dict]:
        """Get order info by ID."""
        return self._private_get(f"/api/v1/private/order/get/{order_id}")

    def get_history_orders(self, symbol: Optional[str] = None,
                           page_num: int = 1, page_size: int = 20) -> List[Dict]:
        params = {"page_num": page_num, "page_size": page_size}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/order/list/history_orders", params) or []

    # ── Plan / Trigger Orders ──────────────────────────────────────────

    def place_plan_order(self, symbol: str, side: int, vol: int,
                         trigger_price: float, trigger_type: int = 1,
                         order_type: int = 5, price: Optional[float] = None,
                         leverage: Optional[int] = None, open_type: int = 2,
                         execute_cycle: int = 87600,
                         external_oid: Optional[str] = None) -> str:
        """
        Place a conditional/plan (trigger) order.

        trigger_type: 1=fair price, 2=index price, 3=last price
        execute_cycle: validity in hours (default 87600 = ~10 years)
        Returns order ID string.
        """
        body: Dict[str, Any] = {
            "symbol": to_mexc_symbol(symbol),
            "side": side,
            "vol": vol,
            "triggerPrice": trigger_price,
            "triggerType": trigger_type,
            "type": order_type,
            "openType": open_type,
            "executeCycle": execute_cycle,
        }
        if price is not None and order_type != 5:
            body["price"] = price
        if leverage is not None:
            body["leverage"] = leverage
        if external_oid:
            body["externalOid"] = external_oid

        return self._private_post("/api/v1/private/planorder/place/v2", body)

    def cancel_plan_orders(self, orders: List[Dict]) -> bool:
        """Cancel plan orders: [{"symbol":"BTC_USDT","orderId":123}, ...]."""
        self._private_post("/api/v1/private/planorder/cancel", orders)
        return True

    def cancel_all_plan_orders(self, symbol: Optional[str] = None) -> bool:
        body = {}
        if symbol:
            body["symbol"] = to_mexc_symbol(symbol)
        self._private_post("/api/v1/private/planorder/cancel_all", body)
        return True

    def get_plan_orders(self, symbol: Optional[str] = None,
                        page_num: int = 1, page_size: int = 50) -> List[Dict]:
        params = {"page_num": page_num, "page_size": page_size}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/planorder/list/orders", params) or []

    # ── TP/SL (Stop) Orders ────────────────────────────────────────────

    def place_stop_order(self, symbol: str, position_type: int,
                         stop_loss_price: Optional[float] = None,
                         take_profit_price: Optional[float] = None,
                         position_id: Optional[int] = None,
                         stop_loss_vol: Optional[int] = None,
                         take_profit_vol: Optional[int] = None) -> Any:
        """
        Place TP/SL stop order by position.
        position_type: 1=long, 2=short
        position_id:   required by MEXC to link order to position
        stop_loss_vol / take_profit_vol: contract volume (required for partial TP/SL)
        """
        body: Dict[str, Any] = {
            "symbol": to_mexc_symbol(symbol),
            "positionType": position_type,
        }
        if position_id is not None:
            body["positionId"] = position_id
        if stop_loss_price is not None and stop_loss_price > 0:
            body["stopLossPrice"] = stop_loss_price
            body["lossTrend"] = 1  # 1=fair price trigger
            if stop_loss_vol is not None and stop_loss_vol > 0:
                body["stopLossVol"] = stop_loss_vol
                body["profitLossVolType"] = "QUANTITY"
        if take_profit_price is not None and take_profit_price > 0:
            body["takeProfitPrice"] = take_profit_price
            body["profitTrend"] = 1  # 1=fair price trigger
            if take_profit_vol is not None and take_profit_vol > 0:
                body["takeProfitVol"] = take_profit_vol
                body["profitLossVolType"] = "QUANTITY"
        return self._private_post("/api/v1/private/stoporder/place", body)

    def cancel_stop_orders(self, stop_order_ids: List[int]) -> bool:
        """Cancel TP/SL orders by ID."""
        payload = [{"stopPlanOrderId": sid} for sid in stop_order_ids]
        self._private_post("/api/v1/private/stoporder/cancel", payload)
        return True

    def cancel_all_stop_orders(self, symbol: Optional[str] = None) -> bool:
        body = {}
        if symbol:
            body["symbol"] = to_mexc_symbol(symbol)
        self._private_post("/api/v1/private/stoporder/cancel_all", body)
        return True

    def get_stop_orders(self, symbol: Optional[str] = None,
                        page_num: int = 1, page_size: int = 50) -> List[Dict]:
        params = {"page_num": page_num, "page_size": page_size}
        if symbol:
            params["symbol"] = to_mexc_symbol(symbol)
        return self._private_get("/api/v1/private/stoporder/list/orders", params) or []

    # ── Position-Level Actions ─────────────────────────────────────────

    def reverse_position(self, symbol: str) -> bool:
        """Reverse an open position."""
        self._private_post("/api/v1/private/position/reverse",
                           {"symbol": to_mexc_symbol(symbol)})
        return True

    def close_all_positions(self) -> bool:
        """Close ALL open positions at market price."""
        self._private_post("/api/v1/private/position/close_all")
        return True

    # ══════════════════════════════════════════════════════════════════
    # HIGH-LEVEL HELPERS (used by copy_trading integration)
    # ══════════════════════════════════════════════════════════════════

    def calculate_contracts(self, symbol: str, notional_usd: float,
                            entry_price: float) -> int:
        """
        Convert a USD notional value to MEXC contract count.

        contracts = notional_usd / (contractSize * entry_price)

        E.g. BTC_USDT contractSize=0.0001:
            $100 notional at $100,000 = 100 / (0.0001 * 100000) = 10 contracts
        """
        info = self.get_contract_info(symbol)
        if not info:
            raise ValueError(f"Contract info not found for {symbol}")
        contract_size = float(info.get("contractSize", 0))
        if contract_size <= 0:
            raise ValueError(f"Invalid contractSize for {symbol}: {contract_size}")
        vol_scale = int(info.get("volScale", 0))
        min_vol = int(info.get("minVol", 1))

        raw_contracts = notional_usd / (contract_size * entry_price)

        if vol_scale == 0:
            # Integer contracts
            contracts = max(min_vol, int(math.floor(raw_contracts)))
        else:
            # Decimal contracts with precision
            factor = 10 ** vol_scale
            contracts = max(min_vol, math.floor(raw_contracts * factor) / factor)

        return contracts

    def contracts_to_base_qty(self, symbol: str, vol: float) -> float:
        """Convert contract count to base asset quantity."""
        info = self.get_contract_info(symbol)
        if not info:
            return 0.0
        return vol * float(info.get("contractSize", 0))

    def get_position_as_binance_format(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Get open positions formatted like Binance futures_position_information()
        so the existing copy-trading PnL display code works unchanged.

        Binance format:
        {
            'symbol': 'BTCUSDT',
            'positionAmt': '0.001',  (signed, negative for short)
            'entryPrice': '100000.0',
            'markPrice': '101000.0',
            'unRealizedProfit': '1.0',
            'leverage': '20',
            'positionSide': 'BOTH',
        }
        """
        positions = self.get_open_positions(symbol)
        result = []
        for p in positions:
            mexc_sym = p.get("symbol", "")
            binance_sym = to_binance_symbol(mexc_sym)
            hold_vol = float(p.get("holdVol", 0))
            pos_type = int(p.get("positionType", 1))  # 1=long, 2=short
            leverage = int(p.get("leverage", 1))
            entry_price = float(p.get("holdAvgPrice", 0))

            # Convert contracts to base qty
            contract_size = 0.0
            info = self.get_contract_info(mexc_sym)
            if info:
                contract_size = float(info.get("contractSize", 0))
            base_qty = hold_vol * contract_size if contract_size else hold_vol

            # Signed: positive for long, negative for short
            signed_qty = base_qty if pos_type == 1 else -base_qty

            # Get current fair price for unrealized PnL
            try:
                mark_price = self.get_fair_price(mexc_sym)
            except Exception:
                mark_price = entry_price

            # Calculate unrealized PnL
            if pos_type == 1:  # long
                unrealized = (mark_price - entry_price) * base_qty
            else:  # short
                unrealized = (entry_price - mark_price) * base_qty

            # Map positionSide
            if pos_type == 1:
                position_side = "LONG"
            else:
                position_side = "SHORT"

            result.append({
                "symbol": binance_sym,
                "positionAmt": str(signed_qty),
                "entryPrice": str(entry_price),
                "markPrice": str(mark_price),
                "unRealizedProfit": str(round(unrealized, 6)),
                "leverage": str(leverage),
                "positionSide": position_side,
                "liquidatePrice": str(p.get("liquidatePrice", 0)),
                # MEXC-specific extras
                "_mexc_hold_vol": hold_vol,
                "_mexc_position_id": p.get("positionId"),
                "_mexc_symbol": mexc_sym,
                "_mexc_im": float(p.get("im", 0)),
            })
        return result

    def validate_key(self) -> Dict:
        """
        Validate the API key by fetching account assets.
        Returns dict with success/error and balance info.
        """
        try:
            assets = self.get_account_assets()
            usdt = next((a for a in assets if a.get("currency") == "USDT"), None)
            balance = float(usdt.get("availableBalance", 0)) if usdt else 0.0
            equity = float(usdt.get("equity", 0)) if usdt else 0.0
            return {
                "success": True,
                "permissions": {
                    "futures_trading": True,
                    "withdrawals": False,  # MEXC API keys for futures can't withdraw
                },
                "balance_usdt": balance,
                "equity_usdt": equity,
            }
        except MexcAPIError as e:
            if e.code in (10007, 10017):
                return {"error": "Invalid API key or secret. Check your MEXC credentials."}
            return {"error": f"MEXC validation failed: {e}"}
        except Exception as e:
            return {"error": f"MEXC validation failed: {str(e)[:200]}"}


class MexcAPIError(Exception):
    """MEXC API error with code and message."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"MEXC API Error {code}: {message}")
