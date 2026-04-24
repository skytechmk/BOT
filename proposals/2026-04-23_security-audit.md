# Security Audit — Aladdin / Anunnaki World Platform

**Date:** 2026-04-23
**Auditor:** SPECTRE (static review only — no active exploitation)
**Scope:** Full backend (`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA`), dashboard web app, Binance/Telegram/OpenRouter integrations, SQLite stores, environment handling. `venv/` excluded.
**Status:** Draft — operator review required; fixes not applied.

---

## 0. TL;DR

Overall posture is **solid at the application layer** (bcrypt passwords, Fernet-encrypted Binance keys, HMAC-verified payment webhooks, tier-gated APIs, device fingerprinting, no hardcoded secrets, no wide-open CORS, no dangerous eval/pickle paths reachable over HTTP). 

However, there are **two critical filesystem-level issues** that dominate the risk surface:

| # | Severity | Issue | Fix effort |
|---|---|---|---|
| **C1** | 🔴 **CRITICAL** | `.env` and `.env.bak.*` are world-readable (`644`), exposing live Telegram bot tokens, Fernet encryption key, JWT secret, Binance master keys, OpenRouter key, NOWPayments IPN secret to any local user on the server | 2 minutes |
| **C2** | 🔴 **CRITICAL** | All `*.db` files including `users.db` (password hashes, JWT reset tokens) and `copy_trading` tables (Fernet-encrypted Binance keys per user) are world-readable (`644`) | 2 minutes |
| H1 | 🟠 High | Committed `.env.bak.20260422_233250` in workspace root — exact copy of live `.env` | 1 minute |
| H2 | 🟠 High | JWT stored in `localStorage` (no `httpOnly` cookie) — any XSS = full session takeover | design decision |
| M1 | 🟡 Medium | Several `innerHTML = ...` sinks on dashboard use dynamic data that *could* contain attacker-controlled strings if a Binance pair or signal field were ever mutated upstream | 1–2 h |
| M2 | 🟡 Medium | Inconsistent admin auth pattern — some routes `Depends(require_admin)`, others `Depends(get_current_user) + if not check_is_admin(user)` | 30 min refactor |
| M3 | 🟡 Medium | `execute(f'DELETE FROM "oi_{pair}" ...')` uses f-string table interpolation — safe today (pair comes from Binance) but fragile pattern | 10 min |
| L1 | 🟢 Low | No HSTS / Secure-cookie / CSP headers emitted by FastAPI (likely set at reverse proxy — verify) | 1 h |
| L2 | 🟢 Low | bcrypt rounds = 10 (acceptable; 12 is current recommendation) | 1 line |
| L3 | 🟢 Low | `code_audit_tools.py` contains `exec()` — not reachable from any HTTP route, but should be deleted or sandboxed anyway | 15 min |
| I1 | ℹ️ Info | No CORS misconfig, no SQL injection in user-facing paths, no shell injection, no pickle deserialization, no debug mode | — |

**Priority order: fix C1 and C2 today. Everything else this week.**

---

## 1. Methodology

Static review via `grep`/`ripgrep` over the entire non-vendored codebase
searching for known dangerous patterns:

- Hardcoded secrets / API keys / tokens
- SQL string concatenation / f-string SQL
- `shell=True`, `os.system`, `os.popen`
- `eval()`, `exec()`, `pickle.loads()`, `yaml.load()` (unsafe variants)
- Debug modes, reload flags
- Wide-open CORS (`allow_origins=["*"]`)
- JWT config (algorithms, verify flags)
- Password hashing algorithms
- Payment / webhook signature verification
- Admin auth guards on `/api/admin/*`
- XSS sinks (`innerHTML`, `document.write`, `eval` in JS)
- Path traversal (`open(request.params...)`, `send_file(...)`)
- File permissions on sensitive artifacts (`.env`, `*.db`)
- Dependency management (`git ls-files`, `.gitignore`)

Tested against running service via curl only for non-destructive reads
(`/api/public/stats`, `/robots.txt`).

