"""
tv_screener.py — TradingView Screener pre-filter + webhook receiver integration.

Two modes:
  A) Pull:  get_tv_priority_pairs()  — query TV screener every cycle, returns
            Binance perp pairs sorted by signal strength. Used as pre-filter
            to reduce 200-pair universe to 40-60 high-priority pairs.
  B) Push:  TV Pine Script fires an alert → webhook → process_pair(tv_override)
            Endpoint registered in dashboard/app.py: POST /webhook/tradingview
"""

import time
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────
_TV_CACHE: dict = {"pairs": None, "ts": 0}
_TV_CACHE_TTL = 600  # 10 min — TV screener is not real-time, no need to hammer it

# ── RSI extreme thresholds for TV pre-filter ─────────────────────────────────
RSI_OS_MAX = 38    # RSI ≤ 38 → oversold (LONG candidate)
RSI_OB_MIN = 62    # RSI ≥ 62 → overbought (SHORT candidate)
MIN_REL_VOL = 1.0  # relative volume ≥ 1× 10-day avg (basic activity filter)


def get_tv_priority_pairs(binance_pairs: list) -> list:
    """
    Query TradingView's crypto screener for USDT futures pairs showing extreme
    RSI or high relative volume, then intersect with the bot's Binance universe.

    Returns a sorted list: TV-confirmed pairs first, remaining pairs appended.
    Falls back to the original list if TV is unavailable.
    """
    global _TV_CACHE
    now = time.time()
    if _TV_CACHE["pairs"] is not None and (now - _TV_CACHE["ts"]) < _TV_CACHE_TTL:
        tv_priority = _TV_CACHE["pairs"]
        return _merge_priority(tv_priority, binance_pairs)

    try:
        from tradingview_screener import Query, col

        # ── Build TV symbol set from Binance pairs for fast lookup ──────────
        # TV perp format: BTCUSDT.P  →  strip to BTCUSDT for matching
        binance_set = set(binance_pairs)

        # ── Query: crypto perpetuals on Binance with RSI extremes / vol ─────
        _, df = (
            Query()
            .set_markets("crypto")
            .select(
                "name",
                "close",
                "RSI",
                "MACD.macd",
                "MACD.signal",
                "volume",
                "relative_volume_10d_calc",
                "change",
            )
            .where(
                col("exchange").isin(["BINANCE", "BYBIT"]),
                col("relative_volume_10d_calc") >= MIN_REL_VOL,
            )
            .limit(500)
            .get_scanner_data()
        )
        # Filter perpetuals server-side filter (.like('%.P')) is broken in this
        # tradingview_screener version — apply it in Python instead
        df = df[df["name"].str.endswith(".P", na=False)]

        tv_priority = []
        tv_scores: dict = {}

        for _, row in df.iterrows():
            raw_name = str(row.get("name", "")).upper()
            # Normalise: BTCUSDT.P → BTCUSDT
            sym = raw_name.replace(".P", "").replace("-PERP", "")
            if not sym.endswith("USDT"):
                sym = sym + "USDT"
            if sym not in binance_set:
                continue

            rsi = row.get("RSI", 50) or 50
            rel_vol = row.get("relative_volume_10d_calc", 1.0) or 1.0
            macd = row.get("MACD.macd", 0) or 0
            macd_sig = row.get("MACD.signal", 0) or 0
            change = abs(row.get("change", 0) or 0)

            # ── Score: prioritise RSI extremes + vol spike + MACD cross ─────
            score = 0.0
            if rsi <= RSI_OS_MAX:
                score += (RSI_OS_MAX - rsi) * 2      # deeper = better
            elif rsi >= RSI_OB_MIN:
                score += (rsi - RSI_OB_MIN) * 2
            score += min(rel_vol, 5.0) * 3            # vol spike (cap at 5×)
            if (macd > macd_sig and rsi < 50) or (macd < macd_sig and rsi > 50):
                score += 5                            # MACD agrees with RSI
            score += change * 0.5                     # price momentum

            if score > 0:
                tv_scores[sym] = score
                tv_priority.append(sym)

        tv_priority.sort(key=lambda s: tv_scores.get(s, 0), reverse=True)

        _TV_CACHE["pairs"] = tv_priority
        _TV_CACHE["ts"] = now

        n_found = len(tv_priority)
        log.info(f"[TVScreener] {n_found} priority pairs from TradingView "
                 f"(RSI extremes + vol spike)")

    except Exception as exc:
        log.warning(f"[TVScreener] Unavailable ({exc}) — using full Binance list")
        return binance_pairs

    return _merge_priority(tv_priority, binance_pairs)


def _merge_priority(tv_list: list, full_list: list) -> list:
    """TV-confirmed pairs first, then any remaining Binance pairs not in TV list."""
    tv_set = set(tv_list)
    remainder = [p for p in full_list if p not in tv_set]
    # Only include TV pairs that are in the Binance universe
    tv_valid = [p for p in tv_list if p in set(full_list)]
    merged = tv_valid + remainder
    return merged


def parse_tv_webhook(body: dict) -> Optional[dict]:
    """
    Parse a TradingView webhook alert body into a tv_override dict.

    Expected TV alert message JSON (set in Pine Script alertcondition message):
    {
      "ticker":   "{{ticker}}",       e.g. "BTCUSDT"
      "action":   "{{strategy.order.action}}",  "buy" | "sell"
      "price":    "{{close}}",
      "strategy": "RH Webhook",
      "time":     "{{timenow}}"
    }

    Returns dict suitable for process_pair(tv_override=...) or None if invalid.
    """
    try:
        ticker = str(body.get("ticker", "")).upper().replace("BINANCE:", "")
        ticker = ticker.replace(".P", "").replace("-PERP", "")
        if not ticker.endswith("USDT"):
            ticker += "USDT"

        action = str(body.get("action", "")).lower()
        if action in ("buy", "long"):
            signal = "LONG"
        elif action in ("sell", "short"):
            signal = "SHORT"
        else:
            log.warning(f"[TVWebhook] Unknown action='{action}' for {ticker}")
            return None

        price = float(body.get("price", 0) or 0)
        strategy = str(body.get("strategy", "TradingView"))

        return {
            "pair":     ticker,
            "signal":   signal,
            "price":    price,
            "strategy": strategy,
            "source":   "tv_webhook",
        }
    except Exception as exc:
        log.error(f"[TVWebhook] Parse error: {exc} | body={body}")
        return None


def invalidate_cache():
    """Force next call to re-query TradingView."""
    _TV_CACHE["pairs"] = None
    _TV_CACHE["ts"] = 0
