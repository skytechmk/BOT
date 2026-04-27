"""
Aladdin Dashboard — Signal Copy-Trading Engine (Pro Feature)

Encrypted API key storage, automated order execution, SQI-scaled position sizing.
Safety: max position cap, daily loss limit, kill switch, no withdrawal permission.
"""
import os
import re
import sys
import time
import base64
import hashlib
import sqlite3
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()

# ── B1 fix: make `auth` / `device_security` / `market_classifier` importable
# regardless of caller cwd.  main.py runs from the project root; app.py runs
# from dashboard/.  Without this guard, `from auth import ...` (inside the
# execute_copy_trades loop) raised ModuleNotFoundError on every bot-fired
# signal, silently killing copy-trading for every user. ─────────────────────
_DASH_DIR = os.path.dirname(os.path.abspath(__file__))
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

# Lifted out of the per-user inner loop (was at ~line 893) — one import per
# process instead of one per (signal × user).
from auth import tier_rank, TIERS_CANONICAL  # noqa: E402

log = logging.getLogger("copy_trading")
if not log.handlers:
    _log_path = Path(__file__).resolve().parent.parent / "debug_log10.txt"
    _fh = logging.FileHandler(str(_log_path), encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [copy_trading] %(message)s'))
    log.addHandler(_fh)
    log.setLevel(logging.DEBUG)
    log.propagate = False

# ── Signal registry path (absolute — shared with main bot) ─────────────
_SIGNAL_DB_PATH = str(Path(__file__).resolve().parent.parent / "signal_registry.db")

# ── Exchange info cache (shared across all users, refreshed every 5 min) ──
_EXINFO_CACHE: dict = {}
_EXINFO_TS: float = 0.0
_EXINFO_TTL: float = 300.0  # 5 minutes

# ── Per-user Binance client cache (avoids new TCP session per trade) ────────
_CLIENT_CACHE: Dict[int, Any] = {}   # user_id → Client
_CLIENT_TS:    Dict[int, float] = {} # user_id → last_refresh_time
_CLIENT_TTL = 600.0  # 10 minutes — refresh after key rotation window

# ── Per-user hedge mode cache (avoids redundant API call per trade) ─────────
_HEDGE_CACHE: Dict[int, bool] = {}
_HEDGE_TS:    Dict[int, float] = {}

# ── Per-(user,pair) leverage + margin-type caches ─────────────────────────────
# Binance's WS Trade API does NOT expose change_leverage / change_margin_type
# (they remain REST-only on Binance's side). Pre-WS-API era: every single trade
# fired both calls unconditionally → REST weight bleed + IP-ban risk.
# These caches make the calls fire ONLY when state actually changes (~95%+
# reduction). 12-hour TTL is safe because nothing else mutates these settings.
_LEVERAGE_CACHE:   Dict[tuple, int]   = {}   # (user_id, pair) -> leverage
_LEVERAGE_TS:      Dict[tuple, float] = {}   # (user_id, pair) -> last-set ts
_MARGIN_CROSS_SET: Dict[tuple, float] = {}   # (user_id, pair) -> last-set ts
_LEV_MARGIN_TTL = 12 * 3600                  # 12 h


def _ensure_leverage_cached(client, user_id: int, pair: str, leverage: int) -> int:
    """Set leverage on Binance only if cached value differs (or TTL expired).
    Returns the leverage that's now active. Falls back to pair-max on rejection.
    """
    key = (user_id, pair)
    now = time.time()
    cached_lev = _LEVERAGE_CACHE.get(key)
    cached_ts  = _LEVERAGE_TS.get(key, 0)
    if cached_lev == leverage and (now - cached_ts) < _LEV_MARGIN_TTL:
        return leverage    # already at this leverage, no REST call needed
    try:
        client.futures_change_leverage(symbol=pair, leverage=leverage)
        _LEVERAGE_CACHE[key] = leverage
        _LEVERAGE_TS[key]    = now
        return leverage
    except Exception as e:
        log.warning(f"Leverage change failed for {pair}: {e} — fetching pair max")
        try:
            brackets = client.futures_leverage_bracket(symbol=pair)
            pair_max = int(brackets[0]['brackets'][0]['initialLeverage'])
            clamped  = min(leverage, pair_max)
            client.futures_change_leverage(symbol=pair, leverage=clamped)
            _LEVERAGE_CACHE[key] = clamped
            _LEVERAGE_TS[key]    = now
            log.info(f"Clamped leverage to pair max {clamped}x for {pair}")
            return clamped
        except Exception as e2:
            log.warning(f"Could not clamp leverage for {pair}: {e2}")
            return leverage   # caller continues with requested; Binance may reject order


def _ensure_margin_cross_cached(client, user_id: int, pair: str) -> None:
    """Set margin type to CROSSED only if not already cached as such.
    The Binance API throws -4046 if margin type is already correct, which is
    silently ignored — but the call still hits REST weight. Cache eliminates
    the redundant call.
    """
    key = (user_id, pair)
    now = time.time()
    last = _MARGIN_CROSS_SET.get(key, 0)
    if (now - last) < _LEV_MARGIN_TTL:
        return    # already CROSSED within TTL window
    try:
        client.futures_change_margin_type(symbol=pair, marginType='CROSSED')
    except Exception:
        pass  # already cross OR position open — both are fine
    _MARGIN_CROSS_SET[key] = now


def _invalidate_leverage_margin_caches(user_id: int, pair: str | None = None) -> None:
    """Invalidate caches when Binance rejects with -4046/-4061/etc — forces
    re-set on next trade. Call from error handlers.
    """
    if pair is None:
        # User-wide flush (key rotation, account change)
        for k in list(_LEVERAGE_CACHE):
            if k[0] == user_id:
                _LEVERAGE_CACHE.pop(k, None); _LEVERAGE_TS.pop(k, None)
        for k in list(_MARGIN_CROSS_SET):
            if k[0] == user_id:
                _MARGIN_CROSS_SET.pop(k, None)
    else:
        key = (user_id, pair)
        _LEVERAGE_CACHE.pop(key, None); _LEVERAGE_TS.pop(key, None)
        _MARGIN_CROSS_SET.pop(key, None)


def _is_maintenance() -> bool:
    """
    Resolve is_maintenance_mode() regardless of how copy_trading.py was imported
    (either as `dashboard.copy_trading` from main.py, or directly from within
    the dashboard package).  Fail-CLOSED: if the import itself fails, treat as
    maintenance ON so no orders are sent.
    """
    try:
        from dashboard.device_security import is_maintenance_mode
        return is_maintenance_mode()
    except ImportError:
        pass
    try:
        from device_security import is_maintenance_mode
        return is_maintenance_mode()
    except ImportError:
        log.error("[maintenance_gate] device_security unavailable — treating as MAINTENANCE ON")
        return True


def _round_to_tick(price: float, tick: str) -> float:
    """
    B2 fix: align a price to the symbol's PRICE_FILTER.tickSize exactly.

    `round(x, N)` only rounds to N decimal places — this breaks for symbols
    whose tickSize isn't a round decimal (e.g. tick=0.05, tick=0.25 for some
    equity perps). Binance then rejects the order with -1111 "Precision over
    maximum for this asset".  We use Decimal with ROUND_HALF_UP so the price
    lands exactly on a tick multiple.
    """
    from decimal import Decimal, ROUND_HALF_UP
    try:
        t = Decimal(tick)
        if t <= 0:
            return float(price)
        q = (Decimal(str(price)) / t).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * t
        return float(q)
    except Exception:
        # Fallback: decimal-place rounding from the tick's fractional length
        places = max(0, len(tick.rstrip('0').split('.')[-1])) if '.' in tick else 0
        return round(float(price), places)


def _get_exchange_info_cached(client) -> dict:
    """Return cached futures_exchange_info, refreshing every 5 minutes."""
    global _EXINFO_CACHE, _EXINFO_TS
    now = time.time()
    if not _EXINFO_CACHE or (now - _EXINFO_TS) > _EXINFO_TTL:
        _EXINFO_CACHE = client.futures_exchange_info()
        _EXINFO_TS = now
        log.debug("[cache] exchange_info refreshed")
    return _EXINFO_CACHE

# ── Encryption ─────────────────────────────────────────────────────
_ENC_SECRET = os.getenv("DASHBOARD_JWT_SECRET")
if not _ENC_SECRET:
    raise RuntimeError("DASHBOARD_JWT_SECRET env variable is not set — cannot encrypt API keys safely")
_FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(_ENC_SECRET.encode()).digest())
_fernet = Fernet(_FERNET_KEY)


def encrypt_key(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


# ── Database ───────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "users.db"


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_copy_trading_db():
    """Create copy-trading tables in users.db."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS copy_trading_config (
            user_id       INTEGER PRIMARY KEY,
            api_key_enc   TEXT NOT NULL,
            api_secret_enc TEXT NOT NULL,
            is_active     INTEGER DEFAULT 0,
            size_pct      REAL DEFAULT 2.0,
            max_size_pct  REAL DEFAULT 5.0,
            max_leverage   INTEGER DEFAULT 20,
            daily_loss_limit REAL DEFAULT -5.0,
            scale_with_sqi INTEGER DEFAULT 1,
            tp_mode       TEXT DEFAULT 'pyramid',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS copy_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            signal_id     TEXT NOT NULL,
            pair          TEXT NOT NULL,
            direction     TEXT NOT NULL,
            entry_price   REAL,
            quantity       REAL,
            leverage       INTEGER,
            size_usd      REAL,
            status        TEXT DEFAULT 'pending',
            exchange_order_id TEXT,
            pnl_pct       REAL DEFAULT 0,
            pnl_usd       REAL DEFAULT 0,
            error_msg     TEXT,
            created_at    REAL NOT NULL,
            closed_at     REAL DEFAULT 0,
            sl_price      REAL DEFAULT 0,
            tp_prices     TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ct_user_signal ON copy_trades(user_id, signal_id);
        CREATE INDEX IF NOT EXISTS idx_ct_status ON copy_trades(status);
    """)
    conn.commit()
    # Migrate: add new columns if missing (existing deployments)
    for _col_sql in [
        "ALTER TABLE copy_trading_config ADD COLUMN tp_mode TEXT DEFAULT 'pyramid'",
        "ALTER TABLE copy_trading_config ADD COLUMN size_mode TEXT DEFAULT 'pct'",
        "ALTER TABLE copy_trading_config ADD COLUMN fixed_size_usd REAL DEFAULT 5.0",
        "ALTER TABLE copy_trading_config ADD COLUMN leverage_mode TEXT DEFAULT 'auto'",
        "ALTER TABLE copy_trading_config ADD COLUMN tradefi_signed INTEGER DEFAULT 0",
        "ALTER TABLE copy_trading_config ADD COLUMN allowed_tiers TEXT DEFAULT 'blue_chip,large_cap,mid_cap,small_cap,high_risk'",
        "ALTER TABLE copy_trading_config ADD COLUMN allowed_sectors TEXT DEFAULT 'all'",
        "ALTER TABLE copy_trading_config ADD COLUMN hot_only INTEGER DEFAULT 0",
        "ALTER TABLE copy_trading_config ADD COLUMN copy_experimental INTEGER DEFAULT 0",
        "ALTER TABLE copy_trading_config ADD COLUMN sl_mode TEXT DEFAULT 'signal'",
        "ALTER TABLE copy_trading_config ADD COLUMN sl_pct REAL DEFAULT 3.0",
        "ALTER TABLE copy_trades ADD COLUMN sl_price REAL DEFAULT 0",
        "ALTER TABLE copy_trades ADD COLUMN tp_prices TEXT DEFAULT '[]'",
    ]:
        try:
            conn.execute(_col_sql)
            conn.commit()
        except Exception:
            pass
    conn.close()
    log.info("Copy-trading tables initialized")


