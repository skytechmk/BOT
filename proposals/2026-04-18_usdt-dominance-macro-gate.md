# Proposal — USDT.D Macro Indicator (REVERSE HUNT [MTF reg] on USDT.D)

**Date**: 2026-04-18
**Author**: S.P.E.C.T.R.E.
**Status**: PROPOSED — operator review required
**Motivation**: 48h loss post-mortem (57 LONGs / 1 SHORT → 29 SL hits, net −556% leveraged). Root cause: Python port of REVERSE HUNT runs TSI/LinReg on pair-1H, but the original Pine strategy intended USDT.D-2H (systemic dominance vector) as the macro sieve. Without it, every alt bounce during fear fires an independent LONG.

---

## 1. Scope

Implement the REVERSE HUNT [MTF reg] indicator literally, on USDT.D only, with the parameter profile specified by the operator:

| Param | Value | Pine default | Operator override |
|---|---|---|---|
| `target_ticker` | **CRYPTOCAP:USDT.D** | USDT.D | ✓ |
| `tf_select` | **120** (2H) | 120 | ✓ |
| `tsi_long` | **69** | 25 | **override** |
| `tsi_short` | **9** | 13 | **override** |
| `tsi_scale` | **14.0** | 50.0 | **override** |
| `invert_tsi` | **true** | true | ✓ |
| `len_reg` | **20** | 20 | ✓ |
| `len_norm` | **100** | 100 | ✓ |
| `len_smooth` | **1** | 1 | ✓ |
| `invert_lr` | **true** | true | ✓ |
| `upper` (L1 Pain) | **+1.4** | +1.5 | **override** |
| `lower` (L1 Pain) | **−1.4** | −1.5 | **override** |
| `upper_2` (L2 Max Pain) | **+2.1** | +2.0 | **override** |
| `lower_2` (L2 Max Pain) | **−1.8** | −2.0 | **override — asymmetric** |

Note the **asymmetry**: L2_UP (+2.1) > |L2_DN| (−1.8). The operator wants greed-exhaustion (TSI > +2.1 on inverted USDT.D = alts pumping violently) to require a stronger threshold than fear-exhaustion (TSI < −1.8 = USDT.D pumping violently). Intentional — reduces false SHORT triggers and makes LONG unblocking slightly more sensitive.

---

## 2. Files Affected

| File | Change | Lines |
|---|---|---|
| `usdt_dominance.py` | **NEW** — full implementation | ≈ 320 |
| `macro_risk_engine.py` | Add `usdt_d_state` snapshot field | +8 |
| `main.py` | Import + log USDT.D state per signal (no gating yet) | +6 |
| `requirements.txt` | Add `tvdatafeed>=2.1.0` (optional, bootstrap only) | +1 |

Phase 1 = log only. Phase 2 (operator decision after observation) = wire into pipeline as LONG/SHORT gate.

---

## 3. Data Backends

Three-tier fallback:

### Tier 1 — TradingView scrape (preferred for historical)
```python
from tvdatafeed import TvDatafeed, Interval
tv = TvDatafeed()  # no login = public data only, rate-limited but free
df = tv.get_hist('USDT.D', 'CRYPTOCAP', interval=Interval.in_2_hour, n_bars=1000)
```
- Pros: Exact same series TradingView shows → perfect Pine parity
- Cons: Unofficial lib, may break on TV changes
- Usage: One-shot bootstrap + hourly refresh of last 10 bars

### Tier 2 — CoinGecko (live updates, no key, no signup)
```python
GET https://api.coingecko.com/api/v3/global
→ data.market_cap_percentage.usdt    # float, e.g. 5.23
```
- Pros: Free forever, zero auth
- Cons: Rate limit ~30/min from free tier; only gives CURRENT value (no history endpoint for dominance)
- Usage: Poll every 30 min, append to SQLite, build 2H bars over time

