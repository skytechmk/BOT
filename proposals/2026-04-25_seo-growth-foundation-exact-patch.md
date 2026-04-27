# Proposal: SEO Growth Foundation — Exact Patch Bundle
**Date**: 2026-04-25
**Priority**: HIGH
**Supersedes**: `proposals/2026-04-25_seo-growth-foundation.md` for implementation detail
**Files affected**: `dashboard/analytics.py`, `dashboard/app.py`, `dashboard/signal_seo.html`, `dashboard/landing.html`, `dashboard/index.html`, `dashboard/referrals.py`, `dashboard/affiliate.html` (new), `dashboard/faq.html` (new), `dashboard/blog_content.py` (new), `dashboard/blog_index.html` (new), `dashboard/blog_post.html` (new)

## Purpose
This is the operator-ready version of the SEO proposal. It converts the high-level plan into concrete code blocks and exact replace targets, while keeping with the S.P.E.C.T.R.E. maintenance rule that proposals are reviewed and applied by the operator from the IDE.

## Apply Order
1. Create new files: `blog_content.py`, `affiliate.html`, `faq.html`, `blog_index.html`, `blog_post.html`
2. Update `analytics.py`
3. Update `app.py`
4. Replace `signal_seo.html`
5. Update `landing.html`
6. Update `index.html`
7. Update `referrals.py`
8. Restart `anunnaki-dashboard`

## 1) Update `dashboard/analytics.py`
Insert the following function **after** `get_pair_performance()` and **before** `get_hourly_heatmap()`.

```python
def get_public_pair_summary(pair: str, limit: int = 8) -> dict:
    """Public-safe aggregate summary for a single pair.

    Designed for SEO pages only. Returns historical / aggregate data and does
    not expose live premium entry, TP, or stop-loss levels.
    """
    conn = _get_signal_db()
    if not conn:
        return {"exists": False, "pair": pair}

    try:
        live_rows = conn.execute(
            "SELECT signal_id, pair, signal, confidence, timestamp, status, pnl, targets_hit "
            "FROM signals WHERE pair=? AND COALESCE(signal_tier,'production')='production'",
            (pair,)
        ).fetchall()
        try:
            archived_rows = conn.execute(
                "SELECT signal_id, pair, signal, confidence, timestamp, status, pnl, targets_hit "
                "FROM archived_signals WHERE pair=? AND COALESCE(signal_tier,'production')='production'",
                (pair,)
            ).fetchall()
        except sqlite3.Error:
            archived_rows = []
    finally:
        conn.close()

    rows = sorted(list(live_rows) + list(archived_rows), key=lambda r: r['timestamp'], reverse=True)
    if not rows:
        return {"exists": False, "pair": pair}

    closed = [r for r in rows if r['status'] == 'CLOSED' and r['pnl'] is not None]
    wins = [r for r in closed if r['pnl'] > 0]
    best_trade = max(closed, key=lambda r: r['pnl']) if closed else None
    worst_trade = min(closed, key=lambda r: r['pnl']) if closed else None
    latest = rows[0]

    recent_closed = []
    for r in closed[:limit]:
        ts_utc = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
        recent_closed.append({
            "direction": r['signal'],
            "timestamp": r['timestamp'],
            "time_local": ts_utc.strftime('%d %b %H:%M UTC'),
            "pnl": round(r['pnl'], 2),
            "targets_hit": int(r['targets_hit'] or 0),
        })

    return {
        "exists": True,
        "pair": pair,
        "total_signals": len(rows),
        "closed_signals": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_pnl": round(sum(r['pnl'] for r in closed) / len(closed), 2) if closed else 0,
        "best_trade": round(best_trade['pnl'], 2) if best_trade else None,
        "worst_trade": round(worst_trade['pnl'], 2) if worst_trade else None,
        "last_signal": {
            "direction": latest['signal'],
            "status": latest['status'],
            "timestamp": latest['timestamp'],
            "confidence": round((latest['confidence'] or 0) * 100, 1),
        },
        "recent_closed": recent_closed,
    }
```

## 2) Update `dashboard/app.py`

### 2.1 Import changes

Replace the first import line:

```diff
-import sys, os, json, time, asyncio, sqlite3, logging, urllib.request
+import sys, os, json, time, asyncio, sqlite3, logging, urllib.request, html
```

Update analytics imports:

```diff
 from analytics import (
     get_performance_summary, get_equity_curve, get_pair_performance,
     get_hourly_heatmap, get_daily_pnl, get_signal_breakdown,
-    get_indicator_attribution, get_regime_performance,
+    get_indicator_attribution, get_regime_performance,
+    get_public_pair_summary,
 )
```

Update market classifier imports:

```diff
 from market_classifier import (
     init_market_db, run_market_refresh_loop,
-    get_all_classifications, get_tier_labels, get_sector_labels,
+    get_all_classifications, get_tier_labels, get_sector_labels, get_pair_info,
 )
```

Add a new import below the dashboard-module import section:

```python
from blog_content import BLOG_POSTS
```

### 2.2 Add helper functions
Add these helpers **after** the `_STREAM_TOKEN` block and before route declarations.