def save_filters(user_id: int, allowed_tiers: str, allowed_sectors: str, hot_only: bool) -> Dict:
    """Save pair tier/sector filter preferences for a user."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE copy_trading_config SET allowed_tiers=?, allowed_sectors=?, hot_only=? WHERE user_id=?",
            (allowed_tiers, allowed_sectors, int(hot_only), user_id)
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def mark_tradefi_signed(user_id: int) -> Dict:
    """Mark the TradFi-Perps agreement as signed for a user and clear any
    past -4411 errors from copy_trades so the pre-flight gate unblocks."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE copy_trading_config SET tradefi_signed=1 WHERE user_id=?",
            (user_id,)
        )
        # Wipe historical -4411 error rows so _tradfi_blocked_pairs() clears.
        conn.execute(
            "DELETE FROM copy_trades "
            "WHERE user_id=? AND status='error' AND error_msg LIKE '%TradFi%'",
            (user_id,)
        )
        conn.commit()
        # Drop in-memory cache too so the next signal re-queries fresh.
        try:
            _invalidate_tradfi_cache(user_id)
        except NameError:
            pass  # defined later in module; harmless on first call
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def has_tradefi_errors(user_id: int) -> bool:
    """Return True if the user has any recent -4411 TradFi-Perps errors."""
    conn = _get_db()
    row = conn.execute(
        "SELECT 1 FROM copy_trades WHERE user_id=? AND error_msg LIKE '%TradFi%' LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


# ── Sync → async bridge for WS API calls ──────────────────────────
# _execute_single_trade_blocking is a synchronous function running in a
# thread pool via asyncio.to_thread.  The WS API (binance_ws_api) is
# async.  To call async methods from the thread we submit coroutines
# back to the main event loop captured at FastAPI startup.
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once from app.py lifespan."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _run_async(coro, timeout: float = 30.0):
    """
    Run an async coroutine from within a sync thread, blocking the thread
    until the result is ready.  Uses the main event loop captured at startup.
    """
    if _MAIN_LOOP is None or _MAIN_LOOP.is_closed():
        raise RuntimeError("main event loop not set/closed")
    fut = asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
    return fut.result(timeout=timeout)


def _ws_orders_enabled() -> bool:
    """Feature-gate mirror so callers don't have to import binance_ws_api."""
    return os.getenv("BINANCE_WS_ORDERS", "true").strip().lower() in ("1", "true", "yes")


def _ws_call(user_id: int, method: str, rest_fn, **params):
    """
    Call a signed Binance endpoint via WS-API when possible, falling back
    to the supplied REST function (`rest_fn(**params)`) on any WS failure.

    Invariants:
      • Never double-submits: WS success → we RETURN, no REST fires.
      • On WS failure: logged, we call rest_fn ONCE.
      • On WS disabled via flag: rest_fn fires directly without log noise.
      • Timeouts in the WS path propagate to REST fallback.

    `method` is one of the binance_ws_api public functions:
      "create_order", "cancel_order", "get_order", "account_balance",
      "account_position", "account_status", "edit_order".
    """
    if not _ws_orders_enabled() or _MAIN_LOOP is None or _MAIN_LOOP.is_closed():
        return rest_fn(**params)

    try:
        import binance_ws_api as _ws
        ws_fn = getattr(_ws, method)
        # Wrap coroutine call so we can run_coroutine_threadsafe with kwargs
        async def _runner():
            return await ws_fn(user_id, **params)
        result = _run_async(_runner(), timeout=15.0)
        log.debug(f"[ws] user {user_id}: {method} OK via WebSocket")
        return result
    except Exception as ws_err:
        # Any WS failure → fall back to REST. This is the whole point of
        # the feature-flag architecture: if Binance's WS-API has a hiccup
        # we still place the order.
        log.warning(f"[ws] user {user_id}: {method} WS failed, REST fallback: {ws_err}")
        return rest_fn(**params)


# ── B4: per-pair TradFi pre-flight gate ────────────────────────────
# After a -4411 failure on (user, pair), block that specific pair until the
# user clicks "I've signed" (which calls mark_tradefi_signed and wipes the
# offending rows). Pairs are cached in-process for 60 s to avoid a DB hit
# on every signal.
_TRADFI_BLOCKED_CACHE: Dict[int, tuple] = {}   # user_id → (set_of_pairs, ts)
_TRADFI_BLOCKED_TTL = 60.0


def _tradfi_blocked_pairs(user_id: int) -> set:
    """Return the set of pairs for which this user has a past -4411 error."""
    now = time.time()
    cached = _TRADFI_BLOCKED_CACHE.get(user_id)
    if cached and (now - cached[1]) < _TRADFI_BLOCKED_TTL:
        return cached[0]
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT pair FROM copy_trades "
            "WHERE user_id=? AND error_msg LIKE '%TradFi%'",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()
    blocked = {r[0] for r in rows}
    _TRADFI_BLOCKED_CACHE[user_id] = (blocked, now)
    return blocked


def _invalidate_tradfi_cache(user_id: int):
    _TRADFI_BLOCKED_CACHE.pop(user_id, None)


# ── Config CRUD ────────────────────────────────────────────────────
def save_api_keys(user_id: int, api_key: str, api_secret: str,
                  size_pct: float = 2.0, max_size_pct: float = 5.0,
                  max_leverage: int = 20,
                  scale_with_sqi: bool = True, tp_mode: str = 'pyramid',
                  size_mode: str = 'pct', fixed_size_usd: float = 5.0,
                  leverage_mode: str = 'auto', sl_mode: str = 'signal',
                  sl_pct: float = 3.0,
                  copy_experimental: bool = False) -> Dict:
    """Encrypt and store Binance API credentials."""
    # Basic validation — explicit reject with error, no silent clamping.
    api_key = api_key.strip()
    api_secret = api_secret.strip()
    if not api_key or not api_secret:
        return {"error": "API key and secret are required"}
    if len(api_key) < 20 or len(api_secret) < 20:
        return {"error": "Invalid API key format"}
    if not (0.1 <= size_pct <= 25.0):
        return {"error": "Size % must be between 0.1 and 25.0"}
    if not (0.1 <= max_size_pct <= 50.0):
        return {"error": "Max size % must be between 0.1 and 50.0"}
    if not (1 <= int(max_leverage) <= 125):
        return {"error": "Max leverage must be between 1 and 125"}
    if not (0.1 <= float(sl_pct) <= 50.0):
        return {"error": "SL % must be between 0.1 and 50.0"}
    if not (0.10 <= float(fixed_size_usd) <= 100000.0):
        return {"error": "Fixed size must be between $0.10 and $100,000"}
    if tp_mode not in ('tp1_only', 'tp1_tp2', 'pyramid', 'all_tps'):
        return {"error": "Invalid tp_mode"}
    if size_mode not in ('pct', 'fixed_usd'):
        return {"error": "Invalid size_mode"}
    if leverage_mode not in ('auto', 'fixed', 'max_pair'):
        return {"error": "Invalid leverage_mode"}
    if sl_mode not in ('signal', 'pct', 'none'):
        return {"error": "Invalid sl_mode"}

    # Validate key permissions (non-blocking: save keys even if validation fails)
    validation = _validate_binance_key(api_key, api_secret)
    # Hard-block ONLY on withdrawal permission — this is a security risk
    if validation.get("error") and "withdrawal" in validation["error"].lower():
        return validation
    if validation.get("error") and "internal transfer" in validation["error"].lower():
        return validation

    now = time.time()
    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO copy_trading_config
                (user_id, api_key_enc, api_secret_enc, size_pct, max_size_pct,
                 max_leverage, scale_with_sqi, tp_mode,
                 size_mode, fixed_size_usd, leverage_mode, sl_mode, sl_pct,
                 copy_experimental, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                api_key_enc=excluded.api_key_enc,
                api_secret_enc=excluded.api_secret_enc,
                size_pct=excluded.size_pct,
                max_size_pct=excluded.max_size_pct,
                max_leverage=excluded.max_leverage,
                scale_with_sqi=excluded.scale_with_sqi,
                tp_mode=excluded.tp_mode,
                size_mode=excluded.size_mode,
                fixed_size_usd=excluded.fixed_size_usd,
                leverage_mode=excluded.leverage_mode,
                sl_mode=excluded.sl_mode,
                sl_pct=excluded.sl_pct,
                copy_experimental=excluded.copy_experimental,
                updated_at=excluded.updated_at
        """, (user_id, encrypt_key(api_key), encrypt_key(api_secret),
              size_pct, max_size_pct, max_leverage,
              int(scale_with_sqi), tp_mode, size_mode, fixed_size_usd,
              leverage_mode, sl_mode, sl_pct, int(copy_experimental), now, now))
        conn.commit()
        _invalidate_client_cache(user_id)  # force fresh client with new keys on next trade
        result = {"success": True, "permissions": validation.get("permissions", {})}
        if validation.get("error"):
            result["warning"] = validation["error"]
        if validation.get("balance_usdt") is not None:
            result["balance_usdt"] = validation["balance_usdt"]
        return result
    except Exception as e:
        return {"error": f"Database error: {e}"}
    finally:
        conn.close()


def get_config(user_id: int) -> Optional[Dict]:
    """Get copy-trading config (without decrypted keys)."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM copy_trading_config WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    # Mask keys for display
    try:
        ak = decrypt_key(d['api_key_enc'])
        d['api_key_masked'] = ak[:6] + '...' + ak[-4:]
    except InvalidToken:
        d['api_key_masked'] = '***corrupted***'
    del d['api_key_enc']
    del d['api_secret_enc']
    d['has_tradefi_errors'] = has_tradefi_errors(user_id)
    # PP4 · API-key rotation nudge — surface age so the UI can show a
    # soft banner at 90 days and a stronger one at 180. The key itself
    # is still perfectly valid; rotation is a hygiene recommendation,
    # not a forced expiry.
    try:
        import time as _t
        age = max(0.0, _t.time() - float(d.get('updated_at') or d.get('created_at') or 0))
        d['api_key_age_days']        = round(age / 86400.0, 1)
        d['api_key_rotation_needed'] = age >= (90 * 86400)      # >= 90 d: suggest
        d['api_key_rotation_urgent'] = age >= (180 * 86400)     # >= 180 d: strong
    except Exception:
        d['api_key_age_days']        = None
        d['api_key_rotation_needed'] = False
        d['api_key_rotation_urgent'] = False
    return d


def _get_decrypted_keys(user_id: int) -> Optional[tuple]:
    """Internal: get decrypted API key + secret."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT api_key_enc, api_secret_enc FROM copy_trading_config WHERE user_id=?",
            (user_id,)
        ).fetchone()
        conn.close()
    except Exception as e:
        log.error(f"[keys] DB error reading keys for user {user_id}: {e}")
        return None
    if not row:
        return None
    try:
        return decrypt_key(row['api_key_enc']), decrypt_key(row['api_secret_enc'])
    except InvalidToken:
        log.error(f"[keys] InvalidToken decrypting keys for user {user_id}")
        return None
    except Exception as e:
        log.error(f"[keys] Unexpected error decrypting keys for user {user_id}: {e}")
        return None


def _classify_binance_error(e: Exception) -> Dict:
    """Map a raw Binance client exception to a short code + user-facing hint.
    The UI uses `code` to render an actionable message; `detail` is the
    raw message for support/debugging (shown in a tooltip)."""
    msg = str(e)
    low = msg.lower()
    if "-2015" in msg or "invalid api-key" in low or "ip, or permissions" in low:
        return {"code": "invalid_key_or_ip",
                "hint": "API key invalid, IP not whitelisted, or Futures permission missing on the key. "
                        "Re-check the key and add this server's IP to the whitelist.",
                "detail": msg}
    if "-2014" in msg or "api-key format" in low:
        return {"code": "bad_key_format",
                "hint": "API key format is invalid. Re-paste it without extra whitespace.",
                "detail": msg}
    if "-1022" in msg or "signature" in low:
        return {"code": "bad_signature",
                "hint": "API secret is wrong, or the server clock is out of sync. Re-paste the secret.",
                "detail": msg}
    if "-1021" in msg or "recvwindow" in low or "timestamp" in low:
        return {"code": "clock_skew",
                "hint": "Server clock is drifting. Restart NTP sync on the host.",
                "detail": msg}
    if "-4131" in msg or "tradfi" in low:
        return {"code": "tradfi_unsigned",
                "hint": "Binance TradFi-Perps agreement not signed. Sign it in Binance Futures UI.",
                "detail": msg}
    if "timed out" in low or "timeout" in low or "read timed out" in low:
        return {"code": "timeout",
                "hint": "Binance did not respond within 30 s. Try again in a moment.",
                "detail": msg}
    if "connection" in low or "dns" in low or "name or service" in low:
        return {"code": "network",
                "hint": "Can't reach Binance (network/DNS). Check server connectivity.",
                "detail": msg}
    return {"code": "unknown", "hint": msg, "detail": msg}


# ── Live-balance cache (per-user, 15 s TTL) ─────────────────────────────
# The dashboard polls /api/copy-trading/balance every couple of seconds. Each
# miss fires TWO Binance REST calls (futures_account_balance + futures_account)
# whose weight adds up quickly. Without this cache we burn through Binance's
# IP-weight budget and get slapped with a -1003 ban on the entire server IP,
# which also kills order placement. TTL=15 s means at most 8 Binance calls/min
# per user — well within budget.
_BALANCE_CACHE: Dict[int, Dict] = {}    # user_id → result dict
_BALANCE_TS:    Dict[int, float] = {}
_BALANCE_TTL = 15.0

# Global ban-until timestamp (seconds since epoch). When Binance returns -1003
# with "banned until <ms>" we remember it and short-circuit ALL futures_*
# REST calls until the ban lifts — preventing us from poking an already-banned
# endpoint and extending the ban.
_BINANCE_IP_BAN_UNTIL: float = 0.0


def _binance_ip_banned_until() -> float:
    """Return epoch seconds when the current IP ban lifts, or 0 if not banned."""
    global _BINANCE_IP_BAN_UNTIL
    if _BINANCE_IP_BAN_UNTIL and time.time() >= _BINANCE_IP_BAN_UNTIL:
        _BINANCE_IP_BAN_UNTIL = 0.0
    return _BINANCE_IP_BAN_UNTIL


def _note_binance_ip_ban(msg: str):
    """Parse '-1003 ... banned until <ms>' out of a Binance error and remember it."""
    global _BINANCE_IP_BAN_UNTIL
    try:
        m = re.search(r'banned until (\d{10,})', msg)
        if m:
            until_ms = int(m.group(1))
            _BINANCE_IP_BAN_UNTIL = until_ms / 1000.0
            log.warning(f"[rate-limit] Binance IP ban detected until {time.ctime(_BINANCE_IP_BAN_UNTIL)} "
                        f"— all REST calls short-circuited until then")
    except Exception:
        pass


def get_live_balance(user_id: int) -> Dict:
    """Fetch live Binance Futures USDT balance for the user.

    Preferred path (zero Binance REST cost): the per-user WebSocket User
    Data Stream maintains a push-updated in-memory state. If fresh, return
    it directly — no REST call, no rate-limit budget consumed.

    Fallback path: the 15-second REST cache below, which itself falls back
    to a live futures_account / futures_account_balance pair on miss.
    """
    # ── WebSocket User Data Stream (primary source) ─────────────────────
    # Push-based; costs exactly zero signed REST calls. If the stream is
    # fresh we bypass REST entirely, which is what eliminated the -1003
    # IP ban risk.
    try:
        from binance_user_stream import get_state as _ws_state, is_fresh as _ws_fresh
        if _ws_fresh(user_id):
            s = _ws_state(user_id) or {}
            return {
                "balance_usdt":       s.get("balance_usdt", 0.0),
                "available_usdt":     s.get("available_usdt", 0.0),
                "unrealized_pnl":     s.get("unrealized_pnl", 0.0),
                "unrealized_pnl_pct": s.get("unrealized_pnl_pct", 0.0),
                "total_invested_usd": s.get("total_invested_usd", 0.0),
                "positions":          s.get("positions") or {},
                "server_time":        s.get("server_time", time.time()),
                "source":             "websocket",
            }
    except Exception as _ws_e:
        # Any failure in the WS layer → silently fall through to REST.
        log.debug(f"[balance] WS state unavailable for user {user_id}: {_ws_e}")

    # Serve from cache if fresh
    _now = time.time()
    _cached = _BALANCE_CACHE.get(user_id)
    if _cached is not None and (_now - _BALANCE_TS.get(user_id, 0)) < _BALANCE_TTL:
        return {**_cached, "cached": True}

    # If the IP is currently banned, return the last cached payload (even if
    # stale) with a clear error field so the UI can show the banner. Do NOT
    # hit Binance — that only extends the ban.
    _ban_until = _binance_ip_banned_until()
    if _ban_until:
        retry_in = max(1, int(_ban_until - _now))
        base = dict(_cached) if _cached else {
            "balance_usdt": 0, "available_usdt": 0, "unrealized_pnl": 0,
            "total_invested_usd": 0, "positions": {},
        }
        base.update({
            "error": f"Live Binance balance unavailable — IP rate-limited for {retry_in}s",
            "error_code": "rate_limited",
            "error_detail": f"Banned until {time.ctime(_ban_until)} (server-side protection active)",
            "rate_limited": True,
            "retry_in_seconds": retry_in,
            "stale": True,
            "server_time": _now,
        })
        return base

    keys = _get_decrypted_keys(user_id)
    if not keys:
        return {"error": "No API keys configured",
                "error_code": "no_keys",
                "error_hint": "Paste your Binance Futures API key + secret below to see live balance."}
    api_key, api_secret = keys
    try:
        from binance.client import Client
        client = Client(api_key, api_secret, requests_params={"proxies": {}, "timeout": 30})  # NO proxy — server IP must be whitelisted
        balances = client.futures_account_balance()
        usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
        if not usdt:
            return {"balance_usdt": 0.0, "available_usdt": 0.0, "unrealized_pnl": 0.0, "total_invested_usd": 0.0}
        total  = float(usdt.get('balance', 0))
        avail  = float(usdt.get('availableBalance', 0))
        # unrealizedProfit + per-position live PnL are both in futures_account.
        # Piggy-back on that single call so the dashboard can refresh balance
        # cards AND the open-trade rows on the same 5 s tick — no extra API
        # round-trip, no extra Binance rate-limit cost.
        positions: Dict[str, Dict] = {}
        unrealized_pct = 0.0
        try:
            acc = client.futures_account()
            unrealized = float(acc.get('totalUnrealizedProfit', 0))
            total_invested = float(acc.get('totalInitialMargin', 0))
            # Account-level ROI: unrealized / initial margin * 100. Matches
            # how Binance shows position ROI% in the Futures UI.
            unrealized_pct = round(unrealized / total_invested * 100, 2) if total_invested else 0.0
            for p in (acc.get('positions') or []):
                amt = float(p.get('positionAmt', 0) or 0)
                if amt == 0:
                    continue
                sym   = p.get('symbol') or ''
                entry = float(p.get('entryPrice', 0) or 0)
                lev   = int(float(p.get('leverage', 1) or 1)) or 1
                im    = abs(amt) * entry / lev if entry else 0
                pnl_u = float(p.get('unrealizedProfit', 0) or 0)
                pnl_p = (pnl_u / im * 100) if im else 0.0
                positions[sym] = {
                    "pnl_usd":   round(pnl_u, 4),
                    "pnl_pct":   round(pnl_p, 4),
                    "leverage":  lev,
                    "entry":     entry,
                }
        except Exception as _sub:
            log.warning(f"[balance] futures_account() failed for user {user_id}: {_sub}")
            unrealized = 0.0
            total_invested = 0.0
        result = {
            "balance_usdt":       round(total, 2),
            "available_usdt":     round(avail, 2),
            "unrealized_pnl":     round(unrealized, 2),
            "unrealized_pnl_pct": unrealized_pct,
            "total_invested_usd": round(total_invested, 2),
            "positions":          positions,
            "server_time":        time.time(),
        }
        # Cache for subsequent pollers (TTL above)
        _BALANCE_CACHE[user_id] = result
        _BALANCE_TS[user_id] = time.time()
        return result
    except Exception as e:
        raw = str(e)
        # Detect IP-level rate-limit ban and persist it so we stop hitting
        # Binance for the duration of the ban.
        if "-1003" in raw or "Too many requests" in raw or "banned until" in raw:
            _note_binance_ip_ban(raw)
            _ban_until = _binance_ip_banned_until()
            retry_in = max(1, int(_ban_until - time.time())) if _ban_until else 60
            # Serve last-known-good if we have one so the UI doesn't flash empty.
            base = dict(_BALANCE_CACHE.get(user_id) or {})
            base.update({
                "error": f"Live Binance balance unavailable — IP rate-limited for {retry_in}s",
                "error_code": "rate_limited",
                "error_detail": raw[:300],
                "rate_limited": True,
                "retry_in_seconds": retry_in,
                "stale": bool(base),
                "server_time": time.time(),
            })
            log.warning(f"[balance] -1003 rate-limit for user {user_id}: {raw[:200]}")
            return base
        info = _classify_binance_error(e)
        log.error(f"[balance] Binance error for user {user_id} [{info['code']}]: {info['detail']}")
        return {"error": info["hint"],
                "error_code": info["code"],
                "error_detail": info["detail"]}


def toggle_active(user_id: int, active: bool) -> Dict:
    """Enable or disable copy-trading for a user."""
    conn = _get_db()
    row = conn.execute(
        "SELECT user_id FROM copy_trading_config WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "No copy-trading configuration found. Save API keys first."}
    conn.execute(
        "UPDATE copy_trading_config SET is_active=?, updated_at=? WHERE user_id=?",
        (int(active), time.time(), user_id)
    )
    conn.commit()
    conn.close()
    result: Dict = {"success": True, "is_active": active}
    # Warn user if enabling during maintenance — trades won't execute until maintenance ends
    if active and _is_maintenance():
        result["warning"] = "Platform is currently under maintenance — copy-trade execution is paused. Your setting is saved and will take effect automatically when maintenance ends."
    return result


def update_settings(user_id: int, size_pct: float = None, max_size_pct: float = None,
                    max_leverage: int = None,
                    scale_with_sqi: bool = None, tp_mode: str = None,
                    size_mode: str = None, fixed_size_usd: float = None,
                    leverage_mode: str = None, sl_mode: str = None,
                    sl_pct: float = None,
                    copy_experimental: bool = None) -> Dict:
    """Update copy-trading settings without re-entering keys."""
    conn = _get_db()
    row = conn.execute(
        "SELECT user_id FROM copy_trading_config WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "No copy-trading configuration found"}

    updates = []
    params = []
    if size_pct is not None:
        if not (0.1 <= float(size_pct) <= 25.0):
            conn.close()
            return {"error": "Size % must be between 0.1 and 25.0"}
        updates.append("size_pct=?")
        params.append(float(size_pct))
    if max_size_pct is not None:
        if not (0.1 <= float(max_size_pct) <= 50.0):
            conn.close()
            return {"error": "Max size % must be between 0.1 and 50.0"}
        updates.append("max_size_pct=?")
        params.append(float(max_size_pct))
    if max_leverage is not None:
        if not (1 <= int(max_leverage) <= 125):
            conn.close()
            return {"error": "Max leverage must be between 1 and 125"}
        updates.append("max_leverage=?")
        params.append(int(max_leverage))
    if scale_with_sqi is not None:
        updates.append("scale_with_sqi=?")
        params.append(int(scale_with_sqi))
    if tp_mode is not None:
        _VALID = {'tp1_only', 'tp1_tp2', 'pyramid', 'all_tps'}
        if tp_mode in _VALID:
            updates.append("tp_mode=?")
            params.append(tp_mode)
    if size_mode is not None and size_mode in ('pct', 'fixed_usd'):
        updates.append("size_mode=?")
        params.append(size_mode)
    if fixed_size_usd is not None:
        updates.append("fixed_size_usd=?")
        params.append(max(0.10, min(float(fixed_size_usd), 9999.0)))
    if leverage_mode is not None and leverage_mode in ('auto', 'fixed', 'max_pair'):
        updates.append("leverage_mode=?")
        params.append(leverage_mode)
    if sl_mode is not None and sl_mode in ('signal', 'pct', 'none'):
        updates.append("sl_mode=?")
        params.append(sl_mode)
    if sl_pct is not None:
        updates.append("sl_pct=?")
        params.append(max(0.1, min(float(sl_pct), 50.0)))
    if copy_experimental is not None:
        updates.append("copy_experimental=?")
        params.append(int(copy_experimental))

    if not updates:
        conn.close()
        return {"error": "No settings to update"}

    updates.append("updated_at=?")
    params.append(time.time())
    params.append(user_id)

    conn.execute(
        f"UPDATE copy_trading_config SET {', '.join(updates)} WHERE user_id=?", params
    )
    conn.commit()
    conn.close()
    return {"success": True}


def delete_config(user_id: int) -> Dict:
    """Remove API keys and config entirely."""
    conn = _get_db()
    conn.execute("DELETE FROM copy_trading_config WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"success": True}


# ── Live PnL for open trades ────────────────────────────────────────
def get_open_trades_live_pnl(user_id: int) -> Dict[str, Dict]:
    """
    Returns {pair: {pnl_usd, pnl_pct, mark_price}} for every open Binance
    Futures position belonging to this user.  Used to enrich trade history
    with live unrealized PnL so the dashboard shows real numbers instead of
    'Open' / '—'.
    """
    client = _get_futures_client(user_id)
    if not client:
        return {}
    try:
        positions = client.futures_position_information()
    except Exception as e:
        log.warning(f"[live_pnl] Binance fetch failed for user {user_id}: {e}")
        return {}

    result: Dict[str, Dict] = {}
    for p in positions:
        amt = float(p.get('positionAmt', 0))
        if amt == 0:
            continue
        sym        = p.get('symbol', '')
        pnl_usd    = round(float(p.get('unRealizedProfit', 0)), 4)
        mark_price = float(p.get('markPrice', 0))
        entry      = float(p.get('entryPrice', 0))
        leverage   = int(float(p.get('leverage', 1))) or 1
        # Binance ROI% = unRealizedProfit / initialMargin * 100
        # initialMargin = abs(positionAmt) * entryPrice / leverage
        initial_margin = abs(amt) * entry / leverage if entry else 0
        if initial_margin:
            pnl_pct = round(pnl_usd / initial_margin * 100, 4)
        elif entry and mark_price:
            side = 1 if amt > 0 else -1
            pnl_pct = round(side * (mark_price - entry) / entry * 100 * leverage, 4)
        else:
            pnl_pct = 0.0
        result[sym] = {
            'pnl_usd':    pnl_usd,
            'pnl_pct':    pnl_pct,
            'mark_price': mark_price,
        }
    return result


# ── Recalculate realized PnL for every closed copy-trade ───────────
def backfill_closed_pnl(user_id: int, lookback_days: int = 90,
                       only_missing: bool = False) -> Dict:
    """
    Recompute realized PnL (USD + leverage-aware %) for every closed
    copy-trade in the last `lookback_days`.

    PREVIOUS BEHAVIOUR (caused -1003 IP bans):
      Fired ONE `futures_income_history` REST call PER closed trade in a
      tight loop — easily 50–200 signed calls in rapid succession.

    NEW BEHAVIOUR:
      1. Refuse to run if the IP is currently under a Binance ban window.
      2. Fetch income history in BATCHES covering the whole lookback window
         (one call returns up to 1000 records), then match locally.
      3. Paginate forward until exhausted, never hitting the same endpoint
         more than ceil(total_records / 1000) times.
      4. Sleep 250 ms between pages as a cheap extra rate-limit guard.

    Args:
      lookback_days: how far back to look (default 90 d, effectively all).
      only_missing:  if True, skip trades that already have a non-zero
                     pnl_usd. Default False — refreshes every row.

    Returns: {updated, skipped, errors, api_calls}.
    """
    # Hard gate — if we're already banned, don't poke the endpoint and
    # extend the ban window.
    _ban_until = _binance_ip_banned_until()
    if _ban_until:
        retry_in = max(1, int(_ban_until - time.time()))
        return {"error": f"Binance IP rate-limited for {retry_in}s — try again later",
                "error_code": "rate_limited",
                "retry_in_seconds": retry_in,
                "updated": 0, "skipped": 0, "errors": []}

    client = _get_futures_client(user_id)
    if not client:
        return {"error": "Failed to connect to Binance — check API keys"}

    cutoff = time.time() - lookback_days * 86400
    conn = _get_db()
    where = "WHERE user_id=? AND status='closed' AND created_at > ?"
    if only_missing:
        where += " AND (pnl_usd IS NULL OR pnl_usd=0)"
    rows = conn.execute(
        f"SELECT * FROM copy_trades {where}",
        (user_id, cutoff)
    ).fetchall()
    conn.close()
    rows = [dict(r) for r in rows]
    if not rows:
        return {"updated": 0, "skipped": 0, "errors": [], "api_calls": 0}

    # ── Batch-fetch ALL REALIZED_PNL income across the whole window ──
    # One paginated scan across ALL pairs beats N per-pair scans. Binance
    # caps `limit=1000` per call; we paginate forward using startTime.
    import math as _math
    window_start_ms = int(min(r.get('created_at', cutoff) or cutoff for r in rows) * 1000)
    window_end_ms   = int((max((r.get('closed_at') or time.time()) for r in rows) * 1000)
                          + 10 * 60 * 1000)  # +10 min pad

    income_records: List[Dict[str, Any]] = []
    api_calls = 0
    cursor = window_start_ms
    MAX_PAGES = 30  # safety cap: 30 × 1000 = 30k rows; plenty for 90-day history
    for _page in range(MAX_PAGES):
        # Ban-check between pages too — short-circuit if we got banned mid-scan
        if _binance_ip_banned_until():
            log.warning("[backfill_pnl] aborting pagination — IP ban detected mid-scan")
            break
        try:
            page = client.futures_income_history(
                incomeType='REALIZED_PNL',
                startTime=cursor,
                endTime=window_end_ms,
                limit=1000,
            )
            api_calls += 1
        except Exception as e:
            raw = str(e)
            if "-1003" in raw or "banned until" in raw:
                _note_binance_ip_ban(raw)
                log.error(f"[backfill_pnl] hit -1003 during pagination: {raw[:200]}")
                return {"error": "Binance rate-limited mid-scan — partial results discarded",
                        "error_code": "rate_limited",
                        "updated": 0, "skipped": 0, "errors": [raw[:200]],
                        "api_calls": api_calls}
            log.error(f"[backfill_pnl] fetch error page {_page}: {raw[:200]}")
            return {"error": raw[:200], "updated": 0, "skipped": 0,
                    "errors": [raw[:200]], "api_calls": api_calls}

        if not page:
            break
        income_records.extend(page)
        if len(page) < 1000:
            break  # last page
        # Advance cursor past the last record's time (+1 ms to avoid dupes)
        cursor = int(page[-1].get('time', cursor)) + 1
        time.sleep(0.25)  # small rate-limit guard between pages

    # Index income by (symbol, time) for fast per-trade lookup
    by_pair: Dict[str, List[Dict[str, Any]]] = {}
    for inc in income_records:
        by_pair.setdefault(inc.get('symbol', ''), []).append(inc)

    # ── Apply to each trade using the already-fetched data ──
    updated, skipped, errors = 0, 0, []
    for t in rows:
        pair      = t.get('pair', '')
        qty       = float(t.get('quantity', 0) or 0)
        entry_px  = float(t.get('entry_price', 0) or 0)
        lev       = int(t.get('leverage', 1) or 1)
        start_ms  = int(t.get('created_at', cutoff) * 1000)
        end_ms    = int((t.get('closed_at') or time.time()) * 1000) + 10 * 60 * 1000

        try:
            pair_income = by_pair.get(pair) or []
            matching = [i for i in pair_income
                        if start_ms <= int(i.get('time', 0)) <= end_ms]
            if not matching:
                skipped += 1
                continue
            pnl_usd = round(sum(float(i.get('income', 0) or 0) for i in matching), 4)
            if pnl_usd == 0:
                skipped += 1
                continue
            init_margin = qty * entry_px / lev if (qty and entry_px and lev) else 0
            pnl_pct = round(pnl_usd / init_margin * 100, 4) if init_margin else 0

            conn2 = _get_db()
            try:
                conn2.execute(
                    "UPDATE copy_trades SET pnl_usd=?, pnl_pct=? WHERE id=?",
                    (pnl_usd, pnl_pct, t['id'])
                )
                conn2.commit()
            finally:
                conn2.close()
            updated += 1
        except Exception as e:
            errors.append(f"{pair}: {str(e)[:80]}")
            log.warning(f"[backfill_pnl] {pair} local match failed: {e}")

    log.info(f"[backfill_pnl] user={user_id} done: updated={updated} "
             f"skipped={skipped} api_calls={api_calls} "
             f"(was O(N={len(rows)}), now O(pages))")
    return {"updated": updated, "skipped": skipped,
            "errors": errors, "api_calls": api_calls}


# ── Trade History ──────────────────────────────────────────────────
def get_trade_history(user_id: int, limit: int = 50) -> List[Dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM copy_trades WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_stats(user_id: int) -> Dict:
    """Aggregate stats for a user's copy-trades."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT status, pnl_pct, pnl_usd, size_usd, created_at FROM copy_trades WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return {"total": 0, "open": 0, "won": 0, "lost": 0,
                "total_pnl_usd": 0, "win_rate": 0, "avg_win_usd": 0,
                "avg_loss_usd": 0, "best_trade_usd": 0, "worst_trade_usd": 0,
                "total_invested_usd": 0, "roi_pct": 0, "profit_factor": 0}

    executed = [r for r in rows if r['status'] not in ('error', 'skipped')]
    total  = len(executed)
    opened = sum(1 for r in executed if r['status'] in ('open', 'pending'))
    closed = [r for r in executed if r['status'] == 'closed']
    winners = [r for r in closed if r['pnl_usd'] > 0]
    losers  = [r for r in closed if r['pnl_usd'] <= 0]
    won  = len(winners)
    lost = len(losers)
    total_pnl      = sum(r['pnl_usd'] for r in closed)
    gross_profit   = sum(r['pnl_usd'] for r in winners)
    gross_loss     = abs(sum(r['pnl_usd'] for r in losers))
    total_invested = sum(r['size_usd'] for r in executed if r['size_usd'])
    wr = round(won / len(closed) * 100, 1) if closed else 0
    avg_win  = round(gross_profit / won, 2)  if won  else 0
    avg_loss = round(gross_loss  / lost, 2)  if lost else 0
    best  = round(max((r['pnl_usd'] for r in closed), default=0), 2)
    worst = round(min((r['pnl_usd'] for r in closed), default=0), 2)
    roi   = round(total_pnl / total_invested * 100, 2) if total_invested else 0
    pf    = round(gross_profit / gross_loss, 2) if gross_loss else (999 if gross_profit > 0 else 0)

    return {
        "total": total, "open": opened, "won": won, "lost": lost,
        "total_pnl_usd": round(total_pnl, 2), "win_rate": wr,
        "avg_win_usd": avg_win, "avg_loss_usd": avg_loss,
        "best_trade_usd": best, "worst_trade_usd": worst,
        "total_invested_usd": round(total_invested, 2),
        "roi_pct": roi, "profit_factor": pf,
    }


# ── Binance API Validation ────────────────────────────────────────
def _validate_binance_key(api_key: str, api_secret: str) -> Dict:
    """Validate API key: must have futures trading, must NOT have withdrawal."""
    try:
        from binance.client import Client
        client = Client(api_key, api_secret, requests_params={"proxies": {}, "timeout": 30})  # NO proxy — server IP must be whitelisted
        info = client.get_account_api_trading_status()
        perms = client.get_account_api_permissions()

        can_trade = perms.get('enableFutures', False) or perms.get('futuresTradingAllowed', False)
        can_withdraw = perms.get('enableWithdrawals', False)
        can_internal = perms.get('enableInternalTransfer', False)

        if can_withdraw:
            return {"error": "SECURITY RISK: This API key has withdrawal permissions enabled. "
                    "Create a new key with ONLY 'Enable Futures' — no withdrawal, no transfer."}
        if can_internal:
            return {"error": "SECURITY RISK: This API key has internal transfer permissions. "
                    "Create a new key with ONLY 'Enable Futures'."}
        if not can_trade:
            return {"error": "This API key does not have futures trading permission. "
                    "Enable 'Futures' on your Binance API key settings."}

        # Quick futures balance check
        try:
            futures_balance = client.futures_account_balance()
            usdt_bal = next((b for b in futures_balance if b['asset'] == 'USDT'), None)
            balance = float(usdt_bal['balance']) if usdt_bal else 0
        except Exception:
            balance = 0

        return {
            "success": True,
            "permissions": {
                "futures_trading": True,
                "withdrawals": False,
                "internal_transfer": can_internal,
            },
            "balance_usdt": balance,
        }
    except Exception as e:
        err = str(e)
        if 'Invalid API-key' in err or 'APIError' in err:
            return {"error": "Invalid API key or secret. Check your credentials."}
        return {"error": f"Validation failed: {err}"}


def _get_futures_client(user_id: int):
    """Return a cached Binance futures client for a user (TTL=10min). Creates fresh on miss."""
    now = time.time()
    if user_id in _CLIENT_CACHE and (now - _CLIENT_TS.get(user_id, 0)) < _CLIENT_TTL:
        return _CLIENT_CACHE[user_id]
    # Cache miss — create new client below
    client = _get_futures_client_fresh(user_id)
    if client:
        _CLIENT_CACHE[user_id] = client
        _CLIENT_TS[user_id] = now
    return client


def _invalidate_client_cache(user_id: int):
    """Call after key update so next trade gets a fresh client."""
    _CLIENT_CACHE.pop(user_id, None)
    _CLIENT_TS.pop(user_id, None)
    _HEDGE_CACHE.pop(user_id, None)
    _HEDGE_TS.pop(user_id, None)
    _invalidate_leverage_margin_caches(user_id)


def _get_futures_client_fresh(user_id: int):
    """Create a Binance futures client for a user. Retries up to 3x on transient errors."""
    keys = _get_decrypted_keys(user_id)
    if not keys:
        log.error(f"[client] No keys for user {user_id} — decryption failed or no config")
        return None
    from binance.client import Client
    import time as _time
    last_err = None
    for attempt in range(1, 4):
        try:
            return Client(keys[0], keys[1], requests_params={"proxies": {}, "timeout": 30})  # NO proxy — server IP must be whitelisted
        except Exception as e:
            last_err = e
            log.warning(f"[client] Binance Client init attempt {attempt}/3 failed for user {user_id}: {e}")
            if attempt < 3:
                _time.sleep(attempt * 1.5)
    log.error(f"[client] All 3 init attempts failed for user {user_id}: {last_err}")
    return None


# ── Order Execution Engine ─────────────────────────────────────────
async def execute_copy_trades(signal_data: Dict):
    """
    Called when a new signal is registered. Finds all active copy-traders
    and places orders for each.

    signal_data expected keys:
        signal_id, pair, direction (LONG/SHORT), price, targets, stop_loss,
        leverage, sqi_score, sqi_grade
    """
    signal_id = signal_data.get('signal_id', '')
    pair = signal_data.get('pair', '')
    direction = signal_data.get('direction', '').upper()
    entry_price = float(signal_data.get('price', 0))
    stop_loss = float(signal_data.get('stop_loss', 0))
    targets = signal_data.get('targets', [])
    leverage = int(signal_data.get('leverage', 5))
    sqi_score = float(signal_data.get('sqi_score', 50))
    signal_tier = str(signal_data.get('signal_tier', 'production') or 'production').lower()

    if not all([signal_id, pair, direction, entry_price, stop_loss]):
        log.warning(f"Copy-trade skipped: incomplete signal data for {signal_id}")
        return []

    # Global maintenance gate — pause all copy-trading when admin enabled it
    if _is_maintenance():
        log.warning(f"[execute_copy_trades] BLOCKED (maintenance mode) — signal {signal_id}")
        return []

    # Binance IP rate-limit ban gate — don't poke an already-banned endpoint
    # (each rejected call resets the ban timer). Skip the signal entirely;
    # Binance will auto-restore access when the ban lifts.
    _ban_until = _binance_ip_banned_until()
    if _ban_until:
        log.warning(f"[execute_copy_trades] BLOCKED (Binance IP ban active until "
                    f"{time.ctime(_ban_until)}) — signal {signal_id} skipped")
        return []

    # Get all active copy-trading configs
    conn = _get_db()
    configs = conn.execute(
        "SELECT ctc.*, u.tier, u.tier_expires FROM copy_trading_config ctc "
        "JOIN users u ON ctc.user_id = u.id "
        "WHERE ctc.is_active = 1"
    ).fetchall()
    conn.close()

    results = []
    eligible = []
    for cfg in configs:
        cfg = dict(cfg)
        uid = cfg['user_id']

        # Duplicate signal guard — skip if already executed (non-error)
        _dup_conn = _get_db()
        _dup = _dup_conn.execute(
            "SELECT id FROM copy_trades WHERE user_id=? AND signal_id=? AND status NOT IN ('error')",
            (uid, signal_id)
        ).fetchone()
        _dup_conn.close()
        if _dup:
            log.info(f"Copy-trade skip user {uid}: signal {signal_id} already executed")
            continue

        # Must be Pro tier or higher (canonical: plus < pro <= ultra).
        # canonicalize_tier also tolerates legacy 'elite' values on stale JWTs.
        # `tier_rank` / `TIERS_CANONICAL` now imported at module level (B1 fix).
        if tier_rank(cfg.get('tier')) < TIERS_CANONICAL['pro']:
            log.info(f"Copy-trade skip user {uid}: tier below Pro (have '{cfg.get('tier')}')")
            continue
        if cfg.get('tier_expires', 0) and time.time() > cfg['tier_expires']:
            log.info(f"Copy-trade skip user {uid}: tier expired")
            continue

        if signal_tier == 'experimental' and not bool(cfg.get('copy_experimental', 0)):
            log.info(f"Copy-trade skip user {uid}: experimental signal {signal_id} not enabled")
            continue

        # B4: TradFi pre-flight — skip pairs that previously failed with
        # -4411 until the user clicks "I've signed" in the UI.
        if pair in _tradfi_blocked_pairs(uid):
            log.info(f"Copy-trade skip user {uid}: {pair} blocked — TradFi-Perps agreement not signed")
            _record_trade(uid, signal_id, pair, direction, 0, 0, leverage, 0,
                          'skipped',
                          error_msg=f"TradFi-Perps agreement not signed for {pair}. "
                                    "Sign it on Binance Futures, then click 'I've signed' in the dashboard.")
            continue

        # Pair classification filter
        try:
            from market_classifier import get_pair_info as _get_pair_info
            _info = _get_pair_info(pair)
            _allowed_tiers = (cfg.get('allowed_tiers') or 'blue_chip,large_cap,mid_cap,small_cap,high_risk').split(',')
            _allowed_sectors_raw = cfg.get('allowed_sectors') or 'all'
            _hot_only = bool(cfg.get('hot_only', 0))
            if _info['tier'] not in _allowed_tiers:
                log.info(f"Copy-trade skip user {uid}: {pair} tier '{_info['tier']}' not in allowed tiers")
                _record_trade(uid, signal_id, pair, direction, 0, 0, leverage, 0,
                              'skipped', error_msg=f"Tier '{_info['tier']}' filtered out by user settings")
                continue
            if _allowed_sectors_raw != 'all':
                _allowed_sectors = _allowed_sectors_raw.split(',')
                if _info['sector'] not in _allowed_sectors:
                    log.info(f"Copy-trade skip user {uid}: {pair} sector '{_info['sector']}' not allowed")
                    _record_trade(uid, signal_id, pair, direction, 0, 0, leverage, 0,
                                  'skipped', error_msg=f"Sector '{_info['sector']}' filtered out by user settings")
                    continue
            if _hot_only and not _info['is_hot']:
                log.info(f"Copy-trade skip user {uid}: {pair} is not HOT (hot_only=True)")
                _record_trade(uid, signal_id, pair, direction, 0, 0, leverage, 0,
                              'skipped', error_msg='Pair is not a HOT token (filtered by hot_only setting)')
                continue
        except ImportError:
            pass  # market_classifier not available — skip filter silently

        eligible.append((uid, cfg))

    # Execute ALL eligible users in parallel — each in its own thread
    if eligible:
        tasks = [
            asyncio.to_thread(_execute_single_trade_sync, uid, cfg, signal_data)
            for uid, cfg in eligible
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Log any unexpected exceptions
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                uid = eligible[i][0]
                log.error(f"[copy_trading] unhandled exception for user {uid}: {r}")
                _record_trade(uid, signal_id, pair, direction, 0, 0, 0, 0,
                              'error', error_msg=str(r)[:300])
        results = [r for r in results if not isinstance(r, Exception)]

    if results:
        log.info(f"Copy-trades for {signal_id}: {len(results)} executions attempted")
    return results


def _execute_single_trade_sync(user_id: int, config: Dict, signal: Dict) -> Dict:
    """Synchronous wrapper — runs in a thread pool via asyncio.to_thread."""
    import asyncio as _asyncio
    loop = None
    try:
        loop = _asyncio.get_event_loop()
    except RuntimeError:
        pass
    if loop and loop.is_running():
        # We are already inside asyncio.to_thread — just call sync version directly
        return _execute_single_trade_blocking(user_id, config, signal)
    return _execute_single_trade_blocking(user_id, config, signal)


async def _execute_single_trade(user_id: int, config: Dict, signal: Dict) -> Dict:
    """Async wrapper kept for backward compatibility."""
    return await asyncio.to_thread(_execute_single_trade_blocking, user_id, config, signal)


def _execute_single_trade_blocking(user_id: int, config: Dict, signal: Dict) -> Dict:
    """Execute a copy-trade for one user (blocking, runs in thread pool)."""
    signal_id = signal['signal_id']
    pair = signal['pair']
    direction = signal['direction'].upper()
    entry_price = float(signal['price'])
    stop_loss = float(signal['stop_loss'])
    targets = signal.get('targets', [])
    sig_leverage = int(signal.get('leverage', 5))
    sqi_score = float(signal.get('sqi_score', 50))

    # Leverage mode: auto (signal-capped), fixed (user-set exact), max_pair (resolved inside try)
    leverage_mode = config.get('leverage_mode', 'auto')
    if leverage_mode == 'fixed':
        leverage = int(config.get('max_leverage', 20))
    else:  # 'auto' or 'max_pair' — max_pair refined after client is ready
        leverage = min(sig_leverage, int(config.get('max_leverage', 125)))

    try:
        client = _get_futures_client(user_id)
        if not client:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, 0, 'error', error_msg='Failed to create client')

        # Detect hedge mode — cached per user to avoid redundant API calls.
        # B3: if detection fails we must NOT silently default to False — that
        # causes -4061 "position side does not match" for hedge-mode users.
        # Bail out explicitly; the outer except will surface the real reason.
        _now_hm = time.time()
        if user_id in _HEDGE_CACHE and (_now_hm - _HEDGE_TS.get(user_id, 0)) < _CLIENT_TTL:
            hedge_mode = _HEDGE_CACHE[user_id]
        else:
            try:
                pos_mode = client.futures_get_position_mode()
                hedge_mode = pos_mode.get('dualSidePosition', False)
            except Exception as _pm_e:
                # Don't guess — abort this trade and let operator see the reason.
                raise Exception(f"Could not detect position mode for user {user_id}: {_pm_e}") from _pm_e
            _HEDGE_CACHE[user_id] = hedge_mode
            _HEDGE_TS[user_id] = _now_hm
        position_side = direction if hedge_mode else 'BOTH'

        def _place_conditional(params: dict):
            """
            Place a conditional order via the Binance Algo API (migrated 2025-12-09).
            POST /fapi/v1/algoOrder with algoType=CONDITIONAL and triggerPrice.
            Falls back to legacy /fapi/v1/order for non-migrated accounts.
            """
            algo_p = {
                'symbol':      params['symbol'],
                'side':        params['side'],
                'algoType':    'CONDITIONAL',
                'type':        params['type'],
                'triggerPrice': str(params.get('stopPrice') or params.get('triggerPrice', '')),
                'workingType': params.get('workingType', 'MARK_PRICE'),
            }
            if params.get('positionSide'):
                algo_p['positionSide'] = params['positionSide']
            if params.get('closePosition'):
                algo_p['closePosition'] = 'true'
            elif params.get('quantity'):
                algo_p['quantity'] = str(params['quantity'])
            if params.get('price'):  # STOP / TAKE_PROFIT limit types
                algo_p['price'] = str(params['price'])
            try:
                return client._request_futures_api('post', 'algoOrder', True, data=algo_p)
            except Exception as _algo_e:
                _err = str(_algo_e)
                # -4120 is only raised by the LEGACY endpoint on migrated accounts.
                # If the algo endpoint rejected the order, fall back to the legacy
                # create_order path (via WS-API when enabled, REST otherwise).
                # If legacy also fails with -4120, the account is migrated and
                # something is wrong with our algo params — surface the original error.
                log.debug(f"Algo API failed ({_err}), trying legacy create_order (WS-preferred)")
                try:
                    return _ws_call(
                        user_id, "create_order",
                        lambda **p: client.futures_create_order(**p),
                        **params,
                    )
                except Exception as _legacy_e:
                    if '-4120' in str(_legacy_e):
                        raise Exception(f"Algo API failed: {_err} | Legacy endpoint also blocked (-4120 migrated account)") from _algo_e
                    raise

        # Get futures USDT balance (WS state → WS API → REST, in that order)
        balances = None
        try:
            # 1. UDS in-memory state (fastest, zero Binance cost)
            from binance_user_stream import get_state as _ws_state, is_fresh as _ws_fresh
            if _ws_fresh(user_id):
                s = _ws_state(user_id) or {}
                balances = [{
                    "asset": "USDT",
                    "balance": str(s.get("balance_usdt", 0)),
                    "availableBalance": str(s.get("available_usdt", 0)),
                }]
        except Exception:
            pass
        if balances is None:
            # 2. WS-API call (separate bucket from REST); REST fallback on failure
            balances = _ws_call(
                user_id, "account_balance",
                lambda **p: client.futures_account_balance(**p),
            )
        usdt_bal = next((b for b in (balances or []) if b.get('asset') == 'USDT'), None)
        if not usdt_bal:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, 0, 'error', error_msg='No USDT balance')

        available = float(usdt_bal['availableBalance'])
        if available < 1:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, 0, 'error', error_msg=f'Insufficient balance: ${available:.2f}')

        # Resolve pair-maximum leverage if requested
        if leverage_mode == 'max_pair':
            try:
                brackets = client.futures_leverage_bracket(symbol=pair)
                leverage = int(brackets[0]['brackets'][0]['initialLeverage'])
            except Exception as e:
                log.warning(f"Could not fetch max leverage for {pair}: {e}")

        # Calculate position size
        size_mode = config.get('size_mode', 'pct')
        max_pct = config.get('max_size_pct', 5.0) / 100.0

        if size_mode == 'fixed_usd':
            size_usd = float(config.get('fixed_size_usd', 5.0))
            # Optional SQI scaling ±25% on fixed amount, but never below $1.00
            if config.get('scale_with_sqi', 1):
                sqi_mult = 0.75 + (min(sqi_score, 167) / 167) * 0.5
                size_usd = max(round(size_usd * sqi_mult, 2), 1.0)
        else:
            # Percentage-of-balance mode
            base_pct = config.get('size_pct', 2.0) / 100.0
            if config.get('scale_with_sqi', 1):
                sqi_mult = 0.5 + (min(sqi_score, 167) / 167) * 1.0
                size_pct_calc = base_pct * sqi_mult
            else:
                size_pct_calc = base_pct
            size_pct_calc = min(size_pct_calc, max_pct)
            size_usd = available * size_pct_calc

        # Guard against truly zero sizes — let the notional-bump logic handle small sizes
        if size_usd <= 0:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, size_usd, 'skipped',
                                 error_msg='Calculated size is $0')
        if size_usd > available:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, size_usd, 'skipped',
                                 error_msg=f'Fixed size ${size_usd:.2f} exceeds available balance ${available:.2f}')

        # Get symbol info for precision (shared cache, refreshed every 5 min)
        info = _get_exchange_info_cached(client)
        sym_info = next((s for s in info['symbols'] if s['symbol'] == pair), None)
        if not sym_info:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, size_usd, 'error',
                                 error_msg=f'Symbol {pair} not found')

        # Get quantity precision, price precision, and minimum notional
        qty_precision = 3
        price_precision = 2
        min_notional = 5.0  # Binance default floor; overridden by exchange filter
        min_qty = 0.0
        step_size = 0.001  # default; overridden by LOT_SIZE filter
        tick_str = "0.01"   # B2: keep string form for exact tick-alignment via Decimal
        for f in sym_info.get('filters', []):
            if f['filterType'] == 'LOT_SIZE':
                step_str = f['stepSize']
                step_size = float(step_str)
                qty_precision = max(0, len(step_str.rstrip('0').split('.')[-1]))
                try:
                    min_qty = float(f.get('minQty', 0))
                except Exception:
                    pass
            if f['filterType'] == 'PRICE_FILTER':
                tick_str = f['tickSize']
                price_precision = max(0, len(tick_str.rstrip('0').split('.')[-1]))
            if f['filterType'] in ('MIN_NOTIONAL', 'NOTIONAL'):
                try:
                    min_notional = max(min_notional, float(f.get('notional', f.get('minNotional', 5.0))))
                except Exception:
                    pass

        # Calculate position notional and check against exchange minimum
        notional = size_usd * leverage
        if notional < min_notional:
            # Bump size_usd up to meet the minimum
            required_usd = min_notional / leverage
            # For fixed_usd mode, cap at available balance (pct cap is irrelevant)
            if size_mode == 'fixed_usd':
                max_allowed_usd = available
            else:
                max_allowed_usd = available * max_pct
            if required_usd > max_allowed_usd:
                return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                     leverage, size_usd, 'skipped',
                                     error_msg=(
                                         f'Min notional ${min_notional:.1f} requires ${required_usd:.2f} '
                                         f'margin at {leverage}x, but user max is ${max_allowed_usd:.2f}'
                                     ))
            if required_usd > available:
                return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                     leverage, size_usd, 'skipped',
                                     error_msg=f'Min notional ${min_notional:.1f} requires ${required_usd:.2f} — insufficient balance ${available:.2f}')
            log.info(f"Copy-trade [{user_id}] {pair}: bumped size ${size_usd:.2f}→${required_usd:.2f} to meet min notional ${min_notional:.1f}")
            size_usd = required_usd
            notional = size_usd * leverage

        # Calculate quantity — floor to exact step-size multiple (round() causes -4003 precision errors)
        raw_qty = notional / entry_price
        if step_size > 0:
            import math as _math
            quantity = _math.floor(raw_qty / step_size) * step_size
            quantity = round(quantity, qty_precision)  # clean float repr
        else:
            quantity = round(raw_qty, qty_precision)

        # Enforce minimum quantity step
        if min_qty > 0 and quantity < min_qty:
            quantity = round(_math.ceil(min_qty / step_size) * step_size, qty_precision)
            notional = quantity * entry_price
            size_usd = notional / leverage

        if quantity <= 0:
            return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                                 leverage, size_usd, 'error',
                                 error_msg='Calculated quantity is 0')

        # Set leverage — cached: only fires REST when leverage changes vs last trade.
        actual_leverage = _ensure_leverage_cached(client, user_id, pair, leverage)
        if actual_leverage != leverage:
            # Leverage was clamped to pair max — recalculate notional + qty
            leverage = actual_leverage
            notional = size_usd * leverage
            quantity = round(notional / entry_price, qty_precision)
            if min_qty > 0 and quantity < min_qty:
                quantity = round(min_qty, qty_precision)
                size_usd = (quantity * entry_price) / leverage

        # Set margin type to CROSS — cached: only fires once per TTL
        _ensure_margin_cross_cached(client, user_id, pair)

        # Place market order (WS API preferred, REST fallback on any failure)
        side = 'BUY' if direction == 'LONG' else 'SELL'
        order_params = dict(
            symbol=pair,
            side=side,
            type='MARKET',
            quantity=quantity,
        )
        if hedge_mode:
            order_params['positionSide'] = position_side
        order = _ws_call(
            user_id, "create_order",
            lambda **p: client.futures_create_order(**p),
            **order_params,
        )
        order_id = order.get('orderId', '')
        avg_price = float(order.get('avgPrice', 0) or 0)
        # avgPrice is '0' for MARKET orders on PM accounts — fetch actual fill from position.
        # WS-API account_position is preferred; REST is fallback.
        if avg_price == 0:
            try:
                import time as _time; _time.sleep(0.5)
                pos_info = _ws_call(
                    user_id, "account_position",
                    lambda **p: client.futures_position_information(**p),
                    symbol=pair,
                )
                for _p in (pos_info or []):
                    if _p.get('symbol') == pair and abs(float(_p.get('positionAmt', 0) or 0)) > 0:
                        avg_price = float(_p.get('entryPrice', 0) or 0)
                        break
            except Exception:
                pass
        if avg_price == 0:
            avg_price = entry_price  # final fallback to signal price

        # ── Stop-Loss placement — respects user's sl_mode setting ──
        sl_mode  = config.get('sl_mode', 'signal')
        sl_pct   = float(config.get('sl_pct', 3.0) or 3.0)
        sl_side  = 'SELL' if direction == 'LONG' else 'BUY'

        if sl_mode == 'none':
            sl_price = 0.0
            log.info(f"[{user_id}] SL mode=none — no stop-loss placed for {pair}")
        elif sl_mode == 'pct':
            # Custom percentage below (LONG) or above (SHORT) entry
            fill_ref = avg_price if avg_price else entry_price
            sl_raw   = fill_ref * (1 - sl_pct / 100) if direction == 'LONG' \
                       else fill_ref * (1 + sl_pct / 100)
            sl_price = _round_to_tick(sl_raw, tick_str)  # B2: exact tick alignment
            log.info(f"[{user_id}] SL mode=pct ({sl_pct}%) → {sl_price} for {pair}")
        else:  # 'signal' (default)
            sl_price = _round_to_tick(stop_loss, tick_str)  # B2

        if sl_price > 0:
            # Attempt exchange conditional SL (works on non-PM accounts)
            try:
                sl_params = dict(
                    symbol=pair, side=sl_side, type='STOP_MARKET',
                    stopPrice=sl_price, workingType='MARK_PRICE', closePosition=True,
                )
                if hedge_mode:
                    sl_params['positionSide'] = position_side
                _place_conditional(sl_params)
                log.info(f"SL exchange order placed user {user_id} {pair} @ {sl_price}")
            except Exception as e:
                log.info(f"SL exchange blocked ({e}) — software monitor will enforce @ {sl_price}")

        # Place TP orders — tp_mode determines how quantity is split across targets
        if targets:
            tp_mode = config.get('tp_mode', 'pyramid')
            active_tps = list(targets)  # all TPs from signal

            # Build allocation fractions based on mode
            n = len(active_tps)
            if tp_mode == 'tp1_only':
                active_tps = active_tps[:1]
                allocs = [1.0]
            elif tp_mode == 'tp1_tp2':
                active_tps = active_tps[:2]
                allocs = [0.65, 0.35] if n >= 2 else [1.0]
            elif tp_mode == 'pyramid':
                # Institutional standard: front-loaded exit, let a runner go
                if n == 1:   allocs = [1.0]
                elif n == 2: allocs = [0.60, 0.40]
                elif n == 3: allocs = [0.50, 0.30, 0.20]
                else:        allocs = [0.50, 0.30, 0.15] + [0.05 / max(1, n - 3)] * (n - 3)
            else:  # all_tps — equal split
                allocs = [1.0 / n] * n

            # Normalize in case of float drift
            total_alloc = sum(allocs)
            allocs = [a / total_alloc for a in allocs]

            placed_qty = 0.0
            for i, (tp, alloc) in enumerate(zip(active_tps, allocs)):
                tp_price = _round_to_tick(float(tp), tick_str)  # B2: exact tick alignment
                is_last = (i == len(active_tps) - 1)
                if is_last:
                    raw_close = quantity - placed_qty
                else:
                    raw_close = quantity * alloc
                # Floor to step-size (same as entry qty) to avoid -1111 precision errors
                import math as _math
                if step_size > 0:
                    close_qty = _math.floor(raw_close / step_size) * step_size
                    close_qty = round(close_qty, qty_precision)
                else:
                    close_qty = round(raw_close, qty_precision)
                close_qty = max(close_qty, 0)
                if close_qty <= 0:
                    continue
                try:
                    tp_params = dict(
                        symbol=pair,
                        side=sl_side,
                        type='TAKE_PROFIT_MARKET',
                        stopPrice=tp_price,
                        quantity=close_qty,
                        workingType='MARK_PRICE',
                    )
                    if hedge_mode:
                        tp_params['positionSide'] = position_side
                    else:
                        tp_params['reduceOnly'] = True
                    _place_conditional(tp_params)
                    placed_qty += close_qty
                    log.info(f"TP{i+1} placed user {user_id} {pair} @ {tp_price} qty={close_qty}")
                except Exception as e:
                    log.error(f"TP{i+1} FAILED user {user_id} {pair} @ {tp_price} qty={close_qty} | err={e}")

        log.info(f"Copy-trade EXECUTED: user={user_id} {direction} {pair} qty={quantity} "
                 f"lev={leverage}x size=${size_usd:.2f} order={order_id}")

        return _record_trade(user_id, signal_id, pair, direction, avg_price,
                             quantity, leverage, size_usd, 'open',
                             exchange_order_id=str(order_id),
                             sl_price=sl_price,  # already computed per sl_mode
                             tp_prices=[float(t) for t in targets] if targets else [])

    except Exception as e:
        raw = str(e)
        _BINANCE_ERRORS = {
            '-4411': 'Sign TradFi-Perps agreement on Binance for this pair (TradFi)',
            '-4061': 'Position side mismatch — Hedge-mode detection was stale; will auto-retry on next signal',
            '-2019': 'Insufficient margin — add funds or reduce size',
            '-2015': 'Invalid API key / IP / permission — copy-trading auto-paused until keys are fixed',
            '-1013': 'Order size below minimum notional',
            '-1121': 'Invalid symbol — pair may be delisted',
            '-2011': 'Order does not exist (already filled or cancelled)',
            '-4003': 'Quantity precision error — check lot size',
            '-1111': 'Precision error on quantity/price (TradFi)' if 'TradFi' in raw else 'Precision error on quantity/price',
            '-4164': 'Order notional must be ≥ minimum for this pair',
        }
        friendly = next((msg for code, msg in _BINANCE_ERRORS.items() if code in raw), None)
        error_msg = friendly if friendly else raw[:300]
        log.error(f"Copy-trade FAILED for user {user_id}: {raw}")

        # ── B3: hedge-mode was wrong → invalidate cache so next trade re-detects.
        if '-4061' in raw:
            _HEDGE_CACHE.pop(user_id, None)
            _HEDGE_TS.pop(user_id, None)
            log.info(f"[B3] Hedge-mode cache cleared for user {user_id} after -4061")

        # ── B4: first -4411 for this pair → remember it so we skip next time.
        if '-4411' in raw:
            # Ensure the error_msg contains 'TradFi' so _tradfi_blocked_pairs()
            # picks it up on the next signal.
            if 'TradFi' not in error_msg:
                error_msg = f"TradFi: {error_msg}"
            _invalidate_tradfi_cache(user_id)
            log.warning(f"[B4] {pair} added to TradFi-blocked list for user {user_id}")

        # ── B5: -2015 = bad API key / IP / permission → auto-pause this user
        # so we stop hammering Binance and the operator can surface a banner.
        if '-2015' in raw:
            try:
                _p_conn = _get_db()
                _p_conn.execute(
                    "UPDATE copy_trading_config SET is_active=0 WHERE user_id=?",
                    (user_id,)
                )
                _p_conn.commit()
                _p_conn.close()
                log.warning(
                    f"[B5] Auto-paused copy-trading for user {user_id} "
                    f"after -2015 (invalid key/IP/permissions). "
                    f"User must fix key settings + re-enable."
                )
            except Exception as _pause_e:
                log.error(f"[B5] Failed to auto-pause user {user_id}: {_pause_e}")

        return _record_trade(user_id, signal_id, pair, direction, 0, 0,
                             leverage, 0, 'error', error_msg=error_msg)