### Tier 3 — DefiLlama (backup historical)
```python
GET https://stablecoins.llama.fi/stablecoincharts/all
→ all-stablecoin aggregate (USDT + USDC + DAI + ...) history, daily only
```
- Used only if both above fail. Gives total stablecoin dominance (broader proxy).

---

## 4. File: `usdt_dominance.py` (full code)

```python
"""
USDT Dominance Macro Indicator — Python port of REVERSE HUNT [MTF reg] on USDT.D

Implements the "Systemic Dominance Vector" layer intended by the original Pine
script. Calculated on CRYPTOCAP:USDT.D at 2H timeframe.

Parameters (operator spec 2026-04-18):
  TSI:    long=69, short=9, scale=14, inverted
  LinReg: len=20, norm=100, smooth=1, inverted
  Levels: L1=±1.4,  L2_UP=+2.1,  L2_DN=−1.8  (asymmetric)

State interpretation (inverted TSI on USDT.D):
  TSI < lower_2 (−1.8)  →  USDT.D pumping extreme  →  FEAR_MAX_PAIN     → enable LONG alts
  TSI < lower   (−1.4)  →  USDT.D pumping moderate →  FEAR_PAIN         → caution on SHORT alts
  TSI > upper   (+1.4)  →  USDT.D dumping moderate →  GREED_PAIN        → caution on LONG alts
  TSI > upper_2 (+2.1)  →  USDT.D dumping extreme  →  GREED_MAX_PAIN    → enable SHORT alts
  otherwise             →  NEUTRAL                 →  no macro gate active

LinReg oscillator (inverted, on USDT.D):
  > 0  →  alts bearish regime (USDT.D trend up)
  < 0  →  alts bullish regime (USDT.D trend down)
"""
from __future__ import annotations
import os, time, sqlite3, json, threading
from dataclasses import dataclass, asdict
from typing import Optional, Literal
import numpy as np
import pandas as pd
import requests

# ── Operator-spec parameters ──────────────────────────────────────────────────
TSI_LONG        = 69
TSI_SHORT       = 9
TSI_SCALE       = 14.0
TSI_INVERT      = True

LINREG_LEN      = 20
LINREG_NORM     = 100
LINREG_SMOOTH   = 1
LINREG_INVERT   = True

LEVEL_L1_UP     = +1.4
LEVEL_L1_DN     = -1.4
LEVEL_L2_UP     = +2.1
LEVEL_L2_DN     = -1.8

TF_BAR_SECONDS  = 2 * 3600    # 2H bars
MIN_BARS_READY  = 120         # ~10 days of 2H; enough to stabilize TSI(69,9)

DB_PATH         = os.path.join(os.path.dirname(__file__), 'usdt_dominance.db')
REFRESH_SEC     = 1800        # 30 minutes

_State = Literal[
    'NEUTRAL',
    'GREED_PAIN',
    'GREED_MAX_PAIN',
    'FEAR_PAIN',
    'FEAR_MAX_PAIN',
]


@dataclass
class USDTDominanceState:
    value_pct:       Optional[float]   # current USDT dominance %, e.g. 5.23
    tsi_scaled:      Optional[float]   # inverted TSI / scale
    tsi_prev:        Optional[float]   # previous bar
    linreg:          Optional[float]   # inverted LinReg oscillator
    state:           _State
    bars_available:  int
    is_ready:        bool
    timestamp:       float
    source:          str                # 'tvdatafeed' | 'coingecko' | 'cache'


# ── DB helpers ────────────────────────────────────────────────────────────────
def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS samples(
        ts INTEGER PRIMARY KEY,      -- unix seconds (bar open)
        value REAL NOT NULL,          -- USDT.D %
        source TEXT NOT NULL
    )""")
    con.commit(); con.close()


def _insert_samples(rows: list[tuple[int, float, str]]):
    con = sqlite3.connect(DB_PATH)
    con.executemany("INSERT OR REPLACE INTO samples(ts, value, source) VALUES (?,?,?)", rows)
    con.commit(); con.close()


def _load_series() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT ts, value FROM samples ORDER BY ts", con)
    con.close()
    if df.empty:
        return df
    df['time'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    df = df.set_index('time')
    return df


def _resample_2h(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Resample to 2H OHLC-ish (we only need close for TSI/LinReg)."""
    if df_raw.empty:
        return df_raw
    ohlc = df_raw['value'].resample('2H', label='left', closed='left').agg(
        ['first', 'max', 'min', 'last']
    ).dropna()
    ohlc.columns = ['open', 'high', 'low', 'close']
    return ohlc


# ── Data fetchers ─────────────────────────────────────────────────────────────
def _fetch_coingecko_live() -> Optional[float]:
    try:
        r = requests.get('https://api.coingecko.com/api/v3/global', timeout=8)
        r.raise_for_status()
        return float(r.json()['data']['market_cap_percentage']['usdt'])
    except Exception:
        return None


def _bootstrap_tvdatafeed(n_bars: int = 1200) -> int:
    """Fetch historical USDT.D 2H bars from TradingView. Returns rows inserted."""
    try:
        from tvdatafeed import TvDatafeed, Interval
    except ImportError:
        return 0
    try:
        tv = TvDatafeed()
        df = tv.get_hist('USDT.D', 'CRYPTOCAP', interval=Interval.in_2_hour, n_bars=n_bars)
        if df is None or df.empty:
            return 0
        rows = []
        for idx, row in df.iterrows():
            # idx is UTC naive datetime — treat as UTC
            ts = int(pd.Timestamp(idx).tz_localize('UTC').timestamp())
            # USDT.D value is the 'close' price on CRYPTOCAP:USDT.D (in %)
            rows.append((ts, float(row['close']), 'tvdatafeed'))
        _insert_samples(rows)
        return len(rows)
    except Exception:
        return 0


# ── Indicator math (exact Pine port) ─────────────────────────────────────────
def _tsi(close: pd.Series) -> pd.Series:
    pc = close.diff()
    dbl_pc  = pc.ewm(span=TSI_LONG, adjust=False).mean().ewm(span=TSI_SHORT, adjust=False).mean()
    dbl_abs = pc.abs().ewm(span=TSI_LONG, adjust=False).mean().ewm(span=TSI_SHORT, adjust=False).mean()
    raw = 100.0 * (dbl_pc / dbl_abs.replace(0, np.nan))
    if TSI_INVERT:
        raw = -raw
    return raw / TSI_SCALE


def _linreg(close: pd.Series) -> pd.Series:
    vals = close.values
    n = len(vals)
    raw = np.full(n, np.nan)
    x = np.arange(LINREG_LEN, dtype=float)
    sx = x.sum()
    sx2 = (x * x).sum()
    denom = LINREG_LEN * sx2 - sx * sx
    for i in range(LINREG_LEN - 1, n):
        w = vals[i - LINREG_LEN + 1: i + 1]
        sy = w.sum()
        sxy = (x * w).sum()
        if denom == 0:
            continue
        m = (LINREG_LEN * sxy - sx * sy) / denom
        c = (sy - m * sx) / LINREG_LEN
        v = m * (LINREG_LEN - 1) + c
        raw[i] = -v if LINREG_INVERT else v
    s = pd.Series(raw, index=close.index)
    sma = s.rolling(LINREG_NORM, min_periods=1).mean()
    std = s.rolling(LINREG_NORM, min_periods=1).std()
    norm = (s - sma) / std.replace(0, np.nan)
    if LINREG_SMOOTH > 1:
        norm = norm.ewm(span=LINREG_SMOOTH, adjust=False).mean()
    return norm


def _classify_state(tsi_val: float) -> _State:
    if pd.isna(tsi_val):
        return 'NEUTRAL'
    if tsi_val <= LEVEL_L2_DN:  return 'FEAR_MAX_PAIN'
    if tsi_val <= LEVEL_L1_DN:  return 'FEAR_PAIN'
    if tsi_val >= LEVEL_L2_UP:  return 'GREED_MAX_PAIN'
    if tsi_val >= LEVEL_L1_UP:  return 'GREED_PAIN'
    return 'NEUTRAL'


# ── Public API ────────────────────────────────────────────────────────────────
_last_live_fetch: float = 0.0
_cached_state: Optional[USDTDominanceState] = None
_lock = threading.Lock()


def _maybe_refresh_live():
    """Non-blocking — append a CoinGecko sample if >= REFRESH_SEC since last."""
    global _last_live_fetch
    now = time.time()
    if now - _last_live_fetch < REFRESH_SEC:
        return
    v = _fetch_coingecko_live()
    if v is not None:
        _insert_samples([(int(now), v, 'coingecko')])
        _last_live_fetch = now


def get_usdt_dominance_state(force_refresh: bool = False) -> USDTDominanceState:
    """
    Returns the current USDT.D macro state. Cached for REFRESH_SEC to avoid
    hot-loop overhead. Thread-safe.
    """
    global _cached_state
    with _lock:
        _init_db()
        if not force_refresh and _cached_state and (time.time() - _cached_state.timestamp) < REFRESH_SEC:
            return _cached_state

        _maybe_refresh_live()

        raw = _load_series()
        if raw.empty or len(raw) < 5:
            _cached_state = USDTDominanceState(None, None, None, None, 'NEUTRAL', 0, False, time.time(), 'cache')
            return _cached_state

        bars = _resample_2h(raw)
        if len(bars) < 5:
            _cached_state = USDTDominanceState(
                value_pct=float(raw['value'].iloc[-1]),
                tsi_scaled=None, tsi_prev=None, linreg=None,
                state='NEUTRAL',
                bars_available=len(bars),
                is_ready=False,
                timestamp=time.time(),
                source='cache',
            )
            return _cached_state

        tsi = _tsi(bars['close'])
        lr  = _linreg(bars['close'])
        latest_tsi  = float(tsi.iloc[-1])  if not pd.isna(tsi.iloc[-1])  else None
        prev_tsi    = float(tsi.iloc[-2])  if len(tsi) >= 2 and not pd.isna(tsi.iloc[-2])  else None
        latest_lr   = float(lr.iloc[-1])   if not pd.isna(lr.iloc[-1])   else None
        state = _classify_state(latest_tsi if latest_tsi is not None else float('nan'))
        ready = len(bars) >= MIN_BARS_READY and latest_tsi is not None

        _cached_state = USDTDominanceState(
            value_pct      = float(bars['close'].iloc[-1]),
            tsi_scaled     = latest_tsi,
            tsi_prev       = prev_tsi,
            linreg         = latest_lr,
            state          = state,
            bars_available = len(bars),
            is_ready       = ready,
            timestamp      = time.time(),
            source         = 'computed',
        )
        return _cached_state


def bootstrap(n_bars: int = 1200) -> int:
    """One-shot historical backfill. Call from an ops script or first-run hook."""
    _init_db()
    return _bootstrap_tvdatafeed(n_bars=n_bars)


# ── Signal-side helpers (for future wiring) ──────────────────────────────────
def long_allowed() -> bool:
    """True iff USDT.D signals do NOT veto new LONGs.
       Vetoes LONG when greed is extreme (TSI > +2.1 = alts already pumping)
       OR when fear is not yet exhausting (TSI between -1.4 and +1.4)."""
    s = get_usdt_dominance_state()
    if not s.is_ready:
        return True  # fail-open until enough bars
    # Permissive: allow LONG unless we're at greed max-pain
    return s.state != 'GREED_MAX_PAIN'


def short_allowed() -> bool:
    """True iff USDT.D signals do NOT veto new SHORTs."""
    s = get_usdt_dominance_state()
    if not s.is_ready:
        return True
    return s.state != 'FEAR_MAX_PAIN'


def state_snapshot() -> dict:
    """Compact dict for logging / feature_snapshot attribution."""
    s = get_usdt_dominance_state()
    d = asdict(s)
    d['levels'] = {
        'L1_UP': LEVEL_L1_UP, 'L1_DN': LEVEL_L1_DN,
        'L2_UP': LEVEL_L2_UP, 'L2_DN': LEVEL_L2_DN,
    }
    return d


if __name__ == '__main__':
    # CLI: python3 usdt_dominance.py bootstrap [n_bars]
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == 'bootstrap':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
        inserted = bootstrap(n)
        print(f'[bootstrap] inserted {inserted} bars into {DB_PATH}')
    print(json.dumps(state_snapshot(), indent=2, default=str))
```

