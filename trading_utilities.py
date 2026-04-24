
import numpy as np
import pandas as pd
from datetime import datetime, time, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    _SKOPJE_TZ = ZoneInfo('Europe/Skopje')
except Exception:
    _SKOPJE_TZ = None  # fallback to naive local time if zoneinfo unavailable
import json
import os

# Aladdin Rust Core Integration (availability check in rust_integration.py)
from rust_integration import RUST_CORE_AVAILABLE
if RUST_CORE_AVAILABLE:
    import aladdin_core
import time as time_module
import uuid
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from utils_logger import log_message, log_message as log_msg

# ══════════════════════════════════════════════════════════════════════
#  Equity-Perp Market Hours Filter
#  Binance lists tokenized stock / ETF perpetuals (TSLA, NVDA, SPY, QQQ …)
#  that track assets whose underlying market is closed on weekends.
#  Signals generated while the underlying market is shut use stale candles
#  and should be skipped.
# ══════════════════════════════════════════════════════════════════════

# Seed set — manually curated. Expanded at runtime by
# `discover_equity_perps_from_exchange()` which scans Binance exchangeInfo
# for perp pairs whose base asset matches a known US-listed ticker.
EQUITY_PERP_PAIRS = {
    # US stocks
    'TSLAUSDT', 'NVDAUSDT', 'AAPLUSDT', 'MSTRUSDT', 'COINUSDT', 'HOODUSDT',
    'PAYPUSDT', 'CRCLUSDT', 'CRWVUSDT', 'PLTRUSDT', 'AMZNUSDT', 'MSFTUSDT',
    'METAUSDT', 'GOOGLUSDT', 'GOOGUSDT', 'NFLXUSDT', 'AMDUSDT', 'SMCIUSDT',
    'MARAUSDT', 'RIOTUSDT', 'BABAUSDT', 'NIOUSDT', 'DISUSDT', 'MCDUSDT',
    'PYPLUSDT', 'UBERUSDT', 'ABNBUSDT', 'SHOPUSDT', 'SNAPUSDT', 'SBUXUSDT',
    'INTCUSDT', 'ORCLUSDT', 'CSCOUSDT', 'JPMUSDT', 'BACUSDT', 'GSUSDT',
    # US ETFs
    'SPYUSDT', 'QQQUSDT', 'IWMUSDT', 'DIAUSDT', 'GLDUSDT', 'TLTUSDT',
    'VOOUSDT', 'VTIUSDT', 'EEMUSDT',
}

# Known US-listed tickers (stocks + ETFs). Used by the auto-discovery
# pass to recognise newly listed Binance equity-perps without a manual
# update. Conservative list — only tickers with no known crypto conflict.
# Excludes ambiguous 3-letter tickers that overlap crypto symbols
# (e.g. "F" for Ford vs crypto token F, "V" for Visa, "T" for AT&T).
_US_EQUITY_TICKERS = frozenset({
    # Mega-cap tech
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO',
    'ORCL', 'AMD', 'INTC', 'CSCO', 'IBM', 'QCOM', 'TXN', 'ADBE', 'CRM',
    'NFLX', 'INTU', 'NOW', 'PLTR', 'SHOP', 'PANW', 'CRWD', 'SNOW', 'DDOG',
    # Crypto-adjacent equities
    'COIN', 'MSTR', 'HOOD', 'MARA', 'RIOT', 'CLSK', 'HUT', 'BITF', 'CORZ',
    'CIFR', 'BTBT', 'WULF', 'IREN', 'BTDR',
    # Fintech / payments
    'PYPL', 'PAYP', 'SQ', 'AFRM', 'SOFI', 'UPST',
    # Retail / consumer (excl. "W" — overlaps Wormhole token)
    'WMT', 'TGT', 'COST', 'HD', 'LOW', 'MCD', 'SBUX', 'CMG', 'NKE', 'LULU',
    'DIS', 'CMCSA', 'NFLX', 'EBAY', 'ETSY', 'RH',
    # Travel / rideshare
    'UBER', 'LYFT', 'ABNB', 'BKNG', 'EXPE', 'DAL', 'UAL', 'AAL', 'LUV',
    # Financials (excl. single-letter tickers like "C" that collide with crypto)
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'BLK', 'SCHW', 'AXP', 'COF',
    # Energy / materials (excl. "CVX" — overlaps Convex Finance token)
    'XOM', 'COP', 'OXY', 'HAL', 'SLB', 'FCX', 'NEM',
    # Healthcare / biotech
    'JNJ', 'PFE', 'MRK', 'ABBV', 'LLY', 'UNH', 'CVS', 'MRNA', 'BNTX',
    'NVAX', 'BIIB', 'REGN', 'VRTX', 'GILD', 'AMGN',
    # EV / auto (excl. "F" — overlaps crypto token F)
    'NIO', 'LI', 'XPEV', 'RIVN', 'LCID', 'GM', 'STLA',
    # China ADRs
    'BABA', 'JD', 'PDD', 'BIDU', 'NTES',
    # Growth / meme / speculative (excl. "OPEN" — overlaps OpenDAO token)
    'GME', 'AMC', 'BBBY', 'SOFI', 'WISH', 'CLOV', 'SNDL',
    # New IPOs / recent listings
    'CRCL', 'CRWV', 'SMCI', 'ARM', 'KLAR', 'CART', 'HIMS', 'HIMX', 'SOUN',
    # ETFs
    'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI', 'EEM', 'EFA', 'VEA', 'VWO',
    'GLD', 'SLV', 'USO', 'UUP', 'TLT', 'IEF', 'HYG', 'LQD', 'XLK', 'XLF',
    'XLE', 'XLV', 'XLI', 'XLP', 'XLY', 'XLU', 'XLB', 'XLRE', 'ARKK', 'ARKW',
})

