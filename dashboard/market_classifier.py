"""
market_classifier.py — CoinGecko + DeFiLlama powered pair classification.

Provides:
  - Market-cap rank tiers: blue_chip / large_cap / mid_cap / small_cap / high_risk
  - Sector labels: layer1 / layer2 / defi / gaming / ai / tradefi / meme / infra / other
  - HOT detection: rank improved ≥ 15 positions in the last 24 hours
  - Hourly CoinGecko refresh (tiers + HOT detection)
  - 6-hour DeFiLlama refresh (~2000 protocols → automatic sector classification)

Priority: CoinGecko cache (live) > DeFiLlama (dynamic) > static _SECTOR_MAP (fallback)
"""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

import httpx

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "market_data.db"
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1"
    "&sparkline=false&price_change_percentage=24h"
)
REFRESH_INTERVAL = 3600   # 1 hour (CoinGecko)
DFL_REFRESH_INTERVAL = 21600  # 6 hours (DeFiLlama)
HOT_THRESHOLD = 15        # rank must improve by this many positions
HOT_WINDOW = 86400        # compare against snapshot from 24 h ago

DEFILAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"

# Maps DeFiLlama protocol categories → our internal sector keys
_DFL_CATEGORY_MAP: Dict[str, str] = {
    # Layer 1 chains
    "Chain":            "layer1",
    "Layer 1":          "layer1",
    # Layer 2 / bridges
    "Rollup":           "layer2",
    "Layer 2":          "layer2",
    "Cross Chain":      "layer2",
    "Bridge":           "layer2",
    # DeFi (broad)
    "Dexes":            "defi",
    "Decentralized Exchange": "defi",
    "DEX Aggregator":   "defi",
    "Lending":          "defi",
    "Yield":            "defi",
    "Yield Aggregator": "defi",
    "Liquid Staking":   "defi",
    "Stablecoins":      "defi",
    "CDP":              "defi",
    "Derivatives":      "defi",
    "Perpetuals":       "defi",
    "Options":          "defi",
    "Decentralized Options": "defi",
    "Options Vault":    "defi",
    "Leveraged Farming":"defi",
    "Algo-Stables":     "defi",
    "Synthetics":       "defi",
    "RWA Lending":      "defi",
    "Launchpad":        "defi",
    "Reserve Currency": "defi",
    "Index":            "defi",
    "Insurance":        "defi",
    "Prediction Market":"defi",
    # TradFi / Real World Assets
    "RWA":              "tradefi",
    "Tokenized Stocks": "tradefi",
    "Real World Assets":"tradefi",
    # Gaming / NFT
    "Gaming":           "gaming",
    "NFT Marketplace":  "gaming",
    "NFT Lending":      "gaming",
    "NFT":              "gaming",
    "SocialFi":         "gaming",
    "Social":           "gaming",
    # AI
    "AI Agents":        "ai",
    "AI":               "ai",
    # Meme
    "Meme":             "meme",
    # Infrastructure / Oracle / Storage
    "Infrastructure":   "infra",
    "Oracle":           "infra",
    "Storage":          "infra",
    "Identity":         "infra",
    "Privacy":          "infra",
    "Payments":         "infra",
    "Data Availability":"infra",
}

# In-memory DeFiLlama sector map: symbol (upper) → sector
_defilama_map: Dict[str, str] = {}