def _record_trade(user_id: int, signal_id: str, pair: str, direction: str,
                  entry_price: float, quantity: float, leverage: int,
                  size_usd: float, status: str, exchange_order_id: str = '',
                  error_msg: str = '', sl_price: float = 0.0,
                  tp_prices: list = None) -> Dict:
    """Record a copy-trade in the database."""
    import json as _json
    now = time.time()
    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO copy_trades
                (user_id, signal_id, pair, direction, entry_price, quantity,
                 leverage, size_usd, status, exchange_order_id, error_msg,
                 created_at, sl_price, tp_prices)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, signal_id, pair, direction, entry_price, quantity,
              leverage, size_usd, status, exchange_order_id, error_msg, now,
              sl_price, _json.dumps(tp_prices or [])))
        conn.commit()
    except Exception as e:
        log.error(f"Failed to record trade: {e}")
    finally:
        conn.close()

    return {
        "user_id": user_id,
        "signal_id": signal_id,
        "pair": pair,
        "direction": direction,
        "quantity": quantity,
        "leverage": leverage,
        "size_usd": size_usd,
        "status": status,
        "error": error_msg,
    }


def quick_entry_trade(
    user_id: int,
    pair: str,
    direction: str,
    sl_price: float,
    tp_prices: list,
    leverage: int = 0,
) -> Dict:
    """
    One-click manual entry from Pre-Signal Alerts (pro/ultra tier).

    Builds a synthetic signal dict and routes it through the standard
    _execute_single_trade_blocking pipeline so all user settings
    (size_mode, sl_mode, tp_mode, leverage_mode, etc.) are respected.

    Parameters
    ----------
    user_id   : authenticated user
    pair      : e.g. 'SKRUSDT'
    direction : 'LONG' or 'SHORT'
    sl_price  : stop-loss price (CE level from pre-signal data)
    tp_prices : list of TP prices [tp1, tp2, tp3]
    leverage  : override leverage (0 = use user config)
    """
    direction = direction.upper()
    if direction not in ('LONG', 'SHORT'):
        return {"error": "direction must be LONG or SHORT"}
    if not sl_price or sl_price <= 0:
        return {"error": "sl_price is required"}
    if not tp_prices:
        return {"error": "tp_prices is required"}

    # Check user has copy-trading configured
    cfg = get_config(user_id)
    if not cfg:
        return {"error": "Copy-trading not configured — add Binance API keys first"}

    # Fetch live mark price for entry
    client = _get_futures_client(user_id)
    if not client:
        return {"error": "Failed to connect to Binance — check API keys"}
    try:
        mark_data = client.futures_mark_price(symbol=pair)
        entry_price = float(mark_data.get('markPrice', 0))
        if entry_price <= 0:
            return {"error": f"Could not fetch mark price for {pair}"}
    except Exception as e:
        return {"error": f"Mark price fetch failed: {str(e)[:120]}"}

    # Sanity-check: SL must be on the correct side of entry
    if direction == 'LONG' and sl_price >= entry_price:
        return {"error": f"SL ({sl_price}) must be below entry ({entry_price:.6g}) for LONG"}
    if direction == 'SHORT' and sl_price <= entry_price:
        return {"error": f"SL ({sl_price}) must be above entry ({entry_price:.6g}) for SHORT"}

    # Build a synthetic signal dict matching _execute_single_trade_blocking's API
    import uuid as _uuid
    signal_id = f"QE-{pair}-{int(time.time())}-{_uuid.uuid4().hex[:6].upper()}"
    effective_leverage = leverage if leverage > 0 else int(cfg.get('max_leverage', 10))

    synthetic_signal = {
        'signal_id':  signal_id,
        'pair':       pair,
        'direction':  direction,
        'price':      entry_price,
        'stop_loss':  sl_price,
        'targets':    [float(t) for t in tp_prices],
        'leverage':   effective_leverage,
        'sqi_score':  75.0,   # neutral SQI — no scaling penalty
    }

    # Override sl_mode to 'signal' so our explicit SL is used, not user's % setting
    cfg_override = dict(cfg)
    cfg_override['sl_mode'] = 'signal'

    log.info(f"[quick_entry] User {user_id} manual entry: {direction} {pair} "
             f"entry≈{entry_price} sl={sl_price} tps={tp_prices} lev={effective_leverage}x")

    result = _execute_single_trade_blocking(user_id, cfg_override, synthetic_signal)
    result['signal_id'] = signal_id
    result['entry_price_used'] = entry_price
    return result


