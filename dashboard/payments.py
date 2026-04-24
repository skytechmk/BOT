"""
Anunnaki Dashboard — Crypto Payment System

Three flows supported:
  1. NOWPayments INVOICE  (hosted checkout, 300+ coins) — RECOMMENDED
  2. NOWPayments PAYMENT  (direct pay-to-address) — legacy
  3. MANUAL WALLET        (user sends to our address) — fallback if NP unconfigured
"""
import logging
import os
import secrets
import time
from typing import Optional

from dotenv import load_dotenv
from fastapi import HTTPException, Request
from pydantic import BaseModel

load_dotenv()

from auth import _get_db, upgrade_user_tier
from referrals import credit_referral
import nowpayments as np_client

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────
# Set these in .env or environment — YOUR personal wallet addresses
WALLET_ADDRESSES = {
    "usdt_trc20": os.getenv("WALLET_USDT_TRC20", ""),
    "usdt_bep20": os.getenv("WALLET_USDT_BEP20", ""),
    "btc": os.getenv("WALLET_BTC", ""),
    "eth": os.getenv("WALLET_ETH", ""),
    "ltc": os.getenv("WALLET_LTC", ""),
}

TIER_PRICES = {
    # Canonical plan-ID keys (Phase-2 frontend sweep applied) — these strings
    # are what the frontend POSTs to /api/payments/create.
    "plus_monthly":    {"price": 53,  "tier": "plus",  "days": 30, "label": "Plus Monthly"},
    "plus_quarterly":  {"price": 139, "tier": "plus",  "days": 90, "label": "Plus Quarterly (save 13%)"},
    "pro_monthly":     {"price": 109, "tier": "pro",   "days": 30, "label": "Pro Monthly"},
    "pro_quarterly":   {"price": 279, "tier": "pro",   "days": 90, "label": "Pro Quarterly (save 14%)"},
    # Ultra tier — scaffolded but NOT purchasable until feature rollout
    "ultra_monthly":   {"price": 200, "tier": "ultra", "days": 30, "label": "Ultra Monthly",              "coming_soon": True},
    "ultra_quarterly": {"price": 519, "tier": "ultra", "days": 90, "label": "Ultra Quarterly (save 13%)", "coming_soon": True},
    # ── Legacy aliases ────────────────────────────────────────────────
    # Kept so in-flight NowPayments callbacks or bookmarked links with the
    # old plan IDs continue to resolve.  Can be removed after ~30 days
    # once the old IDs drain from pending-payment tables.
    "elite_monthly":   {"price": 109, "tier": "pro",   "days": 30, "label": "Pro Monthly",   "_legacy_alias_of": "pro_monthly"},
    "elite_quarterly": {"price": 279, "tier": "pro",   "days": 90, "label": "Pro Quarterly", "_legacy_alias_of": "pro_quarterly"},
}

# Accepted payment methods
PAYMENT_METHODS = [
    {"id": "usdt_trc20", "name": "USDT", "network": "TRC20", "icon": "₮"},
    {"id": "usdt_bep20", "name": "USDT", "network": "BEP20", "icon": "₮"},
    {"id": "btc", "name": "Bitcoin", "network": "BTC", "icon": "₿"},
    {"id": "eth", "name": "Ethereum", "network": "ETH", "icon": "⟠"},
    {"id": "ltc", "name": "Litecoin", "network": "LTC", "icon": "Ł"},
]

# Telegram notification for payment verification (optional)
ADMIN_TELEGRAM_CHAT_ID = os.getenv("ADMIN_TELEGRAM_CHAT_ID", "")


# ── Models ──────────────────────────────────────────────────────────
class CreatePaymentRequest(BaseModel):
    plan_id: str  # e.g. "pro_monthly", "elite_quarterly"
    pay_method: str = "usdt_trc20"  # wallet key


class ConfirmPaymentRequest(BaseModel):
    payment_id: str
    tx_hash: str = ""  # optional: customer can provide tx hash