# ── Sector map ─────────────────────────────────────────────────────
_SECTOR_MAP: Dict[str, str] = {
    # Layer 1
    "BTC": "layer1", "ETH": "layer1", "SOL": "layer1", "ADA": "layer1",
    "AVAX": "layer1", "DOT": "layer1", "ATOM": "layer1", "NEAR": "layer1",
    "APT": "layer1", "SUI": "layer1", "TON": "layer1", "TRX": "layer1",
    "LTC": "layer1", "BCH": "layer1", "XRP": "layer1", "EOS": "layer1",
    "ALGO": "layer1", "FTM": "layer1", "ONE": "layer1", "KAVA": "layer1",
    "CELO": "layer1", "EGLD": "layer1", "ICP": "layer1", "HBAR": "layer1",
    "XLM": "layer1", "VET": "layer1", "ETC": "layer1", "THETA": "layer1",
    "XTZ": "layer1", "MINA": "layer1", "FLOW": "layer1", "ZIL": "layer1",
    "IOTA": "layer1", "NEO": "layer1", "WAVES": "layer1", "QTUM": "layer1",
    "ICX": "layer1", "ZEC": "layer1", "DASH": "layer1", "XMR": "layer1",
    "FIL": "layer1", "XDC": "layer1", "MOVR": "layer1", "SEI": "layer1",
    "INJ": "layer1", "OSMO": "layer1", "CELESTIA": "layer1", "TIA": "layer1",
    "CORE": "layer1", "CFX": "layer1", "LUNA": "layer1", "LUNC": "layer1",

    # Layer 2
    "ARB": "layer2", "OP": "layer2", "MATIC": "layer2", "POL": "layer2",
    "IMX": "layer2", "LRC": "layer2", "METIS": "layer2", "SKL": "layer2",
    "CELR": "layer2", "BOBA": "layer2", "ZKS": "layer2", "STRK": "layer2",
    "MANTA": "layer2", "ZETA": "layer2", "TAIKO": "layer2",

    # DeFi
    "AAVE": "defi", "UNI": "defi", "SUSHI": "defi", "COMP": "defi",
    "MKR": "defi", "YFI": "defi", "CRV": "defi", "SNX": "defi",
    "BAL": "defi", "1INCH": "defi", "RUNE": "defi", "CAKE": "defi",
    "DYDX": "defi", "GMX": "defi", "GNS": "defi", "LINK": "defi",
    "BAND": "defi", "PENDLE": "defi", "RDNT": "defi", "STG": "defi",
    "LQTY": "defi", "FXS": "defi", "LDO": "defi", "RPL": "defi",
    "ALPHA": "defi", "BNT": "defi", "PERP": "defi", "COW": "defi",
    "ONDO": "defi", "JUP": "defi", "RAY": "defi", "DRIFT": "defi",
    "HFT": "defi", "HOOK": "defi", "POLYX": "defi", "TWT": "defi",
    "VELO": "defi", "AEVO": "defi", "ZRX": "defi", "KNC": "defi",
    "XVS": "defi", "BANANA": "defi", "BLUR": "defi", "LOOKS": "defi",

    # Gaming / Metaverse
    "AXS": "gaming", "SAND": "gaming", "MANA": "gaming", "ENJ": "gaming",
    "ILV": "gaming", "GALA": "gaming", "ALICE": "gaming", "GMT": "gaming",
    "TLM": "gaming", "PYR": "gaming", "YGG": "gaming", "SLP": "gaming",
    "MAGIC": "gaming", "BEAM": "gaming", "COMBO": "gaming", "GHST": "gaming",
    "ULTRA": "gaming", "NFT": "gaming", "PIXEL": "gaming", "TNSR": "gaming",
    "PORTAL": "gaming", "MAVIA": "gaming", "XBORG": "gaming", "MYRIA": "gaming",
    "RON": "gaming", "APE": "gaming", "ACH": "gaming",

    # AI
    "FET": "ai", "TAO": "ai", "AGIX": "ai", "OCEAN": "ai",
    "RNDR": "ai", "AKT": "ai", "NMR": "ai", "GRT": "ai",
    "WLD": "ai", "OLAS": "ai", "PAAL": "ai", "ARKM": "ai",
    "VRA": "ai", "PHALA": "ai", "PHA": "ai", "AIOZ": "ai",
    "AGI": "ai", "CGPT": "ai", "MYSHELL": "ai", "VIRTUAL": "ai",
    "ZIG": "ai",

    # TradFi / RWA / Stock Perps
    "INTC": "tradefi", "AAPL": "tradefi", "HOOD": "tradefi",
    "COIN": "tradefi", "MSTR": "tradefi", "AMZN": "tradefi",
    "GOOGL": "tradefi", "META": "tradefi", "NVDA": "tradefi",
    "TSLA": "tradefi", "BRKB": "tradefi", "XOM": "tradefi",
    "JPM": "tradefi", "GS": "tradefi", "AMD": "tradefi",
    "MSFT": "tradefi", "NFLX": "tradefi", "PYPL": "tradefi",
    "SQ": "tradefi", "UBER": "tradefi", "ABNB": "tradefi",

    # Meme
    "DOGE": "meme", "SHIB": "meme", "PEPE": "meme", "FLOKI": "meme",
    "BONK": "meme", "WIF": "meme", "BOME": "meme", "NEIRO": "meme",
    "TURBO": "meme", "MEME": "meme", "POPCAT": "meme", "MOG": "meme",
    "BRETT": "meme", "COQ": "meme", "LADYS": "meme", "MYRO": "meme",
    "CAT": "meme", "ELON": "meme", "BABYDOGE": "meme", "WOJAK": "meme",
    "HIPPO": "meme", "PNUT": "meme", "ACT": "meme", "GOAT": "meme",
    "CHEEMS": "meme", "NFTS": "meme",

    # Infrastructure / Oracle / Storage
    "STORJ": "infra", "AR": "infra", "HOT": "infra", "NKN": "infra",
    "CTSI": "infra", "BAT": "infra", "ANKR": "infra", "API3": "infra",
    "POWR": "infra", "ROSE": "infra", "KEEP": "infra", "NU": "infra",
    "HIVE": "infra", "BLZ": "infra", "UTK": "infra", "TOMO": "infra",
    "REQ": "infra", "OXT": "infra", "STMX": "infra", "AION": "infra",
    "IEXEC": "infra", "RLC": "infra", "DENT": "infra", "MTL": "infra",
    "WAN": "infra", "SXP": "infra", "FIO": "infra", "ORBS": "infra",
}