# Base assets that are both a common crypto AND a US ticker — treat as crypto.
# Keeps the heuristic safe: if a pair's base is in this set, don't auto-flag
# as an equity-perp even if the ticker exists on NYSE.
_CRYPTO_TICKER_EXCLUDES = frozenset({
    'BTC', 'ETH', 'BNB', 'SOL', 'ADA', 'XRP', 'DOT', 'LINK', 'UNI', 'AAVE',
    'APE', 'AR', 'AXS', 'BAT', 'CAKE', 'CHZ', 'COMP', 'CRO', 'DOGE', 'EOS',
    'FTM', 'GRT', 'ICP', 'KDA', 'LTC', 'MATIC', 'NEAR', 'OP', 'SAND', 'SHIB',
    'SNX', 'SUSHI', 'TRX', 'VET', 'XLM', 'XMR', 'XTZ', 'ZEC', 'ZIL',
    # Ambiguous single-letter / short tickers that collide with crypto tokens
    'C', 'CVX', 'F', 'W', 'OPEN',
})

try:
    _ET_TZ = ZoneInfo('America/New_York')
except Exception:
    _ET_TZ = None


def is_equity_perp(pair: str) -> bool:
    """True if the pair tracks a traditional equity / ETF listed on US markets."""
    return pair.upper() in EQUITY_PERP_PAIRS


def discover_equity_perps_from_exchange(client) -> int:
    """Expand `EQUITY_PERP_PAIRS` by scanning Binance Futures exchangeInfo
    for any USDT perpetual whose base asset matches a known US ticker.

    Returns the number of newly discovered pairs. Safe to call at startup;
    silently skips on error (keeps the manual seed set intact).
    """
    try:
        info = client.futures_exchange_info()
    except Exception as exc:
        log_message(f"[equity-gate] exchangeInfo fetch failed: {exc}")
        return 0

    new_count = 0
    for s in info.get('symbols', []):
        if s.get('contractType') != 'PERPETUAL':
            continue
        if s.get('quoteAsset') != 'USDT':
            continue
        base = (s.get('baseAsset') or '').upper()
        pair = (s.get('symbol') or '').upper()
        if not base or not pair:
            continue
        if pair in EQUITY_PERP_PAIRS:
            continue
        if base in _CRYPTO_TICKER_EXCLUDES:
            continue
        if base in _US_EQUITY_TICKERS:
            EQUITY_PERP_PAIRS.add(pair)
            new_count += 1
    if new_count:
        log_message(f"[equity-gate] auto-discovered {new_count} new equity-perp pairs "
                    f"from Binance exchangeInfo (total={len(EQUITY_PERP_PAIRS)})")
    return new_count


# ── NYSE Holiday Calendar ────────────────────────────────────────────
# Full-market closures (equity markets closed all day). Dates are in the
# US/Eastern timezone. Refresh annually — NYSE publishes next year's
# calendar in advance.  Early-close days (1pm ET) are NOT treated as
# closed, since equity futures still trade.
NYSE_FULL_CLOSURES = frozenset({
    # 2026
    '2026-01-01',  # New Year's Day
    '2026-01-19',  # MLK Day
    '2026-02-16',  # Presidents Day
    '2026-04-03',  # Good Friday
    '2026-05-25',  # Memorial Day
    '2026-06-19',  # Juneteenth
    '2026-07-03',  # Independence Day (Jul 4 = Sat → observed Fri)
    '2026-09-07',  # Labor Day
    '2026-11-26',  # Thanksgiving
    '2026-12-25',  # Christmas
    # 2027
    '2027-01-01',  # New Year's Day
    '2027-01-18',  # MLK Day
    '2027-02-15',  # Presidents Day
    '2027-03-26',  # Good Friday
    '2027-05-31',  # Memorial Day
    '2027-06-18',  # Juneteenth (Jun 19 = Sat → observed Fri)
    '2027-07-05',  # Independence Day (Jul 4 = Sun → observed Mon)
    '2027-09-06',  # Labor Day
    '2027-11-25',  # Thanksgiving
    '2027-12-24',  # Christmas (Dec 25 = Sat → observed Fri)
    # 2028
    '2028-01-17',  # MLK Day
    '2028-02-21',  # Presidents Day
    '2028-04-14',  # Good Friday
    '2028-05-29',  # Memorial Day
    '2028-06-19',  # Juneteenth
    '2028-07-04',  # Independence Day
    '2028-09-04',  # Labor Day
    '2028-11-23',  # Thanksgiving
    '2028-12-25',  # Christmas
})


