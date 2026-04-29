"""
Anunnaki Dashboard — NOWPayments integration client.

Provides a clean, typed interface to NOWPayments REST API v1:
  • create_invoice()     — hosted checkout (RECOMMENDED UX)
  • create_payment()     — direct pay-to-address flow
  • get_payment_status() — poll status (fallback if IPN fails)
  • get_currencies()     — available cryptos
  • get_api_status()     — health check / config validation
  • verify_ipn_signature() — HMAC-SHA512 webhook verification

ENV variables required:
  NOWPAYMENTS_API_KEY      — merchant API key (get from account.nowpayments.io)
  NOWPAYMENTS_IPN_SECRET   — IPN signature secret (set in NOWPayments dashboard)
  NOWPAYMENTS_SANDBOX      — "true" to use sandbox (default: false)
  PUBLIC_BASE_URL          — e.g. https://bot.skytech.mk (for success/cancel/IPN URLs)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────
_API_KEY    = os.getenv("NOWPAYMENTS_API_KEY", "").strip()
_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "").strip()
_SANDBOX    = os.getenv("NOWPAYMENTS_SANDBOX", "false").strip().lower() == "true"
_BASE_URL   = os.getenv("PUBLIC_BASE_URL", "https://bot.skytech.mk").rstrip("/")

_API_BASE = (
    "https://api-sandbox.nowpayments.io/v1"
    if _SANDBOX else
    "https://api.nowpayments.io/v1"
)

# Reasonable timeouts for outbound requests
_TIMEOUT = 15.0


# ── Helpers ──────────────────────────────────────────────────────────
def is_configured() -> bool:
    """Return True iff both API key and IPN secret are set."""
    return bool(_API_KEY) and bool(_IPN_SECRET)


def _headers() -> Dict[str, str]:
    return {
        "x-api-key": _API_KEY,
        "Content-Type": "application/json",
    }


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{_API_BASE}{path}"
    r = requests.post(url, json=payload, headers=_headers(), timeout=_TIMEOUT)
    data = _safe_json(r)
    if r.status_code not in (200, 201):
        raise NowPaymentsError(
            f"NOWPayments {path} returned {r.status_code}: {data.get('message', r.text)}"
        )
    return data


def _get(path: str, *, auth: bool = True) -> Dict[str, Any]:
    url = f"{_API_BASE}{path}"
    headers = _headers() if auth else {}
    r = requests.get(url, headers=headers, timeout=_TIMEOUT)
    data = _safe_json(r)
    if r.status_code != 200:
        raise NowPaymentsError(
            f"NOWPayments GET {path} returned {r.status_code}: {data.get('message', r.text)}"
        )
    return data


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json() or {}
    except Exception:
        return {"raw": resp.text[:200]}


class NowPaymentsError(Exception):
    """Raised on any NOWPayments API error."""


# ── Public API ───────────────────────────────────────────────────────
def get_api_status() -> Dict[str, Any]:
    """
    Health check — does NOT require API key. Returns {'message': 'OK'} on success.
    Useful for admin config validation.
    """
    try:
        data = _get("/status", auth=False)
        return {"ok": True, "message": data.get("message", "OK"), "sandbox": _SANDBOX}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "sandbox": _SANDBOX}


def get_currencies() -> list[str]:
    """Return list of currently-available pay currencies (merchant-selected)."""
    if not _API_KEY:
        return []
    try:
        data = _get("/merchant/coins")
        return sorted(data.get("selectedCurrencies", []))
    except Exception as e:
        logger.warning(f"get_currencies failed: {e}")
        return []


def create_invoice(
    *,
    price_amount: float,
    price_currency: str = "usd",
    order_id: str,
    order_description: str,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    ipn_callback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a HOSTED checkout invoice. Returns a dict with `invoice_url` that
    the user should be redirected to. NOWPayments handles coin selection,
    QR code, payment detection, confirmations, and redirects back to
    `success_url` when complete.

    Docs: https://documenter.getpostman.com/view/7907941/S1a32n38#9f7f4c68-d6d2-4a9e-9e6b-9db3d7e6f8a3
    """
    if not _API_KEY:
        raise NowPaymentsError("NOWPAYMENTS_API_KEY not configured")

    payload: Dict[str, Any] = {
        "price_amount":      round(float(price_amount), 2),
        "price_currency":    price_currency.lower(),
        "order_id":          order_id,
        "order_description": order_description[:200],  # NP limit
        "is_fixed_rate":     True,   # lock rate at invoice creation
        "is_fee_paid_by_user": False,
    }
    if success_url:      payload["success_url"]      = success_url
    if cancel_url:       payload["cancel_url"]       = cancel_url
    if ipn_callback_url: payload["ipn_callback_url"] = ipn_callback_url

    return _post("/invoice", payload)


