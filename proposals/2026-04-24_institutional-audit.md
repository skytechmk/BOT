# Project Institutional — Zero-Mercy Codebase Audit & 30/60/90 Plan

**Date:** 2026-04-24
**Author:** SPECTRE
**Scope:** Entire platform — Python/Rust backend, FastAPI dashboard, SPA shell, landing page, ML pipeline, copy-trading engine
**Brief:** Brutal honesty. Identify technical debt, security gaps, performance bottlenecks, UI/UX amateur-hour moments. Deliver a 30/60/90-day roadmap.

---

## Executive summary

Anunnaki World has **solid institutional bones**: WebSocket User Data streams, Rust indicator batch, XGBoost+Transformer ensemble, `-1003` circuit breaker, Fernet-encrypted API keys, crypto-verified JWT with `require_admin` guard. The **algorithmic surface is genuinely institutional-grade**.

What makes it still *look* like a side project:

1. **Frontend amateur tells** — 1,724-line `index.html` with inline styles, hardcoded `566` stat, generic spinners, no skeleton loaders, no security headers.
2. **Admin surface hygiene** — `/admin` HTML route unauthenticated, `admin.js` publicly served (reveals every admin endpoint).
3. **Latent scalability ceilings** — ML inference on the GIL, liquidation dict pruning on the event loop, SQLite lock contention at >50 concurrent users.
4. **Zero backtesting** — strategy changes ship to live capital without historical validation.

Across the already-drafted proposals (10 this week) + the gaps identified below, we have **a clear path to genuinely institutional posture in 90 days** without a rewrite, without breaking production, and without losing the velocity that got us here.

---

## 1 · Critical Vulnerabilities (High Priority)

### 1.1 Admin surface leaks metadata — HIGH (trust gap)
- `/admin` route serves full HTML to anyone (`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:938-942`)
- `/static/js/admin.js` publicly served → reveals every `/api/admin/*` endpoint
- `check_is_admin(user)` inlined 20× — one forgotten line = endpoint exposure

**Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_security-hardening.md` (F1, F2, F3)

### 1.2 No browser security headers — MEDIUM (compliance)
- Zero of CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy are set
- Every security scanner flags this instantly — any institutional customer's InfoSec team fails us on page 1

**Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_security-hardening.md` (F4)

### 1.3 CORS admits `http://localhost` in production — LOW
- Gratuitous attack surface; single env-gated config flip

**Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_security-hardening.md` (F5)

### 1.4 No `.well-known/security.txt` — LOW (compliance)
**Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_security-hardening.md` (F6)

### 1.5 No API key rotation nudge — LOW (hygiene)
Users who onboarded 180 days ago still use the same Binance key. Soft banner at 90 days.

**Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_platform-polish.md` (item 8.1)

### 1.6 **What we got right and should NOT change**
- `Fernet` encryption of API keys (`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/copy_trading.py:123-131`)
- Withdrawal-permission hard block (`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/copy_trading.py:1085-1098`)
- `-1003` IP ban circuit breaker with cached read-through
- JWT HS256 with env-gated secret
- `require_admin` crypto-verified chain

Per the parallel audit `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_access-control-resilience-audit.md`: access control is **PASS**.

---

## 2 · Performance Bottlenecks

### 2.1 ML inference on the main GIL — HIGH
`signal_generator.py` runs XGBoost + Transformer inference inline with Telegram delivery + WS parsing. Any model stall = signal delivery lag. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_ml-inference-isolation.md`

### 2.2 Liquidation in-memory dict — HIGH
10k events × N symbols stored in Python dicts, pruned via hourly `asyncio.to_thread` iteration → GIL micro-stalls during peak volatility (exactly when we least want them). **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_timescaledb-migration.md`

### 2.3 SQLite lock contention — MEDIUM
At 50+ concurrent screener requests, WAL-mode SQLite still serialises readers behind writers. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_redis-state-management.md`

### 2.4 UDS 60-second REST reconcile — LOW but compounding
`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/binance_user_stream.py` reconciles state every 60 s "just in case". Event stream has proven reliable for 2 weeks. Drop to 5 min or gap-gated. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_platform-polish.md` (item 1.1)

### 2.5 Heatmap cold-start "Connecting…" — MEDIUM (perceived perf)
Snapshot-first render before WS hooks up. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_frontend-optimizations.md` (§2)