# Tier label display config
TIER_LABELS = {
    "blue_chip": {"label": "Blue Chip",  "color": "#2196f3", "emoji": "🔵"},
    "large_cap":  {"label": "Large Cap",  "color": "#4caf50", "emoji": "🟢"},
    "mid_cap":    {"label": "Mid Cap",    "color": "#f0b429", "emoji": "🟡"},
    "small_cap":  {"label": "Small Cap",  "color": "#ff9800", "emoji": "🟠"},
    "high_risk":  {"label": "High Risk",  "color": "#f44336", "emoji": "🔴"},
}

SECTOR_LABELS = {
    "layer1":  {"label": "Layer 1",  "emoji": "⛓️"},
    "layer2":  {"label": "Layer 2",  "emoji": "🔗"},
    "defi":    {"label": "DeFi",     "emoji": "🏦"},
    "gaming":  {"label": "Gaming",   "emoji": "🎮"},
    "ai":      {"label": "AI",       "emoji": "🤖"},
    "tradefi": {"label": "TradFi",   "emoji": "📈"},
    "meme":    {"label": "Meme",     "emoji": "🐸"},
    "infra":   {"label": "Infra",    "emoji": "⚙️"},
    "other":   {"label": "Other",    "emoji": "🔷"},
}


# ── Database ────────────────────────────────────────────────────────
def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_market_db():
    """Create market_data.db tables."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rank_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT NOT NULL,
            rank          INTEGER NOT NULL,
            market_cap    REAL,
            snapshot_time REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snap_sym_time
            ON rank_snapshots(symbol, snapshot_time);

        CREATE TABLE IF NOT EXISTS refresh_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at REAL NOT NULL,
            count      INTEGER NOT NULL,
            status     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS defilama_sectors (
            symbol      TEXT PRIMARY KEY,
            sector      TEXT NOT NULL,
            name        TEXT,
            dfl_category TEXT,
            updated_at  REAL NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    log.info("[market] DB initialized")


# ── Helpers ─────────────────────────────────────────────────────────
def _rank_to_tier(rank: Optional[int]) -> str:
    if rank is None:
        return "high_risk"
    if rank <= 10:
        return "blue_chip"
    if rank <= 30:
        return "large_cap"
    if rank <= 50:
        return "mid_cap"
    if rank <= 100:
        return "small_cap"
    return "high_risk"


def _symbol_from_pair(pair: str) -> str:
    """Strip USDT suffix: 'BTCUSDT' → 'BTC'."""
    return pair.upper().replace("USDT", "").replace("BUSD", "").replace("USDC", "")


# ── In-memory cache (avoids DB hit on every signal) ─────────────────
_cache: Dict[str, dict] = {}   # symbol → {tier, sector, rank, is_hot, rank_change}
_cache_ts: float = 0.0


def _load_defilama_map_from_db():
    """Load persisted DeFiLlama sector map from DB into _defilama_map."""
    global _defilama_map
    try:
        conn = _get_db()
        rows = conn.execute("SELECT symbol, sector FROM defilama_sectors").fetchall()
        conn.close()
        _defilama_map = {r['symbol']: r['sector'] for r in rows}
        log.info(f"[defilama] Loaded {len(_defilama_map)} sector entries from DB")
    except Exception as e:
        log.warning(f"[defilama] Could not load from DB: {e}")


def _build_cache():
    """Rebuild in-memory cache from latest DB snapshot + 24h-ago comparison."""
    global _cache, _cache_ts
    conn = _get_db()
    now = time.time()

    # Latest snapshot per symbol
    latest_rows = conn.execute("""
        SELECT symbol, rank, market_cap, snapshot_time
        FROM rank_snapshots
        WHERE snapshot_time = (
            SELECT MAX(snapshot_time) FROM rank_snapshots
        )
    """).fetchall()

    if not latest_rows:
        conn.close()
        return

    # 24h-ago snapshot per symbol (within ±2h window for tolerance)
    target_old = now - HOT_WINDOW
    old_rows = conn.execute("""
        SELECT symbol, rank
        FROM rank_snapshots
        WHERE snapshot_time BETWEEN ? AND ?
        ORDER BY ABS(snapshot_time - ?) ASC
    """, (target_old - 7200, target_old + 7200, target_old)).fetchall()
    conn.close()

    old_rank: Dict[str, int] = {}
    for r in old_rows:
        sym = r['symbol']
        if sym not in old_rank:  # keep the closest one per symbol
            old_rank[sym] = r['rank']

    new_cache: Dict[str, dict] = {}
    for row in latest_rows:
        sym = row['symbol']
        rank = row['rank']
        old = old_rank.get(sym)
        rank_change = (old - rank) if old else 0  # positive = improved (moved up)
        is_hot = rank_change >= HOT_THRESHOLD
        new_cache[sym] = {
            "tier":        _rank_to_tier(rank),
            "sector":      _SECTOR_MAP.get(sym, "other"),
            "rank":        rank,
            "is_hot":      is_hot,
            "rank_change": rank_change,
        }

    _cache = new_cache
    _cache_ts = now
    log.info(f"[market] Cache rebuilt: {len(_cache)} symbols, "
             f"{sum(1 for v in _cache.values() if v['is_hot'])} HOT")


# ── DeFiLlama fetch ────────────────────────────────────────────────
async def refresh_defilama_classifications():
    """
    Fetch all protocols from DeFiLlama, map their category to our sector
    taxonomy, persist to DB, and reload _defilama_map.
    Covers ~2000+ protocols that CoinGecko doesn't classify by sector.
    """
    global _defilama_map
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(DEFILAMA_PROTOCOLS_URL,
                                    headers={"Accept": "application/json"})
            resp.raise_for_status()
            protocols = resp.json()
    except Exception as e:
        log.warning(f"[defilama] Fetch failed: {e}")
        return

    now = time.time()
    new_map: Dict[str, str] = {}
    rows = []
    for p in protocols:
        raw_sym = (p.get("symbol") or "").strip().upper()
        if not raw_sym:
            continue
        category = (p.get("category") or "").strip()
        sector = _DFL_CATEGORY_MAP.get(category)
        if not sector:
            continue  # skip unknowns — don't pollute with 'other'
        name = (p.get("name") or "")[:64]
        if raw_sym not in new_map:  # first match wins (highest TVL protocols come first)
            new_map[raw_sym] = sector
            rows.append((raw_sym, sector, name, category, now))

    if not rows:
        log.warning("[defilama] No usable rows returned")
        return

    try:
        conn = _get_db()
        conn.executemany(
            "INSERT OR REPLACE INTO defilama_sectors "
            "(symbol, sector, name, dfl_category, updated_at) VALUES (?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"[defilama] DB write failed: {e}")
        return

    _defilama_map = new_map
    log.info(f"[defilama] Updated {len(new_map)} sector classifications from DeFiLlama")


# ── CoinGecko fetch ────────────────────────────────────────────────
async def refresh_market_data():
    """Fetch CoinGecko market data, store snapshot, rebuild cache."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(COINGECKO_URL, headers={"Accept": "application/json"})
            resp.raise_for_status()
            coins = resp.json()
    except Exception as e:
        log.warning(f"[market] CoinGecko fetch failed: {e}")
        return

    now = time.time()
    conn = _get_db()
    rows = [
        (c["symbol"].upper(), c.get("market_cap_rank"), c.get("market_cap"), now)
        for c in coins
        if c.get("symbol") and c.get("market_cap_rank")
    ]
    conn.executemany(
        "INSERT INTO rank_snapshots (symbol, rank, market_cap, snapshot_time) VALUES (?,?,?,?)",
        rows
    )
    # Prune snapshots older than 8 days to keep DB small
    conn.execute("DELETE FROM rank_snapshots WHERE snapshot_time < ?", (now - 8 * 86400,))
    conn.execute(
        "INSERT INTO refresh_log (fetched_at, count, status) VALUES (?,?,?)",
        (now, len(rows), "ok")
    )
    conn.commit()
    conn.close()

    _build_cache()
    log.info(f"[market] Refreshed {len(rows)} coins from CoinGecko")


