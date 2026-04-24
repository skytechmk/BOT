# Proposal: Dedicated Marketing Homepage / Dashboard Split

- **Author:** S.P.E.C.T.R.E.
- **Date:** 2026-04-19
- **Status:** Draft — awaiting operator approval
- **Type:** UI/UX + SEO + Architecture
- **Risk:** Medium (breaks current muscle memory for returning users; mitigated with auto-redirect)
- **Scope:** Frontend-only. No changes to signal engine, ML, payments, copy-trading, or trading-bot logic.

---

## 1. Executive Summary

`dashboard/index.html` is **1,378 lines** serving two conflicting jobs:
1. **Marketing landing** — hero, pricing, roadmap, trust strip, exchange badges, FAQ-ish content.
2. **Authenticated application** — signals feed, charts, screener, heatmap, copy-trading, account, admin.

Both jobs live in the same HTML, the same stylesheet stack (`main.css` + `premium.css` + `admin.css` = ~80 KB), and load the same ~1.1 MB of JavaScript (`lightweight-charts` + 12 in-house modules) on every visit — even for a visitor who just wants to read the pricing.

**Proposal:** split into two distinct surfaces.

| Surface | Route | Purpose | Audience | Bundle size |
|---|---|---|---|---|
| **Marketing site** | `/` | Convert visitors → sign-ups | Unauthenticated public | ~45 KB (no charts lib) |
| **Application** | `/app` | Deliver signal intelligence | Authenticated users | ~1.1 MB (current) |

Logged-out users hitting `/` see the marketing page. Logged-in users hitting `/` are auto-redirected to `/app`. The two share a minimal CSS token file for visual consistency but use independent bundles.

---

## 2. Current State Audit

### File-level ownership

| File | Lines | Contains |
|---|---|---|
| `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/index.html` | 1378 | **Both** landing + app |
| `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/css/main.css` | ~1100 | Base tokens + both contexts |
| `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/css/premium.css` | 1947 | Premium polish — mixed |
| `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/app-r7.js` | ~1500 | App + auth modal wiring |
| 12 other JS modules | | Signals, charts, screener, heatmap, copytrading, macro, analytics, payments, lounge, init, admin, client-security |

### Marketing sections currently embedded in `index.html`

These will move to the new marketing file (line numbers approximate from current HEAD):

- **Hero** — lines ~891-907 (`.landing-hero` block)
- **Stats bar** — lines ~909-913 (`.stats-bar`)
- **Trust strip** — lines ~916-922 (`.aw-trust-strip`)
- **Pricing cards** — lines ~924-980 (`.pricing-grid`)
- **Crypto badges** — lines ~982-986
- **Roadmap** — lines ~987-1177 (just updated with PREDATOR / USDT.D / DEX pre-dev)
- **Exchange badges** — lines ~1104-1175

### Problems this split solves

1. **SEO blindness** — Google bots rendering `/` today see a React-like app shell, not readable content. Rankings for "crypto trading signals", "binance futures signals" are anemic.
2. **Conversion leak** — first paint shows nav tabs + timer + tier badges. Prospects who aren't logged in see chrome for a product they can't use yet.
3. **Performance penalty** — 1.1 MB of JS downloaded + parsed for a visitor who might not sign up. Lighthouse performance score currently ~54.
4. **Stylesheet collisions** — the last 7 commits were spent overriding dark app styles so they look right in light mode on the landing. This will keep happening.
5. **Maintenance cost** — every new marketing iteration risks breaking app layout and vice-versa.

---

## 3. Proposed Architecture

### Route map

```
/                    → marketing.html   (public, indexed, ~45 KB)
/pricing             → marketing.html#pricing  (anchor)
/roadmap             → marketing.html#roadmap  (anchor)
/features            → marketing.html#features (anchor)
/whitepaper          → /static/whitepaper.html (exists)
/app                 → index.html       (auth-required, ~1.1 MB, current behavior)
/app/signals         → app tab
/app/charts          → app tab
/app/admin           → app tab
/admin               → admin.html (standalone admin panel, exists)
/login, /register    → marketing.html with auth modal pre-opened
/verify-email        → existing endpoint unchanged
/reset-password      → existing endpoint unchanged
/api/...             → unchanged
```

### Redirect logic (FastAPI side)

At `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py` add:

