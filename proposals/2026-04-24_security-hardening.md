# Proposal: Security Hardening — Trust-Gap Closures

**Date:** 2026-04-24
**Author:** SPECTRE
**Scope:** Admin surface, HTTP headers, secret handling, CORS, attack-surface reduction
**Status:** Proposal — operator-reviewed before apply

---

## TL;DR

The **data layer is secure** — `require_admin` crypto gate (`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/auth.py:825`) plus the `-1003` circuit breaker make unauthorised reads impossible. What we're leaking is **attack-surface metadata**: admin panel existence, every admin endpoint path, and the absence of modern browser-security headers. These are "trust gap" findings — they don't grant access, they just make us look unprofessional and make attackers' reconnaissance cheaper.

Six concrete fixes, all <1 hour each, zero downtime.

---

## Findings & Fixes

### F1 · `/admin` HTML route has no server-side auth — **HIGH** (trust gap, not data leak)

**Evidence:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:938-942`

```@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:938-942
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    """Serve the admin panel shell. Auth is enforced client-side + on every API call."""
    html_path = Path(__file__).parent / "admin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)
```

Anyone on the public internet can `GET /admin` and receive the full admin HTML shell. While the data APIs are safe, this:

- **Confirms the panel exists** (recon foothold)
- **Reveals every admin UI element** (tab labels, DOM IDs, payment-flow structure)
- **Tells attackers exactly which endpoints to probe** (admin.js is referenced in the HTML)

### Fix F1

```@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:938-942
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Serve the admin panel shell ONLY to authenticated admins.

    Non-admins, unauthenticated visitors, and holders of stale tokens
    get a 404 — indistinguishable from a non-existent route. This is
    security-through-silence: we refuse to even confirm the panel
    exists to unauthorised requesters."""
    # Read token from Authorization header OR `?t=` query OR cookie
    token = (request.headers.get("authorization", "").replace("Bearer ", "") or
             request.query_params.get("t") or
             request.cookies.get("aladdin_token") or "")
    try:
        from auth import decode_access_token, _db_get_user, is_admin as _is_admin
        payload = decode_access_token(token) if token else None
        user = _db_get_user(payload["sub"]) if payload else None
        if not user or not _is_admin(user):
            # Return 404 — do not confirm the route exists
            return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
    except Exception:
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
    html_path = Path(__file__).parent / "admin.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)
```

### F2 · `admin.js` served to all clients — **MEDIUM**

**Evidence:** `curl http://localhost:8050/static/js/admin.js` → HTTP 200 (no auth check). The file is loaded in `index.html:1714` for every logged-in user. Reveals every `/api/admin/*` endpoint, request bodies, and admin UI logic.

### Fix F2 · Move admin.js behind a gated route

1. Rename `static/js/admin.js` → `admin/admin.js` (outside `StaticFiles` mount)
2. Add a protected route:

```python
@app.get("/admin/admin.js")
async def admin_js(user: dict = Depends(require_admin)):
    path = Path(__file__).parent / "admin" / "admin.js"
    return FileResponse(path, media_type="application/javascript")
```

3. Change `index.html` reference from `/static/js/admin.js` → `/admin/admin.js`, loaded **conditionally** only when `user.is_admin`:

```js
if (_user && _user.is_admin) {
    const s = document.createElement('script');
    s.src = '/admin/admin.js?v=20260419d';
    document.head.appendChild(s);
}
```

Non-admins never even fetch the file.

### F3 · `check_is_admin(user)` inline 20× — DRY violation, easy to forget — **MEDIUM**

**Evidence:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py` has 20 hand-written `if not check_is_admin(user): return 403` blocks. Already exists: `require_admin` dependency at `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/auth.py:825`. Not used.

### Fix F3 · Migrate all admin endpoints to `Depends(require_admin)`

**Before:**
```python
@app.get("/api/admin/users")
async def api_admin_users(user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        return JSONResponse(content={"error": "Admin access required"}, status_code=403)
    users = await asyncio.to_thread(get_all_users)
    return JSONResponse(content={"users": users})
```

**After:**
```python
@app.get("/api/admin/users")
async def api_admin_users(user: dict = Depends(require_admin)):
    users = await asyncio.to_thread(get_all_users)
    return JSONResponse(content={"users": users})
```

Saves ~60 lines across the file. More importantly: if a dev forgets `Depends(require_admin)`, the linter/reviewer will catch it far more easily than a missing inline guard. Raises HTTP 401 for unauth (no token) and 403 for auth-but-not-admin (semantically correct).

**Bonus:** Mount admin routes under an `APIRouter` with a module-level dependency so no individual endpoint can be added without protection:

```python
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
# ... all admin endpoints register on admin_router, not app
app.include_router(admin_router)
```

### F4 · No security headers — **MEDIUM** (ratings/compliance)

**Evidence:** `curl -I http://localhost:8050/` returns zero `Content-Security-Policy`, `X-Frame-Options`, `Strict-Transport-Security`, `Referrer-Policy`, or `Permissions-Policy`. Any security scanner will flag this immediately.

### Fix F4 · Add `SecurityHeadersMiddleware`

Add after the existing `NoCacheJSMiddleware` at `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:876`:

```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Institutional-grade HTTP security headers. Applied to every
    response; no per-route opt-out (we want these everywhere)."""
    async def dispatch(self, request, call_next):
        r = await call_next(request)
        # Prevent clickjacking
        r.headers["X-Frame-Options"] = "DENY"
        # Stop MIME-sniff attacks
        r.headers["X-Content-Type-Options"] = "nosniff"
        # HSTS — 1 year, include subdomains, preload-ready
        r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # Modern replacement for X-XSS-Protection
        r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Lock down browser APIs we don't use
        r.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        # CSP — tuned to actual asset sources. Report-only first to catch
        # any violations before enforcing.
        r.headers["Content-Security-Policy-Report-Only"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://s3.tradingview.com; "
            "style-src  'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src   'self' https://fonts.gstatic.com; "
            "img-src    'self' data: https:; "
            "connect-src 'self' wss: https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self';"
        )
        return r