### 2.6 Screener spinner — LOW (perceived perf)
Shimmering skeleton grid. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_skeleton-loaders.md`

### 2.7 Global CSS bloat — LOW
`main.css` 52 KB + `premium.css` 72 KB loaded on every page including the landing. Route-split. Or **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_tailwind-migration.md` (full utility migration).

### 2.8 `index.html` 1,724 lines with 12+ inline style props per block
DOM bloat, FCP drag, maintenance nightmare. **Ticket:** tailwind-migration.md.

### 2.9 Admin-only `admin.js` downloaded by all logged-in users
~15 KB wasted bandwidth per session for non-admins; also security gap (§1.1). **Ticket:** security-hardening.md F2.

---

## 3 · UI/UX Debt — "rookie tells" that make the platform look amateur

Called out with zero sugar-coating. All fixable in the Phase-1/2 sprint.

### 3.1 Hardcoded `566` pairs stat in 3 places while scanner runs `605`
Visible cosmetic drift. **Ticket:** platform-polish.md (item 2.2)

### 3.2 Generic `<div class="loading"><div class="spinner"></div>…</div>` everywhere
Skeleton loaders are table-stakes in 2026. **Ticket:** skeleton-loaders.md

### 3.3 Inline styles on hundreds of elements in `index.html`
```html
<div style="display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px">
```
No cascade, no dark-mode override possible per-component, no consistency. **Ticket:** tailwind-migration.md

### 3.4 Favicon is a JPEG, blurry on high-DPI tabs
`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/logo.jpeg` used as favicon. Generate PNG 32/48/96/192/512 + SVG. **Ticket:** platform-polish.md (item 7.2)

### 3.5 OG banner does not carry the new motto
We just rebranded to *"We do the math. You make the move."* — the Twitter/Telegram preview image still shows the old tagline. **Ticket:** platform-polish.md (item 7.1)

### 3.6 Fake/static social proof counter
`hero-signals-fired` with `data-live-signals="1"` — not verified to be actually live. Fake counters erode trust. **Ticket:** platform-polish.md (item 2.4)

### 3.7 Admin tab `display:none` instead of `.remove()`
Inspect-element reveals the "Admin" nav entry to curious users. Cosmetic, but looks sloppy. **Ticket:** frontend-optimizations.md (§1)

### 3.8 No FAQ section on landing
Top-3 pre-sale objections unanswered: *"Does this work on Bybit?", "Is my API key safe?", "What if Binance goes down?"*. **Ticket:** platform-polish.md (item 2.5)

### 3.9 No mobile bottom-tab nav
Side-drawer on mobile ≤ 600 px = 2-3× lower engagement vs. bottom tabs. **Ticket:** platform-polish.md (item 6.2)

### 3.10 Empty-states absent on half the pages
Signals (logged-out), heatmap (pair not ready), order-flow (no data) — all show blank panels. **Ticket:** platform-polish.md (item 5.2)

### 3.11 Toasts spam when rate-limited
12 simultaneous API calls → 12 identical error toasts. Throttle to 1 per 3 s per message. **Ticket:** platform-polish.md (item 5.4)

### 3.12 Admin panel has no log/error telemetry widget
Health at a glance: *"Last 24h: 24 ERR, 47 WARN"*. **Ticket:** platform-polish.md (items 4.1, 4.3)

---

## 4 · Scalability & ML Integration

### 4.1 ML inference latency — current behaviour
- Model load: one-time at boot (fine)
- Per-signal inference: ~40-80 ms in-process on GIL → blocks event loop
- Telegram delivery delayed by 40-80 ms × pairs-in-batch

### Fix — **Ticket:** ml-inference-isolation.md
Dedicated gRPC or Triton inference microservice on the Proxmox cluster. Main loop sends features, gets confidence back in ~5-15 ms over the wire (faster than in-process once the GIL contention is gone in high-load moments).

