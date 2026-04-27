# Proposal: SEO Growth Foundation — Pair Pages, Affiliate, Blog & FAQ
**Date**: 2026-04-25
**Priority**: HIGH
**Files affected**: `dashboard/app.py`, `dashboard/analytics.py`, `dashboard/landing.html`, `dashboard/signal_seo.html`, `dashboard/affiliate.html` (new), `dashboard/faq.html` (new), `dashboard/blog_content.py` (new), `dashboard/blog_index.html` (new), `dashboard/blog_post.html` (new)

## Problem
The current public SEO surface is still too thin to compound search traffic:

- The homepage is the only meaningful crawlable marketing asset.
- `/signals/{pair}` exists, but it is currently a thin placeholder page with no real pair-level data and no validation against unknown symbols.
- `/sitemap.xml` includes routes that should not be emphasized for search (`/app`, `/landing`) while excluding future content hubs like `/affiliate`, `/faq`, and `/blog`.
- There is no standalone crawlable editorial layer for long-tail search terms (required for durable SEO and a future AdSense application).
- The referral offer is inconsistent across the public surface:
  - `dashboard/referrals.py` credits a flat **7 bonus days** to referrer and referred user after the first verified payment.
  - `dashboard/app.py` referral landing currently markets **20% off**.
  - `dashboard/index.html` referral page markets **20% of first payment as bonus days**.

This mismatch will hurt conversion trust if traffic acquisition begins before copy is aligned.

## Proposed Changes

### File: `dashboard/analytics.py`
Add a public-safe pair summary helper to power unique, server-rendered SEO pages without exposing premium real-time internals.

```diff
+def get_public_pair_summary(pair: str, days: int = 3650, limit: int = 10) -> dict:
+    """Public-safe summary for SEO pair pages.
+
+    Only returns sanitized historical / aggregate data:
+      - total signals
+      - closed signals
+      - win rate
+      - average pnl
+      - best / worst trade
+      - latest signal timestamp / direction / outcome
+      - recent closed signal summaries
+    Does NOT expose live premium-only entry / TP / SL data.
+    """
+    conn = _get_signal_db()
+    if not conn:
+        return {"exists": False, "pair": pair}
+
+    rows = conn.execute(
+        "SELECT signal_id, pair, signal, confidence, timestamp, status, pnl, targets_hit "
+        "FROM signals WHERE pair=? AND COALESCE(signal_tier,'production')='production' "
+        "ORDER BY timestamp DESC",
+        (pair,)
+    ).fetchall()
+    conn.close()
+
+    if not rows:
+        return {"exists": False, "pair": pair}
+
+    closed = [r for r in rows if r['status'] == 'CLOSED' and r['pnl'] is not None]
+    wins = [r for r in closed if r['pnl'] > 0]
+    recent_closed = closed[:limit]
+
+    return {
+        "exists": True,
+        "pair": pair,
+        "total_signals": len(rows),
+        "closed_signals": len(closed),
+        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
+        "avg_pnl": round(sum(r['pnl'] for r in closed) / len(closed), 2) if closed else 0,
+        "best_trade": max((r['pnl'] for r in closed), default=None),
+        "worst_trade": min((r['pnl'] for r in closed), default=None),
+        "last_signal": {
+            "direction": rows[0]['signal'],
+            "status": rows[0]['status'],
+            "timestamp": rows[0]['timestamp'],
+            "confidence": round((rows[0]['confidence'] or 0) * 100, 1),
+        },
+        "recent_closed": [
+            {
+                "direction": r['signal'],
+                "timestamp": r['timestamp'],
+                "pnl": round(r['pnl'], 2),
+                "targets_hit": int(r['targets_hit'] or 0),
+            }
+            for r in recent_closed
+        ],
+    }
```

Why here:
- `analytics.py` already owns signal-history aggregation.
- Reusing it avoids inventing a second path into `signal_registry.db`.
- The helper can feed both HTML SEO pages and a future public JSON endpoint if needed.

### File: `dashboard/app.py`
Use real data in pair pages, add public content routes, clean up sitemap priorities, and mark duplicate / utility pages correctly for search engines.