def _close_order_params(pos: dict, symbol: str) -> dict:
    """Build futures_create_order kwargs for a market close, handling both one-way and hedge mode."""
    amt        = float(pos.get('positionAmt', 0))
    close_side = 'SELL' if amt > 0 else 'BUY'
    qty        = abs(amt)
    pos_side   = pos.get('positionSide', 'BOTH')  # 'LONG'/'SHORT' in hedge mode, 'BOTH' in one-way
    params     = dict(symbol=symbol, side=close_side, type='MARKET', quantity=qty)
    if pos_side in ('LONG', 'SHORT'):
        params['positionSide'] = pos_side   # hedge mode: specify side, no reduceOnly
    else:
        params['reduceOnly'] = True          # one-way mode
    return params


def close_all_positions(user_id: int) -> Dict:
    """Close ALL open Binance Futures positions at market and mark DB trades closed.

    Uses WS API (_ws_call) for every signed call — both position fetch and
    order placement — so a user slamming this button during a ban window
    doesn't hit REST weight and extend the ban.
    """
    # Ban gate — short-circuit cleanly instead of hammering the endpoint
    _ban_until = _binance_ip_banned_until()
    if _ban_until:
        retry_in = max(1, int(_ban_until - time.time()))
        return {"error": f"Binance IP rate-limited for {retry_in}s — try again later",
                "error_code": "rate_limited", "retry_in_seconds": retry_in}

    client = _get_futures_client(user_id)
    if not client:
        return {"error": "Failed to initialize Binance client. Check API keys."}
    try:
        # Prefer WS-API; REST fallback automatic inside _ws_call
        positions = _ws_call(
            user_id, "account_position",
            lambda **p: client.futures_position_information(**p),
        )
        closed, errors = [], []
        for pos in (positions or []):
            amt = float(pos.get('positionAmt', 0) or 0)
            if amt == 0:
                continue
            symbol = pos['symbol']
            try:
                # Cancel-all is still REST-only (no WS wrapper); wrap in
                # try/except so one failure doesn't abort the whole loop.
                try:
                    client.futures_cancel_all_open_orders(symbol=symbol)
                except Exception:
                    pass
                _ws_call(
                    user_id, "create_order",
                    lambda **p: client.futures_create_order(**p),
                    **_close_order_params(pos, symbol),
                )
                closed.append(symbol)
                log.info(f"close_all: {symbol} {abs(amt)} closed for user {user_id}")
            except Exception as e:
                errors.append(f"{symbol}: {str(e)[:120]}")
                log.warning(f"close_all failed {symbol} user {user_id}: {e}")
        if closed:
            conn = _get_db()
            conn.execute(
                "UPDATE copy_trades SET status='closed', closed_at=? WHERE user_id=? AND status='open'",
                (time.time(), user_id)
            )
            conn.commit()
            conn.close()
        return {"success": True, "closed": closed, "errors": errors, "count": len(closed)}
    except Exception as e:
        return {"error": f"Failed to fetch positions: {e}"}