```python
def _normalize_pair(pair: str) -> str:
    pair = (pair or "").upper().strip()
    if not pair:
        return ""
    return pair if pair.endswith("USDT") else f"{pair}USDT"


def _known_public_pairs() -> set:
    if not _SIGNAL_DB_PATH.exists():
        return set()
    conn = sqlite3.connect(f"file:{_SIGNAL_DB_PATH}?mode=ro", uri=True)
    try:
        pairs = set()
        rows = conn.execute(
            "SELECT DISTINCT pair FROM signals WHERE COALESCE(signal_tier,'production')='production'"
        ).fetchall()
        pairs.update(r[0] for r in rows if r and r[0])
        try:
            archived = conn.execute(
                "SELECT DISTINCT pair FROM archived_signals WHERE COALESCE(signal_tier,'production')='production'"
            ).fetchall()
            pairs.update(r[0] for r in archived if r and r[0])
        except sqlite3.Error:
            pass
        return pairs
    finally:
        conn.close()


def _render_public_pair_rows(rows) -> str:
    if not rows:
        return '<p class="table-empty">No closed production signals have been recorded for this pair yet.</p>'

    out = [
        '<table class="recent-table">',
        '<thead><tr><th>Time</th><th>Direction</th><th>Targets Hit</th><th>PnL</th></tr></thead>',
        '<tbody>',
    ]
    for row in rows:
        pnl = float(row.get("pnl", 0) or 0)
        pnl_class = "pnl-pos" if pnl > 0 else "pnl-neg" if pnl < 0 else "pnl-flat"
        out.append(
            "<tr>"
            f"<td>{html.escape(row.get('time_local', '—'))}</td>"
            f"<td>{html.escape(str(row.get('direction', '—')))}</td>"
            f"<td>{int(row.get('targets_hit', 0) or 0)}</td>"
            f"<td class=\"{pnl_class}\">{pnl:.2f}%</td>"
            "</tr>"
        )
    out.append('</tbody></table>')
    return ''.join(out)
```

### 2.3 Replace `/signals/{pair}` route
Replace the existing route block at lines `963-976` with:

```python
@app.get("/signals/{pair}", response_class=HTMLResponse)
async def seo_pair_page(pair: str):
    """Programmatic SEO page for a real tracked pair with public-safe stats."""
    pair = _normalize_pair(pair)
    if not pair:
        raise HTTPException(status_code=404, detail="Unknown pair")

    known_pairs = _known_public_pairs()
    if pair not in known_pairs:
        raise HTTPException(status_code=404, detail="Unknown pair")

    summary = await asyncio.to_thread(get_public_pair_summary, pair, 8)
    if not summary.get("exists"):
        raise HTTPException(status_code=404, detail="No public data for pair")

    pair_meta = get_pair_info(pair)
    last_signal = summary.get("last_signal") or {}
    recent_rows_html = _render_public_pair_rows(summary.get("recent_closed") or [])

    html_path = Path(__file__).parent / "signal_seo.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Pair page not found</h1>", status_code=404)

    template = html_path.read_text()
    page_html = (
        template
        .replace("__PAIR__", html.escape(pair))
        .replace("__WIN_RATE__", f"{float(summary.get('win_rate', 0) or 0):.1f}")
        .replace("__TOTAL_SIGNALS__", str(int(summary.get("total_signals", 0) or 0)))
        .replace("__CLOSED_SIGNALS__", str(int(summary.get("closed_signals", 0) or 0)))
        .replace("__AVG_PNL__", f"{float(summary.get('avg_pnl', 0) or 0):.2f}")
        .replace("__BEST_TRADE__", "—" if summary.get("best_trade") is None else f"{float(summary['best_trade']):.2f}%")
        .replace("__WORST_TRADE__", "—" if summary.get("worst_trade") is None else f"{float(summary['worst_trade']):.2f}%")
        .replace("__SECTOR__", html.escape(str(pair_meta.get("sector", "other"))))
        .replace("__TIER__", html.escape(str(pair_meta.get("tier", "high_risk"))))
        .replace("__RANK__", "—" if pair_meta.get("rank") is None else str(pair_meta.get("rank")))
        .replace("__HOT_STATUS__", "HOT" if pair_meta.get("is_hot") else "Stable")
        .replace("__LAST_SIGNAL_DIRECTION__", html.escape(str(last_signal.get("direction", "—"))))
        .replace("__LAST_SIGNAL_STATUS__", html.escape(str(last_signal.get("status", "—"))))
        .replace("__LAST_SIGNAL_CONFIDENCE__", f"{float(last_signal.get('confidence', 0) or 0):.1f}")
        .replace("__RECENT_SIGNALS_TABLE__", recent_rows_html)
    )
    return HTMLResponse(content=page_html, status_code=200, headers={"Cache-Control": "public, max-age=300"})
```

### 2.4 Add public content routes
Insert these routes **between** `/signals/{pair}` and `/robots.txt`.