```diff
 from market_classifier import (
     init_market_db, run_market_refresh_loop,
-    get_all_classifications, get_tier_labels, get_sector_labels,
+    get_all_classifications, get_tier_labels, get_sector_labels, get_pair_info,
 )
 
 from analytics import (
     get_performance_summary, get_equity_curve, get_pair_performance,
-    get_hourly_heatmap, get_daily_pnl, get_signal_breakdown,
+    get_hourly_heatmap, get_daily_pnl, get_signal_breakdown,
+    get_public_pair_summary,
     get_indicator_attribution, get_regime_performance,
 )
+
+from blog_content import BLOG_POSTS
```

Add helper normalization / validation:

```diff
+def _normalize_pair(pair: str) -> str:
+    pair = (pair or "").upper().strip()
+    return pair if pair.endswith("USDT") else f"{pair}USDT"
+
+
+def _known_public_pairs() -> set[str]:
+    known = set(_store.get("all_pairs", []))
+    if _SIGNAL_DB_PATH.exists():
+        conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
+        try:
+            rows = conn.execute("SELECT DISTINCT pair FROM signals").fetchall()
+            known.update(r[0] for r in rows)
+        finally:
+            conn.close()
+    return known
```

Replace the current thin pair page route:

```diff
 @app.get("/signals/{pair}", response_class=HTMLResponse)
 async def seo_pair_page(pair: str):
-    """Programmatic SEO page for each crypto pair."""
-    pair = pair.upper()
-    if not pair.endswith("USDT"):
-        pair += "USDT"
-
-    html_path = Path(__file__).parent / "signal_seo.html"
-    if not html_path.exists():
-        return HTMLResponse(content="<h1>Pair page not found</h1>", status_code=404)
-
-    template = html_path.read_text()
-    html = template.replace("{pair}", pair)
-    return HTMLResponse(content=html, status_code=200)
+    """Programmatic SEO page for a real monitored / traded pair only."""
+    pair = _normalize_pair(pair)
+    if pair not in _known_public_pairs():
+        raise HTTPException(status_code=404, detail="Unknown pair")
+
+    summary = await asyncio.to_thread(get_public_pair_summary, pair, 3650)
+    if not summary.get("exists"):
+        raise HTTPException(status_code=404, detail="No public data for pair")
+
+    pair_meta = get_pair_info(pair)
+    html_path = Path(__file__).parent / "signal_seo.html"
+    template = html_path.read_text()
+
+    html = (
+        template
+        .replace("__PAIR__", pair)
+        .replace("__WIN_RATE__", str(summary["win_rate"]))
+        .replace("__TOTAL_SIGNALS__", str(summary["total_signals"]))
+        .replace("__CLOSED_SIGNALS__", str(summary["closed_signals"]))
+        .replace("__AVG_PNL__", str(summary["avg_pnl"]))
+        .replace("__SECTOR__", pair_meta.get("sector", "other"))
+        .replace("__TIER__", pair_meta.get("tier", "high_risk"))
+    )
+    return HTMLResponse(content=html, status_code=200, headers={"Cache-Control": "public, max-age=300"})
```

Add public content routes:

```diff
+@app.get("/affiliate", response_class=HTMLResponse)
+async def affiliate_page():
+    html_path = Path(__file__).parent / "affiliate.html"
+    return HTMLResponse(content=html_path.read_text(), status_code=200)
+
+
+@app.get("/faq", response_class=HTMLResponse)
+async def faq_page():
+    html_path = Path(__file__).parent / "faq.html"
+    return HTMLResponse(content=html_path.read_text(), status_code=200)
+
+
+@app.get("/blog", response_class=HTMLResponse)
+async def blog_index_page():
+    html_path = Path(__file__).parent / "blog_index.html"
+    html = html_path.read_text()
+    cards = []
+    for slug, post in BLOG_POSTS.items():
+        cards.append(f'<article><h2><a href="/blog/{slug}">{post["title"]}</a></h2><p>{post["description"]}</p></article>')
+    return HTMLResponse(content=html.replace("__BLOG_CARDS__", "\n".join(cards)), status_code=200)
+
+
+@app.get("/blog/{slug}", response_class=HTMLResponse)
+async def blog_post_page(slug: str):
+    post = BLOG_POSTS.get(slug)
+    if not post:
+        raise HTTPException(status_code=404, detail="Article not found")
+    html_path = Path(__file__).parent / "blog_post.html"
+    html = html_path.read_text()
+    return HTMLResponse(content=(
+        html
+        .replace("__TITLE__", post["title"])
+        .replace("__DESCRIPTION__", post["description"])
+        .replace("__BODY__", post["body_html"])
+        .replace("__SLUG__", slug)
+    ), status_code=200)
```

