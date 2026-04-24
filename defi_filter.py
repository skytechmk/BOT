"""
defi_filter.py — DefiLlama TVL trend filter for DeFi token pairs.

For known DeFi protocol tokens (UNI, AAVE, CRV, etc.), checks the 30-day TVL
trend from api.llama.fi. A declining TVL signals fundamental weakness → reduces
signal confidence multiplier.

Integration point: call get_defi_tvl_filter(pair) before emitting a signal.
Returns a multiplier (0.7–1.0) and a verdict string.

Cache TTL: 4 hours per protocol (TVL data is slow-moving).
"""

import os
import time
import json
import asyncio
import aiohttp
from typing import Optional
from utils_logger import log_message

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "performance_logs", "defi_tvl_cache.json")
_CACHE_TTL  = 4 * 3600   # 4 hours

# Mapping: Binance USDT perp symbol → DefiLlama protocol slug
# Source: api.llama.fi/protocols
DEFI_PROTOCOL_MAP: dict[str, str] = {
    "UNIUSDT":    "uniswap",
    "AAVEUSDT":   "aave",
    "CRVUSDT":    "curve-dex",
    "SUSHIUSDT":  "sushiswap",
    "COMPUSDT":   "compound-finance",
    "MKRUSDT":    "makerdao",
    "SNXUSDT":    "synthetix",
    "YFIUSDT":    "yearn-finance",
    "1INCHUSDT":  "1inch-network",
    "LDOUSDT":    "lido",
    "RPLUSUSDT":  "rocket-pool",
    "GRTUSDT":    "the-graph",
    "PENDLEUSDT": "pendle",
    "EIGENUSDT":  "eigenlayer",
    "ENAAUSDT":   "ethena",
    "ENAUSDT":    "ethena",
    "JUPUSDT":    "jupiter-exchange-solana",
    "RAYUSDT":    "raydium",
    "GMXUSDT":    "gmx",
    "DYDXUSDT":   "dydx",
    "KAVAUSDT":   "kava",
    "ANKRUSDT":   "ankr",
}

_cache: dict = {}


def _load_cache() -> dict:
    global _cache
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH) as f:
                _cache = json.load(f)
    except Exception:
        _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w") as f:
            json.dump(_cache, f)
    except Exception:
        pass


def is_defi_token(pair: str) -> bool:
    return pair.upper() in DEFI_PROTOCOL_MAP


async def _fetch_tvl_trend(slug: str) -> Optional[dict]:
    """Fetch 30-day TVL history from DefiLlama and compute trend."""
    url = f"https://api.llama.fi/protocol/{slug}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        tvl_history = data.get("tvl", [])
        if len(tvl_history) < 31:
            return None

        # Last 30 daily TVL values
        recent = [entry["totalLiquidityUSD"] for entry in tvl_history[-30:]]
        tvl_now  = recent[-1]
        tvl_7d   = recent[-7]
        tvl_30d  = recent[0]

        pct_7d  = (tvl_now - tvl_7d)  / (tvl_7d  + 1e-9) * 100
        pct_30d = (tvl_now - tvl_30d) / (tvl_30d + 1e-9) * 100

        # Trend verdict
        if pct_30d < -25 or pct_7d < -15:
            trend = "STRONG_DECLINE"
        elif pct_30d < -10 or pct_7d < -7:
            trend = "DECLINE"
        elif pct_30d > 20 or pct_7d > 10:
            trend = "GROWTH"
        elif pct_30d > 5:
            trend = "STABLE_GROWTH"
        else:
            trend = "STABLE"

        return {
            "slug":    slug,
            "tvl_now": round(tvl_now / 1e6, 1),   # millions
            "pct_7d":  round(pct_7d, 1),
            "pct_30d": round(pct_30d, 1),
            "trend":   trend,
        }
    except Exception as exc:
        log_message(f"[defi_filter] TVL fetch error for {slug}: {exc}")
        return None


async def get_defi_tvl_filter(pair: str) -> dict:
    """
    Returns:
        {
          'is_defi':    bool,
          'multiplier': float,   # 0.7–1.0 — apply to signal confidence/size
          'verdict':    str,
          'tvl_now_m':  float,   # TVL in $M
          'pct_30d':    float,
        }
    """
    pair_up = pair.upper()
    if pair_up not in DEFI_PROTOCOL_MAP:
        return {"is_defi": False, "multiplier": 1.0, "verdict": "NOT_DEFI", "tvl_now_m": 0, "pct_30d": 0}

    slug = DEFI_PROTOCOL_MAP[pair_up]

    # Check cache
    _load_cache()
    cached = _cache.get(slug)
    if cached and time.time() - cached.get("ts", 0) < _CACHE_TTL:
        tvl_data = cached["data"]
    else:
        tvl_data = await _fetch_tvl_trend(slug)
        if tvl_data:
            _cache[slug] = {"ts": time.time(), "data": tvl_data}
            _save_cache()

    if not tvl_data:
        return {"is_defi": True, "multiplier": 1.0, "verdict": "TVL_UNAVAILABLE", "tvl_now_m": 0, "pct_30d": 0}

    trend = tvl_data["trend"]
    mult_map = {
        "STRONG_DECLINE": 0.70,
        "DECLINE":        0.82,
        "STABLE":         1.00,
        "STABLE_GROWTH":  1.00,
        "GROWTH":         1.05,  # slight bonus for growing TVL
    }
    multiplier = mult_map.get(trend, 1.0)

    return {
        "is_defi":    True,
        "multiplier": multiplier,
        "verdict":    trend,
        "tvl_now_m":  tvl_data["tvl_now"],
        "pct_30d":    tvl_data["pct_30d"],
        "pct_7d":     tvl_data["pct_7d"],
    }