```python
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    token = request.cookies.get("access_token") or None
    # No auth cookie → serve marketing page
    if not token:
        return FileResponse("marketing.html")
    # Has cookie → verify cheaply; on success redirect to /app; on failure serve marketing
    try:
        user = decode_access_token(token)
        if user:
            return RedirectResponse("/app", status_code=302)
    except Exception:
        pass
    return FileResponse("marketing.html")

@app.get("/app", response_class=HTMLResponse)
async def app_shell(request: Request):
    # Current index.html behavior — auth checked client-side via JWT in localStorage
    return FileResponse("index.html")
```

**Edge case**: Users with an expired JWT in localStorage but no cookie will land on marketing first, then `app-r7.js` auto-opens the auth modal. That's acceptable UX.

### File tree (new + moved)

```
dashboard/
├── marketing.html                    (NEW — ~900 lines)
├── index.html                        (RENAMED: serves /app; strip marketing sections)
├── admin.html                        (unchanged)
├── static/
│   ├── css/
│   │   ├── tokens.css                (NEW — theme vars only, ~80 lines, shared)
│   │   ├── marketing.css             (NEW — ~800 lines, landing-specific)
│   │   ├── main.css                  (trimmed: remove landing-only rules)
│   │   ├── premium.css               (trimmed: remove landing-only rules)
│   │   └── admin.css                 (unchanged)
│   ├── js/
│   │   ├── marketing.js              (NEW — ~150 lines: ticker, FAQ accordion, theme)
│   │   ├── app-r7.js                 (trimmed: remove landing init branch)
│   │   └── ... (all other app JS unchanged)
│   ├── og-marketing.png              (NEW — 1200×630 OG image for socials)
│   └── demo/                         (NEW — short GIFs/MP4s for "how it works")
│       ├── demo-signal-feed.mp4
│       ├── demo-chart-overlay.mp4
│       └── demo-heatmap.mp4
├── marketing_routes.py               (NEW — /sitemap.xml, /robots.txt handlers)
```

---

## 4. Marketing Page — Section Wireframes

All sections live inside a single HTML file for simplicity. No SPA. Anchor links scroll.

### 4.1 Header (sticky, ~64 px)

```
┌────────────────────────────────────────────────────────────────────────┐
│  [Logo] Anunnaki World              Features  Pricing  Roadmap  Docs   │
│  Institutional · AI · Crypto Derivatives           [Login]  [Get Free] │
└────────────────────────────────────────────────────────────────────────┘
```

- Logged-out: `[Login] [Get Free]`
- Logged-in: `[Open Dashboard →]` (replaces both)

### 4.2 Hero (viewport height ~620 px)

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   ◉ LIVE · INSTITUTIONAL INTELLIGENCE · CRYPTO DERIVATIVES             │
│                                                                        │
│           Where Smart Money                                            │
│           Meets Smart Signals                                          │
│                                                                        │
│   AI scanning 538 Binance USDT-perp pairs in real time.                │
│   PREDATOR regime engine, liquidation heatmaps, institutional          │
│   risk gates. Read-only API keys — no custody, ever.                   │
│                                                                        │
│   [Start Free — no card]  [Read Whitepaper]                            │
│                                                                        │
│   ╔══════════ LIVE SIGNAL TICKER ══════════╗                           │
│   ║ BTCUSDT  LONG  +0.42%  ·  ETHUSDT SHORT +1.10% ... ║               │
│   ╚═══════════════════════════════════════╝                            │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

Ticker fetches from a new public endpoint `/api/public/ticker` (returns last 20 closed signals, anonymized — just pair/direction/PnL/timestamp). Refreshes every 15 s.

### 4.3 Trust strip (40 px row, animated marquee on mobile)

```
🔒 Bank-Grade Encryption · ⚡ Sub-Second Latency · 🧠 XGBoost + Transformer AI ·
🛡️ Read-Only API Keys · ✨ No Custody, Ever · 🔔 Device-Fingerprint Security
```

### 4.4 Stats bar (real numbers from API)

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│    538       │   1,247      │    61.2%     │   +34.8%     │
│ PAIRS MON.   │ SIGNALS SENT │   WIN RATE   │  AVG RETURN  │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

Pulled from `/api/public/stats` (new endpoint, aggregated from `performance_tracker`).

### 4.5 How it works (3 steps)