Clean up sitemap priorities and add the new hubs:

```diff
-    static_routes = ["/", "/whitepaper", "/whitepaper/mk", "/app", "/landing"]
+    static_routes = ["/", "/whitepaper", "/whitepaper/mk", "/affiliate", "/faq", "/blog"]
 
     for route in static_routes:
         xml.append('  <url>')
         xml.append(f'    <loc>{base_url}{route}</loc>')
         xml.append('    <changefreq>daily</changefreq>')
         xml.append('  </url>')
+
+    for slug in BLOG_POSTS:
+        xml.append('  <url>')
+        xml.append(f'    <loc>{base_url}/blog/{slug}</loc>')
+        xml.append('    <changefreq>monthly</changefreq>')
+        xml.append('  </url>')
```

Mark duplicate / utility routes as non-indexable:

```diff
 @app.get("/ref/{code}", response_class=HTMLResponse)
 async def referral_landing(code: str):
@@
+    <meta name="robots" content="noindex,nofollow">
```

Rationale:
- `/ref/{code}` is a near-infinite set of duplicate invitation pages and should not compete in search.
- `/app` and `/landing` should not be sitemap priorities. `/landing` is a duplicate of `/` and `/app` is a SPA shell, not an SEO destination.

### File: `dashboard/signal_seo.html`
Replace the placeholder-only pair page with a true server-rendered SEO asset using real stats and structured data.

```diff
-<title>{pair} Live AI Trading Signals & Market Data — Anunnaki World</title>
-<meta name="description" content="Institutional-grade AI crypto trading signals for {pair}. View live market data, technical regime, and historical signal accuracy for {pair} Binance USDT perpetuals.">
+<title>__PAIR__ AI Signals, Win Rate & Market Profile — Anunnaki World</title>
+<meta name="description" content="Historical signal performance, market classification, and AI trading profile for __PAIR__ on Binance Futures.">
@@
-<h1>{pair} Live AI Trading Signals</h1>
-<p>Advanced algorithmic trading engine scanning <strong>{pair}</strong> ...</p>
+<h1>__PAIR__ AI Signals & Performance</h1>
+<p>Server-rendered public intelligence for __PAIR__: classification, historical signal outcomes, and recent AI trade performance.</p>
+
+<div class="stats-grid">
+  <div class="stat-card"><span>All-time signals</span><strong>__TOTAL_SIGNALS__</strong></div>
+  <div class="stat-card"><span>Closed signals</span><strong>__CLOSED_SIGNALS__</strong></div>
+  <div class="stat-card"><span>Win rate</span><strong>__WIN_RATE__%</strong></div>
+  <div class="stat-card"><span>Avg PnL</span><strong>__AVG_PNL__%</strong></div>
+</div>
+
+<div class="meta-row">
+  <span>Sector: __SECTOR__</span>
+  <span>Tier: __TIER__</span>
+</div>
+
+<section>
+  <h2>Why __PAIR__ is different</h2>
+  <p>This page uses real signal-history aggregates from the Anunnaki production registry rather than generic token copy.</p>
+</section>
+
+<section>
+  <h2>Recent closed signals</h2>
+  __RECENT_SIGNALS_TABLE__
+</section>
+
+<script type="application/ld+json">{ "@type": "BreadcrumbList", ... }</script>
+<script type="application/ld+json">{ "@type": "FAQPage", ... }</script>
```

Content rules for this page:
- Use **historical / aggregate** data only.
- Do **not** leak real-time premium entry, TP, or stop-loss values.
- 404 unknown pairs instead of generating thin content for arbitrary strings.

### File: `dashboard/landing.html`
Use the homepage more aggressively as the internal-link hub for the new crawlable content.