# ── Public API ──────────────────────────────────────────────────────
def get_pair_info(pair: str) -> dict:
    """Return classification dict for a USDT perp pair."""
    sym = _symbol_from_pair(pair)
    if sym in _cache:
        return _cache[sym]
    # Fallback: sector from static map, tier unknown
    return {
        "tier":        "high_risk",
        "sector":      _SECTOR_MAP.get(sym, "other"),
        "rank":        None,
        "is_hot":      False,
        "rank_change": 0,
    }


def get_all_classifications() -> dict:
    """Return full symbol → classification map for API endpoint.

    Priority (highest wins):
      1. Live CoinGecko cache  (tier + HOT + sector from static/DFL)
      2. DeFiLlama dynamic map (~2000 protocols, refreshed every 6h)
      3. Static _SECTOR_MAP    (hardcoded fallback for known tokens)
    """
    result: Dict[str, dict] = {}

    # Layer 0: static map (lowest priority, always present)
    for sym, sector in _SECTOR_MAP.items():
        result[sym] = {
            "tier":        "high_risk",
            "sector":      sector,
            "rank":        None,
            "is_hot":      False,
            "rank_change": 0,
        }

    # Layer 1: DeFiLlama dynamic classifications (overrides static sector)
    for sym, sector in _defilama_map.items():
        if sym in result:
            result[sym]["sector"] = sector  # update sector only
        else:
            result[sym] = {
                "tier":        "high_risk",
                "sector":      sector,
                "rank":        None,
                "is_hot":      False,
                "rank_change": 0,
            }

    # Layer 2: Live CoinGecko cache (highest quality, full override)
    result.update(_cache)
    return result


def get_tier_labels() -> dict:
    return TIER_LABELS


def get_sector_labels() -> dict:
    return SECTOR_LABELS


# ── Background loop ─────────────────────────────────────────────────
async def run_market_refresh_loop():
    """Background task: CoinGecko every 1h, DeFiLlama every 6h."""
    # Initial load from DB (avoids cold-start wait after restart)
    try:
        _build_cache()
    except Exception as e:
        log.warning(f"[market] Initial cache build failed: {e}")
    try:
        _load_defilama_map_from_db()
    except Exception as e:
        log.warning(f"[defilama] Initial load failed: {e}")

    # Immediate fresh fetch on startup
    await refresh_market_data()
    await refresh_defilama_classifications()

    _dfl_last = time.time()
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            await refresh_market_data()
        except Exception as e:
            log.error(f"[market] CoinGecko refresh error: {e}")
        # DeFiLlama refresh every 6 hours
        if time.time() - _dfl_last >= DFL_REFRESH_INTERVAL:
            try:
                await refresh_defilama_classifications()
                _dfl_last = time.time()
            except Exception as e:
                log.error(f"[defilama] Refresh error: {e}")
