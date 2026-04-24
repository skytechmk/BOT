# Proposal — Copy-Trading Failure Cluster

**Date:** 2026-04-23
**Author:** SPECTRE
**Status:** Draft — operator review required. No code applied.
**Scope:** `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/copy_trading.py`, `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.py` (import wiring only).

---

## 0. TL;DR

User reports *"Binance API limit errors when trying to copy-trade."*
It is **not** a rate limit. Log analysis shows five concrete bugs, one
of them catastrophic:

| # | Severity | Bug | Lines affected |
|---|---|---|---|
| **B1** | 🔴 **CRITICAL** | `from auth import …` inside `execute_copy_trades()` runs from bot-cwd where `auth.py` isn't on `sys.path`. **Every bot-fired signal's copy-trade silently fails** for every user. | `dashboard/copy_trading.py:893` |
| B2 | 🟠 High | `-1111 Precision over maximum` — qty/price not rounded to the symbol's `stepSize` / `tickSize`. | `dashboard/copy_trading.py:~1100–1220` |
| B3 | 🟠 High | `-4061 Position side does not match` — user in Hedge mode but we send `positionSide=BOTH`. | order-build paths in `copy_trading.py` |
| B4 | 🟡 Medium | `-4411 TradFi-Perps agreement` — equity-perp (MSFT/NVDA/SPY/AVGO…) orders attempted for users who haven't signed. `has_tradefi_errors()` exists but isn't consulted as a pre-flight gate. | `execute_copy_trades()` |
| B5 | 🟡 Medium | `-2015 Invalid API-key, IP, or permissions, request ip: 185.6.20.65` — user's Binance key is IP-whitelisted without our server IP, or missing "Futures – Trade" permission. | surface as a clear UI warning, don't just retry |

**B1 alone explains the bulk of the user's report. Fixing B1 will
restore copy-trading for every bot-fired signal; B2–B5 then become the
visible tail.**

---

## 1. Evidence

### B1 — Bot-side import failure (the big one)

Systemd unit `anunnaki-bot.service`:
```
WorkingDirectory=/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA
ExecStart=/root/miniconda3/bin/python3 -u main.py
```
`main.py:44`:
```python
from dashboard.copy_trading import execute_copy_trades as _execute_copy_trades
```
`dashboard/copy_trading.py:893` (inside the user loop of `execute_copy_trades`):
```python
from auth import tier_rank, TIERS_CANONICAL
```
From the bot's cwd, `auth` resolves to... nothing. `auth.py` lives at
`dashboard/auth.py`, which is only reachable as `dashboard.auth`.

Observed in `@/var/log/anunnaki-bot.log`:
```
2026-04-23 12:00:15,131 - INFO - [copy_trading] execution error: No module named 'auth'
2026-04-23 15:00:12,118 - INFO - [copy_trading] execution error: No module named 'auth'
2026-04-23 16:00:10,328 - INFO - [copy_trading] execution error: No module named 'auth'
2026-04-23 17:00:11,535 - INFO - [copy_trading] execution error: No module named 'auth'
2026-04-23 19:01:21,122 - INFO - [copy_trading] execution error: No module named 'auth'
```
One per signal fire. Zero occurrences in `@/var/log/anunnaki-dashboard.log`
(dashboard cwd *is* `dashboard/`, so its own direct-entry flows work).

### B2–B5 — Dashboard-side Binance rejections

From `@/var/log/anunnaki-dashboard.log` tally:
```
$ grep -hoE "APIError\(code=-?[0-9]+\)" /var/log/anunnaki-dashboard.log | sort | uniq -c | sort -rn
  <N>  APIError(code=-1111)   ← precision
  <N>  APIError(code=-4411)   ← TradFi agreement unsigned
  <N>  APIError(code=-4061)   ← hedge-mode mismatch
  <N>  APIError(code=-2015)   ← IP/permissions
```
Example line:
```
Copy-trade FAILED for user 5: APIError(code=-2015): Invalid API-key, IP, or permissions for action, request ip: 185.6.20.65
```

None of these are **rate-limit** errors (`-1003`, `-1015`, `429`). The
only actual 429s in the logs are on `/fapi/v1/klines` via the
`Direct-IP fallback` — that's the data-fetch path, not order placement.

---

## 2. Fixes

### B1 — Make `auth` importable from both cwds