def is_us_equity_market_open() -> bool:
    """True while US stock-index futures are actively trading.

    Closed windows:
      • Friday   ≥ 17:00 ET    (weekly close)
      • Saturday — all day
      • Sunday   < 18:00 ET    (weekly open)
      • NYSE full-closure holidays (see NYSE_FULL_CLOSURES)
    """
    if _ET_TZ is not None:
        now_et = datetime.now(_ET_TZ)
    else:
        # EST/EDT fallback: assume EST (UTC-5). Close enough for weekend logic.
        now_et = datetime.utcnow() - timedelta(hours=5)

    # NYSE full closure for today's date in ET
    if now_et.strftime('%Y-%m-%d') in NYSE_FULL_CLOSURES:
        return False

    wd = now_et.weekday()  # Mon=0 … Sun=6
    h = now_et.hour
    if wd == 5:                    # Saturday
        return False
    if wd == 4 and h >= 17:        # Friday after 5pm ET
        return False
    if wd == 6 and h < 18:         # Sunday before 6pm ET
        return False
    return True


def is_prime_trading_session():
    """Check if current time is within high-volatility session overlaps.

    Anchored to Europe/Skopje (CET/CEST) — server local time.
    London and NY are the highest-volume sessions; Tokyo is secondary.
    """
    now = datetime.now(_SKOPJE_TZ).time() if _SKOPJE_TZ is not None else datetime.now().time()
    london_start, london_end = time(8, 0), time(16, 0)
    ny_start, ny_end = time(13, 0), time(21, 0)
    tokyo_start, tokyo_end = time(0, 0), time(8, 0)

    in_london = london_start <= now <= london_end
    in_ny = ny_start <= now <= ny_end
    in_tokyo = tokyo_start <= now <= tokyo_end
    return in_london or in_ny or (in_tokyo and now >= time(2,0))

def get_order_book_imbalance(client, symbol):
    """Calculate the bid/ask volume imbalance ratio"""
    try:
        depth = client.futures_order_book(symbol=symbol, limit=20)
        bids, asks = depth.get('bids', []), depth.get('asks', [])
        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        if ask_vol == 0: return 2.0
        return bid_vol / ask_vol
    except Exception:
        return 1.0

# Cache BTC klines so we don't re-fetch for every pair in the cycle
_BTC_CORR_KLINE_CACHE = {'klines': None, 'timestamp': 0, 'timeframe': None, 'limit': 0}
_BTC_CORR_KLINE_TTL = 60  # refresh every 60 seconds

def calculate_pearson_correlation(client, symbol1, symbol2='BTCUSDT', timeframe='1h', limit=25):
    """Calculate the 24h Pearson correlation using percentage RETURNS (not raw prices)"""
    try:
        k1 = client.futures_klines(symbol=symbol1, interval=timeframe, limit=limit)

        # Use cached BTC klines to avoid ~500 redundant API calls per cycle
        now = time_module.time()
        cache = _BTC_CORR_KLINE_CACHE
        if (cache['klines'] is not None
                and now - cache['timestamp'] < _BTC_CORR_KLINE_TTL
                and cache['timeframe'] == timeframe
                and cache['limit'] == limit):
            k2 = cache['klines']
        else:
            k2 = client.futures_klines(symbol=symbol2, interval=timeframe, limit=limit)
            cache['klines'] = k2
            cache['timestamp'] = now
            cache['timeframe'] = timeframe
            cache['limit'] = limit
        
        # Use pct_change on close prices to get returns correlation
        c1 = pd.Series([float(k[4]) for k in k1]).pct_change().dropna()
        c2 = pd.Series([float(k[4]) for k in k2]).pct_change().dropna()
        
        if len(c1) < 10 or len(c2) < 10: return 0.7
        
        correlation = c1.corr(c2)
        return correlation if not pd.isna(correlation) else 0.7
    except Exception:
        return 0.7

def check_btc_correlation(client, signal_type, symbol=None):
    """Check if BTC is moving in the same direction and calculate strength"""
    try:
        btc_klines = client.futures_klines(symbol='BTCUSDT', interval='15m', limit=5)
        closes = [float(k[4]) for k in btc_klines]
        btc_trend = 'LONG' if closes[-1] > closes[0] else 'SHORT'
        
        direction_match = btc_trend == signal_type.upper()
        
        correlation_strength = 0.7
        if symbol:
            correlation_strength = calculate_pearson_correlation(client, symbol)
            
        return direction_match, correlation_strength
    except Exception:
        return True, 0.7

_BTC_REGIME_CACHE = {'regime': 'neutral', 'timestamp': 0}
_BTC_REGIME_TTL = 1800  # refresh every 30 minutes

def get_btc_htf_regime(client) -> str:
    """Return 'bullish', 'bearish', or 'neutral' based on BTC 1h SMA20/SMA50.

    Bullish:  price > SMA20 AND SMA20 > SMA50
    Bearish:  price < SMA20 AND SMA20 < SMA50
    Neutral:  anything else (transitioning / conflicting)

    Result is cached for 30 minutes so it costs only one API call per half-hour
    regardless of how many pairs are scanned.
    """
    import time as _t
    now = _t.time()
    if now - _BTC_REGIME_CACHE['timestamp'] < _BTC_REGIME_TTL:
        return _BTC_REGIME_CACHE['regime']
    try:
        klines = client.futures_klines(symbol='BTCUSDT', interval='1h', limit=55)
        closes = [float(k[4]) for k in klines]
        price = closes[-1]
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50
        if price > sma20 and sma20 > sma50:
            regime = 'bullish'
        elif price < sma20 and sma20 < sma50:
            regime = 'bearish'
        else:
            regime = 'neutral'
        _BTC_REGIME_CACHE['regime'] = regime
        _BTC_REGIME_CACHE['timestamp'] = now
        log_message(f"📊 BTC 1h HTF Regime: {regime.upper()} (price={price:.0f} SMA20={sma20:.0f} SMA50={sma50:.0f})")
        return regime
    except Exception as e:
        log_message(f"BTC HTF regime fetch error: {e}")
        return _BTC_REGIME_CACHE.get('regime', 'neutral')


