# Platform Polish — punch-list

**Date:** 2026-04-24
**Author:** SPECTRE (operator-reviewed)
**Scope:** Dashboard, landing page, copy-trading, telemetry, branding
**Status:** Proposal — awaiting operator prioritisation

---

## How this list was built

Grounded in concrete evidence from the last 72 hours of operation, not speculation:

- `138` rate-limit events in `debug_log10.txt` over the current window
- `24` `[balance] Binance` ERRORs + `17` `[balance] futures_account()` WARNINGs — stale balance fetch path still flaky
- `5` `[copy_trading] [rate-limit]` short-circuits (proves ban-gate works, but the *triggering* bursts still exist)
- Just-shipped features that created surface-area: `live-pnl` endpoint, WS-API migration, motto/brand update, homepage-share flow, UDS ban-aware reconnect

Items are tagged by **effort** (🟢 < 1 h · 🟡 1-4 h · 🔴 day+) and **impact** (★ basic · ★★ noticeable · ★★★ compounding/systemic).

---

## 1. Copy-trading — reliability & feel

### 1.1 🟢 ★★★ Kill the 60-second REST reconcile in UDS
`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/binance_user_stream.py` hydrates state via `futures_account()` every 60 s as a safety net. Now that we've proven the event stream carries all deltas reliably, drop the interval to **5 min** or gate it behind an event-gap detector (only reconcile if no event in last 120 s). Cuts per-user REST weight by ~12×.

