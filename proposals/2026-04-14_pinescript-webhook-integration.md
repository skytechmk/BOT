# Proposal: Pine Script Webhook Integration
# CE Pro Hybrid + REVERSE HUNT [MTF] → Aladdin Bot

**Date:** 2026-04-14  
**Status:** READY TO IMPLEMENT — no code changes needed, setup only  
**Risk level:** Low (additive signal source, existing webhook pipeline already live)

---

## Overview

Two proprietary Pine Script v5 indicators are to be connected to the bot via
TradingView webhook alerts. Both indicators already have exact Python counterparts
running in the bot, but the TV versions provide an additional advantage:

- **CE Pro Hybrid** fires on the PAIR's own chart with zero-repaint confirmed flips
- **REVERSE HUNT [MTF]** runs on `CRYPTOCAP:USDT.D` — systemic crypto dominance —
  a macro regime signal the bot CANNOT replicate per-pair at scale

When TV fires an alert, the bot's existing `tv_queue_processor()` picks it up within
60 seconds and routes it through the full SQI + PREDATOR + ML + Cornix pipeline.

---

## Infrastructure Already Live (No Code Changes Required)

| Component | Status | Notes |
|---|---|---|
| Webhook endpoint | ✅ Live | `POST /api/webhook/tradingview` on port 443 |
| Webhook secret | ✅ Set | `TV_WEBHOOK_SECRET` in `.env` |
| `tv_alerts.db` | ✅ Created | SQLite, persists all incoming alerts |
| `tv_queue_processor()` | ✅ Running | Polls DB every 60s, calls `process_pair()` |
| `tv_override` path in `main.py` | ✅ Wired | Bypasses RH engine, goes straight to SQI |

---

## Step 1 — Modify CE Pro Hybrid Pine Script

Replace the two `alertcondition` lines at the bottom with:

```pine
// ── Webhook Alerts ────────────────────────────────────────────────────
wh_secret   = input.string("eeeea87b42d5f82885c1486426dbfe024736de6a4a5f1b20", "Webhook Secret", group="Webhook")
wh_strategy = input.string("CE Pro Hybrid", "Strategy Name", group="Webhook")

ce_long_msg  = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"buy","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"CE Line flipped LONG"}'

ce_short_msg = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"sell","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"CE Line flipped SHORT"}'

if buySignal
    alert(ce_long_msg,  alert.freq_once_per_bar_close)
if sellSignal
    alert(ce_short_msg, alert.freq_once_per_bar_close)

alertcondition(buySignal,  "Line Buy",  "Trend Change LONG")
alertcondition(sellSignal, "Line Sell", "Trend Change SHORT")
```

**Where:** Pine Editor → CE Pro Hybrid script → replace original `alertcondition` block

---

## Step 2 — Modify REVERSE HUNT [MTF] Pine Script

Add this entire block at the very end of the script (after section 6 — Zero Cross Lines):

```pine
// =============================================================================
// 7. WEBHOOK ALERTS — Aladdin Bot Integration
// =============================================================================
wh_secret   = input.string("eeeea87b42d5f82885c1486426dbfe024736de6a4a5f1b20", "Webhook Secret",  group = "Webhook")
wh_strategy = input.string("REV HUNT USDT.D", "Strategy Name", group = "Webhook")

rh_long_msg  = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"buy","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"LR_CROSS_UP tsi=' + str.tostring(scaled_tsi, "#.##") + '"}'

rh_short_msg = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"sell","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"LR_CROSS_DN tsi=' + str.tostring(scaled_tsi, "#.##") + '"}'

tsi_exit_long_msg  = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"buy","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"TSI_EXIT_OS tsi=' + str.tostring(scaled_tsi, "#.##") + '"}'

tsi_exit_short_msg = '{"secret":"' + wh_secret + '","symbol":"' + syminfo.ticker
               + '","action":"sell","price":' + str.tostring(close, "#.######")
               + ',"strategy":"' + wh_strategy
               + '","message":"TSI_EXIT_OB tsi=' + str.tostring(scaled_tsi, "#.##") + '"}'

if cond2        // LinReg zero cross UP → macro regime bullish
    alert(rh_long_msg,         alert.freq_once_per_bar_close)
if cond1        // LinReg zero cross DOWN → macro regime bearish
    alert(rh_short_msg,        alert.freq_once_per_bar_close)
if tsi_exit_dn  // TSI exits oversold → reversal LONG confirmation
    alert(tsi_exit_long_msg,   alert.freq_once_per_bar_close)
if tsi_exit_up  // TSI exits overbought → reversal SHORT confirmation
    alert(tsi_exit_short_msg,  alert.freq_once_per_bar_close)

alertcondition(cond2,       "LR Zero Cross UP",    "Macro: BULLISH")
alertcondition(cond1,       "LR Zero Cross DOWN",   "Macro: BEARISH")
alertcondition(tsi_exit_dn, "TSI Exit Oversold",    "Reversal LONG")
alertcondition(tsi_exit_up, "TSI Exit Overbought",  "Reversal SHORT")
```