def assign_leverage(confidence: float, signal_type: str, pair: str = None) -> int:
    """Assign leverage based on confidence — smooth scaling from 2x to 25x.
    
    Confidence layers NO LONGER reject signals. Instead, every validated
    Reverse Hunt signal is sent, and confidence determines leverage:
    
      Confidence   Leverage
      ─────────────────────
      0.00 – 0.30    2x     (minimum — low conviction)
      0.30 – 0.45    3x     
      0.45 – 0.55    5x     
      0.55 – 0.65    8x     
      0.65 – 0.75   12x     
      0.75 – 0.85   18x     
      0.85 – 1.00   25x     (maximum — full conviction)
    
    High-volatility tokens are capped at 5x regardless of confidence.
    """
    # Smooth tiered mapping
    if confidence >= 0.85:
        base_lev = 25
    elif confidence >= 0.75:
        base_lev = 18
    elif confidence >= 0.65:
        base_lev = 12
    elif confidence >= 0.55:
        base_lev = 8
    elif confidence >= 0.45:
        base_lev = 5
    elif confidence >= 0.30:
        base_lev = 3
    else:
        base_lev = 2  # Minimum — never reject, just use low leverage
    
    # Pair-specific caps for ultra-volatile tokens (ATR% > 5%)
    high_risk_pairs = {
        'PUMPUSDT', 'XANUSDT', 'COSUSDT', 'LEVERUSDT', 
        'TROYUSDT', '1000SATSUSDT', 'PEPEUSDT', 'FLOKIUSDT'
    }
    if pair in high_risk_pairs:
        base_lev = min(base_lev, 5)

    return max(2, min(25, int(base_lev)))