app.add_middleware(SecurityHeadersMiddleware)
```

Start with `Report-Only` for 48 h, monitor violations, then flip to enforcing `Content-Security-Policy`. Same header spelling without the `-Report-Only` suffix.

### F5 · CORS permits `http://localhost:8050` in production — **LOW**

**Evidence:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:851-857`

```python
allow_origins=["https://anunnakiworld.com", "https://www.anunnakiworld.com",
               "http://localhost:8050", "http://127.0.0.1:8050"],
```

In production this means a compromised LAN host can issue browser-credentialed calls. Not exploitable today (no attacker has LAN access) but gratuitous.

### Fix F5 · Environment-gated origins

```python
_PROD = os.getenv("ENVIRONMENT", "dev") == "production"
_ORIGINS = (
    ["https://anunnakiworld.com", "https://www.anunnakiworld.com"]
    if _PROD else
    ["https://anunnakiworld.com", "https://www.anunnakiworld.com",
     "http://localhost:8050", "http://127.0.0.1:8050"]
)
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, ...)
```

Set `ENVIRONMENT=production` in the systemd unit file.

### F6 · Missing `.well-known/security.txt` — **LOW** (compliance)

**Evidence:** `curl -o/dev/null -w "%{http_code}" http://localhost:8050/.well-known/security.txt` → 404. RFC 9116 standard for responsible disclosure. Not having one is flagged by every security scanner.

### Fix F6 · Add `static/.well-known/security.txt`

```
Contact: mailto:security@anunnakiworld.com
Expires: 2027-04-24T00:00:00Z
Encryption: https://anunnakiworld.com/.well-known/pgp-key.txt
Preferred-Languages: en, mk
Canonical: https://anunnakiworld.com/.well-known/security.txt
Policy: https://anunnakiworld.com/security-policy
```

Add route:
```python
@app.get("/.well-known/security.txt")
async def security_txt():
    return FileResponse(_STATIC_DIR / ".well-known" / "security.txt", media_type="text/plain")
```

---

## What this proposal does NOT change

- **No functional behaviour changes.** Every endpoint returns identical data for identical valid requests.
- **No new dependencies.** All fixes use stdlib + existing FastAPI/Starlette primitives.
- **No DB migrations.**
- **No auth logic changes** — `require_admin` already works exactly right; we're just using it.

## Rollout order (30 minutes total)

| # | Fix | Risk | Verify |
|---|-----|------|--------|
| 1 | F4 — CSP Report-Only | **Zero** — report-only | `curl -I /` shows header |
| 2 | F5 — CORS gated | **Zero** — dev env unaffected | curl `Origin: http://evil.com /api/auth/me` → blocked |
| 3 | F6 — security.txt | **Zero** — new route | `curl /.well-known/security.txt` → 200 |
| 4 | F1 — /admin auth | **Low** — unauth 404 | `curl /admin` unauth → 404; admin JWT → 200 |
| 5 | F3 — Depends(require_admin) × 20 | **Low** — identical semantics | `pytest tests/admin/` or manual walk |
| 6 | F2 — admin.js gated | **Low** — conditional load | DevTools → non-admin has no admin.js in Sources |

After 48 hours of CSP Report-Only with zero violations, flip to enforcing.

## Regression-test checklist

Manual walk (no formal test suite exists for the admin surface yet):

1. Log in as non-admin, visit `/admin` → expect **404**
2. Log in as non-admin, open DevTools Sources → no `admin.js`
3. Log in as admin, visit `/admin` → expect full panel
4. Log in as admin, click every admin tab (users, payments, devices, settings) → all work
5. `curl -I http://localhost:8050/` → expect 5 security headers
6. `curl /.well-known/security.txt` → expect 200 with contact line

---

## Effort

- **Coding:** 90 min
- **CSP tuning + monitoring:** 48 h passive
- **Deployment:** single dashboard restart

## Priority justification

These are *not* active exploits. But the platform's positioning is **"Institutional-grade AI trading signals"**. A security scanner run by a prospective Ultra-tier customer (or a compliance officer at a fund considering us) will score us poorly on the basics before they ever look at the algo. Fixing these closes the easiest rejection vector.