```diff
+<script type="application/ld+json">
+{
+  "@context": "https://schema.org",
+  "@type": "FAQPage",
+  "mainEntity": [
+    {"@type": "Question", "name": "Do I need to pay to test it?", "acceptedAnswer": {"@type": "Answer", "text": "No. The Free tier shows delayed signals so users can verify performance before paying."}},
+    {"@type": "Question", "name": "How is risk managed?", "acceptedAnswer": {"@type": "Answer", "text": "The engine uses macro risk, portfolio correlation, circuit breakers, and per-signal stop loss management."}}
+  ]
+}
+</script>
@@
+<div class="seo-hub-links">
+  <a href="/affiliate">Affiliate Program</a>
+  <a href="/faq">Full FAQ</a>
+  <a href="/blog">Learning Center</a>
+  <a href="/signals/BTCUSDT">BTCUSDT Signals</a>
+  <a href="/signals/ETHUSDT">ETHUSDT Signals</a>
+  <a href="/signals/SOLUSDT">SOLUSDT Signals</a>
+</div>
```

Why:
- Internal linking distributes authority to the new pages.
- FAQ schema turns the already-written homepage FAQ into something Google can understand.

### File: `dashboard/affiliate.html` (new)
Create a standalone, crawlable referral / affiliate landing page that matches the actual implemented reward logic.

```diff
+<!DOCTYPE html>
+<html lang="en">
+<head>
+  <title>Affiliate Program — Anunnaki World</title>
+  <meta name="description" content="Invite traders to Anunnaki World. When their first payment is verified, both of you receive 7 bonus days.">
+  <link rel="canonical" href="https://anunnakiworld.com/affiliate">
+  <script type="application/ld+json">{ "@type": "WebPage", ... }</script>
+  <script type="application/ld+json">{ "@type": "HowTo", ... }</script>
+</head>
+<body>
+  <h1>Affiliate / Referral Program</h1>
+  <p>Share your invite link. When a new trader registers through your link and completes a first verified payment, both accounts receive 7 bonus days.</p>
+  <ol>
+    <li>Create your account</li>
+    <li>Copy your personal referral link from the dashboard</li>
+    <li>Invite traders from your network</li>
+    <li>Earn 7 bonus days when their first payment is verified</li>
+  </ol>
+  <a href="/app?signup=1">Create Free Account</a>
+</body>
+</html>
```

Important business rule:
- Public copy must be aligned to the current code path in `dashboard/referrals.py`.
- If the business decision is truly **20% off** or **20% commission**, change checkout / referral-credit logic in a separate proposal first. Do not silently market an offer the backend does not grant.

### File: `dashboard/faq.html` (new)
Extract the highest-converting FAQ items into a dedicated page.

```diff
+<!DOCTYPE html>
+<html lang="en">
+<head>
+  <title>FAQ — Anunnaki World</title>
+  <meta name="description" content="Frequently asked questions about Anunnaki World AI crypto signals, copy trading, risk management, pricing, and security.">
+  <link rel="canonical" href="https://anunnakiworld.com/faq">
+  <script type="application/ld+json">{ "@type": "FAQPage", ... }</script>
+</head>
+<body>
+  <h1>Frequently Asked Questions</h1>
+  <details>...</details>
+  <details>...</details>
+  <details>...</details>
+</body>
+</html>
```

Use the same substance already present on `landing.html` so content remains consistent.

### File: `dashboard/blog_content.py` (new)
Create a central registry for crawlable articles.

```diff
+BLOG_POSTS = {
+    "what-is-funding-rate": {
+        "title": "What Is Funding Rate in Crypto Futures?",
+        "description": "A practical guide to funding rates, why they matter, and how Anunnaki uses them in signal filtering.",
+        "published": "2026-04-25",
+        "updated": "2026-04-25",
+        "body_html": "<p>...</p><h2>...</h2>",
+    },
+    "binance-futures-risk-management-guide": {
+        "title": "Binance Futures Risk Management Guide",
+        "description": "How to size trades, use stop losses, and avoid liquidation when trading perps.",
+        "published": "2026-04-25",
+        "updated": "2026-04-25",
+        "body_html": "<p>...</p>",
+    },
+    "how-take-profit-ladders-work": {
+        "title": "How Take-Profit Ladders Work in Crypto Trading",
+        "description": "Why staggered exits and trailing stops can outperform all-or-nothing exits.",
+        "published": "2026-04-25",
+        "updated": "2026-04-25",
+        "body_html": "<p>...</p>",
+    },
+    "copy-trading-safely": {
+        "title": "How to Use Copy Trading Safely",
+        "description": "A risk-first checklist before connecting your exchange API to any signal platform.",
+        "published": "2026-04-25",
+        "updated": "2026-04-25",
+        "body_html": "<p>...</p>",
+    },
+    "ai-crypto-signals-explained": {
+        "title": "AI Crypto Signals Explained",
+        "description": "What makes AI-assisted trade selection different from manual signal channels.",
+        "published": "2026-04-25",
+        "updated": "2026-04-25",
+        "body_html": "<p>...</p>",
+    },
+}
```