def institutional_risk_adjust(entry, ce_stop, targets, atr, signal_direction, precision, adx=20.0, df=None):
    """
    Institutional-grade risk/reward adjustment.

    Problem: CE Line stop (ATR=22, mult=3.0) can be 10-20% from entry on volatile
    micro-caps, while ATR-based TPs are only 3-5% away → terrible R:R.

    Solution — 5-layer hybrid:
    ┌──────────────────────────────────────────────────────────────────────────┐
    │ Layer 1: SL CAP — min(CE_stop, 2.5×ATR, 6% hard cap)                  │
    │          Keeps minimum 0.5×ATR to avoid noise stopouts.                │
    │ Layer 2: TP SCALING — TPs guaranteed ≥ [1.0, 1.5, 2.5]× risk distance │
    │          Original TPs kept if already wider (VP/FVG magnets).          │
    │ Layer 3: REALISM CAP — No TP beyond 15% from entry.                   │
    │ Layer 4: SIZE PENALTY — If CE was wider than cap, reduce position      │
    │          proportionally (min 25% of base size).                        │
    │ Layer 5: LEVERAGE DAMP — Wide-stop trades get leverage reduced by      │
    │          ratio of (capped_risk / entry) to keep $ risk constant.       │
    └──────────────────────────────────────────────────────────────────────────┘

    Returns dict with adjusted SL, TPs, size_multiplier, leverage_dampener, rr,
    or None if signal should be rejected (R:R < 1.0 after all adjustments).
    """
    is_long = signal_direction.upper() in ['LONG', 'BUY']
    sign = 1 if is_long else -1

    # ── Layer 1: Cap SL distance ─────────────────────────────────────────
    raw_risk = abs(entry - ce_stop)
    raw_risk_pct = raw_risk / entry if entry > 0 else 0

    # Trending markets (ADX > 30) get slightly wider stops: 3.0×ATR cap
    # Ranging markets (ADX < 20): tighter 2.0×ATR cap
    # Default: 2.5×ATR
    atr_mult_cap = 3.0 if adx > 30 else 2.0 if adx < 20 else 2.5
    atr_cap = atr_mult_cap * atr
    hard_cap = entry * 0.06          # 6% absolute max
    capped_risk = min(raw_risk, atr_cap, hard_cap)

    # Floor: minimum 0.5×ATR to avoid getting stopped by normal noise
    min_risk = 0.5 * atr
    capped_risk = max(capped_risk, min_risk)

    stop_loss = entry - sign * capped_risk

    # ── Swing Level Snap (ZigZag-style pivot detection) ───────────────
    # If a significant swing low (LONG) / swing high (SHORT) sits within
    # 0.5×ATR of our computed stop, snap to it for a more natural placement.
    try:
        if df is not None and len(df) >= 20:
            _highs = df['high'].values
            _lows  = df['low'].values
            left_bars, right_bars = 5, 2
            swing_candidates = []
            end_idx = len(_lows) - right_bars - 1
            for i in range(left_bars, end_idx):
                if is_long:
                    if (all(_lows[i] <= _lows[i - j] for j in range(1, left_bars + 1)) and
                            all(_lows[i] <= _lows[i + j] for j in range(1, right_bars + 1))):
                        swing_candidates.append(_lows[i])
                else:
                    if (all(_highs[i] >= _highs[i - j] for j in range(1, left_bars + 1)) and
                            all(_highs[i] >= _highs[i + j] for j in range(1, right_bars + 1))):
                        swing_candidates.append(_highs[i])
            if swing_candidates:
                # SAFE-SIDE FILTER: a snap must move the stop DEEPER (away from
                # entry), never tighter. For LONG this means swing_low ≤ current
                # stop_loss; for SHORT swing_high ≥ current stop_loss.
                if is_long:
                    safe = [s for s in swing_candidates if s <= stop_loss]
                else:
                    safe = [s for s in swing_candidates if s >= stop_loss]
                if safe:
                    nearest = min(safe, key=lambda s: abs(s - stop_loss))
                    if abs(nearest - stop_loss) <= 0.5 * atr:
                        stop_loss = nearest
    except Exception:
        pass

    # ── Post-snap safety: re-enforce minimum distance floors ─────────
    # Guarantees SL is never tighter than max(0.5×ATR, 0.25% of entry) after
    # any swing snap or rounding. Prevents degenerate R:R ≫ 10:1 signals.
    _min_dist = max(0.5 * atr, entry * 0.0025)
    if abs(entry - stop_loss) < _min_dist:
        stop_loss = entry - sign * _min_dist
        capped_risk = _min_dist

    # ── Layer 2: Scale TPs to guarantee minimum R:R ──────────────────────
    # Institutional standard: TP1=1:1, TP2=1.5:1, TP3=2.5:1
    rr_steps = [1.0, 1.5, 2.5]
    min_tps = [entry + sign * capped_risk * step for step in rr_steps]

    # Merge: keep the BETTER of original TP or R:R-minimum TP
    adj_targets = []
    for i in range(min(3, len(targets))):
        orig = targets[i]
        rr_floor = min_tps[i] if i < len(min_tps) else orig
        if is_long:
            adj_targets.append(max(orig, rr_floor))
        else:
            adj_targets.append(min(orig, rr_floor))

    # Fill to 3 if needed
    while len(adj_targets) < 3 and len(adj_targets) < len(min_tps):
        adj_targets.append(min_tps[len(adj_targets)])

    # ── Layer 3: Realism cap — no TP beyond 15% from entry ──────────────
    max_tp_pct = 0.15
    for i in range(len(adj_targets)):
        dist = abs(adj_targets[i] - entry)
        if dist / entry > max_tp_pct:
            adj_targets[i] = entry + sign * entry * max_tp_pct

    # ── Layer 4: Position size penalty ───────────────────────────────────
    # If CE stop was wider than our cap, the pair is more volatile than our
    # SL can cover. Reduce position size proportionally to compensate.
    if raw_risk > 0 and raw_risk > capped_risk:
        size_multiplier = capped_risk / raw_risk
        size_multiplier = max(0.25, min(1.0, size_multiplier))  # 25%-100%
    else:
        size_multiplier = 1.0

    # ── Layer 5: Leverage dampener ───────────────────────────────────────
    # Wide-risk trades need lower leverage to keep notional risk constant.
    # Baseline: 2% risk = full leverage. Scale down proportionally.
    adj_risk_pct = capped_risk / entry if entry > 0 else 0.02
    leverage_dampener = min(1.0, 0.02 / adj_risk_pct) if adj_risk_pct > 0 else 1.0
    leverage_dampener = max(0.3, leverage_dampener)  # floor at 30%

    # ── Final R:R validation ─────────────────────────────────────────────
    best_tp = adj_targets[-1] if adj_targets else entry
    reward = abs(best_tp - entry)
    risk = abs(entry - stop_loss)
    rr = reward / risk if risk > 0 else 0

    # Hard reject: R:R < 1.0 means even TP3 doesn't cover the risk
    if rr < 1.0:
        return None

    return {
        'stop_loss': round(stop_loss, precision),
        'targets': [round(t, precision) for t in adj_targets],
        'size_multiplier': round(size_multiplier, 2),
        'leverage_dampener': round(leverage_dampener, 2),
        'rr': round(rr, 2),
        'sl_capped': raw_risk > capped_risk + 1e-10,
        'raw_risk_pct': round(raw_risk_pct * 100, 2),
        'adj_risk_pct': round(adj_risk_pct * 100, 2),
    }


def detect_market_regime(df):
    """Detect if market is trending or ranging using ADX and BB Width"""
    if len(df) < 30: return "UNKNOWN"
    latest_adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 20
    if 'Upper Band' in df.columns and 'Lower Band' in df.columns and 'SMA_20' in df.columns:
        sma20 = df['SMA_20'].iloc[-1]
        bb_width = (df['Upper Band'].iloc[-1] - df['Lower Band'].iloc[-1]) / sma20 if sma20 > 0 else 0.05
    else:
        bb_width = 0.05
    if latest_adx > 25: return "TRENDING"
    elif bb_width < 0.02: return "RANGING_NARROW"
    else: return "RANGING"