### 4.2 No backtesting
Strategy changes ship to live USD. **Ticket:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-24_backtesting-engine.md`

### 4.3 No horizontal scalability for dashboard
Single `uvicorn` process. At 500+ concurrent users we will saturate. Redis state (redis-state-management.md) enables stateless horizontal scale-out.

### 4.4 Mobile app readiness
Current code is responsive but not app-shell. PWA manifest exists. Native wrapper (Capacitor) is 2-3 days once push notifications (native-push-alerts.md) are live.

---

## 5 · Strategic Action Plan — 30 / 60 / 90 days

### Phase 1 — "Trust Clean-up" (Days 1-30)
**Goal:** Close every "looks amateur" gap. Ship security hardening. Lock down admin surface. Polish first-impression elements.

| Week | Deliverable | Owner | Ticket |
|---|---|---|---|
| 1 | Security hardening (F1-F6) | SPECTRE | security-hardening.md |
| 1 | Fix hardcoded `566` → live count | SPECTRE | platform-polish.md 2.2 |
| 1 | Regenerate OG banner with motto | Design + SPECTRE | platform-polish.md 7.1 |
| 1 | Favicon PNG/SVG set | SPECTRE | platform-polish.md 7.2 |
| 2 | Admin tab `.remove()` + heatmap snapshot-first | SPECTRE | frontend-optimizations.md |
| 2 | Skeleton loaders (screener, copy-trading, signals) | SPECTRE | skeleton-loaders.md |
| 2 | Toast dedup + empty-states | SPECTRE | platform-polish.md 5.2, 5.4 |
| 3 | Drop UDS REST reconcile 60 s → 5 min | SPECTRE | platform-polish.md 1.1 |
| 3 | Admin panel telemetry widget (ERR/WARN counts) | SPECTRE | platform-polish.md 4.1 |
| 3 | FAQ section on landing | Copy + SPECTRE | platform-polish.md 2.5 |
| 4 | API-key rotation nudge | SPECTRE | platform-polish.md 8.1 |
| 4 | Trailing-SL state in open-trades row | SPECTRE | platform-polish.md 1.4 |
| 4 | Close-reason tooltip on closed trades | SPECTRE | platform-polish.md 1.5 |

**Phase 1 exit criteria:**
- Security scanner score A+ on `securityheaders.com`
- `/admin` returns 404 to non-admins
- Lighthouse Best-Practices + PWA both ≥ 90
- Zero "566" in codebase; live count served from API
- Skeleton loaders on every major data fetch

### Phase 2 — "Scalability" (Days 31-60)
**Goal:** Kill the three architectural ceilings (ML-on-GIL, liquidation-in-dict, SQLite-lock). Introduce Redis. Start Tailwind migration.

| Week | Deliverable | Ticket |
|---|---|---|
| 5 | Redis deployed, live-balance cache moved off SQLite | redis-state-management.md |
| 5-6 | Liquidation collector → TimescaleDB | timescaledb-migration.md |
| 6-7 | ML inference microservice (gRPC on Proxmox) | ml-inference-isolation.md |
| 7 | WebSocket refactoring — backpressure on `forceOrder` stream | (new ticket — see §6 below) |
| 8 | Tailwind migration — landing page first (smallest surface) | tailwind-migration.md |
| 8 | Mobile bottom-tab nav | platform-polish.md 6.2 |
| 8 | Native push notifications (PWA) | native-push-alerts.md |

**Phase 2 exit criteria:**
- Dashboard sustains 500 concurrent WebSocket users at <100 ms p95 API latency
- ML inference p99 latency <25 ms (vs. current ~80 ms p99)
- Liquidation events are never pruned in Python again — TSDB handles retention
- Tailwind proof-of-concept live on landing.html with 50% smaller CSS payload

### Phase 3 — "Expansion" (Days 61-90)
**Goal:** Ship backtesting. Ship mobile-first polish. Complete Tailwind migration on SPA. Harden for next 10× growth.

| Week | Deliverable | Ticket |
|---|---|---|
| 9-10 | Backtesting sandbox (historical replay through signal_generator) | backtesting-engine.md |
| 10 | Tailwind migration — SPA shell `index.html` | tailwind-migration.md |
| 11 | Mobile app wrapper (Capacitor around PWA) | (new ticket) |
| 11 | Horizontal scale-out proof (N=3 uvicorn workers behind nginx) | (new ticket) |
| 12 | Full security re-audit + pentest | external vendor |

**Phase 3 exit criteria:**
- Operator can run a 30-day historical backtest of any strategy variant in <60 s
- Mobile app submitted to App Store / Play Store
- Can horizontally scale dashboard to 3+ workers without session desync
- Third-party pentest report: zero critical, zero high

---

## 6 · New tickets to open (not yet in proposals folder)

### 6.1 WebSocket backpressure on `forceOrder` stream
`liquidation_collector.py` consumes ~1k events/min at peak. No backpressure — if processing stalls, we either drop or back up memory. Bounded `asyncio.Queue(maxsize=5000)` + overflow-drop-oldest policy + metric counter.

### 6.2 Horizontal scale-out proof
Nginx upstream to N uvicorn workers. Requires:
- Session state externalised (Redis — already in Phase 2)
- WS sticky sessions OR stateless WS via Redis pub/sub fan-out
- Database pool sizing review

### 6.3 Mobile Capacitor wrapper
PWA → Capacitor → App Store / Play Store. 2-3 days once push notifications are in.

### 6.4 Admin audit log
Every admin action (tier-change, payment-activate, user-deactivate) → append-only log in `admin_audit` table with actor, timestamp, target, before/after JSON. Forensics + compliance.

### 6.5 Rate-limit telemetry dashboard
Time-series of Binance request weight / second with ban-threshold line. Surfaces pre-ban trends hours before the ban.

---

## 7 · What we will deliberately NOT do

- **No framework rewrite.** FastAPI + vanilla JS is working. React/Vue is a solution to a problem we don't have.
- **No SSR.** The SPA shell caches well; SSR adds complexity for landing-page SEO that OG tags already solve.
- **No microservice-everything.** Only ML inference leaves the monolith. The unified Python loop is an asset for most paths.
- **No "Admin Panel v2".** Per operator directive Apr 23. Existing admin is fine — we add *widgets* to it (telemetry, audit log), not rebrand.
- **No feature sprawl.** The copy-trading / signals / heatmap / screener / order-flow / macro / chat combo is already ample. Ship polish, not surface.
- **No algorithm changes in Phase 1.** PREDATOR + ensemble is producing signals. Phase 2 unlocks backtesting so future changes ship safely.

---

## 8 · Referenced proposals (already in folder)

All ten draft proposals this week, now cross-referenced from a single plan:

| Ticket | Phase | Status |
|---|---|---|
| `2026-04-24_security-hardening.md` | 1 | NEW — drafted today |
| `2026-04-24_platform-polish.md` | 1 | drafted Apr 24 |
| `2026-04-24_frontend-optimizations.md` | 1 | drafted Apr 24 |
| `2026-04-24_skeleton-loaders.md` | 1 | drafted Apr 24 |
| `2026-04-24_access-control-resilience-audit.md` | 1 | audit-only (PASS) |
| `2026-04-24_redis-state-management.md` | 2 | drafted Apr 24 |
| `2026-04-24_timescaledb-migration.md` | 2 | drafted Apr 24 |
| `2026-04-24_ml-inference-isolation.md` | 2 | drafted Apr 24 |
| `2026-04-24_tailwind-migration.md` | 2-3 | drafted Apr 24 |
| `2026-04-24_native-push-alerts.md` | 2 | drafted Apr 24 |
| `2026-04-24_backtesting-engine.md` | 3 | drafted Apr 24 |
| `2026-04-23_security-audit.md` | 1 | earlier draft — superseded by security-hardening |
| `2026-04-23_in-app-chat-assistant.md` | 3 | separate feature track |

---

## 9 · Open questions for operator

1. **Phase 1 go/no-go on security-hardening.md today?** Fixes are all <1 hour, zero functional change.
2. **Design capacity** for OG banner regen + email templates?
3. **Budget for external pentest at end of Phase 3?** ~$3-8k for a solid crypto-platform audit.
4. **Mobile priority** — are current % visitors on mobile enough to move bottom-tab nav into Phase 1 (from Phase 2)?
5. **Redis / TimescaleDB hosting** — Proxmox containers or managed (Upstash / Timescale Cloud)? Managed costs ~$40/mo combined and removes ops burden.

---

## 10 · The brutal one-liner

*The algorithm is institutional. The chrome around it still reads as "skilled developer's side project." Phase 1 fixes the chrome in 30 days. Phase 2 removes the three hidden scaling ceilings before they bite at user #500. Phase 3 delivers the two features institutions actually demand — backtesting and mobile — and we commission a third-party pentest to put a stamp on it.*

Awaiting operator prioritisation.