# ── NOWPayments: Hosted Invoice (RECOMMENDED) ───────────────────────
# Maps our pay_method ids → NOWPayments currency codes
_NP_CURRENCY_MAP = {
    "usdt_trc20": "usdttrc20",
    "usdt_bep20": "usdtbsc",  # BSC is NP's code for BEP20
    "usdt_erc20": "usdterc20",
    "btc": "btc",
    "eth": "eth",
    "ltc": "ltc",
    "bnb": "bnbbsc",
    "sol": "sol",
    "xrp": "xrp",
    "ada": "ada",
    "doge": "doge",
    "matic": "maticmainnet",
}


def create_invoice(user_id: int, plan_id: str) -> dict:
    """
    Create a hosted NOWPayments checkout invoice. Returns a URL the user
    should be redirected to. User picks their preferred coin on NOWPayments,
    sees QR, pays, is auto-redirected back to our success_url when done.

    This is the PREFERRED flow — much better UX than direct payment.
    """
    if plan_id not in TIER_PRICES:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan_id}")

    plan = TIER_PRICES[plan_id]

    # Block checkout for tiers still in development
    if plan.get("coming_soon"):
        raise HTTPException(
            status_code=403,
            detail=f"{plan['label']} is still in development. It will become available soon.",
        )

    if not np_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Crypto checkout is not yet available. Please contact support.",
        )

    order_id = f"inv_{secrets.token_hex(8)}"
    urls = np_client.build_urls(order_id)

    try:
        # price_currency=usdttrc20 → customer sees exact amount (e.g. 49 USDT),
        # merchant absorbs all NP + network + rate-lock fees (~8%).
        # Cross-chain (USDT-BSC etc.) is auto-converted by NP at ~1:1.
        data = np_client.create_invoice(
            price_amount      = plan['price'],
            price_currency    = "usdttrc20",
            order_id          = order_id,
            order_description = f"Anunnaki World — {plan['label']}",
            **urls,
        )
    except np_client.NowPaymentsError as e:
        logger.error(f"NOWPayments invoice creation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Payment provider error: {str(e)[:200]}")

    invoice_url = data.get("invoice_url")
    invoice_id  = str(data.get("id", ""))
    if not invoice_url:
        raise HTTPException(status_code=502, detail="NOWPayments did not return an invoice URL")

    # Store pending invoice in DB (payment_id = order_id, method = 'nowpayments_invoice')
    _record_payment(
        user_id       = user_id,
        amount_usd    = plan['price'],
        pay_method    = "nowpayments_invoice",
        payment_id    = order_id,
        status        = "awaiting_payment",
        tier_granted  = plan['tier'],
        duration_days = plan['days'],
        memo          = invoice_id,
    )

    _notify_telegram_payment_initiated(user_id, plan, "NOWPayments Invoice", invoice_id)

    return {
        "order_id":    order_id,
        "invoice_id":  invoice_id,
        "invoice_url": invoice_url,
        "plan":        plan['label'],
        "tier":        plan['tier'],
        "days":        plan['days'],
        "amount_usd":  plan['price'],
    }


