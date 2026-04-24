# Proposal & Audit Report: Access Control & Copy-Trading Resilience

## 1. Access Control Audit (Backend Admin Validation)

**Objective**: Verify if `/api/admin/*` endpoints strictly enforce backend cryptographic validation or if they rely solely on the frontend DOM-hiding (`app-r7.js`).

**Findings**: 
- **PASS**: The backend is securely locked.
- **Evidence**: Every endpoint mapped in `dashboard/app.py` under the `/api/admin` namespace relies on `check_is_admin(user: dict = Depends(get_current_user))`.
- `get_current_user()` (in `dashboard/auth.py`) uses `jose.jwt` to cryptographically verify the HS256 signature using `DASHBOARD_JWT_SECRET`. 
- The `is_admin` function confirms the JWT `sub` ID matches a strict database boundary (`is_admin=1` or `ADMIN_EMAILS`).
- **Conclusion**: The DOM obfuscation in `app-r7.js` (removing the Admin tab for non-admins) is purely a UX optimization. The underlying API structure is cryptographically resilient against unauthorized requests.

## 2. Copy-Trading Resilience (Binance WebSocket vs. REST)

**Objective**: Validate the WebSocket User Data streams logic to ensure the dashboard bypasses Binance REST balance polling, preventing `-1003` IP bans.

**Findings**:
- **PASS**: The `get_live_balance(user_id)` method in `dashboard/copy_trading.py` exhibits robust, institutional-grade rate-limiting fallback architecture.
- **Evidence**:
    1. **Primary Circuit (Zero-Cost)**: Uses `binance_user_stream.get_state()` directly. If `is_fresh(user_id)` is `True`, it returns the live memory state. This costs zero API calls.
    2. **Secondary Circuit (15s Cache)**: If WS fails or goes stale, it falls back to REST but enforces a strict 15-second cache (`_BALANCE_TTL = 15.0`). At fastest, this triggers 4 round trips per minute, safely below Binance limits.
    3. **Kill Switch (IP Ban Short-Circuit)**: If Binance returns a `-1003` IP ban, `_note_binance_ip_ban()` captures the epoch timestamp. ALL subsequent `get_live_balance` queries immediately return a `"error_code": "rate_limited"` dictionary with the last known cached data until the ban lifts, completely preventing extending the ban.
- **Conclusion**: The copy-trading dashboard resilience is highly optimized and production-ready. 

No actual code changes or diffs are required for these two items. This audit successfully confirms Phase 1 resilience.