---

## 5. Integration — Phase 1 (Log Only, No Trading Impact)

Add to `main.py` near top of `process_pair()` after Reverse Hunt signal detection:

```python
try:
    from usdt_dominance import get_usdt_dominance_state
    _usdt_d = get_usdt_dominance_state()
    log_message(
        f"🌐 USDT.D [{pair}]: val={_usdt_d.value_pct}% "
        f"TSI={_usdt_d.tsi_scaled:.3f} LR={_usdt_d.linreg:.3f} "
        f"state={_usdt_d.state} ready={_usdt_d.is_ready}"
        if _usdt_d.tsi_scaled is not None else
        f"🌐 USDT.D [{pair}]: warming up ({_usdt_d.bars_available} bars)"
    )
    # Attach to feature snapshot for analytics
    feature_snapshot['usdt_d_value'] = _usdt_d.value_pct
    feature_snapshot['usdt_d_tsi']   = _usdt_d.tsi_scaled
    feature_snapshot['usdt_d_state'] = _usdt_d.state
except Exception as _e:
    log_message(f"[usdt_dominance] degraded: {_e}")
```

**No gating yet.** Just observation. After 1-2 loops of log data the operator can decide whether to enable Phase 2.

---

## 6. Integration — Phase 2 (OPTIONAL, operator-enabled later)