def close_single_position(user_id: int, pair: str) -> Dict:
    """Close a SINGLE open Binance Futures position at market and mark it closed in DB."""
    # Ban gate
    _ban_until = _binance_ip_banned_until()
    if _ban_until:
        retry_in = max(1, int(_ban_until - time.time()))
        return {"error": f"Binance IP rate-limited for {retry_in}s — try again later",
                "error_code": "rate_limited", "retry_in_seconds": retry_in}

    client = _get_futures_client(user_id)
    if not client:
        return {"error": "Failed to initialize Binance client. Check API keys."}
    try:
        positions = _ws_call(
            user_id, "account_position",
            lambda **p: client.futures_position_information(**p),
            symbol=pair,
        )
        if not positions:
            return {"error": "Position not found on Binance."}
        # In hedge mode there may be both LONG and SHORT entries; pick the non-zero one
        pos = next((p for p in (positions or []) if float(p.get('positionAmt', 0) or 0) != 0), None)
        if not pos:
            return {"error": "Position is already closed on Binance."}

        amt = float(pos['positionAmt'])
        qty = abs(amt)
        try:
            # Drop open SL/TP orders on this pair (REST-only; no WS wrapper)
            try:
                client.futures_cancel_all_open_orders(symbol=pair)
            except Exception:
                pass
            # Fire the market close order via WS (REST fallback automatic)
            _ws_call(
                user_id, "create_order",
                lambda **p: client.futures_create_order(**p),
                **_close_order_params(pos, pair),
            )
            log.info(f"close_single: {pair} {qty} closed for user {user_id}")

            # Fetch realized PnL from Binance income history
            now = time.time()
            pnl_usd = 0.0
            pnl_pct = 0.0
            try:
                time.sleep(0.8)  # small delay so Binance income record is posted
                income = client.futures_income_history(
                    symbol=pair, incomeType='REALIZED_PNL', limit=20
                )
                # Try 5-min window first, fall back to 30 min
                for window in (300, 1800):
                    cutoff = now - window
                    recent = [float(i['income']) for i in income
                               if float(i['time']) / 1000 > cutoff]
                    if recent:
                        pnl_usd = round(sum(recent), 4)
                        break
                # pnl_pct = ROI relative to initial margin
                entry_px = float(pos.get('entryPrice', 0))
                lev      = int(float(pos.get('leverage', 1))) or 1
                init_margin = qty * entry_px / lev if entry_px else 0
                if init_margin:
                    pnl_pct = round(pnl_usd / init_margin * 100, 4)
            except Exception as _pe:
                log.warning(f"close_single: PnL fetch failed {pair}: {_pe}")

            # Update local state
            conn = _get_db()
            conn.execute(
                "UPDATE copy_trades SET status='closed', pnl_usd=?, pnl_pct=?, closed_at=? "
                "WHERE user_id=? AND pair=? AND status='open'",
                (pnl_usd, pnl_pct, now, user_id, pair)
            )
            conn.commit()
            conn.close()
            return {"success": True, "closed": pair, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct}
        except Exception as e:
            err = str(e)[:120]
            log.warning(f"close_single failed {pair} user {user_id}: {e}")
            return {"error": f"Close failed: {err}"}
    except Exception as e:
        return {"error": f"Failed to fetch position: {e}"}


