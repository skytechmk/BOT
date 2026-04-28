# Proposal: Copy-Trading API Key Format Guard

## Issue

User `cansen_dior@hotmail.com` received:

```text
Error: Invalid API key format
```

Verification showed:

```text
user_found= True
user_id= 18
config= None
exchange_keys= []
```

So no copy-trading config or exchange keys were saved yet. The rejection happened during first-time setup.

## Root Cause

`dashboard/copy_trading.py::save_api_keys()` rejects credentials before storing anything when either submitted value is shorter than 20 characters:

```python
if len(api_key) < 20 or len(api_secret) < 20:
    return {"error": "Invalid API key format"}
```

This means the user likely pasted one of these into the API key/secret fields:

- Account email / account password
- 2FA code
- Partial/truncated API key
- Only API key without full secret
- Wrong exchange credential format

There is also a frontend UX issue after adding multi-exchange mode:

- When `All Exchanges` is selected, the API-key panel still renders as `Binance API Keys`.
- `saveCopyTradingKeys()` sends `exchange: window._ctSelectedExchange`, so in multi mode it can send `exchange: "both"` even though key saving must be per-exchange.
- Backend currently rejects `both` later, but the earlier length check can hide the real issue if the pasted values are short.

## Recommended User Action

Tell the user:

1. Select **Binance** or **MEXC** explicitly, not **All Exchanges**, before adding keys.
2. Paste the exchange-generated **API/Access Key** into `API Key`.
3. Paste the exchange-generated **Secret Key** into `API Secret`.
4. Do **not** paste exchange account email/password.
5. For Binance, use Futures-enabled API key with withdrawals/transfers disabled.
6. For MEXC, use Futures API key/secret.

## Proposed Patch

### 1. Frontend guard in `dashboard/static/js/copytrading.js`

Add a guard to `saveCopyTradingKeys()` before building the request body:

```diff
 async function saveCopyTradingKeys() {
     var apiKey = _ctVal('ct-api-key', '').trim();
     var apiSecret = _ctVal('ct-api-secret', '').trim();
+    var keyExchange = window._ctSelectedExchange || 'binance';
+
+    if (keyExchange !== 'binance' && keyExchange !== 'mexc') {
+        alert('API keys are saved per exchange. Select Binance or MEXC first, then paste that exchange API Key + Secret.');
+        return;
+    }
+
     if (!apiKey || !apiSecret) {
         // Keys blank but config already exists — just save settings
         var hasCfg = !!document.querySelector('[onclick="deleteCopyTradingKeys()"]');
         if (hasCfg) { return saveCopyTradingSettings(); }
         alert('Enter both API Key and API Secret.');
         return;
     }
+
+    if (apiKey.length < 20 || apiSecret.length < 20) {
+        alert('Invalid API key format. Paste the full exchange API/Access Key and Secret Key — not your exchange email, password, or 2FA code.');
+        return;
+    }
+
     var body = {
         api_key:          apiKey,
         api_secret:       apiSecret,
@@
-        exchange:         window._ctSelectedExchange || 'binance',
+        exchange:         keyExchange,
     };
```

### 2. Frontend key-panel label/notice in `renderCopyTrading()`

Replace the key panel title and add notice when `currentExchange === 'both'`:

```diff
-    html += '<div style="font-size:13px;font-weight:700;margin-bottom:4px">🔑 ' + (currentExchange === 'mexc' ? 'MEXC' : 'Binance') + ' API Keys</div>';
+    var keyPanelExchangeName = currentExchange === 'mexc' ? 'MEXC' : (currentExchange === 'binance' ? 'Binance' : 'Per-Exchange');
+    html += '<div style="font-size:13px;font-weight:700;margin-bottom:4px">🔑 ' + keyPanelExchangeName + ' API Keys</div>';
+    if (currentExchange === 'both') {
+        html += '<div style="margin-bottom:12px;padding:10px 12px;border:1px solid #00c9a755;background:#00c9a712;border-radius:8px;font-size:12px;color:var(--text)">API keys are saved separately. Select <strong>Binance</strong> or <strong>MEXC</strong> above before adding/updating keys.</div>';
+    }
```

Optional stricter UX: hide/disable `ct-api-key` and `ct-api-secret` when `currentExchange === 'both'`.

### 3. Backend clearer error in `dashboard/app.py`

Reject invalid key-save exchange before calling `save_api_keys()`:

```diff
     body = await request.json()
     exchange = str(body.get('exchange', 'binance')).lower()
+    if exchange not in ('binance', 'mexc'):
+        return JSONResponse({
+            "error": "API keys are saved per exchange. Select Binance or MEXC first."
+        }, status_code=400)
     result = save_api_keys(
```

### 4. Backend clearer length error in `dashboard/copy_trading.py`

```diff
     if len(api_key) < 20 or len(api_secret) < 20:
-        return {"error": "Invalid API key format"}
+        return {"error": "Invalid API key format. Paste the full exchange API/Access Key and Secret Key — not your exchange email, password, or 2FA code."}
```

## Risk Assessment

- **Risk:** Low.
- **Trading logic:** Unchanged.
- **Credentials:** No new logging of secrets.
- **Security:** Improved, because users are less likely to paste account credentials into API fields.
- **Multi-exchange:** Aligns UX with the existing design: keys are stored per exchange in `exchange_keys`.

## Verification

After applying:

1. Open Copy-Trade as a Pro user with no keys.
2. Select `All Exchanges`.
3. Try saving keys; expected: clear alert telling user to select Binance/MEXC first.
4. Select `Binance`.
5. Paste short strings; expected: clear alert explaining full API key/secret required.
6. Paste valid Binance Futures keys; expected: save succeeds or returns exchange validation warning.
7. Select `MEXC` and repeat.
8. Confirm no secret values are logged.
