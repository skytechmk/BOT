# Proposal: Production Launch Preparation
**Date:** 2026-04-13  
**Domain:** anunnakiworld.com  
**Scope:** Mobile responsiveness · Logo integration · Whitepaper

---

## Task 1 — Mobile Responsiveness

### What breaks on mobile today
| Element | Problem |
|---|---|
| `liq-canvas` + `liq-price-canvas` | Fixed `height:560px` and internal 900px width — renders tiny or overflows on phones |
| Navigation tabs | 8+ tabs overflow horizontally, no wrapping |
| Signal cards | Multi-column layout with absolute-positioned PnL — stacks badly |
| Velocity + Bias cards | Side-by-side `flex` row collapses awkwardly below ~480px |
| TP/SL suggest grid | `grid-template-columns:1fr 1fr` — side-by-side on small screens |
| Cluster table | 7-column table overflows viewport silently |
| Context bar | Items wrap but font/padding not tuned for small screens |
| Quick-pair chips | Overflow but don't scroll |

### Proposed fixes
1. **Nav tabs** — wrap into two rows on <768px, or collapse into a `<select>` dropdown on <480px
2. **Canvas height** — switch from `height:560px` to `height:min(560px, 80vw)` with a JS resize observer that re-renders on resize
3. **Cards row** — already has `flex-wrap:wrap` + `min-width:260px`, just needs `min-width:100%` on <480px via a CSS class
4. **Suggest grid** — add `@media (max-width:600px) { grid-template-columns:1fr }` 
5. **Tables** — wrap in `overflow-x:auto` container, add `min-width:560px` to table
6. **Quick-pair chips** — `overflow-x:auto; white-space:nowrap` on the container
7. **Signal cards** — stack PnL block below direction/price on mobile
8. **Global** — add `<meta name="viewport" content="width=device-width, initial-scale=1">` if missing (critical for any mobile fix to work)

**Estimated changes:** ~80–120 lines of CSS + minor HTML wrapper additions. No logic changes.  
**Risk:** LOW — CSS-only, no backend changes.

---

## Task 2 — Logo Integration

### Source file
`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/anunnaki.jpeg` (2046×1794 px, JPEG)

### Where it goes
| Location | Implementation |
|---|---|
| **Nav bar** (top-left) | `<img src="/static/logo.jpeg" style="height:32px;border-radius:6px">` next to site name |
| **Browser tab favicon** | `<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">` |
| **Whitepaper cover** | Full-width header image |
| **Login/upgrade modal** | Small centered logo above tier cards |

### Static file serving
The logo needs to be served by FastAPI. Copy `anunnaki.jpeg` to `dashboard/static/logo.jpeg` and add a `StaticFiles` mount in `app.py` if not already present.

**Estimated changes:** 3 lines in `app.py` + ~10 lines HTML. Copy command for logo.  
**Risk:** NONE — static file, no auth needed.

---

## Task 3 — Whitepaper

### PDF approach
No PDF rendering tools (`reportlab`, `weasyprint`, `wkhtmltopdf`, Chrome) are installed. Two options:

**Option A (recommended): HTML whitepaper with print CSS**
- Generate `/dashboard/static/whitepaper.html` — a standalone, beautifully styled page
- Add `@media print` CSS rules so File → Print (or Ctrl+P → Save as PDF from any browser) produces a clean, paginated PDF
- No install required, works immediately
- Served at `https://anunnakiworld.com/whitepaper`

**Option B: Install reportlab and generate programmatically**
- `pip install reportlab` — produces a true PDF file
- More control over layout but ~200 lines of Python boilerplate
- Install required (safe, well-maintained package)

### Whitepaper content outline
```
Cover page     — Logo, "ANUNNAKI Intelligence Platform", tagline, date
1. Overview    — What the platform is, who it's for
2. Data Layer  — Binance liquidation stream, VPVR, OI, funding, order book depth
3. Signal Engine — Reverse Hunt strategy, ML ensemble, conviction scoring
4. Dashboard Features
   ├── Liquidation Heatmap (with VPVR, OB depth, velocity, TP/SL suggester)
   ├── Live Signals (with real-time PnL, price ladder)
   ├── Analytics (hourly heatmap, performance stats)
   └── Pre-Signal Alerts (elite exclusive)
5. Membership Tiers — Free / Pro / Elite comparison table
6. Technology Stack — Python/Rust, XGBoost/Transformer, Binance streams
7. Risk Disclaimer — Standard "not financial advice" legal text
8. Contact / Socials
```

**Estimated effort:** 1–2 hours for a polished HTML whitepaper (Option A).  
**Risk:** NONE — static content, no system changes.

---

## Execution Plan (if approved)

| Order | Task | Time | Risk |
|---|---|---|---|
| 1 | Copy logo → `dashboard/static/`, mount StaticFiles, inject into HTML nav + favicon | 15 min | None |
| 2 | Mobile CSS fixes + viewport meta tag | 45 min | Low |
| 3 | Whitepaper HTML (Option A) | 60–90 min | None |

**Total estimated time: ~2.5 hours**

---

## What this proposal does NOT include
- Payment automation (deferred per your instruction)
- HTTPS/nginx setup (separate infra task, 30 min when ready)
- New backend features

---

## Decision

Approve to proceed, or specify changes to scope.