class CircuitBreaker:
    """Manages trading pauses during extreme drawdowns"""
    def __init__(self, log_path="performance_logs/circuit_breaker.json"):
        self.log_path = log_path
        self.load_state()
        
    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    self.state = json.load(f)
            else:
                self.state = {'daily_pnl': 0, 'consecutive_losses': 0, 'last_reset': datetime.now().date().isoformat()}
        except Exception:
            self.state = {'daily_pnl': 0, 'consecutive_losses': 0, 'last_reset': datetime.now().date().isoformat()}

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump(self.state, f)
        except Exception:
            pass

    def check_reset(self):
        today = datetime.now().date().isoformat()
        if self.state['last_reset'] != today:
            self.state['daily_pnl'] = 0
            self.state['consecutive_losses'] = 0
            self.state['last_reset'] = today
            self.save_state()

    def update_pnl(self, pnl):
        self.check_reset()
        self.state['daily_pnl'] += pnl
        if pnl < 0:
            self.state['consecutive_losses'] += 1
        else:
            self.state['consecutive_losses'] = 0
        self.save_state()

    def should_block_trade(self, max_drawdown=-5.0, max_consecutive_losses=3):
        self.check_reset()
        if self.state['daily_pnl'] <= max_drawdown:
            return True, f"Daily drawdown hit ({self.state['daily_pnl']:.2f}%)"
        if self.state['consecutive_losses'] >= max_consecutive_losses:
            return True, f"Max consecutive losses hit ({self.state['consecutive_losses']})"
        return False, ""


def get_symbol_win_rate(symbol, logs_path="performance_logs/cornix_signals.json"):
    """Calculate historical win rate for a specific symbol"""
    try:
        if not os.path.exists(logs_path): return 0.5
        with open(logs_path, 'r') as f:
            signals = json.load(f)
        pair_signals = [s for s in signals.values() if s.get('pair') == symbol]
        if not pair_signals: return 0.5
        wins = sum(1 for s in pair_signals if s.get('status') == 'SUCCESS')
        return wins / len(pair_signals)
    except Exception:
        return 0.5


# ========== PHASE 5: SIGNAL QUALITY ENHANCEMENTS ==========

class PairCooldownManager:
    """Enforces minimum cooldown between signals for the same pair"""
    def __init__(self, cooldown_hours=2):
        self.cooldown_seconds = cooldown_hours * 3600
        self.last_signal_time = {}
    
    def can_send_signal(self, pair):
        now = time_module.time()
        last_time = self.last_signal_time.get(pair, 0)
        elapsed = now - last_time
        if elapsed < self.cooldown_seconds:
            remaining_min = (self.cooldown_seconds - elapsed) / 60
            return False, f"Cooldown active ({remaining_min:.0f}min remaining)"
        return True, ""
    
    def record_signal(self, pair):
        self.last_signal_time[pair] = time_module.time()


class AutoBlacklist:
    """Temporarily blacklists pairs with consecutive losses"""
    def __init__(self, max_consecutive_losses=3, blacklist_hours=24,
                 log_path="performance_logs/pair_blacklist.json"):
        self.max_losses = max_consecutive_losses
        self.blacklist_duration = blacklist_hours * 3600
        self.log_path = log_path
        self.consecutive_losses = {}
        self.blacklisted_until = {}
        self.load_state()
    
    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    data = json.load(f)
                    self.consecutive_losses = data.get('consecutive_losses', {})
                    self.blacklisted_until = data.get('blacklisted_until', {})
        except Exception:
            pass
    
    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump({
                    'consecutive_losses': self.consecutive_losses,
                    'blacklisted_until': self.blacklisted_until
                }, f)
        except Exception:
            pass
    
    def is_blacklisted(self, pair):
        until = self.blacklisted_until.get(pair, 0)
        if time_module.time() < until:
            remaining_h = (until - time_module.time()) / 3600
            return True, f"Blacklisted for {remaining_h:.1f}h ({self.consecutive_losses.get(pair, 0)} consecutive losses)"
        elif until > 0:
            del self.blacklisted_until[pair]
            self.consecutive_losses[pair] = 0
            self.save_state()
        return False, ""
    
    def record_outcome(self, pair, is_win):
        if is_win:
            self.consecutive_losses[pair] = 0
        else:
            self.consecutive_losses[pair] = self.consecutive_losses.get(pair, 0) + 1
            if self.consecutive_losses[pair] >= self.max_losses:
                self.blacklisted_until[pair] = time_module.time() + self.blacklist_duration
        self.save_state()


class DynamicConfidenceThreshold:
    """Raises minimum confidence as daily signal count approaches cap"""
    def __init__(self, max_daily_signals=90):
        self.max_signals = max_daily_signals
        self.tiers = [
            (0.67, 0.45),   # Signals 1-60: 45% min
            (0.89, 0.60),   # Signals 61-80: 60% min
            (1.00, 0.75),   # Signals 81-90: 75% min
        ]
    
    def get_min_confidence(self, current_count):
        fraction = current_count / self.max_signals
        for tier_frac, min_conf in self.tiers:
            if fraction < tier_frac:
                return min_conf
        return self.tiers[-1][1]
    
    def should_send(self, current_count, signal_confidence):
        min_conf = self.get_min_confidence(current_count)
        if signal_confidence < min_conf:
            return False, f"Confidence {signal_confidence:.1%} below dynamic threshold {min_conf:.1%} (#{current_count+1})"
        return True, f"Passed threshold {min_conf:.1%}"