### 1.2 🟢 ★★ Retry `recalc-pnl` countdown in the UI
Today the endpoint returns `{error_code:"rate_limited", retry_in_seconds:361}` during a ban, but the UI shows a generic toast. Replace with a button state: **"⏳ Retry in 5m 59s"** that counts down and auto-enables. File: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/copytrading.js`.

### 1.3 🟡 ★★ Remove remaining REST hot paths
Still on REST per trade-close: `futures_cancel_all_open_orders`, `futures_cancel_order`, `futures_income_history` (in `close_single_position`). `python-binance` has no WS wrappers — either submit a shim through `binance_ws_api.py` or live with it (low frequency, fine).

### 1.4 🟢 ★★ Show trailing-SL state in the open-trades row
Right now `PnL %` is live but the SL column is the original entry SL. Surface the current ratcheted value + arrow indicator when it has moved (🔒 0.00057 → 🔼 0.00061).

### 1.5 🟡 ★★ "Why was this trade closed?" tooltip
DB has `close_reason` (SL, TP1, TP2, manual, external). Show on hover in the closed-trades table.

---

## 2. Landing page — conversion polish

### 2.1 🟢 ★★ Motto needs hero-level typography
We swapped `<h1>` copy but the gold-italic `<em>` treatment in `landing.html:843` was tuned for the old "reasoned by AI" phrase. Re-balance font-size on "You make the move." so it doesn't wrap awkwardly on 390 px widths.

### 2.2 🟢 ★★★ Kill the still-hardcoded `566` stat in 3 places
`landing.html` references `566` / `566+` in hero-eyebrow, hero-sub, and hero-trust count. The scanner hit **605** in the latest cycle log. Either: (a) make it dynamic from `/api/pairs/count`, or (b) round down to **"500+"** to stop cosmetic drift.

### 2.3 🟡 ★★ Replace generic "AI trading signals" copy with the motto narrative
Each feature card should end with a one-line motto-echo: *"You don't decode Ichimoku — we do. You just place the trade."* This cements brand voice without re-writing the whole page.

### 2.4 🟢 ★★ Social proof — wire the real numbers
`hero-signals-fired` uses `data-live-signals="1"` but I haven't verified it actually pulls a live count. Check the endpoint; if stale/fake, either make it live from `signals_db` or remove (fake counters erode trust).

### 2.5 🟡 ★ FAQ section missing
Top-3 pre-sale objections: *"Does this work on Bybit?" · "Is my API key safe?" · "What happens if Binance goes down?"*. Add a collapsible FAQ block; each answer links to a security/trust page.

### 2.6 🟢 ★ Trust bar — add "No custody" + "Read-only+trade keys" badges
Small but powerful pre-purchase trust signal. Three icon chips near the CTAs.

---

## 3. Share / referral UX

### 3.1 🟢 ★★ Mobile share button in top nav
The share button lives on the **Referral** page only. On mobile, add a persistent share icon in the header bar so users can share from anywhere in the app.

### 3.2 🟢 ★ Referral link QR code
One-liner with `qrcode.js` — next to the copy/share buttons, render a QR so users can share in-person (conferences, meetups).

### 3.3 🟡 ★★ Referral leaderboard (opt-in)
Gamify with a public top-10 "Referrers of the Month" block. Opt-in only (GDPR).

---

## 4. Observability & admin

### 4.1 🟢 ★★★ Surface `ERROR` / `WARNING` counts in admin panel
Admin panel shows users/devices/payments but no log health. Add a mini widget: *"Last 24h: 24 ERR, 47 WARN · top: [rate-limit]"*. Reuses existing log files, one endpoint.

### 4.2 🟡 ★★ Rate-limit telemetry page
Today we can only see bans after-the-fact in logs. A small time-series graph of `request weight used / sec` with ban-threshold line. File suggestion: `binance_weight_tracker.py`.

### 4.3 🟢 ★★ Copy-trading health badge on admin dashboard
Green/yellow/red pill: *UDS connected · Last event 0.4s · 12 positions · 0 errors*. Inherits from existing `/api/admin/ws-status`.

### 4.4 🟡 ★★ Per-user "last 30-day WS reliability" metric
% of minutes where UDS had a fresh event. Surfaces silent WS degradation.

---

## 5. SPA polish (logged-in side)

### 5.1 🟢 ★★ Active page indicator in side nav
When on `/app?page=copy-trading`, the side-nav entry doesn't highlight in all states — audit the `.active` class application.

### 5.2 🟢 ★★ Consistent empty-states
`"No trades yet — share your link to get started!"` pattern works. Replicate for: signals (logged-out), heatmap (pair not ready), order-flow (no data).

### 5.3 🟡 ★★ Keyboard shortcuts
`?` → shortcut cheat sheet · `g s` → signals · `g c` → copy-trading · `/` → focus search. Power users will love it.

### 5.4 🟢 ★ Toast de-duplication
When rate-limited, 12 simultaneous API calls currently throw 12 identical toasts. Throttle to 1 per 3 s per error message.

### 5.5 🟢 ★★ Loading skeletons (not spinners)
Copy-trading page shows a single generic spinner. Swap for card-shaped skeletons — feels ~2× faster perceptually.

---

## 6. Mobile / PWA

### 6.1 🟢 ★★ Install prompt
The app is a valid PWA (manifest + service worker). Add a subtle "📱 Install app" chip for mobile Chrome/Safari that triggers `beforeinstallprompt`. Dismissible, once-per-session.

### 6.2 🟢 ★ Bottom-tab navigation on mobile
Currently uses the same side-drawer as desktop. On ≤ 600 px, a fixed bottom tab (Signals · Heatmap · Copy · More) is standard and drives 2-3× engagement.

### 6.3 🟡 ★★ Native push notifications (already on roadmap — accelerate)
Browser Push API → one endpoint, one JS helper. Replaces Telegram for the subset of users who prefer in-app.

---

## 7. Branding / content

### 7.1 🟢 ★★ OG banner does not contain the new motto
`@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/og-banner.png` — regenerate with *"We do the math. You make the move."* so Twitter/Telegram previews reinforce the brand.

### 7.2 🟢 ★ Favicon is the JPEG logo; browser tabs look blurry
Generate 32/48/96/192/512 PNG + SVG set, replace `<link rel="icon">` chain. 15-min win.

### 7.3 🟡 ★★ Email templates
Register / password-reset / new-device-alert emails are functional but bland. Motto + gradient header + consistent footer.

### 7.4 🟢 ★ Short platform bio for AppStore/PWA listings (one-liner)
*"We do the math. You make the move. Institutional-grade AI signals for Binance Futures."* Paste into manifest `description`, PWA install prompt, etc.

---

## 8. Security & compliance (separate proposal exists)

Covered in `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/proposals/2026-04-23_security-audit.md` — not duplicating here. One thing to add:

### 8.1 🟢 ★★★ API-key rotation reminder
If a user's API key is older than 90 days, show a gentle banner on the Copy-Trading page: *"Good security practice: rotate your Binance API key every 90 days."* One query, one dismissible toast.

---

## Suggested order of execution

**Phase 1 — quick wins (same day, 3-4 hours total)**
- 1.1 (reconcile interval) · 2.2 (566 drift) · 4.1 (error widget) · 5.4 (toast dedup) · 7.1 (OG banner) · 7.2 (favicon set) · 8.1 (API-key rotation nudge)

**Phase 2 — UX polish (2-3 days)**
- 1.2 · 1.4 · 1.5 · 2.1 · 2.3 · 2.4 · 2.5 · 3.1 · 3.2 · 5.1 · 5.2 · 5.5 · 6.1 · 6.2

**Phase 3 — infrastructure depth (week+)**
- 1.3 · 2.5 · 3.3 · 4.2 · 4.4 · 5.3 · 6.3 · 7.3

---

## What I would *not* do

- **No feature bloat.** The platform already does copy-trading, signals, heatmap, screener, order-flow, macro, chat (coming). Ship polish, not more surface area.
- **No "Admin Panel v2" framing** — per operator directive, removed from roadmap. Existing admin is fine; add *widgets* to it (item 4.1/4.3), don't rebrand.
- **No theme overhaul.** Current gold-on-dark + light-mode branch is distinctive. Don't chase trends.
- **No copy-pasted "Why choose us?" filler.** Every landing-page block must say something concrete that competitors can't claim.

---

## Open questions for operator

1. Do we have design bandwidth for items 7.1 (OG banner) and 7.3 (email templates), or should I stub with HTML-only fallbacks?
2. Is item 3.3 (public leaderboard) legally OK in all jurisdictions we serve? (GDPR opt-in only, but some EEA states are touchy.)
3. Priority on mobile (section 6) vs. desktop-first polish? Roughly what % of traffic is mobile today?

Once prioritised, I'll open focused sub-proposals for each approved item with exact diffs.