```
┌──────────────────┬──────────────────┬──────────────────┐
│   [icon]         │   [icon]         │   [icon]         │
│   01. Connect    │   02. Receive    │   03. Execute    │
│   Link read-only │   Signals arrive │   Copy-trade on  │
│   API or join    │   via dashboard  │   Binance Futures│
│   Telegram       │   + Telegram     │   or trade manual│
└──────────────────┴──────────────────┴──────────────────┘
```

Each step has a 5-second MP4 loop (muted, autoplay, playsinline) showing the actual UI doing the thing.

### 4.6 Features grid (6 cards, 3×2)

| Card | Icon | One-liner |
|---|---|---|
| **Reverse Hunt Engine** | 🎯 | ATR + Chandelier Exit + TSI adaptive thresholds on 538 pairs. |
| **PREDATOR Regime** | 🐺 | 3-layer state machine: regime + positioning + stop-hunt detector. |
| **Liquidation Heatmap** | 🔥 | Real-time WebSocket liquidation cascade map. |
| **Copy-Trading** | 🤝 | Auto-execution on your Binance Futures account (Pro). |
| **Market Screener** | 📊 | 200+ pairs with zone / TSI / CE filters. |
| **USDT.D Macro Gate** | 🌐 | Dampens signals when USDT-dominance regime is hostile. |

Each card is a clickable link to `/features#<slug>` (anchor on same page for now; separate pages in phase 2 if we want dedicated SEO landing per feature).

### 4.7 Pricing

Clean 4-column grid: Free / Plus / Pro / Ultra (Ultra = coming soon). Moved verbatim from current index.html with two changes:

1. **Monthly / Yearly toggle** (yearly = 2 months free).
2. **Feature-comparison table** below cards (detailed per-tier entitlements).

### 4.8 Exchanges — status matrix

Reuse the just-updated block with LIVE / Q3 / Q4 / PRE-DEV badges including Hyperliquid + Aster.

### 4.9 Roadmap

Reuse the just-updated timeline. Move from `/` → `/#roadmap`. Keep the 4-quarter vertical timeline design.

### 4.10 Testimonials (future — placeholder for now)

```
┌────────────────────────────────────────────────────────────────────────┐
│  "The first signals service I've actually kept paying for after the    │
│   first month. The liquidation heatmap alone is worth it."             │
│                                              — @user, Pro subscriber   │
└────────────────────────────────────────────────────────────────────────┘
```

Start with 3 real quotes from the Telegram community (with permission). Never fake.

### 4.11 FAQ (accordion)

10 questions, pure CSS `<details>/<summary>` — no JS needed:

1. What is Reverse Hunt?
2. How fast do signals arrive?
3. Do you execute trades on my behalf?
4. What happens if I cancel?
5. Why Binance first? When Bybit / KuCoin / OKX?
6. Can I use my own exchange API key?
7. Is the bot's performance verifiable?
8. What's the PREDATOR regime engine?
9. How does device fingerprinting work?
10. Who's behind Anunnaki World?

### 4.12 Footer CTA

```
┌────────────────────────────────────────────────────────────────────────┐
│        Ready to trade with institutional-grade intelligence?           │
│                    [Start Free — no card needed]                       │
│                                                                        │
│  Product         Resources        Company          Connect             │
│  — Features      — Whitepaper     — About          — Telegram          │
│  — Pricing       — Blog (soon)    — Contact        — Twitter/X         │
│  — Roadmap       — API Docs       — Legal          — GitHub            │
│                                                                        │
│  © 2026 Anunnaki World · Terms · Privacy · Risk Disclaimer             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. SEO Plan

### 5.1 Meta tags (per-page)

```html
<title>Anunnaki World — Institutional-Grade Crypto Trading Signals | 538 Binance Perps</title>
<meta name="description" content="Real-time AI signals on 538 Binance USDT-perp pairs. PREDATOR regime engine, liquidation heatmap, copy-trading. No custody, read-only API keys. Start free.">
<meta name="keywords" content="crypto signals, binance futures signals, trading bot, liquidation heatmap, reverse hunt, usdt dominance, copy trading">
<link rel="canonical" href="https://anunnakiworld.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Anunnaki World">
<meta property="og:title" content="Institutional-Grade Crypto Trading Signals">
<meta property="og:description" content="AI scanning 538 Binance perps · Liquidation heatmap · Copy-trading · No custody">
<meta property="og:image" content="https://anunnakiworld.com/static/og-marketing.png">
<meta name="twitter:card" content="summary_large_image">
```

### 5.2 JSON-LD structured data

Three schemas embedded in marketing.html `<head>`:

1. **`SoftwareApplication`** — product with `aggregateRating`, `offers` array (pricing tiers).
2. **`Organization`** — logo, sameAs links to Telegram / Twitter.
3. **`FAQPage`** — all 10 FAQ Q&As (wins FAQ-rich snippets in Google SERP).

### 5.3 `sitemap.xml` + `robots.txt`

New file `marketing_routes.py`:

```python
@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    urls = [
        ("/", "daily", "1.0"),
        ("/pricing", "weekly", "0.9"),
        ("/roadmap", "weekly", "0.7"),
        ("/features", "weekly", "0.8"),
        ("/whitepaper", "monthly", "0.6"),
    ]
    xml = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    for path, freq, prio in urls:
        xml += f'<url><loc>https://anunnakiworld.com{path}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>'
    xml += '</urlset>'
    return Response(content=xml, media_type="application/xml")