# ── NOWPayments: Direct pay-to-address (legacy) ────────────────────
def create_payment(user_id: int, plan_id: str, pay_method: str = "usdt_trc20") -> dict:
    """Direct NOWPayments flow — user sees the exact crypto address + amount."""
    if plan_id not in TIER_PRICES:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan_id}")

    if not np_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Crypto payments are not yet configured. Please contact support.",
        )

    plan = TIER_PRICES[plan_id]
    payment_id = f"pay_{secrets.token_hex(8)}"
    memo = f"ANU-{payment_id[-8:].upper()}"

    np_currency = _NP_CURRENCY_MAP.get(pay_method)
    if not np_currency:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported payment method: {pay_method}",
        )

    method_info = next((m for m in PAYMENT_METHODS if m['id'] == pay_method), None)
    network_name = method_info['network'] if method_info else pay_method.upper()

    try:
        np_data = np_client.create_payment(
            price_amount      = plan['price'],
            price_currency    = "usd",
            pay_currency      = np_currency,
            order_id          = payment_id,
            order_description = plan['label'],
            ipn_callback_url  = np_client.build_urls(payment_id)["ipn_callback_url"],
        )
    except np_client.NowPaymentsError as e:
        logger.error(f"NOWPayments payment creation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Payment provider error: {str(e)[:200]}")

    wallet_address = np_data.get('pay_address')
    pay_amount     = np_data.get('pay_amount')
    pay_currency   = f"{np_data.get('pay_currency', '').upper()} ({network_name})"

    _record_payment(
        user_id=user_id,
        amount_usd=plan['price'],
        pay_method=pay_method,
        payment_id=payment_id,
        status="awaiting_payment",
        tier_granted=plan['tier'],
        duration_days=plan['days'],
        memo=memo,
    )

    _notify_telegram_payment_initiated(user_id, plan, pay_method.upper(), payment_id)

    return {
        "payment_id": payment_id,
        "wallet_address": wallet_address,
        "pay_amount": pay_amount,
        "pay_currency": pay_currency,
        "network": network_name,
        "memo": memo,
        "plan": plan['label'],
        "tier": plan['tier'],
        "days": plan['days'],
        "status": "awaiting_payment",
        "instructions": [
            f"Send exactly {pay_amount} {pay_currency} to the address below",
            f"Please send on the correct network: {network_name}",
            "Your subscription will automatically activate once the blockchain confirms the transaction."
        ],
    }