```python
@app.get("/affiliate", response_class=HTMLResponse)
async def affiliate_page():
    html_path = Path(__file__).parent / "affiliate.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Affiliate page coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/faq", response_class=HTMLResponse)
async def faq_page():
    html_path = Path(__file__).parent / "faq.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>FAQ coming soon</h1>", status_code=200)
    return HTMLResponse(content=html_path.read_text(), status_code=200)


@app.get("/blog", response_class=HTMLResponse)
async def blog_index_page():
    html_path = Path(__file__).parent / "blog_index.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Blog coming soon</h1>", status_code=200)

    cards = []
    for slug, post in BLOG_POSTS.items():
        cards.append(
            '<article class="post-card">'
            f'<div class="post-date">{html.escape(post.get("published", ""))}</div>'
            f'<h2><a href="/blog/{slug}">{html.escape(post["title"])}</a></h2>'
            f'<p>{html.escape(post["description"])}</p>'
            f'<a class="post-link" href="/blog/{slug}">Read article →</a>'
            '</article>'
        )

    template = html_path.read_text()
    return HTMLResponse(content=template.replace("__BLOG_CARDS__", "\n".join(cards)), status_code=200)


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post_page(slug: str):
    post = BLOG_POSTS.get(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Article not found")

    html_path = Path(__file__).parent / "blog_post.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Article template missing</h1>", status_code=500)

    template = html_path.read_text()
    page_html = (
        template
        .replace("__TITLE__", html.escape(post["title"]))
        .replace("__DESCRIPTION__", html.escape(post["description"]))
        .replace("__PUBLISHED__", html.escape(post.get("published", "")))
        .replace("__UPDATED__", html.escape(post.get("updated", post.get("published", ""))))
        .replace("__SLUG__", html.escape(slug))
        .replace("__BODY__", post["body_html"])
    )
    return HTMLResponse(content=page_html, status_code=200)
```

### 2.5 Replace `sitemap_xml()`
Replace the entire existing sitemap function with:

```python
@app.get("/sitemap.xml")
async def sitemap_xml():
    """Dynamic sitemap for public landing, content hubs, articles, and pair pages."""
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    base_url = "https://anunnakiworld.com"
    static_routes = ["/", "/whitepaper", "/whitepaper/mk", "/affiliate", "/faq", "/blog"]

    for route in static_routes:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}{route}</loc>')
        xml.append('    <changefreq>weekly</changefreq>')
        xml.append('  </url>')

    for slug in BLOG_POSTS.keys():
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}/blog/{slug}</loc>')
        xml.append('    <changefreq>monthly</changefreq>')
        xml.append('  </url>')

    try:
        for pair in sorted(_known_public_pairs()):
            xml.append('  <url>')
            xml.append(f'    <loc>{base_url}/signals/{pair}</loc>')
            xml.append('    <changefreq>weekly</changefreq>')
            xml.append('  </url>')
    except Exception as e:
        logger.warning(f"[sitemap] Failed to build pair URLs: {e}")

    xml.append('</urlset>')
    return Response(content='\n'.join(xml), media_type="application/xml")
```

### 2.6 Update referral landing route copy + `noindex`
Replace the existing `referral_landing()` route block with:

```python
@app.get("/ref/{code}", response_class=HTMLResponse)
async def referral_landing(code: str):
    """
    Shareable referral URL with social OG preview cards.
    Shows the current referral offer, then redirects to /?ref=code.
    This route is a utility/share page and should not be indexed.
    """
    safe_code = code.strip().upper()[:12]
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex,nofollow">
    <title>You've been invited to Anunnaki World Signals</title>

    <meta property="og:type"        content="website">
    <meta property="og:url"         content="https://anunnakiworld.com/ref/{safe_code}">
    <meta property="og:title"       content="🎁 Get 7 Bonus Days — Anunnaki World Signals">
    <meta property="og:description" content="You've been personally invited. Create your account through this link and, after the first verified payment, both you and the referrer receive 7 bonus days.">
    <meta property="og:image"       content="https://anunnakiworld.com/static/logo.jpeg">
    <meta property="og:site_name"   content="Anunnaki World Signals">

    <meta name="twitter:card"        content="summary">
    <meta name="twitter:title"       content="🎁 Get 7 Bonus Days — Anunnaki World Signals">
    <meta name="twitter:description" content="Join through this invite link and both accounts receive 7 bonus days after the first verified payment.">
    <meta name="twitter:image"       content="https://anunnakiworld.com/static/logo.jpeg">

    <meta http-equiv="refresh" content="0;url=/?ref={safe_code}">
    <style>
        body {{ margin:0; background:#0d0d0f; color:#fff; font-family:Inter,sans-serif;
               display:flex; align-items:center; justify-content:center; height:100vh; }}
        .card {{ text-align:center; max-width:460px; padding:40px 32px;
                 background:#141416; border:1px solid #2a2a2e; border-radius:16px; }}
        .logo {{ width:72px; height:72px; border-radius:14px; margin-bottom:20px; }}
        h1 {{ font-size:22px; margin:0 0 10px; }}
        p {{ font-size:14px; color:#888; line-height:1.6; margin:0 0 24px; }}
        .badge {{ display:inline-block; background:rgba(0,200,83,.12);
                  color:#00c853; font-size:13px; font-weight:700;
                  padding:6px 16px; border-radius:20px; margin-bottom:20px; }}
        a {{ display:inline-block; background:#00c853; color:#000;
             font-weight:700; font-size:14px; padding:12px 28px;
             border-radius:10px; text-decoration:none; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/logo.jpeg" alt="Anunnaki World" class="logo">
        <div class="badge">🎁 Special Invite</div>
        <h1>You've been invited!</h1>
        <p>Join Anunnaki World through this invite link. After your <strong style="color:#fff">first verified payment</strong>, both you and the referrer receive <strong style="color:#fff">7 bonus days</strong>.</p>
        <a href="/?ref={safe_code}">Accept Invite →</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_doc)
```

