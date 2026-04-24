# Anunnaki World — Feature Roadmap Proposals
**Created:** 2026-04-15  
**Status:** Pending implementation

---

## 1. 🤖 Bybit Integration (Copy-Trading)
**Priority:** High | **Target:** Q3 2026

Extend the existing copy-trading engine to support Bybit Futures alongside Binance.

**Scope:**
- Add `exchange` field to `copy_trading_config` table (`binance` | `bybit`)
- Abstract `_get_futures_client()` into an exchange-agnostic interface
- Implement Bybit API key save/validate/decrypt flow (same Fernet encryption)
- Map Bybit order types to the existing execution engine
- UI: exchange selector dropdown in Copy-Trade settings tab

**Files to touch:** `copy_trading.py`, `dashboard/index.html`, `static/js/copytrading.js`

---

## 2. 📱 Mobile App (iOS & Android)
**Priority:** High | **Target:** Q4 2026

Native mobile app with push notifications, live P&L, and one-tap signal execution.

**Scope:**
- React Native or Flutter front-end consuming existing REST + WebSocket API
- Push notifications via FCM/APNs for new signals, TP hits, SL triggers
- Live P&L screen mirroring the dashboard Overview page
- Biometric authentication (Face ID / Fingerprint) for login
- One-tap copy-trade toggle per signal

**Files to touch:** New repo `aladdin-mobile/`, existing `app.py` API (no breaking changes needed)

---

## 3. 🎯 Backtesting Engine
**Priority:** Medium | **Target:** Q3 2026

Allow users to replay the bot's strategy on historical OHLCV data.

**Scope:**
- Store up to 3 years of 1h OHLCV data per pair in a compressed time-series DB (TimescaleDB or DuckDB)
- Replay signal generation logic (Ichimoku, CE, VWAP, RSI, FVG) against historical bars
- Compute equity curve, max drawdown, win rate, Sharpe, Sortino per strategy config
- UI: date range picker, pair selector, results chart on Analytics page

**Files to touch:** New `backtester.py`, `app.py` (new `/api/backtest` routes), `static/js/analytics.js`

---

## 4. 🔔 Smart Custom Alerts
**Priority:** Medium | **Target:** Q3 2026

Let users define their own alert conditions beyond raw signals.

**Scope:**
- Alert types: price cross, RSI threshold, signal fired on specific pair, TP/SL hit
- Delivery: Telegram DM (via bot token), email, in-app notification badge
- Alert management UI: create / pause / delete alerts
- DB table `user_alerts` with condition JSON, last_triggered, delivery_channel

**Files to touch:** New `alerts.py`, `app.py`, `telegram_handler.py`, `index.html`

---

## 5. 📊 Advanced Portfolio Analytics
**Priority:** Medium | **Target:** Q4 2026

Deeper performance breakdown for Pro/Elite users.

**Scope:**
- Correlation matrix across active pairs
- Rolling drawdown curve with max drawdown annotation
- Sharpe ratio, Sortino ratio, Calmar ratio per period
- Trade duration distribution histogram
- Pair-level win rate heatmap (calendar view)

**Files to touch:** `analytics.py`, `static/js/analytics.js`

---

## 6. ⚡ Screener v2 — Multi-Timeframe Confluence
**Priority:** Medium | **Target:** Q3 2026

Upgrade the screener from single-timeframe to full MTF confluence scoring.

**Scope:**
- Score each pair across 15m / 1h / 4h / 1D simultaneously
- Confluence score = weighted average of timeframe alignment
- Filter by minimum confluence threshold (e.g. 3/4 TFs aligned)
- Visual: per-TF mini-badge grid per pair row
- Export screener snapshot as CSV

**Files to touch:** `screener.py` (or new `screener_v2.py`), `static/js/screener.js`

---

## 7. 🏆 Community Leaderboard
**Priority:** Low | **Target:** Q4 2026

Public leaderboard ranking users by signal accuracy and P&L.

**Scope:**
- Opt-in leaderboard (privacy-first — username only, no email)
- Rank by: win rate, total R earned, streak, signals followed
- Weekly / monthly / all-time tabs
- Badges: 🥇 Top Trader, 🔥 Hot Streak, 💎 Diamond Hands
- DB table `leaderboard_snapshots` updated nightly

**Files to touch:** New `leaderboard.py`, `app.py`, `index.html`

---

## 8. 🧠 AI Model Continuous Learning
**Priority:** Ongoing

The XGBoost + Transformer ensemble already self-improves via `self_learning_data.json`. Formal enhancements:

**Scope:**
- Automated weekly retraining pipeline triggered when `n_new_signals >= 50`
- A/B shadow model: run new model in parallel, compare win rate before promoting
- Feature importance dashboard panel showing top-20 signal drivers
- Model version history with rollback capability

**Files to touch:** `signal_generator.py`, `performance_tracker.py`, new `model_trainer.py`

---

## 9. 🔗 Referral Program Enhancements
**Priority:** Low | **Target:** Q3 2026

Build on the existing referral system (launched 2026-04-15).

**Scope:**
- Cash-out option: convert bonus days to USDT wallet credit
- Tier multipliers: Elite referrers earn 25% instead of 20%
- Referral analytics page for admins: top referrers, conversion funnel
- Multi-level referral (2-tier): referrer's referrer earns 5%

**Files to touch:** `referrals.py`, `app.py`, `index.html`

---

## 10. 📈 TradingView Webhook Integration
**Priority:** Low | **Target:** Q4 2026

Accept inbound webhooks from TradingView Pine Script alerts and convert to bot signals.

**Scope:**
- Authenticated webhook endpoint `POST /api/webhook/tradingview`
- Parse TV alert JSON, validate HMAC signature
- Inject into signal pipeline as if generated by the bot
- Admin toggle: enable/disable per user

**Files to touch:** New `webhook_handler.py`, `app.py`

---

*Last updated: 2026-04-15 by Cascade*