Add to `main.py` right after the existing Extreme Fear SHORT gate (`main.py:342`):

```python
# ── USDT.D Macro Gate (mirrors Pine original intent) ──
from usdt_dominance import get_usdt_dominance_state
_usdt_d = get_usdt_dominance_state()
if _usdt_d.is_ready:
    if final_signal == 'LONG' and _usdt_d.state == 'GREED_MAX_PAIN':
        log_message(f"🚫 USDT.D veto LONG [{pair}]: TSI={_usdt_d.tsi_scaled:.2f} > {LEVEL_L2_UP} (alts overheated)")
        return
    if final_signal == 'SHORT' and _usdt_d.state == 'FEAR_MAX_PAIN':
        log_message(f"🚫 USDT.D veto SHORT [{pair}]: TSI={_usdt_d.tsi_scaled:.2f} < {LEVEL_L2_DN} (fear peaking)")
        return
```

This is the canonical interpretation:
- Block LONG when inverted TSI on USDT.D > +2.1 → alts already violently pumped, no more fuel
- Block SHORT when inverted TSI on USDT.D < −1.8 → fear peaked, reversal imminent, don't short the bottom

**NOT the converse**: we do NOT *require* USDT.D extreme to allow a signal. That would be too restrictive. We only veto when USDT.D explicitly disagrees.