# ── IPN-driven payment status update ────────────────────────────────
def update_payment_status(order_id: str, new_status: str, tx_hash: str = "") -> dict:
    """
    Called from the IPN webhook on every payment-status transition.
    Persists the status, and on `finished` activates the subscription.
    Safe to call multiple times for the same order_id (idempotent).
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM payment_history WHERE payment_id=?",
        (order_id,)
    ).fetchone()

    if not row:
        conn.close()
        logger.warning(f"IPN: payment_id not found in DB: {order_id}")
        return {"status": "ignored", "reason": "unknown order_id"}

    # Already completed — idempotent no-op
    if row['status'] == 'completed':
        conn.close()
        return {"status": "already_completed"}

    # Map NOWPayments status → our internal status string
    status_map = {
        "waiting":        "awaiting_payment",
        "confirming":     "confirming",
        "confirmed":      "confirming",
        "sending":        "confirming",
        "partially_paid": "partial",
        "finished":       "completed",
        "failed":         "failed",
        "refunded":       "refunded",
        "expired":        "expired",
    }
    internal_status = status_map.get(new_status, new_status)

    conn.execute(
        "UPDATE payment_history SET status=?, completed_at=? WHERE payment_id=?",
        (internal_status, time.time() if np_client.is_terminal_success(new_status) else row['completed_at'], order_id)
    )
    conn.commit()
    user_id       = row['user_id']
    tier          = row['tier_granted']
    days          = row['duration_days']
    amount_usd    = row['amount_usd']
    conn.close()

    # On `finished` — upgrade tier and credit referral
    if np_client.is_terminal_success(new_status):
        upgrade_user_tier(user_id, tier, days)
        try:
            credit_referral(
                referred_id=user_id,
                payment_id=order_id,
                amount_usd=amount_usd,
                tier=tier,
                days=days,
            )
        except Exception as e:
            logger.warning(f"Referral credit failed for {order_id}: {e}")
        _notify_telegram_payment_completed(user_id, tier, days, amount_usd, order_id)
        return {"status": "activated", "user_id": user_id, "tier": tier, "days": days}

    if np_client.is_terminal_failure(new_status):
        _notify_telegram_payment_failed(user_id, order_id, new_status)

    return {"status": "updated", "new_status": internal_status}


# ── Telegram notification helpers ───────────────────────────────────
def _notify_telegram(text: str) -> None:
    try:
        import requests
        bot_token = os.getenv("OPS_TELEGRAM_TOKEN", "")
        chat_id   = os.getenv("OPS_TELEGRAM_CHAT_ID", "-5286675274")
        if not bot_token:
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


def _notify_telegram_payment_initiated(user_id: int, plan: dict, method: str, ref: str) -> None:
    try:
        from auth import get_user_by_id
        user = get_user_by_id(user_id) or {}
        username = user.get('username', 'N/A')
        email    = user.get('email', 'N/A')
    except Exception:
        username, email = 'N/A', 'N/A'
    _notify_telegram(
        f"🛒 <b>Payment Initiated</b>\n\n"
        f"👤 {username} ({email})\n"
        f"📦 {plan['label']}\n"
        f"💰 ${plan['price']}\n"
        f"🪙 {method}\n"
        f"🔑 <code>{ref}</code>\n"
        f"⏳ <i>Awaiting user to complete checkout…</i>"
    )


def _notify_telegram_payment_completed(user_id: int, tier: str, days: int, amount: float, order_id: str) -> None:
    try:
        from auth import get_user_by_id
        user = get_user_by_id(user_id) or {}
    except Exception:
        user = {}
    _notify_telegram(
        f"✅ <b>Payment Completed</b>\n\n"
        f"👤 {user.get('username', 'N/A')} ({user.get('email', 'N/A')})\n"
        f"📦 {tier.upper()} · {days} days\n"
        f"💰 ${amount}\n"
        f"🔑 <code>{order_id}</code>\n"
        f"🎉 <i>Subscription activated automatically.</i>"
    )


def _notify_telegram_payment_failed(user_id: int, order_id: str, reason: str) -> None:
    _notify_telegram(
        f"⚠️ <b>Payment {reason.upper()}</b>\n\n"
        f"👤 user_id={user_id}\n"
        f"🔑 <code>{order_id}</code>\n"
        f"ℹ️ <i>No subscription was granted.</i>"
    )


def submit_payment_proof(user_id: int, payment_id: str, tx_hash: str = "") -> dict:
    """Customer submits proof they've paid (TX hash)."""
    conn = _get_db()
    row = conn.execute(
        "SELECT ph.*, u.email, u.username FROM payment_history ph JOIN users u ON ph.user_id = u.id WHERE ph.payment_id=? AND ph.user_id=?",
        (payment_id, user_id)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Payment not found")

    if row['status'] == 'completed':
        conn.close()
        return {"status": "already_activated", "message": "This payment is already activated"}

    # Update with TX hash and mark as pending verification
    conn.execute(
        "UPDATE payment_history SET status='pending_verification', "
        "crypto_amount=?, completed_at=? WHERE payment_id=?",
        (tx_hash if tx_hash else "submitted", time.time(), payment_id)
    )
    conn.commit()
    conn.close()

    # --- Send Telegram Notification ---
    try:
        import requests
        import os
        bot_token = os.getenv("OPS_TELEGRAM_TOKEN", "")
        chat_id = "-5286675274"
        if bot_token:
            text = (
                f"🛎 <b>New Payment Proof Submitted!</b>\n\n"
                f"👤 <b>User:</b> {row['username']} (<code>{row['email']}</code>)\n"
                f"📦 <b>Tier:</b> {row['tier_granted'].upper()} ({row['duration_days']} days)\n"
                f"💰 <b>Amount:</b> ${row['amount_usd']}\n"
                f"🪙 <b>Method:</b> {row['crypto_currency'].upper()}\n"
                f"📄 <b>Memo Assigned:</b> <code>{row['crypto_amount']}</code>\n"
                f"🔍 <b>TX Hash Submitted:</b> <code>{tx_hash if tx_hash else 'N/A'}</code>\n"
                f"🔑 <b>Payment ID:</b> <code>{payment_id}</code>\n\n"
                f"🔧 <b>To Activate:</b>\n"
                f"<code>curl -X POST https://bot.skytech.mk/api/admin/payments/activate/{payment_id} -H \"Authorization: Bearer &lt;your_token&gt;\"</code>\n"
                f"<i>(Or use the Admin Panel if logged in as a Pro/Admin user)</i>"
            )
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
            if resp.status_code != 200:
                print(f"Telegram Notification Failed: {resp.text}")
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")
    # ----------------------------------

    return {
        "status": "pending_verification",
        "message": "Payment submitted! Your subscription will be activated after admin verification (usually within 1 hour).",
        "payment_id": payment_id,
    }


def admin_confirm_payment(payment_id: str) -> dict:
    """Admin confirms a payment and activates the user's tier."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM payment_history WHERE payment_id=?",
        (payment_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Payment not found")

    if row['status'] == 'completed':
        conn.close()
        return {"status": "already_activated"}

    # Activate
    conn.execute(
        "UPDATE payment_history SET status='completed', completed_at=? WHERE payment_id=?",
        (time.time(), payment_id)
    )
    conn.commit()
    conn.close()

    # Upgrade user tier
    upgrade_user_tier(row['user_id'], row['tier_granted'], row['duration_days'])

    # Fire referral credit (no-op if user was not referred)
    ref_result = credit_referral(
        referred_id=row['user_id'],
        payment_id=payment_id,
        amount_usd=row['amount_usd'],
        tier=row['tier_granted'],
        days=row['duration_days'],
    )

    result = {
        "status": "activated",
        "user_id": row['user_id'],
        "tier": row['tier_granted'],
        "days": row['duration_days'],
    }
    if ref_result:
        result['referral_credit'] = ref_result
    return result


def admin_get_pending_payments() -> list:
    """Get all payments awaiting admin verification."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT ph.*, u.email, u.username FROM payment_history ph "
        "JOIN users u ON ph.user_id = u.id "
        "WHERE ph.status IN ('awaiting_payment', 'pending_verification') "
        "ORDER BY ph.created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_payment_status(payment_id: str) -> dict:
    """Check payment status."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM payment_history WHERE payment_id=?", (payment_id,)).fetchone()
    conn.close()
    if not row:
        return {"payment_id": payment_id, "status": "not_found"}
    return {
        "payment_id": payment_id,
        "status": row['status'],
        "tier_granted": row['tier_granted'],
        "amount_usd": row['amount_usd'],
    }


# ── Internal Helpers ────────────────────────────────────────────────
def _record_payment(user_id, amount_usd, pay_method, payment_id, status,
                    tier_granted, duration_days, memo=""):
    conn = _get_db()
    conn.execute(
        "INSERT OR IGNORE INTO payment_history "
        "(user_id, amount_usd, crypto_currency, crypto_amount, payment_id, status, "
        "tier_granted, duration_days, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, amount_usd, pay_method, memo, payment_id,
         status, tier_granted, duration_days, time.time())
    )
    conn.commit()
    conn.close()


def get_payment_history(user_id: int) -> list:
    """Get payment history for a user."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM payment_history WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_plans() -> list:
    """Get available subscription plans."""
    plans = []
    for plan_id, plan in TIER_PRICES.items():
        plans.append({
            "id": plan_id,
            "label": plan['label'],
            "tier": plan['tier'],
            "price_usd": plan['price'],
            "days": plan['days'],
        })
    return plans


def get_payment_methods() -> list:
    """Get available payment methods (only those with configured addresses)."""
    methods = []
    for m in PAYMENT_METHODS:
        addr = WALLET_ADDRESSES.get(m['id'], '')
        if addr:  # Only show methods with configured wallet addresses
            methods.append({
                **m,
                "address_preview": addr[:6] + "..." + addr[-4:] if len(addr) > 10 else addr,
            })
    return methods