**Not performed:** active pen-testing, fuzzing, dependency CVE scan
(`pip-audit` / `safety`) — recommended as follow-up.

---

## 2. Findings in detail

### 🔴 C1 — Secrets in world-readable `.env`

**Evidence:**
```
$ stat -c "%a %U:%G %n" .env
644 root:root .env
```
`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env` contains:
- `TELEGRAM_TOKEN=7444537026:AAF8Gw1MrBtv…` (main signals bot)
- `CLOSED_SIGNALS_TOKEN=8148856396:AAHq0I…` (closed signals bot)
- `OPS_TELEGRAM_TOKEN=...`
- `DASHBOARD_JWT_SECRET=***`
- `FERNET_KEY=***` (decrypts every user's Binance API key)
- `BINANCE_API_KEY` / `BINANCE_API_SECRET`
- `OPENROUTER_API_KEY`
- `NOWPAYMENTS_IPN_SECRET`
- Admin Telegram user IDs

**Impact:** Any user with shell access on the box can read the file and:
- Take over all Telegram bots (DM every subscriber, post fake signals).
- Decrypt every user's stored Binance API key (Fernet key is in `.env`).
- Mint valid JWTs for any user → full account takeover.
- Forge NOWPayments IPN callbacks → grant themselves Ultra tier.
- Drain the Binance master account via stolen API key/secret.

This is the single biggest security issue on the system.

**Fix:**
```bash
chmod 600 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env
chmod 600 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env.bak.*
chown root:root /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env*
```
**Verify** the service still starts — if the systemd unit runs as a
non-root user, change `chown` to that user instead.

**Rotate recommended (not strictly required unless the box has other users):**
- Regenerate `FERNET_KEY` → all users must re-enter their Binance keys,
  or write a migration that re-encrypts existing rows.
- Rotate `DASHBOARD_JWT_SECRET` → invalidates all active sessions (users
  log in again). Low friction.
- Rotate Telegram bot tokens via `@BotFather` → low friction.
- Rotate `OPENROUTER_API_KEY` and `NOWPAYMENTS_IPN_SECRET` via their
  provider dashboards.

---

### 🔴 C2 — World-readable SQLite databases

**Evidence:**
```
$ stat -c "%a %U:%G %n" *.db dashboard/*.db
644 root:root users.db
644 root:root dashboard/users.db
644 root:root signal_registry.db
644 root:root dashboard/dashboard.db
... (all 644)
```

`dashboard/users.db` contains:
- bcrypt password hashes (offline-crackable if weak password)
- Password-reset tokens (`password_reset_tokens` table)
- Email verification tokens
- `is_admin` flags
- Device fingerprints, IP addresses, geo data per user
- Fernet-encrypted Binance API keys in `copy_trades_config` table — but
  if C1 is also present, those decrypt trivially

**Impact:** Same exposure surface as C1 but for user PII + stored
credentials. Exfiltration = full DB of users.

**Fix:**
```bash
chmod 600 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/*.db
chmod 600 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/*.db
# optional: move to /var/lib/anunnaki/ with a dedicated user
```

Also add a defensive umask in the systemd unit so newly-created DBs
inherit `600`:
```ini
[Service]
UMask=0077
```

---

### 🟠 H1 — `.env.bak.20260422_233250` left in workspace

**Evidence:** `.env.bak.20260422_233250` (2763 bytes, root:root, 644) — full
duplicate of live `.env`.

**Impact:** Multiplies C1 surface. Also more likely to slip into a
future `tar` / `rsync` / backup without filtering.

**Fix:**
```bash
mv /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env.bak.* \
   /root/secrets/env-backups/  # off the webroot entirely
chmod 600 /root/secrets/env-backups/.env.bak.*
```

Add `.env*` pattern to `.gitignore` (currently `.env` is ignored per
`git check-ignore`, but I couldn't confirm `.env.bak.*` is — verify).

---

### 🟠 H2 — JWT in `localStorage` (XSS = session takeover)

**Evidence:** `dashboard/auth.py` signs JWTs with `jwt.encode(..., SECRET_KEY, algorithm='HS256')`
and returns them in JSON response bodies. Front-end stores them in
`localStorage` (see `window.localStorage.setItem('awd_token', ...)` in
the auth modal JS). No `Set-Cookie` headers are used for session
tokens anywhere in `dashboard/app.py` or `dashboard/auth.py`.

**Impact:** Any successful XSS = attacker reads `localStorage` = full
session takeover for that user. Cookie-based sessions with
`httpOnly; Secure; SameSite=Lax` would block JS from reading the token
at all.

**Trade-off:** `localStorage` eliminates CSRF (JWT must be attached
manually via `Authorization` header); `httpOnly` cookies add CSRF
exposure but eliminate XSS session-theft. The industry default today
is cookie-based with SameSite protection.

**Recommendation (staged, 1 day of work):**

1. Issue the JWT as `Set-Cookie: awd_session=…; HttpOnly; Secure; SameSite=Lax; Max-Age=…`.
2. On every state-changing request, require a CSRF token (double-submit cookie pattern).
3. For backwards compat, keep `localStorage` path behind a feature flag
   during rollout.
4. Harden XSS surface in parallel (see M1).

---

### 🟡 M1 — `innerHTML` sinks with semi-trusted data

**Evidence:**
```
dashboard/static/js/signals.js:179:
    document.getElementById('pairs-grid').innerHTML = pairs.map(p => {
        const hookBadge = p.hooked ? `<span class="hook-badge">🔄 HOOKED</span>` : '';
        ...
    }).join('');

dashboard/static/js/heatmap.js:1051 (same pattern)
dashboard/static/js/charts.js:192  (same pattern)
```

Fields interpolated include `p.pair` (Binance symbol — always safe),
but also other signal metadata that originates from our own scanner
and could theoretically be mutated upstream (e.g. AI analysis notes,
future fields).

**Impact:** Today, the fields come from our own backend and are
well-constrained → **not exploitable in practice**. But the pattern
is unsafe: any future commit that includes a user-controlled string
in a signal (e.g. a user note, a copied comment from Telegram) would
be XSS-exploitable without any other code change.

**Fix:**
- Replace ad-hoc `innerHTML` with a tiny helper that safely escapes
  untrusted fields, or use `textContent` / `DOMPurify` / safe template
  tags (e.g. `lit-html`).
- At minimum, wrap every `${p.foo}` in the templates with a local
  `esc(v)` helper:
  ```js
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
  ```

This is defensive hardening — not urgent, but closes a class of bugs.

---

### 🟡 M2 — Inconsistent admin auth pattern

**Evidence:** In `dashboard/app.py`, admin routes fall into two patterns:

**Pattern A — correct, concise:**
```python
@app.get("/api/admin/copy-trading")
async def admin_ct_traders(user: dict = Depends(require_admin)):
    ...
```

**Pattern B — works but fragile:**
```python
@app.get("/api/admin/users")
async def api_admin_users(user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        return JSONResponse(content={"error": "Admin access required"}, status_code=403)
    ...
```

Routes using Pattern B that I verified are correctly gated:
lines 1233, 1240, 1248, 1256, 1277, 1285, 1293, 1303, 1310, 1322,
1335, 1353, 1367, 1375.

**Impact:** Today, every Pattern B route has the internal `check_is_admin`
call. But the pattern relies on developer discipline — anyone adding
a new `/api/admin/*` route using `get_current_user` could forget the
internal check, and no test would catch it.

**Fix:** Refactor all `/api/admin/*` to use `Depends(require_admin)`:

```python
# Before
async def api_admin_users(user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    ...

# After
async def api_admin_users(user: dict = Depends(require_admin)):
    ...
```

Add a test that enumerates every route matching `^/api/admin/` and
asserts its dependency tree includes `require_admin`:

```python
# tests/test_admin_guard.py
def test_every_admin_route_requires_admin():
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/admin/"):
            assert any(
                dep.call is require_admin
                for dep in route.dependant.dependencies
            ), f"{route.path} missing require_admin guard"
```

---

### 🟡 M3 — f-string table interpolation in SQL

**Evidence:**
```python
# funding_oi_cache.py:180
conn.execute(f'DELETE FROM "oi_{pair}" WHERE ts < ?', (cutoff_ms,))

# data_fetcher.py:43, 108 — similar pattern in CREATE TABLE
```

**Impact:** `pair` originates from the Binance scanner (not user input),
so this is **safe today**. But if `pair` ever comes from user input
(e.g. a future "custom pair" feature), this is classic SQL injection.

**Fix:** Whitelist-validate `pair` before interpolation:
```python
import re
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")
if not _SYMBOL_RE.match(pair):
    raise ValueError(f"Invalid pair: {pair!r}")
conn.execute(f'DELETE FROM "oi_{pair}" WHERE ts < ?', (cutoff_ms,))
```

Or — better — stop per-pair tables and use a single table with a `pair`
column, then parameters fix the issue for good:
```python
conn.execute("DELETE FROM oi_history WHERE pair = ? AND ts < ?",
             (pair, cutoff_ms))
```

---

### 🟢 L1 — Missing security headers

No HSTS / Content-Security-Policy / X-Frame-Options / X-Content-Type-Options
emitted by FastAPI.

**Likely OK in prod** if nginx / Cloudflare in front of the app sets them,
but I couldn't confirm from the code alone.

**Fix:** Middleware in `dashboard/app.py`:
```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        resp.headers["X-Content-Type-Options"]    = "nosniff"
        resp.headers["X-Frame-Options"]           = "DENY"
        resp.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"]        = "camera=(), microphone=(), geolocation=()"
        # CSP: start in Report-Only to avoid breaking inline scripts, then enforce
        resp.headers["Content-Security-Policy-Report-Only"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.binance.com wss:;"
        )
        return resp

app.add_middleware(SecurityHeadersMiddleware)
```

---

### 🟢 L2 — bcrypt rounds = 10

**Evidence:** `dashboard/auth.py:84`
```python
return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=10)).decode('utf-8')
```

**Impact:** 10 rounds is the 2013-era OWASP minimum; today's guidance is
12. Marginal — attacker would need the DB dump first.

**Fix:** `gensalt(rounds=12)`. Existing hashes continue to verify; only
new passwords use 12 rounds. No migration needed (bcrypt stores rounds
in the hash string).

---

### 🟢 L3 — `exec()` in `code_audit_tools.py`

**Evidence:**
```python
# code_audit_tools.py:371, 376
exec(function_or_code)
```

**Impact:** The function is only called from `ai_audit_interface.py`
and `run_audit.py`, neither of which are wired to any HTTP route.
**Not exploitable remotely.** But `exec()` executing arbitrary strings
is fundamentally dangerous.

**Fix:**
- Delete the function if unused.
- If needed, restrict to `ast.parse` + AST walking (never execute).
- If execution is genuinely required, sandbox with `RestrictedPython`
  or run in a separate process with no filesystem / network access.

---

### ℹ️ I1 — Things that are correct

These deserve explicit callout so we don't accidentally break them:

- ✅ **No hardcoded secrets** in any `.py` / `.js` / `.html` file.
- ✅ **No `shell=True` / `os.system`** in application code (only
  `utils_logger.py` uses `os.system('clear')` with a fixed string — safe).
- ✅ **No unsafe deserialization** (`pickle.loads` / `yaml.load`) in
  application code.
- ✅ **No debug mode / `reload=True`** in production entry points.
- ✅ **No wide-open CORS** (`allow_origins=["*"]` not found).
- ✅ **JWT signed with HS256, algorithm pinned on decode**
  (`jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])`) —
  not vulnerable to the `alg: none` attack.
- ✅ **Fallback `SECRET_KEY = secrets.token_hex(32)`** if env var missing —
  causes session invalidation on restart (denial-of-auth, not auth bypass).
  Env var is set in prod.
- ✅ **Passwords hashed with bcrypt** (not MD5/SHA1/plaintext).
- ✅ **Binance API keys encrypted at rest with Fernet** (AES-128-CBC + HMAC-SHA256).
- ✅ **NOWPayments IPN signature verified with HMAC-SHA512 + constant-time compare**
  (`nowpayments.verify_ipn_signature`).
- ✅ **Stream mode token check uses `hmac.compare_digest`** (constant-time).
- ✅ **`.env` is gitignored** (`git check-ignore .env` returns the file).
- ✅ **All `/api/admin/*` routes ARE gated** — no unguarded admin
  endpoint found. (Pattern inconsistency noted in M2; auth coverage
  is 100 %.)
- ✅ **Rate limiting on Binance-facing calls** (`data_fetcher.rate_limit()`).
- ✅ **Tier gating via `require_tier(...)` dependency** used consistently
  on paywalled endpoints.
- ✅ **Device fingerprinting + per-tier device limits** — implemented and
  audited.

---

## 3. Recommended follow-up (not part of this audit)

1. **Dependency CVE scan:**
   ```bash
   pip install pip-audit
   pip-audit -r /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/requirements.txt
   ```
2. **SAST pass:** `bandit -r dashboard/ -ll` for Python.
3. **Secret scan on full git history:**
   ```bash
   pip install gitleaks
   gitleaks detect --source . --verbose
   ```
   (to confirm no past commit leaked anything that's since been removed).
4. **Penetration test on staging:** at minimum, run OWASP ZAP's
   automated scan against `/api/*` with a valid JWT.
5. **Disaster-recovery rehearsal:** can the team restore the user DB
   from backup *without* the live `.env`? (Answer: probably not — Fernet
   key is required to decrypt Binance keys. Document the backup-and-key
   handling procedure.)
6. **Annual key rotation policy** for `FERNET_KEY` and
   `DASHBOARD_JWT_SECRET` with a documented migration path.

---

## 4. Immediate action checklist (operator)

Ranked by risk × effort:

- [ ] **2 min** — `chmod 600 .env .env.bak.*` and `chmod 600 *.db dashboard/*.db` (C1, C2)
- [ ] **1 min** — Move `.env.bak.*` out of the webroot (H1)
- [ ] **1 min** — Add `UMask=0077` to the systemd unit; restart service
- [ ] **10 min** — Verify `git ls-files` and `gitleaks detect` show no secret in git history
- [ ] **30 min** — Refactor Pattern-B admin routes to `Depends(require_admin)` + add the `test_every_admin_route_requires_admin` unit test (M2)
- [ ] **1 h** — Add `SecurityHeadersMiddleware` (L1)
- [ ] **1 line** — Bump bcrypt rounds from 10 to 12 (L2)
- [ ] **15 min** — Remove or sandbox `code_audit_tools.exec()` (L3)
- [ ] **2 h** — Introduce an `esc()` helper and apply to every `innerHTML = ...` template (M1)
- [ ] **10 min** — Whitelist-validate `pair` before f-string SQL interpolation (M3)
- [ ] **1 day** — Migrate JWT to `httpOnly; Secure; SameSite=Lax` cookies + CSRF token (H2)

Total for C/H/M items: **~4 hours of engineering work** to move the
platform from "OK" to "genuinely hardened".

---

## 5. Closing note

The application-layer security posture is better than average for a
project of this scope — the Fernet-encrypted API keys, bcrypt
passwords, HMAC-verified webhooks, tier gating, and admin auth
coverage are all done correctly. The weakness is **operational**: the
artefacts containing those secrets live on the filesystem with
permissive modes, which undercuts the good cryptography.

Fixing the two 2-minute `chmod` issues (C1, C2) is the single highest
ROI action available on this codebase today.

*This document is a plan. No fixes have been applied. Operator approval
required before any change.*
