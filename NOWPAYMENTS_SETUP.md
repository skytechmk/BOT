# NOWPayments Setup Guide

Complete walk-through to activate crypto checkout on the Anunnaki World dashboard.
Takes ~10 minutes. After this, users can pay for **Plus/Pro** subscriptions with
**300+ cryptocurrencies** via a hosted checkout page.

---

## 1. Create a NOWPayments account

1. Go to **https://account.nowpayments.io/create-account**
2. Register as a **Merchant** (not Customer).
3. Verify your email.
4. Log in.

---

## 2. Add your payout wallets

Under **Store Settings → Payout Wallets** add at least these five (recommended):

| Coin | Network | Where you'll receive the funds |
|------|---------|-------------------------------|
| USDT | TRC20 (Tron) | Your Trust/Exodus/Ledger USDT-TRC20 address |
| USDT | BEP20 (BSC)  | Your BEP20 address |
| BTC  | Bitcoin      | Your BTC address |
| ETH  | Ethereum     | Your ERC20 address |
| LTC  | Litecoin     | Your LTC address |

NOWPayments will **auto-convert** any coin the customer pays → the coin you set for
that currency's payout. Fees ~0.5%.

> **Tip:** If you want ALL incoming payments converted to USDT for accounting ease,
> set all payout wallets to USDT on the network of your choice (TRC20 is cheapest).

---

## 3. Get your API Key

1. Menu **→ Store Settings → API Keys**
2. Click **Create API Key**
3. Give it a name like *"Anunnaki Production"*
4. **Copy the key** (shown only once).

---

## 4. Set the IPN Secret

IPN = Instant Payment Notification (their webhook).

1. Menu **→ Store Settings → Instant Payments Notifications**
2. Paste this URL into the **IPN Callback URL** field:
   ```
   https://YOUR_DOMAIN/api/webhooks/nowpayments
   ```
   Replace `YOUR_DOMAIN` with your actual public domain
   (e.g. `https://bot.skytech.mk`).
3. Click **Generate** next to the **IPN Secret** field (this is auto-generated).
4. **Copy the secret.**

> The secret is what lets the server verify incoming webhooks are genuinely from
> NOWPayments. Without it, **every webhook will be rejected** (as it should).

---

## 5. Paste into your `.env` file

Open `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env` and add:

```bash
# NOWPayments crypto checkout
NOWPAYMENTS_API_KEY=your_api_key_from_step_3
NOWPAYMENTS_IPN_SECRET=your_ipn_secret_from_step_4
NOWPAYMENTS_SANDBOX=false

# Public-facing URL (used for success/cancel/IPN redirects)
PUBLIC_BASE_URL=https://bot.skytech.mk
```

> **Sandbox?** Set `NOWPAYMENTS_SANDBOX=true` + use the sandbox API key/secret
> from https://account-sandbox.nowpayments.io to test without real money.
> Remember to toggle it back to `false` before going live.

---

## 6. Restart the dashboard

```bash
systemctl restart anunnaki-dashboard.service
```

Verify it started cleanly:

```bash
systemctl status anunnaki-dashboard.service
journalctl -u anunnaki-dashboard.service --since "1 minute ago" | tail -30
```

---

## 7. Verify the integration

### A. Public config probe (no auth)

```bash
curl -s http://127.0.0.1:8050/api/payments/config | python3 -m json.tool
```

Expected:
```json
{ "crypto_checkout_enabled": true, "sandbox": false }
```

### B. Admin deep probe (needs admin auth)

From a logged-in admin session, GET:
```
/api/admin/payments/config
```

Expected — API health ping + list of available currencies:
```json
{
  "config":   { "api_key_set": true, "ipn_secret_set": true, "configured": true, ... },
  "health":   { "ok": true, "message": "OK" },
  "currencies": ["btc", "eth", "usdttrc20", "usdtbsc", ...],
  "currency_count": 300
}
```

### C. End-to-end test (with sandbox)

1. Open the dashboard in an incognito window.
2. Go to **Pricing → Subscribe → Plus Monthly**.
3. Click the gold **"💎 Pay with Crypto — 300+ coins"** button.
4. Should redirect to a NOWPayments hosted page.
5. Pick any coin → see QR code → (sandbox) send a fake payment.
6. Should redirect back to `/payment/success`.
7. In another tab, your admin view should show the payment status transition from
   `waiting → confirming → finished`.
8. The user's tier should be **automatically upgraded** to `pro`.

---

## 8. Troubleshooting

### "Crypto checkout is not yet available"
You see this error when calling `POST /api/payment/invoice/create`.

→ `NOWPAYMENTS_API_KEY` or `NOWPAYMENTS_IPN_SECRET` is missing in `.env`.
→ Restart the service after editing `.env`.

### Webhook always rejected with `Invalid signature`
Check `/api/admin/payments/config` — is `ipn_secret_set: true`?

→ Make sure the secret in `.env` **exactly matches** what's in the NOWPayments
  dashboard (no trailing spaces, quotes, etc.).

→ NOWPayments signs the **sorted JSON** of the payload. Our verifier does the
  same (see `nowpayments.py:verify_ipn_signature`). If you customized the handler,
  check the sort_keys=True flag is kept.

### Payments don't auto-activate
Check:
1. `journalctl -u anunnaki-dashboard.service -f` — look for `IPN processed: …`
2. Does NOWPayments show the payment as `finished` in their dashboard?
3. `GET /api/admin/payments/history` — does the payment record exist?
4. Is your public URL reachable from the internet? NOWPayments must be able to
   POST to your webhook URL.

### Tier upgraded but user still sees "Free"
Browser may be caching the old JWT. User needs to **log out and log back in**
to get a fresh JWT with the new tier claim.

---

## 9. Fees

- **NOWPayments fee:** 0.5% of each transaction.
- **Network fee:** paid by customer (invoice rounds up to cover it).
- **Payout conversion fee** (if auto-convert enabled): additional ~0.5%.

Total merchant fee: **~0.5% to 1%** depending on setup.

---

## 10. Security checklist

- [x] API key stored in `.env`, not in git
- [x] IPN secret stored in `.env`, not in git
- [x] HMAC-SHA512 signature verification on every webhook
- [x] Constant-time comparison (no timing attacks)
- [x] Webhook URL uses HTTPS
- [x] Idempotent tier upgrade (webhook retries won't double-grant)
- [x] Failed payment states (`failed`, `expired`, `refunded`) never upgrade tier
- [x] Admin Telegram notification on every payment event

---

## Reference

- **NOWPayments API docs:** https://documenter.getpostman.com/view/7907941/S1a32n38
- **Their status page:** https://status.nowpayments.io
- **Currencies supported:** https://nowpayments.io/supported-coins
- **Our code:**
  - Client — `dashboard/nowpayments.py`
  - Business logic — `dashboard/payments.py`
  - HTTP routes — `dashboard/app.py` (search `nowpayments`)
  - Frontend — `dashboard/static/js/payments.js` (`payWithCrypto`)