def create_payment(
    *,
    price_amount: float,
    price_currency: str = "usd",
    pay_currency: str,
    order_id: str,
    order_description: str,
    ipn_callback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Direct pay-to-address flow. Returns `pay_address`, `pay_amount`, `payment_id`.
    Less user-friendly than create_invoice(); kept for legacy compatibility.
    """
    if not _API_KEY:
        raise NowPaymentsError("NOWPAYMENTS_API_KEY not configured")

    payload: Dict[str, Any] = {
        "price_amount":      round(float(price_amount), 2),
        "price_currency":    price_currency.lower(),
        "pay_currency":      pay_currency.lower(),
        "order_id":          order_id,
        "order_description": order_description[:200],
    }
    if ipn_callback_url:
        payload["ipn_callback_url"] = ipn_callback_url

    return _post("/payment", payload)


def get_payment_status(payment_id: str) -> Dict[str, Any]:
    """
    Poll NOWPayments for current status of a payment_id. Returns full payment
    object including `payment_status`, `pay_amount`, `actually_paid`, etc.
    """
    if not _API_KEY:
        raise NowPaymentsError("NOWPAYMENTS_API_KEY not configured")
    return _get(f"/payment/{payment_id}")


# ── IPN (webhook) signature verification ─────────────────────────────
def verify_ipn_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify a NOWPayments IPN webhook signature.

    NOWPayments generates the signature by:
      1. Parsing the JSON body
      2. Sorting the keys alphabetically (nested included)
      3. Serializing to JSON with no whitespace (separators=(',', ':'))
      4. Computing HMAC-SHA512 with the IPN secret
      5. Sending the hex digest in the `x-nowpayments-sig` header

    Returns True if signature is valid, False otherwise. Uses constant-time
    comparison to prevent timing attacks.
    """
    if not _IPN_SECRET:
        logger.warning("verify_ipn_signature: IPN secret not configured")
        return False
    if not signature_header:
        return False
    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.warning("verify_ipn_signature: invalid JSON")
        return False

    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    expected  = hmac.new(
        _IPN_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


# ── Payment status helpers ───────────────────────────────────────────
# NOWPayments payment_status values (from their docs):
#   waiting         — invoice created, awaiting payment
#   confirming      — payment detected on-chain, awaiting confirmations
#   confirmed       — enough confirmations
#   sending         — sending to merchant wallet
#   partially_paid  — only partial amount received
#   finished        — complete — activate subscription here
#   failed          — error (e.g. wrong currency)
#   refunded        — refund issued
#   expired         — invoice expired unpaid
TERMINAL_SUCCESS  = {"finished"}
TERMINAL_FAILURE  = {"failed", "refunded", "expired"}
TERMINAL_PARTIAL  = {"partially_paid"}
IN_PROGRESS       = {"waiting", "confirming", "confirmed", "sending"}
ALL_STATUSES      = TERMINAL_SUCCESS | TERMINAL_FAILURE | TERMINAL_PARTIAL | IN_PROGRESS


def is_terminal_success(status: str) -> bool:
    return status in TERMINAL_SUCCESS


def is_terminal_failure(status: str) -> bool:
    return status in TERMINAL_FAILURE


def build_urls(order_id: str) -> Dict[str, str]:
    """Build success/cancel/IPN URLs for a given order using PUBLIC_BASE_URL."""
    return {
        "success_url":      f"{_BASE_URL}/payment/success?order={order_id}",
        "cancel_url":       f"{_BASE_URL}/payment/cancel?order={order_id}",
        "ipn_callback_url": f"{_BASE_URL}/api/webhooks/nowpayments",
    }


# ── Diagnostic / admin config info ───────────────────────────────────
def describe_config() -> Dict[str, Any]:
    """Return a safe (non-secret) description of current NOWPayments config."""
    return {
        "api_key_set":    bool(_API_KEY),
        "api_key_hint":   (_API_KEY[:6] + "…" + _API_KEY[-4:]) if _API_KEY else None,
        "ipn_secret_set": bool(_IPN_SECRET),
        "sandbox":        _SANDBOX,
        "api_base":       _API_BASE,
        "public_base":    _BASE_URL,
        "ipn_url":        f"{_BASE_URL}/api/webhooks/nowpayments",
        "configured":     is_configured(),
    }
