# Tier Rename — Phase 2 (DB migration + backend literal flip)

**Status:** ✅ **EXECUTED 2026-04-22** — backend-only. Frontend (JS/HTML) sweep intentionally deferred to a follow-up deploy.

**DB backup:** `dashboard/users.db.bak_pre_tier_rename_20260422_223734` (229 KB)
**Final state:**
- `users.tier`: `free|2` + `pro|13` (was `free|2` + `elite|13`)
- `payment_history.tier_granted`: `plus|11` + `pro|3` (was `pro|11` + `elite|3`)
- `.env`: `TIER_RENAME_APPLIED=true`
- `app.py`: 0 `require_tier("elite")`, 15 `require_tier("pro")`, 25 `require_tier("plus")`, 1 `require_tier("ultra")` — exactly matching the pre-rename `elite=15, pro=25` counts
**Depends on:** Phase 1 shim already deployed (`auth.canonicalize_tier`, alias-tolerant `require_tier`).
**Risk:** Medium — atomic DB + code + frontend deploy. Rollback plan below.

## Canonical mapping

| Legacy | New |
|---|---|
| `free` | `free` |
| `pro` | `plus` |
| `elite` | `pro` |
| `ultra` | `ultra` |

## Steps (execute in order in a single deploy window)

### 1. DB migration — `dashboard/users.db`

```sql
BEGIN TRANSACTION;
-- CORRECT order: legacy-pro → plus FIRST, then legacy-elite → pro.
-- SQLite sees prior UPDATE's changes within the same transaction, so if we
-- did elite→pro first, the subsequent pro→plus would cascade onto the rows
-- we just migrated and everything ends up as 'plus'.  Ran into this the
-- first time — recovered from backup and reversed the order.
UPDATE users              SET tier         = 'plus' WHERE tier         = 'pro';
UPDATE users              SET tier         = 'pro'  WHERE tier         = 'elite';
UPDATE payment_history    SET tier_granted = 'plus' WHERE tier_granted = 'pro';
UPDATE payment_history    SET tier_granted = 'pro'  WHERE tier_granted = 'elite';
COMMIT;
```

Note: `users` has no `tier_granted` column in the current schema; do not reference it.

Backup first: `cp dashboard/users.db dashboard/users.db.bak_$(date +%Y%m%d)`.

### 2. Flip the env flag

Set in `.env`:
```
TIER_RENAME_APPLIED=true
```

After this, `canonicalize_tier('pro')` returns `'pro'` (canonical rank 2) instead of `'plus'`. Existing `require_tier("pro")` call sites (~16 in `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`) will now gate rank 2 instead of rank 1 — **which breaks Plus users' access to analytics**. Must be paired with step 3.

### 3. Python literal sweep (same commit as env flip)

Replace in `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`:

- Every `require_tier("pro")` → `require_tier("plus")`
- Every `require_tier("elite")` → `require_tier("pro")`

(Not: `require_tier("ultra")` — unchanged.)

In `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/auth.py`:
- `TIERS = {"free": 0, "plus": 1, "pro": 2, "ultra": 3}`
- `TIER_PRICES = {"plus": 53, "pro": 109, "ultra": 200}`
- Rename `ELITE_TELEGRAM_INVITE` → `PRO_TELEGRAM_INVITE`
- Admin seed: `'elite'` → `'pro'` (line ~249 `INSERT INTO users … 'elite' …`)
- `get_user_count()` dict keys: `{'pro': …, 'elite': …}` → `{'plus': …, 'pro': …}` — verify frontend consumer

In `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/payments.py`:
- `PLANS` keys: `pro_monthly` → `plus_monthly`, `pro_quarterly` → `plus_quarterly`, `elite_monthly` → `pro_monthly`, `elite_quarterly` → `pro_quarterly`. **Breaks any in-flight NowPayments callbacks** referencing old IDs — drain pending payments first.
- `"tier": "elite"` → `"tier": "pro"`
- `"tier": "pro"` → `"tier": "plus"`

In `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/device_security.py`:
- Drop the legacy aliases `'pro': 1` and `'elite': 2` from `TIER_DEVICE_LIMIT`.
- Add `'pro': 2` as canonical key.
- Update docstring.

### 4. Frontend sweep

Files (~15 from Phase 0 scan):

- `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/app-r7.js` (13 matches), `app-r6.js`, `app-r5.js`, `app.js`
- `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/admin.js`, `signals.js`, `screener.js`, `copytrading.js`, `mobile.js`, `analytics.js`, `payments.js`
- `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/index.html`, `admin.html`
- `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/whitepaper.html`, `whitepaper-mk.html`

For each: replace in this order (tokens only, not substrings — use word boundaries):
1. `'elite'` → `'__TMP_ELITE__'`
2. `'pro'`   → `'plus'`
3. `'__TMP_ELITE__'` → `'pro'`
4. Same for `"elite"` / `"pro"` variants
5. Same for payment product IDs: `elite_monthly`, `elite_quarterly`, `pro_monthly`, `pro_quarterly`

The two-step is necessary to avoid `pro → plus` cascading onto the output of `elite → pro`.

### 5. Post-deploy verification

```sql
SELECT tier, COUNT(*) FROM users GROUP BY tier;
-- expected:  free | 2
--            plus | 0  (was pro=0, so still 0)
--            pro  | 13 (was elite=13)

SELECT tier_granted, COUNT(*) FROM payment_history GROUP BY tier_granted;
-- expected:  plus | 11  (was pro=11)
--            pro  | 3   (was elite=3)
```

Smoke tests:
- Log in as each tier user, hit `/api/analytics/summary` (gated by `require_tier("plus")` after rename) — should work for Plus+ users.
- Hit `/api/copy-trading/server-ip` (gated by `require_tier("pro")` after rename) — should require rank ≥ 2.
- Hit `/api/presignals/quick-entry` (gated by `require_tier("ultra")`) — should still require rank 3.
- Admin panel tier badge should display `PLUS`/`PRO`/`ULTRA` labels.

## Rollback

If any step fails:

1. Restore `dashboard/users.db` from `users.db.bak_YYYYMMDD`.
2. Set `TIER_RENAME_APPLIED=false` in `.env`.
3. `git revert <phase2_commit>`; the Phase 1 shim alone remains — fully functional with legacy DB values.

## What Phase 1 already handles (already shipped)

- `auth.canonicalize_tier()` + `tier_rank()` helpers.
- `require_tier()` uses canonical ranks — accepts both old and new names.
- `copy_trading.execute_copy_trades` uses `tier_rank(...) >= Pro` instead of `== 'elite'`.
- `copy_trading.update_copy_sl_for_signal` gates trailing SL at `tier == 'ultra'` (unchanged by rename).
- `device_security.effective_device_limit` uses new `_tier_device_base()` helper with dual-key lookup.
- `app.py` tier-equality checks (`tier == "pro"`, `tier in ('elite','ultra')`) replaced with canonical compares.

The shim means **Phase 2 is a pure data + literal flip**, with no hidden logic changes. All Python comparison points are already Phase-2-ready.