def check_multi_tf_confirmation(df_15m, df_1h, df_4h, signal_direction):
    """Check if at least 2/3 timeframes agree on signal direction (EMA10 vs EMA50)"""
    agreements = 0
    details = []
    
    for df, tf_name in [(df_15m, '15m'), (df_1h, '1h'), (df_4h, '4h')]:
        if df is None or df.empty or len(df) < 50:
            details.append(f"{tf_name}: SKIP")
            continue
        try:
            ema10 = df['EMA_10'].iloc[-1] if 'EMA_10' in df.columns else df['close'].ewm(span=10).mean().iloc[-1]
            ema50 = df['EMA_50'].iloc[-1] if 'EMA_50' in df.columns else df['close'].ewm(span=50).mean().iloc[-1]
            tf_trend = 'LONG' if ema10 > ema50 else 'SHORT'
            
            is_match = tf_trend.upper() in signal_direction.upper() or signal_direction.upper() in tf_trend.upper()
            if is_match:
                agreements += 1
                details.append(f"{tf_name}: ✅")
            else:
                details.append(f"{tf_name}: ❌")
        except Exception:
            details.append(f"{tf_name}: SKIP")
    
    confirmed = agreements >= 2
    return confirmed, agreements, " | ".join(details)


class SignalPrioritizer:
    """Collects pending signals and ranks them by confidence before sending"""
    def __init__(self, max_per_batch=10):
        self.max_per_batch = max_per_batch
        self.pending_signals = []
    
    def add_pending(self, signal_data):
        self.pending_signals.append(signal_data)
    
    def get_top_signals(self, max_signals=None):
        limit = max_signals or self.max_per_batch
        sorted_signals = sorted(self.pending_signals, key=lambda s: s.get('confidence', 0), reverse=True)
        top = sorted_signals[:limit]
        skipped = sorted_signals[limit:]
        self.pending_signals = []
        return top, skipped
    
    def has_pending(self):
        return len(self.pending_signals) > 0
    
    def clear(self):
        self.pending_signals = []


# ========== ALADDIN PHASE 6: MATHEMATICAL PRECISION ==========

class PortfolioCorrelationManager:
    """
    Prevents over-exposure to correlated assets (e.g., all altcoins moving with BTC).
    """
    def __init__(self, max_correlated_exposure=0.3):
        self.max_exposure = max_correlated_exposure
        self.active_weights = {} # {pair: weight}

    def get_correlation_risk(self, pair, active_signals, btc_correlation=0.0):
        """
        Calculates if adding a new pair exceeds the allowed correlated exposure.
        btc_correlation: Correlation of the new pair to BTC.
        """
        # If correlation to BTC is high (>0.7), count it toward the "Market Cluster"
        if btc_correlation > 0.7:
            current_correlated_count = sum(1 for p in active_signals if p != pair)
            if current_correlated_count >= 3: # Max 3 highly correlated signals at once
                return True, f"High Correlation Risk: {current_correlated_count} active BTC-correlated trades"
        
        return False, ""


class RegimePositionSizer:
    """
    Institutional Position Sizing using RL-inspired feedback.
    Scales trade size based on market regime and recent performance.
    """
    def __init__(self, log_path="performance_logs/position_sizer.json"):
        self.log_path = log_path
        self.multiplier = 1.0
        self.recent_outcomes = [] # List of booleans (True=Win)
        self.load_state()

    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    data = json.load(f)
                    self.multiplier = data.get('multiplier', 1.0)
                    self.recent_outcomes = data.get('recent_outcomes', [])
        except Exception:
            pass

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump({
                    'multiplier': self.multiplier,
                    'recent_outcomes': self.recent_outcomes
                }, f)
        except Exception:
            pass

    def record_outcome(self, is_win):
        """PROPOSAL 6: EMA-based Win-Streak Position Sizing."""
        self.recent_outcomes.append(1.0 if is_win else 0.0)
        if len(self.recent_outcomes) > 20:
            self.recent_outcomes.pop(0)
        
        # Calculate EMA of outcomes (more recent trades weighted higher)
        if len(self.recent_outcomes) >= 3:
            alpha = 2.0 / (len(self.recent_outcomes) + 1)
            ema = self.recent_outcomes[0]
            for val in self.recent_outcomes[1:]:
                ema = alpha * val + (1 - alpha) * ema
            # Map EMA (0.0–1.0) → multiplier (0.5–1.5)
            # 50% winrate = 1.0x, 80% = 1.3x, 20% = 0.7x
            self.multiplier = 0.5 + ema * 1.0
        else:
            # Fallback to simple step logic for first few trades
            if is_win:
                self.multiplier *= 1.05
            else:
                self.multiplier *= 0.90
            
        # Hard caps for safety
        self.multiplier = max(0.3, min(1.5, self.multiplier))
        self.save_state()

    def calculate_multiplier(self, macro_risk_data, ai_sentiment=None):
        """
        Combines performance multiplier, market regime, and AI institutional score.
        """
        regime = macro_risk_data.get('market_regime', 'STABLE')
        regime_mod = 1.0
        
        if regime == 'BULLISH_TREND':
            regime_mod = 1.2
        elif regime == 'VOLATILE_CAUTION':
            regime_mod = 0.5
        elif regime == 'SYSTEMIC_PANIC':
            regime_mod = 0.05
        elif regime == 'HIGH_RISK':
            regime_mod = 0.2
            
        # Add AI Institutional Sentiment Factor (0.0 to 1.0)
        ai_mod = 1.0
        if ai_sentiment and isinstance(ai_sentiment, dict):
            score = ai_sentiment.get('institutional_score', 0.5)
            # Scale ai_mod: 0.5 (very bearish) to 1.5 (very bullish institutional sweep)
            ai_mod = 0.5 + (score * 1.0)
            
        final_multiplier = self.multiplier * regime_mod * ai_mod
        return max(0.0, min(1.5, final_multiplier))