# ── Signal Close Handler ───────────────────────────────────────────
async def handle_signal_close(signal_id: str, pnl_pct: float):
    """Called when a signal is closed. Updates copy-trade records."""
    conn = _get_db()
    trades = conn.execute(
        "SELECT * FROM copy_trades WHERE signal_id=? AND status='open'",
        (signal_id,)
    ).fetchall()
    now = time.time()
    for t in trades:
        t = dict(t)
        pnl_usd = t['size_usd'] * (pnl_pct / 100)
        conn.execute(
            "UPDATE copy_trades SET status='closed', pnl_pct=?, pnl_usd=?, closed_at=? "
            "WHERE id=?",
            (pnl_pct, round(pnl_usd, 2), now, t['id'])
        )
    conn.commit()
    conn.close()
    if trades:
        log.info(f"Closed {len(trades)} copy-trades for signal {signal_id} @ {pnl_pct}%")


# ── Dynamic Trailing SL: propagate new SL to every copy-trader ─────
async def update_copy_sl_for_signal(signal_id: str, new_sl: float) -> Dict:
    """
    Re-position the exchange-side STOP_MARKET order for every open copy-trade
    belonging to `signal_id` to the new trailing SL price.  Also updates
    `copy_trades.sl_price` so the software SL monitor is armed with the same
    level (covers PM accounts where the exchange stop is blocked).

    Binance Futures does NOT support modifying a STOP_MARKET stop-price in
    place — we cancel the existing close-position order and place a fresh
    one.  The race window between cancel and re-place (~100 ms) is covered
    by the software SL monitor which re-reads `sl_price` every 15 s.

    Rate-limit friendly: sequential per user (50 ms pacing) and skips users
    whose copy-trading config is `is_active=0`.

    Returns a summary dict with counts + any error messages.
    """
    if _is_maintenance():
        return {"skipped": True, "reason": "maintenance mode", "updated": 0}
    if not signal_id or not new_sl or new_sl <= 0:
        return {"error": "signal_id and positive new_sl required"}

    # Pull all OPEN copy-trades on this signal, joined with config + user
    # tier.  Dynamic trailing SL is an ULTRA-tier perk — Pro users keep
    # their original signal SL (with the legacy breakeven-after-TP1 fallback
    # enforced by the reconciler).
    conn = _get_db()
    rows = conn.execute(
        "SELECT ct.id, ct.user_id, ct.pair, ct.direction, ct.sl_price, "
        "       ctc.is_active, u.tier, u.tier_expires "
        "FROM copy_trades ct "
        "JOIN copy_trading_config ctc ON ct.user_id = ctc.user_id "
        "JOIN users u                  ON ct.user_id = u.id "
        "WHERE ct.signal_id=? AND ct.status='open'",
        (signal_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"updated": 0, "reason": "no open copy-trades"}

    updated = 0
    skipped_tier = 0
    errors: List[str] = []

    for row in rows:
        trade = dict(row)
        if not trade.get('is_active'):
            continue
        # ── Ultra-tier gate ─────────────────────────────────────────────
        # Admins pass automatically via effective-tier upgrade elsewhere;
        # here we only see the raw DB tier column.  Check expiry too.
        tier = (trade.get('tier') or '').lower()
        tier_expires = float(trade.get('tier_expires') or 0)
        if tier != 'ultra':
            skipped_tier += 1
            continue
        if tier_expires and time.time() > tier_expires:
            skipped_tier += 1
            log.info(f"[trail] user={trade['user_id']} ultra tier expired — skip")
            continue
        uid = trade['user_id']
        pair = trade['pair']
        direction = trade['direction'].upper()

        # Sanity: never move SL to the wrong side of entry direction
        # (defensive — caller should already guarantee this).
        try:
            await asyncio.to_thread(_replace_exchange_sl_blocking,
                                    uid, pair, direction, float(new_sl))
            # Update DB so software monitor picks up the new level
            try:
                con2 = _get_db()
                con2.execute(
                    "UPDATE copy_trades SET sl_price=? WHERE id=?",
                    (float(new_sl), trade['id'])
                )
                con2.commit()
                con2.close()
            except Exception as e:
                errors.append(f"user {uid} DB update: {e}")
            updated += 1
            log.info(f"[trail] user={uid} {pair} SL → {new_sl}")
        except Exception as e:
            errors.append(f"user {uid} {pair}: {str(e)[:120]}")
            log.warning(f"[trail] user={uid} {pair} SL update failed: {e}")

        # Gentle pacing to stay under Binance 2400-req/min ceiling
        await asyncio.sleep(0.05)

    return {
        "updated": updated,
        "total": len(rows),
        "skipped_non_ultra": skipped_tier,
        "errors": errors,
    }


def _replace_exchange_sl_blocking(user_id: int, pair: str, direction: str,
                                  new_sl: float) -> None:
    """
    Cancel any existing STOP_MARKET close-position order on `pair` for this
    user and place a fresh one at `new_sl`.  Handles both legacy futures
    orders and migrated algo orders.  Blocking — call via asyncio.to_thread.
    """
    client = _get_futures_client(user_id)
    if not client:
        raise RuntimeError("no Binance client")

    # Detect hedge mode (cached)
    _now = time.time()
    if user_id in _HEDGE_CACHE and (_now - _HEDGE_TS.get(user_id, 0)) < _CLIENT_TTL:
        hedge_mode = _HEDGE_CACHE[user_id]
    else:
        try:
            pos_mode = client.futures_get_position_mode()
            hedge_mode = pos_mode.get('dualSidePosition', False)
        except Exception:
            hedge_mode = False
        _HEDGE_CACHE[user_id] = hedge_mode
        _HEDGE_TS[user_id] = _now

    is_long = direction in ('LONG', 'BUY')
    sl_side = 'SELL' if is_long else 'BUY'
    position_side = direction if hedge_mode else 'BOTH'

    # 1. Cancel existing close-position STOP_MARKET orders (legacy + algo)
    try:
        for o in client.futures_get_open_orders(symbol=pair) or []:
            try:
                if o.get('type') == 'STOP_MARKET' and (
                        o.get('closePosition') is True or
                        str(o.get('closePosition')).lower() == 'true'):
                    client.futures_cancel_order(symbol=pair, orderId=o['orderId'])
            except Exception as ce:
                log.debug(f"[trail] legacy cancel skipped {pair}: {ce}")
    except Exception as e:
        log.debug(f"[trail] open_orders fetch failed {pair}: {e}")

    try:
        algo_list = client._request_futures_api(
            'get', 'algoOrders', True, data={'algoStatus': 'NEW'}) or []
        for o in algo_list:
            try:
                if o.get('symbol') == pair and o.get('type') == 'STOP_MARKET':
                    client._request_futures_api(
                        'delete', 'algoOrder', True, data={'algoId': o['algoId']})
            except Exception as ce:
                log.debug(f"[trail] algo cancel skipped {pair}: {ce}")
    except Exception as e:
        log.debug(f"[trail] algoOrders fetch failed {pair}: {e}")

    # 2. Resolve price precision via cached exchange_info
    try:
        info = _get_exchange_info_cached(client)
        sym_info = next((s for s in info['symbols'] if s['symbol'] == pair), None)
        price_precision = 4
        if sym_info:
            for f in sym_info.get('filters', []):
                if f['filterType'] == 'PRICE_FILTER':
                    tick = f['tickSize']
                    price_precision = max(0, len(tick.rstrip('0').split('.')[-1]))
                    break
        sl_rounded = round(float(new_sl), price_precision)
    except Exception:
        sl_rounded = round(float(new_sl), 6)

    # 3. Place new STOP_MARKET (algo first, legacy fallback)
    algo_p = {
        'symbol': pair, 'side': sl_side,
        'algoType': 'CONDITIONAL', 'type': 'STOP_MARKET',
        'triggerPrice': str(sl_rounded),
        'workingType': 'MARK_PRICE',
        'closePosition': 'true',
    }
    if hedge_mode:
        algo_p['positionSide'] = position_side
    try:
        client._request_futures_api('post', 'algoOrder', True, data=algo_p)
        return
    except Exception as algo_e:
        # Fallback to legacy endpoint for non-migrated accounts
        legacy_p = dict(symbol=pair, side=sl_side, type='STOP_MARKET',
                        stopPrice=sl_rounded, workingType='MARK_PRICE',
                        closePosition=True)
        if hedge_mode:
            legacy_p['positionSide'] = position_side
        try:
            client.futures_create_order(**legacy_p)
            return
        except Exception as legacy_e:
            raise RuntimeError(
                f"algo={str(algo_e)[:80]} | legacy={str(legacy_e)[:80]}")


# ── Software SL Monitor (fallback when STOP_MARKET is blocked) ──────
async def run_sl_monitor():
    """
    Poll mark prices every 15s for all open copy-trades that have an sl_price.
    If current mark price breaches SL, fire a MARKET close order immediately.
    This is the fallback for Portfolio Margin accounts where STOP_MARKET
    conditional orders cannot be placed via the standard FAPI endpoint.
    """
    import json as _json
    log.info("[sl_monitor] Software SL monitor started")
    while True:
        try:
            await asyncio.sleep(15)
            if _is_maintenance():
                log.debug("[sl_monitor] Skipping tick — maintenance mode active")
                continue
            conn = _get_db()
            trades = conn.execute(
                "SELECT id, user_id, pair, direction, quantity, sl_price "
                "FROM copy_trades WHERE status='open' AND sl_price > 0"
            ).fetchall()
            conn.close()

            if not trades:
                continue

            # Group by user to batch API calls
            by_user: Dict[int, list] = {}
            for t in trades:
                t = dict(t)
                by_user.setdefault(t['user_id'], []).append(t)

            for uid, user_trades in by_user.items():
                try:
                    await asyncio.to_thread(_check_sl_for_user, uid, user_trades)
                except Exception as e:
                    log.warning(f"[sl_monitor] user {uid} check failed: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"[sl_monitor] error: {e}")


def _check_sl_for_user(user_id: int, trades: list):
    """Check SL levels for a single user's open trades and close if breached."""
    if _is_maintenance():
        log.debug(f"[sl_monitor] _check_sl_for_user skipped for user {user_id} — maintenance mode")
        return
    client = _get_futures_client(user_id)
    if not client:
        return

    pairs = list({t['pair'] for t in trades})
    try:
        # Fetch mark prices for all relevant pairs at once
        all_prices = client.futures_mark_price()
        price_map = {p['symbol']: float(p['markPrice']) for p in all_prices if p['symbol'] in pairs}
    except Exception as e:
        log.warning(f"[sl_monitor] Price fetch failed for user {user_id}: {e}")
        return

    # Prefer cached hedge mode (populated on trade entry) to avoid a
    # signed REST call every 15 s per user.
    cached_hm = _HEDGE_CACHE.get(user_id)
    if cached_hm is not None and (time.time() - _HEDGE_TS.get(user_id, 0)) < _CLIENT_TTL:
        hedge_mode = cached_hm
    else:
        try:
            pos_mode = client.futures_get_position_mode()
            hedge_mode = pos_mode.get('dualSidePosition', False)
            _HEDGE_CACHE[user_id] = hedge_mode
            _HEDGE_TS[user_id] = time.time()
        except Exception:
            hedge_mode = False

    for trade in trades:
        pair = trade['pair']
        mark = price_map.get(pair)
        if mark is None:
            continue

        sl = float(trade['sl_price'])
        direction = trade['direction'].upper()
        qty = float(trade['quantity'])

        breached = (direction == 'LONG' and mark <= sl) or \
                   (direction == 'SHORT' and mark >= sl)

        if not breached:
            continue

        log.warning(f"[sl_monitor] SL BREACHED {pair} direction={direction} "
                    f"mark={mark} sl={sl} — firing MARKET close")
        try:
            close_side = 'SELL' if direction == 'LONG' else 'BUY'
            close_params = dict(symbol=pair, side=close_side, type='MARKET', quantity=qty)
            if hedge_mode:
                close_params['positionSide'] = direction
            else:
                close_params['reduceOnly'] = True
            # Route through WS-API (REST fallback baked into _ws_call)
            _ws_call(
                user_id, "create_order",
                lambda **p: client.futures_create_order(**p),
                **close_params,
            )
            log.info(f"[sl_monitor] SL market close executed {pair} qty={qty}")

            # Mark as closed in DB and feed outcome to signal registry
            conn = _get_db()
            conn.execute(
                "UPDATE copy_trades SET status='closed', closed_at=?, error_msg='SL hit (software)' WHERE id=?",
                (time.time(), trade['id'])
            )
            conn.commit()
            conn.close()
            _feed_copy_result_to_registry(trade.get('signal_id', ''), -100.0, 0)  # SL = loss
        except Exception as e:
            err_str = str(e)
            log.error(f"[sl_monitor] MARKET close FAILED {pair}: {e}")

            # -2022: ReduceOnly rejected — position likely already closed/liquidated
            # Verify on exchange and clean up DB to stop infinite retry loop
            if '-2022' in err_str:
                try:
                    pos_info = _ws_call(
                        user_id, "account_position",
                        lambda **p: client.futures_position_information(**p),
                        symbol=pair,
                    )
                    # Direction-aware check: only count the side we are trying to close
                    # SHORT position → positionAmt < 0  |  LONG position → positionAmt > 0
                    # In hedge mode Binance also exposes positionSide; both checks work.
                    if direction == 'SHORT':
                        dir_amt = sum(
                            abs(float(p.get('positionAmt', 0)))
                            for p in pos_info
                            if float(p.get('positionAmt', 0)) < 0
                               or p.get('positionSide', 'BOTH') == 'SHORT'
                        ) if pos_info else 0
                    else:
                        dir_amt = sum(
                            abs(float(p.get('positionAmt', 0)))
                            for p in pos_info
                            if float(p.get('positionAmt', 0)) > 0
                               or p.get('positionSide', 'BOTH') == 'LONG'
                        ) if pos_info else 0
                except Exception as _pe:
                    log.warning(f"[sl_monitor] {pair} position verify failed: {_pe}")
                    dir_amt = -1  # unknown — don't modify DB

                def _mark_closed(reason: str):
                    try:
                        conn = _get_db()
                        conn.execute(
                            "UPDATE copy_trades SET status='closed', closed_at=?, "
                            "error_msg=? WHERE id=?",
                            (time.time(), reason, trade['id'])
                        )
                        conn.commit()
                        conn.close()
                        _feed_copy_result_to_registry(trade.get('signal_id', ''), -100.0, 0)
                    except Exception as _db_e:
                        log.error(f"[sl_monitor] DB cleanup failed {pair}: {_db_e}")

                if dir_amt == 0:
                    # Exchange confirms this direction has no open position
                    # (already liquidated or closed by exchange SL order)
                    log.warning(f"[sl_monitor] {pair} {direction} positionAmt=0 → "
                                f"already closed (liquidated/exchange-SL) — cleaning DB")
                    _mark_closed('SL hit (exchange-closed/liquidated)')

                elif dir_amt > 0:
                    # Position still exists — retry WITHOUT reduceOnly
                    log.warning(f"[sl_monitor] {pair} {direction} position still open "
                                f"(amt={dir_amt:.4f}) — retrying without reduceOnly")
                    try:
                        retry_params = dict(symbol=pair, side=close_side, type='MARKET', quantity=qty)
                        if hedge_mode:
                            retry_params['positionSide'] = direction
                        client.futures_create_order(**retry_params)
                        log.info(f"[sl_monitor] SL retry (no reduceOnly) executed {pair}")
                        _mark_closed('SL hit (software-retry)')
                    except Exception as _re:
                        log.error(f"[sl_monitor] SL retry also FAILED {pair}: {_re}")
                        # If retry also gets -2022, position was closed in the race window
                        # between our position check and the order — clean DB anyway
                        if '-2022' in str(_re):
                            log.warning(f"[sl_monitor] {pair} -2022 on retry → "
                                        f"race condition, position closed mid-check — cleaning DB")
                            _mark_closed('SL hit (race-closed)')


# ── Background Position Monitor ────────────────────────────────────
async def run_position_monitor():
    """
    Background task: every 60s check all open copy-trades against
    live Binance positions. Mark closed + calculate PnL if gone.
    """
    log.info("[ct_monitor] Position monitor started")
    while True:
        try:
            await asyncio.sleep(60)
            if _is_maintenance():
                log.debug("[ct_monitor] Skipping sync — maintenance mode active")
                continue
            await _sync_open_positions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"[ct_monitor] error: {e}")


async def _sync_open_positions():
    """Check each open copy-trade against live Binance and close if no longer open."""
    if _is_maintenance():
        return
    conn = _get_db()
    open_trades = conn.execute(
        "SELECT DISTINCT user_id FROM copy_trades WHERE status='open'"
    ).fetchall()
    conn.close()

    for row in open_trades:
        uid = row['user_id']
        try:
            await asyncio.to_thread(_sync_user_positions, uid)
        except Exception as e:
            log.warning(f"[ct_monitor] sync failed for user {uid}: {e}")


def _sync_user_positions(user_id: int):
    """Sync a single user's open copy-trades with Binance.

    Prefers the in-memory UDS state (zero Binance cost) → falls back to
    WS-API → falls back to REST. This runs on every monitor tick for
    every user, so avoiding REST here is critical at scale.
    """
    # 1. UDS in-memory state (fastest, zero Binance cost)
    open_pairs: set = set()
    live_positions = None
    try:
        from binance_user_stream import get_state as _ws_state, is_fresh as _ws_fresh
        if _ws_fresh(user_id):
            s = _ws_state(user_id) or {}
            positions_dict = s.get("positions") or {}
            open_pairs = {sym for sym, p in positions_dict.items()
                          if abs(float(p.get("amt", 0) or 0)) > 0}
            live_positions = [
                {"symbol": sym,
                 "positionAmt": p.get("amt", 0),
                 "entryPrice": p.get("entry", 0)}
                for sym, p in positions_dict.items()
            ]
    except Exception:
        live_positions = None

    if live_positions is None:
        # 2. Signed call: WS first, REST fallback
        client = _get_futures_client(user_id)
        if not client:
            return
        try:
            live_positions = _ws_call(
                user_id, "account_position",
                lambda **p: client.futures_position_information(**p),
            ) or []
            open_pairs = {p['symbol'] for p in live_positions
                          if float(p.get('positionAmt', 0) or 0) != 0}
        except Exception as e:
            log.warning(f"[ct_monitor] position fetch failed for user {user_id}: {e}")
            return

    conn = _get_db()
    open_trades = conn.execute(
        "SELECT id, signal_id, pair, direction, entry_price, quantity, leverage, size_usd "
        "FROM copy_trades WHERE user_id=? AND status='open'",
        (user_id,)
    ).fetchall()

    now = time.time()
    for trade in open_trades:
        t = dict(trade)
        if t['pair'] in open_pairs:
            continue  # Still open on Binance — leave it

        # Position is closed on Binance — get PnL from income history
        pnl_usd = 0.0
        pnl_pct = 0.0
        try:
            # Check recent futures income for this symbol's realized PnL
            income = client.futures_income_history(
                symbol=t['pair'], incomeType='REALIZED_PNL', limit=10
            )
            # Sum income from last few minutes for this position
            cutoff = now - 300  # 5 min window
            recent_pnl = sum(
                float(i['income']) for i in income
                if float(i['time']) / 1000 > cutoff
            )
            pnl_usd = round(recent_pnl, 4)
            entry  = float(t.get('entry_price', 0) or 0)
            lev    = int(t.get('leverage', 1) or 1)
            qty    = float(t.get('quantity', 0) or 0)
            margin = t.get('size_usd', 0) or 0
            # Binance ROI% = realizedPnL / initialMargin * 100
            # initialMargin = qty * entryPrice / leverage  (= size_usd when correctly stored)
            initial_margin = (qty * entry / lev) if (qty and entry and lev) else (margin or 0)
            if initial_margin:
                pnl_pct = round(pnl_usd / initial_margin * 100, 4)
            elif margin:
                pnl_pct = round(pnl_usd / margin * 100, 4)
            else:
                pnl_pct = 0
        except Exception as e:
            log.warning(f"[ct_monitor] PnL fetch failed for {t['pair']} user {user_id}: {e}")

        conn.execute(
            "UPDATE copy_trades SET status='closed', pnl_usd=?, pnl_pct=?, closed_at=? WHERE id=?",
            (pnl_usd, pnl_pct, now, t['id'])
        )
        log.info(f"[ct_monitor] Closed trade {t['id']} {t['pair']} user {user_id}: pnl=${pnl_usd:.4f}")

        # Feed result back to signal_registry.db for self-learning
        _feed_copy_result_to_registry(t.get('signal_id', ''), pnl_pct, pnl_usd)

    conn.commit()
    conn.close()


def _feed_copy_result_to_registry(signal_id: str, pnl_pct: float, pnl_usd: float):
    """
    Write copy-trade outcome back to main signal_registry.db so self-learning picks it up.
    DISABLED: This was blindly overwriting the canonical signal PnL and status with
    individual user execution results, causing the dashboard to show 'LOSS' with 0% PnL
    and ignoring targets_hit. Canonical performance is handled by performance_tracker.py.
    """
    pass


# ── SL/TP Recovery: Place missing orders on open positions ──────────
async def retry_missing_sl_tp(user_id: int) -> List[Dict]:
    """
    For every open copy-trade that is missing SL/TP orders on Binance,
    place them now using signal data from SIGNAL_REGISTRY.
    Called manually via admin API after a bug-fix deployment.
    """
    if _is_maintenance():
        log.warning(f"[sl_tp_recovery] Blocked for user {user_id} — maintenance mode active")
        return []
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from shared_state import SIGNAL_REGISTRY as _REG
    except Exception as _e:
        log.error(f"[sl_tp_recovery] Cannot import SIGNAL_REGISTRY: {_e}")
        return []

    conn = _get_db()
    open_trades = conn.execute(
        "SELECT * FROM copy_trades WHERE user_id=? AND status='open'", (user_id,)
    ).fetchall()
    cfg_row = conn.execute(
        "SELECT * FROM copy_trading_config WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()

    if not open_trades or not cfg_row:
        return []

    cfg = dict(cfg_row)
    client = _get_futures_client(user_id)
    if not client:
        log.error(f"[sl_tp_recovery] Cannot create client for user {user_id}")
        return []

    # Detect hedge mode
    try:
        pos_mode = client.futures_get_position_mode()
        hedge_mode = pos_mode.get('dualSidePosition', False)
    except Exception:
        hedge_mode = False

    def _place_cond(params):
        """Place via algo API, fall back to legacy."""
        algo_p = {
            'symbol': params['symbol'], 'side': params['side'],
            'algoType': 'CONDITIONAL', 'type': params['type'],
            'triggerPrice': str(params.get('stopPrice') or params.get('triggerPrice', '')),
            'workingType': params.get('workingType', 'MARK_PRICE'),
        }
        if params.get('positionSide'): algo_p['positionSide'] = params['positionSide']
        if params.get('closePosition'): algo_p['closePosition'] = 'true'
        elif params.get('quantity'): algo_p['quantity'] = str(params['quantity'])
        try:
            return client._request_futures_api('post', 'algoOrder', True, data=algo_p)
        except Exception as _e:
            if '-4120' in str(_e): raise
            return client.futures_create_order(**params)

    # Check both regular + algo open orders
    try:
        all_open_orders = client.futures_get_open_orders()
    except Exception:
        all_open_orders = []
    try:
        algo_orders = client._request_futures_api('get', 'algoOrders', True, data={'algoStatus': 'NEW'}) or []
    except Exception:
        algo_orders = []
    pairs_with_orders = {o['symbol'] for o in all_open_orders} | {o.get('symbol') for o in algo_orders if o.get('symbol')}

    results = []
    for trade in open_trades:
        trade = dict(trade)
        pair = trade['pair']
        qty  = float(trade['quantity'])
        direction = trade['direction'].upper()
        signal_id = trade['signal_id']

        # Skip if Binance already has open orders for this pair
        if pair in pairs_with_orders:
            log.info(f"[sl_tp_recovery] {pair}: already has open orders — skipping")
            results.append({'pair': pair, 'status': 'skipped', 'reason': 'orders_exist'})
            continue

        # Get signal data
        sig = _REG.get(signal_id)
        if not sig:
            log.warning(f"[sl_tp_recovery] {pair}: signal {signal_id} not in SIGNAL_REGISTRY")
            results.append({'pair': pair, 'status': 'skipped', 'reason': 'no_signal_data'})
            continue

        stop_loss = float(sig.get('stop_loss', 0))
        targets   = sig.get('targets', [])
        if not stop_loss or not targets:
            log.warning(f"[sl_tp_recovery] {pair}: missing stop_loss or targets in signal")
            results.append({'pair': pair, 'status': 'skipped', 'reason': 'incomplete_signal'})
            continue

        # Get price precision for this symbol
        info = _get_exchange_info_cached(client)
        sym_info = next((s for s in info['symbols'] if s['symbol'] == pair), None)
        price_precision = 4
        qty_precision   = 3
        step_size       = 0.001
        if sym_info:
            for f in sym_info.get('filters', []):
                if f['filterType'] == 'PRICE_FILTER':
                    tick = f['tickSize']
                    price_precision = max(0, len(tick.rstrip('0').split('.')[-1]))
                if f['filterType'] == 'LOT_SIZE':
                    step_str = f['stepSize']
                    step_size = float(step_str)
                    qty_precision = max(0, len(step_str.rstrip('0').split('.')[-1]))

        sl_side  = 'SELL' if direction == 'LONG' else 'BUY'
        sl_price = round(stop_loss, price_precision)
        position_side = direction if hedge_mode else 'BOTH'
        placed = []
        failed = []

        import json as _json2
        import math as _math

        # Always update sl_price + tp_prices in DB so software SL monitor is armed
        _db = _get_db()
        _db.execute(
            "UPDATE copy_trades SET sl_price=?, tp_prices=? WHERE signal_id=? AND user_id=? AND status='open'",
            (sl_price, _json2.dumps([float(t) for t in targets]), signal_id, user_id)
        )
        _db.commit()
        _db.close()
        placed.append(f"SL@{sl_price}(software-monitor-armed)")
        log.info(f"[sl_tp_recovery] Software SL armed {pair} @ {sl_price}")

        # Attempt exchange SL (will succeed if PM key gets fixed later)
        try:
            sl_params = dict(
                symbol=pair, side=sl_side, type='STOP_MARKET',
                stopPrice=sl_price, workingType='MARK_PRICE', closePosition=True,
            )
            if hedge_mode:
                sl_params['positionSide'] = position_side
            _place_cond(sl_params)
            log.info(f"[sl_tp_recovery] Exchange SL also placed {pair} @ {sl_price}")
            placed[-1] = f"SL@{sl_price}(exchange+software)"
        except Exception as e:
            log.info(f"[sl_tp_recovery] Exchange SL blocked ({e}) — software monitor active for {pair}")

        # Place TPs as LIMIT orders (work without PM permission)
        tp_mode = cfg.get('tp_mode', 'pyramid')
        active_tps = list(targets)
        n = len(active_tps)
        if tp_mode == 'tp1_only':
            active_tps = active_tps[:1]; allocs = [1.0]
        elif tp_mode == 'tp1_tp2':
            active_tps = active_tps[:2]; allocs = [0.65, 0.35] if n >= 2 else [1.0]
        elif tp_mode == 'pyramid':
            if n == 1:   allocs = [1.0]
            elif n == 2: allocs = [0.60, 0.40]
            elif n == 3: allocs = [0.50, 0.30, 0.20]
            else:        allocs = [0.50, 0.30, 0.15] + [0.05 / max(1, n-3)] * (n-3)
        else:
            allocs = [1.0 / n] * n
        total_alloc = sum(allocs)
        allocs = [a / total_alloc for a in allocs]

        placed_qty = 0.0
        for i, (tp, alloc) in enumerate(zip(active_tps, allocs)):
            tp_price  = round(float(tp), price_precision)
            is_last   = (i == len(active_tps) - 1)
            if is_last:
                raw_qty = qty - placed_qty
            else:
                raw_qty = qty * alloc
            close_qty = _math.floor(raw_qty / step_size) * step_size
            close_qty = max(round(close_qty, qty_precision), 0)
            if close_qty <= 0:
                continue
            try:
                tp_params = dict(
                    symbol=pair, side=sl_side, type='TAKE_PROFIT_MARKET',
                    stopPrice=tp_price, quantity=close_qty,
                    workingType='MARK_PRICE',
                )
                if hedge_mode:
                    tp_params['positionSide'] = position_side
                else:
                    tp_params['reduceOnly'] = True
                _place_cond(tp_params)
                placed_qty += close_qty
                log.info(f"[sl_tp_recovery] TP{i+1} TAKE_PROFIT_MARKET placed {pair} @ {tp_price} qty={close_qty}")
                placed.append(f"TP{i+1}@{tp_price}(qty={close_qty})")
            except Exception as e:
                log.error(f"[sl_tp_recovery] TP{i+1} FAILED {pair}: {e}")
                failed.append(f"TP{i+1}: {e}")

        results.append({'pair': pair, 'placed': placed, 'failed': failed,
                        'status': 'ok' if not failed else 'partial'})

    log.info(f"[sl_tp_recovery] Done for user {user_id}: {len(results)} positions processed")
    return results


# ── Admin: Get all active copy-traders ─────────────────────────────
def get_all_active_traders() -> List[Dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT ctc.user_id, u.username, u.email, ctc.is_active, ctc.size_pct,
               ctc.max_size_pct, ctc.max_leverage, ctc.scale_with_sqi, ctc.updated_at,
               (SELECT COUNT(*) FROM copy_trades ct WHERE ct.user_id = ctc.user_id) as total_trades,
               (SELECT COALESCE(SUM(pnl_usd), 0) FROM copy_trades ct
                WHERE ct.user_id = ctc.user_id AND ct.status='closed') as total_pnl
        FROM copy_trading_config ctc
        JOIN users u ON ctc.user_id = u.id
        ORDER BY ctc.is_active DESC, ctc.updated_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