---

## Step 3 — TradingView Alert Setup

### For CE Pro Hybrid

Create **one alert per pair** you want to monitor (or use a watchlist alert if on premium TV plan):

| Field | Value |
|---|---|
| Indicator | CE Pro Hybrid (on the pair's chart, e.g. BTCUSDT, 1H) |
| Condition | `Any alert() function call` |
| Webhook URL | `https://<YOUR_SERVER_IP>/api/webhook/tradingview` |
| Message | *(leave blank — script generates JSON automatically)* |
| Trigger | Once Per Bar Close |
| Expiration | Open-ended |

### For REVERSE HUNT [MTF]

Create **one alert** — it applies to ALL pairs because it watches USDT.D:

| Field | Value |
|---|---|
| Indicator | REV HUNT [SkyTech] (on ANY chart, 2H timeframe matches `tf_select=120`) |
| Condition | `Any alert() function call` |
| Webhook URL | `https://<YOUR_SERVER_IP>/api/webhook/tradingview` |
| Message | *(leave blank)* |
| Trigger | Once Per Bar Close |

> **Important:** The `syminfo.ticker` in the REVERSE HUNT will send whatever pair the
> chart is open on — not USDT.D. To send signals for ALL pairs you watch, you need one
> alert per pair, or use TradingView's Multi-Chart alerts (Premium feature).
> Alternative: set the chart to a "master" pair like BTCUSDT and treat RH alerts as a
> macro gate (described below).

---

## Step 4 — Bot-Side Behaviour

### Signal Flow When Webhook Fires

```
TradingView bar closes
    ↓ alert() fires
    → POST https://<ip>/api/webhook/tradingview
        body: {"secret":"...", "symbol":"BTCUSDT", "action":"buy", ...}
    → dashboard/app.py validates secret → writes to tv_alerts.db
    → tv_queue_processor() (polls every 60s) reads unprocessed row
    → calls process_pair("BTCUSDT", tv_override={"signal":"LONG", "strategy":"CE Pro Hybrid"})
    → SKIPS Reverse Hunt engine (TV already confirmed)
    → Runs SQI v3 (150+ pts with ML ensemble, CE, divergence, BEAST, PREDATOR)
    → Runs Monte Carlo, correlation, circuit breaker filters
    → Formats Cornix signal → sends to Telegram
```

### `tv_override` path in `main.py`

When `tv_override` is set, the bot:
- Sets `rh_conviction = 0.67` (equivalent to 4/6 conviction)
- Sets `ce_line_flip = True`, `ce_cloud_agree = True`
- Recomputes CE fresh for accurate SL level
- Logs `📺 TV SIGNAL [PAIR]: LONG | Strategy: CE Pro Hybrid`

---

## Step 5 — Recommended Alert Priority Matrix

| Alert | Timeframe | Source | Conviction Weight | Notes |
|---|---|---|---|---|
| CE Line flip | 1H | Pair chart | High | Zero-repaint confirmed direction change |
| RH LinReg cross UP/DN | 2H | USDT.D | Very High | Macro regime shift — rare, high quality |
| RH TSI exit OB/OS | 2H | USDT.D | Medium | Exhaustion reversal confirmation |

**Recommended setup to start:**
1. CE Pro Hybrid on **BTCUSDT 1H** and **ETHUSDT 1H** → webhook
2. REVERSE HUNT on **BTCUSDT 2H** (watching USDT.D) → webhook

Add more pairs as needed. TradingView free plan allows up to **1 active alert** at a time; Pro allows 20; Premium allows unlimited.

---

## Step 6 — Optional Python Enhancement: USDT.D Macro Gate

To make the bot aware of the USDT.D dominance signal (even without a TV alert), add a
USDT.D fetch to the main loop and use it as a pre-filter.

**File:** `data_fetcher.py`  
**Add function:**
```python
async def fetch_usdt_dominance() -> float:
    """Fetch USDT.D dominance from CoinGecko or Binance USDT.D proxy."""
    # CoinGecko: GET /global → data.market_cap_percentage.usdt
    # Returns float 0-100 (e.g. 5.8 = 5.8% USDT dominance)
```

**File:** `main.py` — compute `linreg_usdt_d` on USDT.D close series, use its zero
cross as an additional `rh_components['usdt_d_aligned']` conviction point (+1/6).

This is a **future enhancement** — the webhook integration in Steps 1-5 is sufficient
to bring USDT.D signals into the bot without any Python changes.

---

## Parameter Alignment (Confirmed Match)

| Parameter | Pine Script Default | Python `reverse_hunt.py` | Match |
|---|---|---|---|
| TSI Long | 25 | `TSI_LONG = 25` | ✅ |
| TSI Short | 13 | `TSI_SHORT = 13` | ✅ |
| TSI Scale | 50.0 | `TSI_SCALE = 50.0` | ✅ |
| TSI Inverted | true | `TSI_INVERT = True` | ✅ |
| LinReg Length | 20 | `LINREG_LEN = 20` | ✅ |
| LinReg Norm | 100 | `LINREG_NORM = 100` | ✅ |
| LinReg Smooth | 1 | `LINREG_SMOOTH = 1` | ✅ |
| LinReg Inverted | true | `LINREG_INVERT = True` | ✅ |
| Level OB L1 | 1.5 | `LEVEL_OB_L1 = 1.5` | ✅ |
| Level OS L1 | -1.5 | `LEVEL_OS_L1 = -1.5` | ✅ |
| Level OB L2 | 2.0 | `LEVEL_OB_L2 = 2.0` | ✅ |
| Level OS L2 | -2.0 | `LEVEL_OS_L2 = -2.0` | ✅ |
| CE Line ATR | 22 | `CE_LINE_ATR_LEN = 22` | ✅ |
| CE Line Look | 22 | `CE_LINE_LOOKBACK = 22` | ✅ |
| CE Line Mult | 3.0 | `CE_LINE_MULT = 3.0` | ✅ |
| CE Line Smooth | RMA | `CE_LINE_SMOOTH = 'RMA'` | ✅ |
| CE Cloud ATR | 50 | `CE_CLOUD_ATR_LEN = 50` | ✅ |
| CE Cloud Look | 50 | `CE_CLOUD_LOOKBACK = 50` | ✅ |
| CE Cloud Mult | 5.0 | `CE_CLOUD_MULT = 5.0` | ✅ |

**Known divergence:** Pine Script RH runs on `CRYPTOCAP:USDT.D`; Python runs on
the pair's own close. This is intentional (can't fetch USDT.D per-pair at scale).
The TV webhook resolves this by bringing the true USDT.D signal back into the bot.

---

## Rollback Plan

No code was changed. To disable TV webhook processing:
- Comment out the `asyncio.create_task(tv_queue_processor())` line in `main.py`
- Or set `TV_WEBHOOK_SECRET=""` in `.env` to reject all incoming webhooks

---

## Files Involved

| File | Role | Change Required |
|---|---|---|
| `dashboard/app.py` | Webhook receiver | None — already live |
| `main.py` | Queue processor + `tv_override` handler | None — already live |
| `tv_alerts.db` | Alert persistence | None — auto-created |
| `.env` | `TV_WEBHOOK_SECRET` | None — already set |
| Pine Script (CE Hybrid) | Add `alert()` calls | Manual in TradingView |
| Pine Script (REV HUNT) | Add `alert()` calls | Manual in TradingView |