def check_gpu_availability():
    """Check and log GPU availability"""
    try:
        # Check CUDA availability
        cuda_available = torch.cuda.is_available()
        device_count = torch.cuda.device_count() if cuda_available else 0
        
        if cuda_available:
            current_device = torch.cuda.current_device()
            device_name = torch.cuda.get_device_name(current_device)
            memory_allocated = torch.cuda.memory_allocated(current_device) / 1024**3  # GB
            memory_total = torch.cuda.get_device_properties(current_device).total_memory / 1024**3  # GB
            
            gpu_info = {
                'available': True,
                'device_count': device_count,
                'current_device': current_device,
                'device_name': device_name,
                'memory_allocated': memory_allocated,
                'memory_total': memory_total,
                'utilization': (memory_allocated / memory_total) * 100
            }
            
            log_message(f"🚀 GPU DETECTED: {device_name}")
            log_message(f"📊 GPU Memory: {memory_allocated:.2f}GB / {memory_total:.2f}GB ({gpu_info['utilization']:.1f}% used)")
            
        else:
            gpu_info = {
                'available': False,
                'device_count': 0,
                'reason': 'CUDA not available'
            }
            log_message("⚠️ GPU NOT AVAILABLE: CUDA not detected")
            
        return gpu_info
        
    except Exception as e:
        log_message(f"⚠️ GPU CHECK ERROR: {e}")
        return {'available': False, 'reason': str(e)}

import talib

def generate_market_summary(df):
    """Generate enhanced text summary of market conditions for transformer"""
    try:
        last_row = df.iloc[-1]
        
        # Basic price and trend information
        rsi_value = talib.RSI(df['close'].values)[-1] if len(df) > 14 else 50
        
        # Safe comparison for MACD trend - fix Series ambiguity
        macd_hist_val = last_row['MACD Histogram']
        if pd.isna(macd_hist_val):
            macd_trend = 'neutral'
        else:
            macd_trend = 'bullish' if float(macd_hist_val) > 0 else 'bearish'
        
        # Safe comparison for VWAP - fix Series ambiguity
        close_val = float(last_row['close'])
        vwap_val = float(last_row['VWAP'])
        price_vs_vwap = 'above' if close_val > vwap_val else 'below'
        
        # Bollinger Bands position - fix Series ambiguity
        close_price = float(last_row['close'])
        upper_band = float(last_row['Upper Band'])
        lower_band = float(last_row['Lower Band'])
        
        if close_price > upper_band:
            bb_position = 'above upper band'
        elif close_price < lower_band:
            bb_position = 'below lower band'
        else:
            bb_position = 'in middle range'
        
        # Advanced indicators if available - fix Series ambiguity
        additional_context = ""
        if 'ADX' in df.columns and not pd.isna(last_row['ADX']):
            adx_val = float(last_row['ADX'])
            trend_strength = "strong" if adx_val > 25 else "weak"
            additional_context += f" The trend strength is {trend_strength} with ADX at {adx_val:.1f}."
        
        if 'MFI' in df.columns and not pd.isna(last_row['MFI']):
            mfi_val = float(last_row['MFI'])
            mfi_condition = "overbought" if mfi_val > 80 else "oversold" if mfi_val < 20 else "neutral"
            additional_context += f" Money flow is {mfi_condition} at {mfi_val:.1f}."
        
        # Pattern information - fix Series ambiguity
        pattern_info = ""
        if 'Pattern' in df.columns:
            pattern_val = str(last_row['Pattern'])
            pattern_type_val = str(last_row['Pattern_Type'])
            if pattern_val != 'None':
                pattern_info = f" A {pattern_val} pattern is detected with {pattern_type_val.lower()} implications."
        
        # Volume context - fix Series ambiguity
        volume_context = ""
        if len(df) > 20:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = float(last_row['volume'])
            if pd.notna(avg_volume) and avg_volume > 0 and pd.notna(current_volume) and current_volume > 0:
                volume_ratio = current_volume / avg_volume
                if volume_ratio > 1.5:
                    volume_context = " Trading volume is significantly above average."
                elif volume_ratio < 0.5:
                    volume_context = " Trading volume is below average."
        
        summary = (
            f"The current price is {last_row['close']:.6f}. "
            f"RSI is at {rsi_value:.1f}. "
            f"MACD is {macd_trend}. "
            f"Price is {price_vs_vwap} VWAP. "
            f"Bollinger Bands show price is {bb_position}."
            f"{additional_context}"
            f"{pattern_info}"
            f"{volume_context}"
        )
        
        return summary
        
    except Exception as e:
        log_message(f"Error generating market summary: {e}")
        return "Market analysis unavailable due to data processing error."