@app.get("/robots.txt", response_class=Response)
async def robots():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /app\n"
        "Disallow: /admin\n"
        "Sitemap: https://anunnakiworld.com/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")
```

### 5.4 Semantic HTML

Marketing page uses proper landmarks:
- `<header>` with `<nav>` for top bar
- `<main>` wrapping all content
- `<section>` per block with `aria-labelledby`
- `<h1>` only in hero; `<h2>` for section headers
- `<article>` per feature card and testimonial
- `<footer>` with `<nav>` for footer links

### 5.5 Performance targets

| Metric | Current `/` | Target marketing `/` |
|---|---|---|
| HTML size | 58 KB | 35 KB |
| CSS size | 82 KB | 28 KB |
| JS size (parsed) | 1.1 MB | 40 KB |
| LCP | 3.2 s | < 1.2 s |
| CLS | 0.14 | < 0.05 |
| Lighthouse | 54 | 95+ |

---

## 6. New Public API Endpoints (lightweight)

All read-only, cached, no auth, suitable for marketing page:

| Endpoint | Payload | Cache | Purpose |
|---|---|---|---|
| `/api/public/stats` | `{pairs, signals_total, win_rate, avg_return}` | 60 s | Hero stats bar |
| `/api/public/ticker` | Last 20 closed signals (pair/dir/pnl/ts, anonymized) | 15 s | Live signal ticker |
| `/api/public/site` | Existing — maintenance + client IP | unchanged | Already used |

Implementation in new file `dashboard/public_routes.py` to avoid bloating `app.py`.

---

## 7. Implementation Phases

### Phase 1 — Skeleton split (2 days)

1. Create `marketing.html` with just:
   - Header + hero + pricing + roadmap + exchanges (copied verbatim from current index.html)
   - Auth modal reused from index.html
2. Create `marketing.css` with minimal tokens (no `premium.css` dependency)
3. Create `marketing.js` (theme toggle + anchor smooth-scroll only)
4. Add FastAPI route logic: `/` → marketing or redirect `/app`
5. Rename main dashboard route to `/app`
6. Update all internal links (`window.location.href = '/'` → `'/app'` where appropriate)
7. Test: logged-out `/` → marketing; logged-in `/` → `/app`; direct `/app` without auth → modal opens.

### Phase 2 — Polish + SEO (2 days)

1. Rewrite hero copy + CTA button (conversion-focused)
2. Add live signal ticker (new `/api/public/ticker` endpoint)
3. Add real stats to stats bar (new `/api/public/stats` endpoint)
4. Add "How it works" section with screenshots (MP4/GIF)
5. Add features grid with 6 cards
6. Add FAQ accordion (pure CSS)
7. Add JSON-LD structured data
8. Add sitemap.xml + robots.txt
9. Create 1200×630 OG image

### Phase 3 — Dedicated per-feature pages (optional, 1–2 days)

1. `/features/predator` — deep dive on PREDATOR regime engine
2. `/features/heatmap` — liquidation heatmap explained
3. `/features/copy-trading` — Binance copy-trading deep dive
4. `/features/reverse-hunt` — methodology + backtests

Each is its own HTML file targeting a long-tail SEO keyword.

### Phase 4 — Testimonials + trust (1 day, ongoing)

1. Collect 3 testimonial quotes from Telegram community (with permission)
2. Add "As seen on" or "Used by traders in X countries" trust line
3. Add compliance / security badges (SSL, etc.)

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Returning users bookmark `/` and lose dashboard muscle memory | High | Low | Auto-redirect logged-in → `/app` makes this invisible to them. |
| Auth flow breaks (modal on `/` redirects to `/app`) | Medium | Medium | Test matrix: `/?redirect=admin`, `/?ref=XYZ`, `/?verify-email=...` all must work. |
| Stylesheet drift — marketing + app diverge visually | Medium | Low | Shared `tokens.css` for colors, fonts, spacing. Visual-regression snapshot test recommended. |
| SEO takes 2–4 weeks to materialize | High | Low | Expected. Not a reason to delay. |
| Marketing page ticker/stats endpoints expose sensitive data | Low | Medium | Hard-code response shape to anonymize: no user IDs, no exact entry prices, only aggregate win rate and pair/direction/PnL-% for ticker. |
| Build breaks during phase 1 skeleton | Low | High | Deploy behind a feature flag: `ENABLE_MARKETING_SPLIT=true` env var; fallback to current behavior if false. |

---

## 9. Open Questions for Operator

1. **Copy voice** — Should hero copy stay current ("Where Smart Money Meets Smart Signals") or move to a more technical-analyst tone ("Institutional-grade crypto derivatives intelligence")?
2. **Testimonials** — OK to reach out to 3 Telegram-channel subscribers for quotes?
3. **Demo videos** — Record yourself or use anonymized screen recordings of a real account? (I'd recommend screen recordings of a throwaway test account.)
4. **Domain strategy** — Stay on `anunnakiworld.com/` for both marketing and app, or split into `www.anunnakiworld.com` + `app.anunnakiworld.com`? (Single domain is simpler, two domains is cleaner long-term.)
5. **Analytics** — Add Plausible or PostHog for conversion funnel tracking? (GDPR-friendly, no cookies.)
6. **Feature flag rollout** — Ship to 10% of visitors first via `ENABLE_MARKETING_SPLIT` header, measure conversion delta, then 100%?
7. **Whitepaper page** — Is current `/static/whitepaper.html` already where you want it, or should it also get marketing-page styling?

---

## 10. Files Changed Summary

### New files (approximate line counts)

```
dashboard/marketing.html                    ~900 lines
dashboard/marketing_routes.py               ~60 lines
dashboard/public_routes.py                  ~80 lines
dashboard/static/css/tokens.css             ~80 lines
dashboard/static/css/marketing.css          ~800 lines
dashboard/static/js/marketing.js            ~150 lines
dashboard/static/og-marketing.png           (image)
dashboard/static/demo/*.mp4                 (3 videos, <1 MB each)
```

### Files modified

```
dashboard/app.py                            + ~40 lines (routes)
dashboard/index.html                        - ~500 lines (remove marketing blocks)
dashboard/static/css/main.css               - ~100 lines (remove landing-only rules)
dashboard/static/css/premium.css            - ~200 lines (remove landing-only rules)
dashboard/static/js/app-r7.js               - ~50 lines (remove landing init branch)
```

### Net change

- ~+2,100 new lines
- ~-850 old lines removed
- **+1,250 net** — but spread across concerns, each file now has a single job.

---

## 11. Not Doing (explicit non-goals)

- Not rebuilding the dashboard UX. `/app` behaves exactly as today.
- Not changing pricing, tiers, or payment flow.
- Not changing signal generation, ML, or any trading logic.
- Not changing the admin panel at `/admin`.
- Not touching the Telegram bots.
- Not changing auth (email/username login, JWT, device fingerprinting — all stay).

---

## 12. Recommendation

**Approve Phase 1 only** to start. It's 2 days of work, no functional change to the bot or dashboard, and it gives us a clean foundation to iterate marketing content on without breaking the app.

If Phase 1 ships and reads well, approve Phase 2 for the SEO + conversion polish work. Phase 3 (dedicated feature pages) and Phase 4 (testimonials) are lower priority and can wait.

**Estimated total work for full vision**: 6–8 days spread over 2–3 weeks.

**Expected outcomes after 30 days**:
- Google organic traffic: +3–8× for target keywords.
- Signup conversion rate: +30–60% (industry benchmarks for SaaS marketing-first sites).
- Lighthouse performance: 54 → 95+.
- Marketing iteration velocity: 5× faster (no more app-side collateral damage per copy change).