## 3) Replace `dashboard/signal_seo.html`
Replace the **entire file** with this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05080F">
<title>__PAIR__ AI Signals, Win Rate & Market Profile — Anunnaki World</title>
<meta name="description" content="Historical AI signal performance, market classification, and recent trade outcomes for __PAIR__ on Binance Futures.">
<meta name="keywords" content="__PAIR__ crypto signals, __PAIR__ binance futures, __PAIR__ AI trading, __PAIR__ perpetual futures">
<link rel="canonical" href="https://anunnakiworld.com/signals/__PAIR__">
<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">
<meta property="og:type" content="website">
<meta property="og:url" content="https://anunnakiworld.com/signals/__PAIR__">
<meta property="og:title" content="__PAIR__ AI Signals & Market Profile — Anunnaki World">
<meta property="og:description" content="Public historical signal performance and AI market profile for __PAIR__.">
<meta property="og:image" content="https://anunnakiworld.com/static/og-banner.png">
<meta name="twitter:card" content="summary_large_image">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Orbitron:wght@600;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/css/premium.css">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "__PAIR__ AI Signals & Market Profile",
  "description": "Historical signal performance and market classification for __PAIR__.",
  "publisher": {
    "@type": "Organization",
    "name": "Anunnaki World",
    "url": "https://anunnakiworld.com"
  }
}
</script>
<style>
:root { --text:#E5E7EB; --text-dim:#94A3B8; --hairline:rgba(255,255,255,0.06); --gold:#E4C375; --green:#22c55e; --red:#ef4444; }
body { margin:0; font-family:'Inter',sans-serif; background:#05080F; color:var(--text); line-height:1.6; }
.container { max-width:980px; margin:0 auto; padding:0 24px; }
.nav { display:flex; justify-content:space-between; align-items:center; padding:24px 0; border-bottom:1px solid var(--hairline); }
.nav a { color:var(--text); text-decoration:none; font-weight:600; }
.hero { padding:80px 0 48px; text-align:center; }
.hero h1 { font-family:'Orbitron',sans-serif; font-size:clamp(34px,5vw,60px); margin:0 0 16px; background:linear-gradient(135deg,#fff 0%,#E4C375 100%); -webkit-background-clip:text; background-clip:text; color:transparent; }
.hero p { font-size:18px; color:var(--text-dim); max-width:720px; margin:0 auto 24px; }
.stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin:36px 0; }
.stat-card,.card { background:rgba(255,255,255,0.02); border:1px solid var(--hairline); border-radius:16px; padding:24px; }
.stat-card span { display:block; font-size:12px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.08em; margin-bottom:10px; }
.stat-card strong { font-size:30px; font-weight:800; }
.meta-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin:0 0 24px; }
.meta-grid .card strong { color:var(--gold); }
.section-title { font-family:'Orbitron',sans-serif; font-size:24px; margin:0 0 14px; }
.card + .card { margin-top:18px; }
.recent-table { width:100%; border-collapse:collapse; }
.recent-table th,.recent-table td { padding:12px 10px; border-bottom:1px solid var(--hairline); text-align:left; font-size:14px; }
.recent-table th { color:var(--text-dim); font-weight:600; }
.pnl-pos { color:var(--green); font-weight:700; }
.pnl-neg { color:var(--red); font-weight:700; }
.pnl-flat { color:var(--text-dim); font-weight:700; }
.table-empty { color:var(--text-dim); margin:0; }
.cta { display:inline-block; margin-top:12px; background:var(--gold); color:#000; text-decoration:none; padding:14px 24px; border-radius:10px; font-weight:800; }
footer { text-align:center; padding:44px 0; color:var(--text-dim); border-top:1px solid var(--hairline); margin-top:56px; }
</style>
</head>
<body>
<div class="container">
  <header class="nav">
    <a href="/">Anunnaki World</a>
    <a href="/app">Launch App</a>
  </header>

  <section class="hero">
    <h1>__PAIR__ AI Signals & Market Profile</h1>
    <p>Public historical performance, pair classification, and recent production signal outcomes for <strong>__PAIR__</strong>.</p>

    <div class="stats-grid">
      <div class="stat-card"><span>All-time signals</span><strong>__TOTAL_SIGNALS__</strong></div>
      <div class="stat-card"><span>Closed signals</span><strong>__CLOSED_SIGNALS__</strong></div>
      <div class="stat-card"><span>Win rate</span><strong>__WIN_RATE__%</strong></div>
      <div class="stat-card"><span>Avg PnL</span><strong>__AVG_PNL__%</strong></div>
    </div>
  </section>

  <div class="meta-grid">
    <div class="card"><span>Sector</span><br><strong>__SECTOR__</strong></div>
    <div class="card"><span>Tier</span><br><strong>__TIER__</strong></div>
    <div class="card"><span>Market-cap rank</span><br><strong>__RANK__</strong></div>
    <div class="card"><span>Momentum label</span><br><strong>__HOT_STATUS__</strong></div>
  </div>

  <div class="meta-grid">
    <div class="card"><span>Last signal direction</span><br><strong>__LAST_SIGNAL_DIRECTION__</strong></div>
    <div class="card"><span>Last signal status</span><br><strong>__LAST_SIGNAL_STATUS__</strong></div>
    <div class="card"><span>Last signal confidence</span><br><strong>__LAST_SIGNAL_CONFIDENCE__%</strong></div>
    <div class="card"><span>Best / worst trade</span><br><strong>__BEST_TRADE__ / __WORST_TRADE__</strong></div>
  </div>

  <div class="card">
    <h2 class="section-title">Why this page exists</h2>
    <p>This page is intentionally server-rendered and based on historical production data so search engines can index something real, not a blank SPA shell. It does not expose live premium entry, stop-loss, or target data.</p>
  </div>

  <div class="card">
    <h2 class="section-title">Recent closed production signals</h2>
    __RECENT_SIGNALS_TABLE__
  </div>

  <div class="card">
    <h2 class="section-title">Follow __PAIR__ inside the dashboard</h2>
    <p>Create a free account to monitor delayed signal history, then upgrade only if the data convinces you.</p>
    <a href="/app?signup=1" class="cta">Create Free Account</a>
  </div>

  <footer>
    &copy; 2026 Anunnaki World. All rights reserved. <a href="/" style="color:var(--text-dim);text-decoration:underline;">Back to Home</a>
  </footer>
</div>
</body>
</html>
```

## 4) Create `dashboard/affiliate.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05080F">
<title>Affiliate Program — Anunnaki World</title>
<meta name="description" content="Invite traders to Anunnaki World. When their first payment is verified, both of you receive 7 bonus days.">
<link rel="canonical" href="https://anunnakiworld.com/affiliate">
<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Orbitron:wght@600;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/css/premium.css">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Anunnaki World Affiliate Program",
  "description": "Invite traders and both accounts receive 7 bonus days after the first verified payment."
}
</script>
<style>
:root { --text:#E5E7EB; --text-dim:#94A3B8; --hairline:rgba(255,255,255,0.06); --gold:#E4C375; }
body { margin:0; font-family:'Inter',sans-serif; background:#05080F; color:var(--text); }
.container { max-width:960px; margin:0 auto; padding:0 24px; }
.hero { padding:96px 0 48px; text-align:center; }
.hero h1 { font-family:'Orbitron',sans-serif; font-size:clamp(36px,5vw,62px); margin:0 0 16px; }
.hero p { max-width:720px; margin:0 auto 26px; color:var(--text-dim); font-size:18px; line-height:1.7; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin:32px 0; }
.card { background:rgba(255,255,255,0.02); border:1px solid var(--hairline); border-radius:16px; padding:24px; }
.cta { display:inline-block; margin-top:12px; background:var(--gold); color:#000; text-decoration:none; padding:14px 24px; border-radius:10px; font-weight:800; }
footer { text-align:center; padding:42px 0; color:var(--text-dim); border-top:1px solid var(--hairline); margin-top:56px; }
</style>
</head>
<body>
<div class="container">
  <section class="hero">
    <h1>Affiliate / Referral Program</h1>
    <p>Share your invite link. When a new trader joins through your link and completes a first verified payment, <strong>both accounts receive 7 bonus days</strong>.</p>
    <a href="/app?signup=1" class="cta">Create Free Account</a>
  </section>

  <div class="grid">
    <div class="card"><h2>1. Create your account</h2><p>Open a free account and access your personal referral link from the dashboard.</p></div>
    <div class="card"><h2>2. Share your link</h2><p>Post it in trading communities, private groups, or social channels where it is relevant.</p></div>
    <div class="card"><h2>3. First verified payment</h2><p>Once the referred user completes a first verified payment, the referral is credited automatically.</p></div>
    <div class="card"><h2>4. Both receive bonus days</h2><p>The referrer gets 7 bonus days and the referred trader also receives 7 bonus days.</p></div>
  </div>

  <div class="card">
    <h2>Important note</h2>
    <p>This page intentionally mirrors the current platform logic exactly. It does not market percentage discounts or percentage commissions that are not granted by the backend.</p>
  </div>

  <footer>
    &copy; 2026 Anunnaki World. <a href="/" style="color:var(--text-dim)">Back to Home</a>
  </footer>
</div>
</body>
</html>
```

## 5) Create `dashboard/faq.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05080F">
<title>FAQ — Anunnaki World</title>
<meta name="description" content="Frequently asked questions about Anunnaki World AI crypto signals, copy trading, pricing, and risk management.">
<link rel="canonical" href="https://anunnakiworld.com/faq">
<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Orbitron:wght@600;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/css/premium.css">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {"@type":"Question","name":"Do I need to pay first to verify performance?","acceptedAnswer":{"@type":"Answer","text":"No. The Free tier shows delayed signals so performance can be verified before paying."}},
    {"@type":"Question","name":"Does copy trading require withdrawal permissions?","acceptedAnswer":{"@type":"Answer","text":"No. Only futures-trading scope is needed. Withdraw permission is never required."}},
    {"@type":"Question","name":"What timeframes does the system trade?","acceptedAnswer":{"@type":"Answer","text":"Primary signal generation runs on 1h with 15m and 4h confirmations."}},
    {"@type":"Question","name":"How is risk managed?","acceptedAnswer":{"@type":"Answer","text":"Through macro risk filters, portfolio correlation limits, circuit breakers, and per-signal stop-loss logic."}}
  ]
}
</script>
<style>
:root { --text:#E5E7EB; --text-dim:#94A3B8; --hairline:rgba(255,255,255,0.06); --gold:#E4C375; }
body { margin:0; font-family:'Inter',sans-serif; background:#05080F; color:var(--text); }
.container { max-width:900px; margin:0 auto; padding:0 24px; }
.hero { padding:84px 0 36px; text-align:center; }
.hero h1 { font-family:'Orbitron',sans-serif; font-size:clamp(34px,5vw,58px); margin:0 0 14px; }
.hero p { color:var(--text-dim); max-width:700px; margin:0 auto; }
details { background:rgba(255,255,255,0.02); border:1px solid var(--hairline); border-radius:14px; padding:18px 20px; margin:14px 0; }
summary { cursor:pointer; font-weight:700; }
.answer { color:var(--text-dim); line-height:1.7; margin-top:14px; }
footer { text-align:center; padding:42px 0; color:var(--text-dim); border-top:1px solid var(--hairline); margin-top:56px; }
</style>
</head>
<body>
<div class="container">
  <section class="hero">
    <h1>Frequently Asked Questions</h1>
    <p>Answers to the most common questions about Anunnaki World AI signals, copy trading, pricing, and risk management.</p>
  </section>

  <details><summary>Do I need to give you money to see if it actually works?</summary><div class="answer">No. The Free tier shows every signal we publish with a 24-hour delay — the same data used to compute public win-rate statistics.</div></details>
  <details><summary>Does copy-trading need me to send you my API keys?</summary><div class="answer">Only futures-trading scope is needed, and withdraw permission is never required.</div></details>
  <details><summary>What timeframes does the AI trade?</summary><div class="answer">Primary signal generation runs on 1h with 15m and 4h confirmations. Holding periods are typically 2–48 hours.</div></details>
  <details><summary>How is risk managed?</summary><div class="answer">Four independent layers: macro risk engine, portfolio correlation filter, circuit breaker logic, and per-signal stop loss with optional trailing.</div></details>
  <details><summary>Can I cancel any time?</summary><div class="answer">Yes. Crypto payments are settled per billing period. There are no recurring card charges.</div></details>
  <details><summary>What happens when the AI is wrong?</summary><div class="answer">It will be wrong regularly. The edge comes from risk-reward geometry, partial take-profits, and constant model feedback from closed trade history.</div></details>

  <footer>
    &copy; 2026 Anunnaki World. <a href="/" style="color:var(--text-dim)">Back to Home</a>
  </footer>
</div>
</body>
</html>
```

## 6) Create `dashboard/blog_content.py`

```python
BLOG_POSTS = {
    "what-is-funding-rate": {
        "title": "What Is Funding Rate in Crypto Futures?",
        "description": "A practical guide to funding rates, why they matter, and how Anunnaki uses them in its market filter stack.",
        "published": "2026-04-25",
        "updated": "2026-04-25",
        "body_html": """
<p>Funding rate is the periodic payment exchanged between longs and shorts in perpetual futures markets. When funding is strongly positive, long positioning is crowded. When it is strongly negative, short positioning is crowded.</p>
<h2>Why traders should care</h2>
<p>Funding is not just a cost. It is also a sentiment gauge. Extreme readings can signal one-sided positioning, which often matters for timing and risk management.</p>
<h2>How Anunnaki uses it</h2>
<p>Anunnaki treats funding as one piece of a broader positioning layer rather than a standalone trading rule. It is combined with price action, regime context, and other filters before a signal is allowed through.</p>
""",
    },
    "binance-futures-risk-management-guide": {
        "title": "Binance Futures Risk Management Guide",
        "description": "How to size trades, place stop losses, and avoid liquidation when trading perpetual futures.",
        "published": "2026-04-25",
        "updated": "2026-04-25",
        "body_html": """
<p>Most futures traders do not lose because they cannot find entries. They lose because they size too large, use too much leverage, and fail to respect stop-loss distance.</p>
<h2>Start with position sizing</h2>
<p>Decide what percentage of your account you are willing to lose if the stop is hit. Then size the trade from the stop distance, not from emotion.</p>
<h2>Respect liquidation math</h2>
<p>Higher leverage narrows your margin for error. Good risk management means surviving enough trades for edge to compound.</p>
""",
    },
    "how-take-profit-ladders-work": {
        "title": "How Take-Profit Ladders Work in Crypto Trading",
        "description": "Why staggered exits and trailing stops can be more robust than all-or-nothing exits.",
        "published": "2026-04-25",
        "updated": "2026-04-25",
        "body_html": """
<p>Take-profit ladders reduce the pressure of needing a single perfect exit. Partial profits can be secured while the remaining position stays open for larger expansion.</p>
<h2>Why ladders help</h2>
<p>Markets often move in waves. Locking partial profit at earlier targets can make the trade psychologically easier to manage.</p>
<h2>Why trailing stops matter</h2>
<p>Trailing logic helps convert strong continuation into outsized winners while still protecting against reversal.</p>
""",
    },
    "copy-trading-safely": {
        "title": "How to Use Copy Trading Safely",
        "description": "A checklist for connecting exchange APIs without exposing unnecessary permissions or oversized risk.",
        "published": "2026-04-25",
        "updated": "2026-04-25",
        "body_html": """
<p>Copy trading is only as safe as the permissions and controls around it. Traders should never grant withdrawal permissions to a signal platform.</p>
<h2>Minimum API scope</h2>
<p>For futures automation, trading permissions are enough. Withdrawals should remain disabled at all times.</p>
<h2>Operational checklist</h2>
<p>Use exchange IP restrictions, keep leverage sane, and start with small size until execution quality is proven in your own account.</p>
""",
    },
    "ai-crypto-signals-explained": {
        "title": "AI Crypto Signals Explained",
        "description": "What makes AI-assisted trade selection different from a typical manual signal channel.",
        "published": "2026-04-25",
        "updated": "2026-04-25",
        "body_html": """
<p>AI-assisted trading signals are not magic predictions. They are scoring systems that combine multiple inputs, filter noisy conditions, and produce more consistent decisions than discretionary guessing.</p>
<h2>What AI does well</h2>
<p>Models are useful for ranking opportunities, classifying regimes, and enforcing repeatable decision rules.</p>
<h2>What AI does not do</h2>
<p>It does not remove risk. It does not guarantee wins. The goal is better process, not certainty.</p>
""",
    },
}
```

## 7) Create `dashboard/blog_index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05080F">
<title>Learning Center — Anunnaki World</title>
<meta name="description" content="Guides on crypto futures, funding rates, risk management, copy trading, and AI trading systems.">
<link rel="canonical" href="https://anunnakiworld.com/blog">
<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Orbitron:wght@600;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/css/premium.css">
<style>
:root { --text:#E5E7EB; --text-dim:#94A3B8; --hairline:rgba(255,255,255,0.06); }
body { margin:0; font-family:'Inter',sans-serif; background:#05080F; color:var(--text); }
.container { max-width:980px; margin:0 auto; padding:0 24px; }
.hero { padding:84px 0 32px; text-align:center; }
.hero h1 { font-family:'Orbitron',sans-serif; font-size:clamp(34px,5vw,58px); margin:0 0 16px; }
.hero p { color:var(--text-dim); max-width:700px; margin:0 auto; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:18px; margin:32px 0 56px; }
.post-card { background:rgba(255,255,255,0.02); border:1px solid var(--hairline); border-radius:16px; padding:22px; }
.post-card h2 { margin:10px 0 10px; font-size:22px; }
.post-card a { color:#fff; text-decoration:none; }
.post-card p,.post-date { color:var(--text-dim); }
.post-link { display:inline-block; margin-top:10px; font-weight:700; }
footer { text-align:center; padding:42px 0; color:var(--text-dim); border-top:1px solid var(--hairline); }
</style>
</head>
<body>
<div class="container">
  <section class="hero">
    <h1>Learning Center</h1>
    <p>Educational content built to rank for search intent and help traders understand the mechanics behind futures, risk, and systematic execution.</p>
  </section>
  <section class="grid">__BLOG_CARDS__</section>
  <footer>&copy; 2026 Anunnaki World. <a href="/" style="color:var(--text-dim)">Back to Home</a></footer>
</div>
</body>
</html>
```

## 8) Create `dashboard/blog_post.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05080F">
<title>__TITLE__ — Anunnaki World</title>
<meta name="description" content="__DESCRIPTION__">
<link rel="canonical" href="https://anunnakiworld.com/blog/__SLUG__">
<link rel="icon" type="image/jpeg" href="/static/logo.jpeg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Orbitron:wght@600;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/css/premium.css">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "__TITLE__",
  "description": "__DESCRIPTION__",
  "datePublished": "__PUBLISHED__",
  "dateModified": "__UPDATED__",
  "publisher": {
    "@type": "Organization",
    "name": "Anunnaki World",
    "url": "https://anunnakiworld.com"
  }
}
</script>
<style>
:root { --text:#E5E7EB; --text-dim:#94A3B8; --hairline:rgba(255,255,255,0.06); --gold:#E4C375; }
body { margin:0; font-family:'Inter',sans-serif; background:#05080F; color:var(--text); }
.container { max-width:860px; margin:0 auto; padding:0 24px; }
article { padding:84px 0 48px; }
h1 { font-family:'Orbitron',sans-serif; font-size:clamp(34px,5vw,56px); margin:0 0 16px; }
.meta { color:var(--text-dim); margin-bottom:28px; }
article p { color:var(--text-dim); line-height:1.8; font-size:17px; }
article h2 { margin-top:34px; font-size:26px; }
.sidebar-links { display:flex; gap:12px; flex-wrap:wrap; margin-top:28px; }
.sidebar-links a { display:inline-block; padding:12px 16px; border-radius:10px; text-decoration:none; background:rgba(255,255,255,0.04); color:#fff; }
footer { text-align:center; padding:42px 0; color:var(--text-dim); border-top:1px solid var(--hairline); }
</style>
</head>
<body>
<div class="container">
  <article>
    <h1>__TITLE__</h1>
    <div class="meta">Published __PUBLISHED__ · Updated __UPDATED__</div>
    __BODY__
    <div class="sidebar-links">
      <a href="/blog">More Articles</a>
      <a href="/faq">FAQ</a>
      <a href="/affiliate">Affiliate Program</a>
      <a href="/app?signup=1">Create Free Account</a>
    </div>
  </article>
  <footer>&copy; 2026 Anunnaki World. <a href="/" style="color:var(--text-dim)">Back to Home</a></footer>
</div>
</body>
</html>
```

## 9) Update `dashboard/landing.html`

### 9.1 Add FAQ schema after the existing SoftwareApplication JSON-LD block
Insert this block **between** the existing `</script>` at line ~827 and `</head>`:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Do I need to give you money to see if it actually works?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. The Free tier shows every signal we publish with a 24-hour delay so you can verify performance before paying."
      }
    },
    {
      "@type": "Question",
      "name": "Does copy-trading need me to send you my API keys?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Only futures-trading scope is needed, and withdraw permission is never required."
      }
    },
    {
      "@type": "Question",
      "name": "What timeframes does the AI trade?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Primary signal generation runs on 1h with 15m and 4h confirmations, with typical holding periods of 2 to 48 hours."
      }
    },
    {
      "@type": "Question",
      "name": "How is risk managed?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Through macro risk filters, portfolio correlation controls, circuit breakers, and per-signal stop-loss logic."
      }
    }
  ]
}
</script>
```

### 9.2 Update footer resources for internal linking
Replace the current `Resources` list:

```diff
             <div class="foot-col">
                 <h5>Resources</h5>
                 <ul>
                     <li><a href="/whitepaper">Whitepaper (EN)</a></li>
                     <li><a href="/whitepaper/mk">Whitepaper (MK)</a></li>
-                    <li><a href="#faq">FAQ</a></li>
+                    <li><a href="/faq">FAQ</a></li>
+                    <li><a href="/affiliate">Affiliate Program</a></li>
+                    <li><a href="/blog">Learning Center</a></li>
+                    <li><a href="/signals/BTCUSDT">BTCUSDT Signals</a></li>
+                    <li><a href="/signals/ETHUSDT">ETHUSDT Signals</a></li>
+                    <li><a href="/signals/SOLUSDT">SOLUSDT Signals</a></li>
                 </ul>
             </div>
```

## 10) Update `dashboard/index.html`
Replace the referral copy with wording that matches the current backend behavior.

```diff
             <p style="color:var(--text-dim);font-size:13px;margin-bottom:28px;line-height:1.7;max-width:640px">
                 Share your unique referral link. When someone subscribes using your link,
-                <strong style="color:var(--text)">you earn 20% of their first payment</strong> as bonus subscription days,
-                and <strong style="color:var(--text)">they get 7 free days</strong> on top of their plan.
+                <strong style="color:var(--text)">both of you receive 7 bonus days</strong>
+                after their first verified payment.
             </p>
```

And replace the third step card text:

```diff
                 <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center">
                     <div style="font-size:28px;margin-bottom:10px">🎁</div>
                     <div style="font-weight:700;margin-bottom:6px">Both Earn Days</div>
-                    <div style="font-size:12px;color:var(--text-dim);line-height:1.5">You earn 20% commission as bonus days. They get 7 free days added automatically.</div>
+                    <div style="font-size:12px;color:var(--text-dim);line-height:1.5">Both accounts receive 7 bonus days after the referred trader's first verified payment.</div>
                 </div>
```

## 11) Update `dashboard/referrals.py`
Fix the misleading docstring in `credit_referral()`.

```diff
     Credits:
-      - Referrer: 20% of payment → bonus days on their subscription
+      - Referrer: 7 free bonus days added to their subscription
       - Referred: 7 free bonus days added to their subscription
```

## Verification
- `python3 -m py_compile dashboard/app.py dashboard/analytics.py dashboard/blog_content.py`
- `curl -s http://127.0.0.1:18789/sitemap.xml | grep -E '/affiliate|/faq|/blog|/signals/BTCUSDT'`
- `curl -s http://127.0.0.1:18789/signals/BTCUSDT | head -n 30`
- `curl -s http://127.0.0.1:18789/affiliate | head -n 20`
- `curl -s http://127.0.0.1:18789/faq | head -n 20`
- `curl -s http://127.0.0.1:18789/blog | head -n 20`
- `curl -s http://127.0.0.1:18789/ref/TESTCODE | grep robots`

## Risks
- Do not ship the pair page if it exposes live premium trade coordinates.
- Do not leave referral copy mismatched after public pages go live.
- Apply the new files before restarting the service, or `app.py` will fail on `from blog_content import BLOG_POSTS`.
- Keep pair pages limited to pairs with real signal history to avoid thin-content pages.