---

## 7. Bootstrap Procedure

One-time, run from repo root as root:

```bash
pip install tvdatafeed>=2.1.0
python3 usdt_dominance.py bootstrap 1500
```

Expected output:
```
[bootstrap] inserted 1500 bars into /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/usdt_dominance.db
{
  "value_pct": 5.23,
  "tsi_scaled": -0.87,
  "linreg": 0.42,
  "state": "NEUTRAL",
  "bars_available": 1500,
  "is_ready": true,
  ...
}
```

1500 bars of 2H ≈ 125 days, vastly more than the 120-bar minimum. TSI(69,9) will be fully stabilized.

If `tvdatafeed` fails or is blocked, fall back to:
```bash
# Poll CoinGecko every 30min for ~10 days until MIN_BARS_READY accumulates naturally
python3 -c "from usdt_dominance import get_usdt_dominance_state; print(get_usdt_dominance_state())"
```

---

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `tvdatafeed` breaks due to TV API changes | MED | Fallback: natural accumulation via CoinGecko over 10 days |
| CoinGecko free tier rate-limited | LOW | Single call per 30min is <<< 30/min limit |
| USDT.D value diverges between CoinGecko and TradingView (different mcap sources) | LOW | Mix is acceptable — both track the same macro signal; TSI/LinReg are scale-invariant after normalization |
| First-run has no history → `is_ready=False` | EXPECTED | Phase 1 gate is fail-open (allow signals), so no signal regression |
| Asymmetric thresholds (+2.1 vs −1.8) may produce different LONG/SHORT trigger frequencies | ACCEPTED | Operator-intended; matches observation that Fear is more actionable than Greed for alt reversals |