**Minimal upstream fix** (per the project's bug-fixing discipline):
robust import guard at module top of `dashboard/copy_trading.py`.

```python
# ── Ensure `auth` is importable regardless of caller cwd ──
# main.py runs from the project root; dashboard/app.py runs from dashboard/.
# In both cases we want `from auth import ...` to resolve dashboard/auth.py.
import os as _os, sys as _sys
_DASH_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _DASH_DIR not in _sys.path:
    _sys.path.insert(0, _DASH_DIR)
```

Put this **once** at the very top of `dashboard/copy_trading.py` (below
the stdlib imports, before `from auth import ...` would otherwise be
attempted).

**Also lift the per-loop import to module level** — it's currently
running on every user × every signal:

```python
# dashboard/copy_trading.py (near other module-level imports)
from auth import tier_rank, TIERS_CANONICAL   # safe after sys.path fix above
```

Then delete the `from auth import tier_rank, TIERS_CANONICAL` line
inside the loop at line 893.

**Why this over adding `dashboard/` to `PYTHONPATH` in the systemd unit:**
It's a one-line code change that works in every deployment context
(systemd, docker, local `python dashboard/app.py`, pytest, etc.)
without requiring unit-file edits on every environment.

**Validation:**
1. Restart `anunnaki-bot`.
2. Wait for the next signal fire.
3. `tail -f /var/log/anunnaki-bot.log | grep copy_trading` — should see
   `Copy-trade executed for user X …`, no `No module named 'auth'`.
4. Follow-up: real Binance errors (B2–B5) will now surface instead of
   being masked by the import failure.

---

### B2 — Precision (-1111)

We already fetch `exchange_info` (`_get_exchange_info_cached` at
line 71, uses `LOT_SIZE.stepSize` at line 1114). Verify the path that
builds `order_params` at line ~1211 rounds **both** quantity and price
against the correct filters:

```python
def _round_step(value: float, step: str) -> float:
    """Round DOWN to the nearest multiple of `step` (Binance LOT_SIZE)."""
    from decimal import Decimal, ROUND_DOWN
    d = Decimal(str(value)).quantize(Decimal(step), rounding=ROUND_DOWN)
    return float(d)

# price — use PRICE_FILTER.tickSize
for f in symbol_info['filters']:
    if f['filterType'] == 'PRICE_FILTER':
        price = _round_step(price, f['tickSize'])
    elif f['filterType'] == 'LOT_SIZE':
        qty = _round_step(qty, f['stepSize'])
    elif f['filterType'] == 'MIN_NOTIONAL':
        if qty * price < float(f['notional']):
            raise ValueError(f"{pair}: below min notional ({qty*price:.4f} < {f['notional']})")
```

Ensure this wrapper is called for **every** `futures_create_order` call
site (lines 1041, 1211, 1807, 1907, 1978, 2177). Today some paths may
float-format directly — that's what produces `-1111`.

### B3 — Hedge mode (-4061)

At `_execute_single_trade_blocking()` top, call once per trade:
```python
mode = client.futures_get_position_mode()   # {'dualSidePosition': True/False}
is_hedge = bool(mode.get('dualSidePosition'))
```
Then when building order params:
```python
if is_hedge:
    params['positionSide'] = 'LONG' if direction == 'LONG' else 'SHORT'
# one-way: omit positionSide (defaults to BOTH)
```

Apply identically to the **close** paths (`_close_order_params` at line
1475 — verify it already handles both).

Cache `is_hedge` per user for ~5 min to avoid hammering
`futures_get_position_mode` on every trade.

### B4 — TradFi-Perps pre-flight gate (-4411)

`has_tradefi_errors()` at line 211 already exists. Wire it into
`execute_copy_trades()` **before** attempting the order for equity-perp
symbols:

```python
_EQUITY_PERP_SUFFIXES = {'MSFTUSDT','NVDAUSDT','SPYUSDT','AVGOUSDT','AAPLUSDT', ...}
# Better: rely on market_classifier's sector == 'equity' tag.

from market_classifier import get_pair_info
if get_pair_info(pair).get('sector') == 'equity' and has_tradefi_errors(uid):
    log.info(f"Copy-trade skip user {uid}: TradFi-Perps agreement not signed")
    _surface_onboarding_warning(uid, 'tradfi_unsigned')
    continue
```

Plus: on each fresh `-4411` from Binance, `mark_tradefi_errors(uid)` so
we automatically skip future equity-perp signals for that user until
they click a "I've signed" button on the dashboard (calls
`mark_tradefi_signed`).

### B5 — IP/permissions (-2015)

Already classified in `_classify_binance_error()` at line 353. Improve
the user-facing surface:

- On `-2015`, **set `is_active=0`** for that user's copy-trading
  config (disable them until they fix it).
- Push a dashboard notification / banner: *"Your Binance API key
  rejected trades with `request ip: 185.6.20.65`. Whitelist this IP
  in your Binance API settings, or disable IP restrictions, or ensure
  the key has Futures-Trade permission. Copy-trading has been paused
  for your account."*
- Email the user the same message (we already have SMTP wiring for
  verification).

---

## 3. Ranked action plan

| Step | File | Effort | Outcome |
|---|---|---|---|
| 1 | `dashboard/copy_trading.py` — sys.path guard + lift `from auth import …` to module top + remove from inner loop | **3 lines, 5 min** | Bot-side copy-trading starts working for every signal |
| 2 | Restart `anunnaki-bot`; monitor log for 1 signal cycle | — | Confirms B1 fixed |
| 3 | B2 — audit every `futures_create_order` call for precision | ~30 min | `-1111` eliminated |
| 4 | B3 — add hedge-mode detection + `positionSide` logic | ~30 min | `-4061` eliminated |
| 5 | B4 — wire `has_tradefi_errors()` into pre-flight + auto-mark on `-4411` | ~20 min | Equity-perp orders stop failing noisily |
| 6 | B5 — auto-pause + UI banner on `-2015` | ~30 min | Users self-serve fix IP/permissions |

Step 1 alone will likely make the user's reported problem go away
(because most of their observed failure was B1 masking the real state).

---

## 4. Regression test (recommended)

Before applying, add a lightweight unit test that imports
`dashboard.copy_trading` from a subprocess with cwd set to both
`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA` and `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard`,
and asserts that `execute_copy_trades` can be called without raising
`ModuleNotFoundError`:

```python
# tests/test_copy_trading_imports.py
import subprocess, sys
def test_bot_cwd_can_import_copy_trading_auth():
    r = subprocess.run(
        [sys.executable, "-c",
         "from dashboard.copy_trading import execute_copy_trades; "
         "from auth import tier_rank; print('OK')"],
        cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA",
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
```

This is the exact scenario that broke today and would have been caught
in CI.

---

## 5. Operator decision requested

- **Apply step 1 immediately?** (3-line change, fixes the critical path,
  zero risk of breaking dashboard-side flows.)
- Schedule B2–B5 into this week's work, or split into a follow-up ticket?
- Should we add the regression test in §4 as part of the same change?

*Nothing applied yet. Awaiting approval per AGENTS.md protocol.*