Why a registry file:
- Faster than building a CMS.
- Easy to add posts in code review.
- Lets the app build blog index, sitemap entries, and article routes from one source of truth.

### File: `dashboard/blog_index.html` (new)
Create a crawlable article hub.

```diff
+<!DOCTYPE html>
+<html lang="en">
+<head>
+  <title>Learning Center — Anunnaki World</title>
+  <meta name="description" content="Guides on crypto futures, funding rates, risk management, copy trading, and AI trading systems.">
+  <link rel="canonical" href="https://anunnakiworld.com/blog">
+</head>
+<body>
+  <h1>Learning Center</h1>
+  <p>Educational content designed to rank for intent-driven search terms and support conversion into the product.</p>
+  <section>__BLOG_CARDS__</section>
+</body>
+</html>
```

### File: `dashboard/blog_post.html` (new)
Create a reusable article template with `Article` schema.

```diff
+<!DOCTYPE html>
+<html lang="en">
+<head>
+  <title>__TITLE__ — Anunnaki World</title>
+  <meta name="description" content="__DESCRIPTION__">
+  <link rel="canonical" href="https://anunnakiworld.com/blog/__SLUG__">
+  <script type="application/ld+json">{ "@type": "Article", ... }</script>
+</head>
+<body>
+  <article>
+    <h1>__TITLE__</h1>
+    <div>__BODY__</div>
+  </article>
+  <aside>
+    <a href="/affiliate">Affiliate Program</a>
+    <a href="/faq">FAQ</a>
+    <a href="/app?signup=1">Try the platform</a>
+  </aside>
+</body>
+</html>
```

## Rollout Order
1. Add pair-summary helper and upgrade `/signals/{pair}`.
2. Create `/affiliate`, `/faq`, `/blog`, and `/blog/{slug}` routes.
3. Add the new templates / content registry.
4. Clean sitemap and noindex duplicate utility pages.
5. Add internal links + FAQ schema to `landing.html`.
6. Submit updated sitemap to Google Search Console.

## Risk Assessment
- **Premium-data leakage risk**: pair pages must stay aggregate / delayed / historical only. Do not expose live premium entry, TP, or SL data.
- **Thin-content risk**: return 404 for unknown pairs and pairs with no signal history.
- **Trust / conversion risk**: referral copy must match backend reality before paid acquisition or SEO scaling.
- **Duplicate-content risk**: avoid indexing `/landing`, `/app`, and `/ref/{code}` as primary search pages.
- **Maintenance risk**: a content registry is simple, but it still requires someone to add / update posts periodically. Five high-quality starter articles are the minimum viable base, not the final state.

## Verification
- `curl /sitemap.xml` contains `/affiliate`, `/faq`, `/blog`, `/blog/{slug}`, and real pair URLs.
- `curl /signals/BTCUSDT` returns `200` with pair-specific metrics rendered into HTML.
- `curl /signals/NOTAREALPAIRUSDT` returns `404`.
- `curl /affiliate` and `/faq` return `200` and include canonical + structured data.
- `curl /ref/ABC123` contains `noindex,nofollow`.
- Search Console inspection shows:
  - homepage indexed
  - pair pages eligible for indexing
  - blog pages recognized as articles
  - referral utility pages excluded

## Notes / Non-Goals
- This proposal intentionally does **not** change referral economics. It only aligns public SEO / marketing copy to the current implementation.
- AdSense should be considered **after** the blog/FAQ layer exists and has enough original content. The first goal is crawlable, intent-matched acquisition.
- If desired later, a second proposal can add public pair leaderboards, top sectors, and “best/worst performers this month” hub pages.