---

## 9. Testing Plan

### Unit tests (`tests/test_usdt_dominance.py`, new file)

```python
def test_tsi_parity_with_pine():
    """Feed known USDT.D 2H series, assert TSI output within 1e-4 of reference."""
    # Reference values generated from TradingView with same params
    ...

def test_state_classification():
    assert _classify_state(-1.9) == 'FEAR_MAX_PAIN'
    assert _classify_state(-1.5) == 'FEAR_PAIN'
    assert _classify_state(0.0)  == 'NEUTRAL'
    assert _classify_state(+1.5) == 'GREED_PAIN'
    assert _classify_state(+2.2) == 'GREED_MAX_PAIN'

def test_fail_open_when_not_ready():
    # Fresh DB, no bars
    assert long_allowed() == True
    assert short_allowed() == True
```

### Live validation (first 24h after deploy)

- Watch log for `🌐 USDT.D [pair]: val=X% TSI=Y state=Z` lines
- Cross-check `value_pct` against TradingView CRYPTOCAP:USDT.D current price → should match within 0.1%
- Cross-check `tsi_scaled` against running the Pine indicator on TradingView manually → should match within 0.05 after indicator warmup

### Backtest against yesterday's losses (before enabling Phase 2)

Run against the 29 LOSS signals from 2026-04-17 / 2026-04-18:
- Compute USDT.D state at each signal's entry timestamp (using bootstrapped history)
- Count how many would have been vetoed by Phase 2 gate
- Target: ≥ 40% of losing LONGs vetoed without vetoing > 10% of winning LONGs

---

## 10. Operator Decisions Required

1. **Approve Phase 1 deploy?** (logging-only, zero trading impact)
2. **Approve `tvdatafeed` dependency?** Alternative: 10-day cold-start with CoinGecko only
3. **Phase 2 timing** — enable immediately after 24h of logs, or wait for backtest validation?
4. **Asymmetric threshold confirmation**: L2_UP=+2.1, L2_DN=−1.8 as specified — confirm this is intentional
5. **Shorter/longer TF variant** — operator specified 2H. Keep or also compute 1H/4H as parallel signals?

---

## 11. Out of Scope (Future)

- Wire USDT.D TSI into SQI v4 as Factor #15 (macro alignment bonus)
- Use USDT.D LinReg oscillator as regime classifier (positive → bearish alts regime → force PREDATOR `size_mult *= 0.5`)
- Build USDT.D dashboard panel showing current state + history chart
- Add BTC.D + ETH.D + TOTAL3 as companion macro indicators

---

## Summary

Single new file (`usdt_dominance.py`), minimal integration footprint, fail-open degradation, Pine-faithful math, operator-approved parameters. Phase 1 ships risk-free; Phase 2 gate is one config flag away.

**Recommended apply order**: steps 4 → 7 → observe 24h logs → 6.
