"""
redis_cache.py — Thin Redis read-through wrapper with SAFE FALLBACK.
===================================================================

Design goals (from proposals/2026-04-24_redis-state-management.md):

    1. Zero-downtime adoption: if Redis is unavailable at import or at
       call-time, every function silently no-ops / returns None so the
       caller falls back to its existing SQLite / in-process path. The
       dashboard MUST NEVER crash because Redis is down.

    2. Local-only: binds to 127.0.0.1:6379 with protected-mode yes, so no
       auth is configured. If we ever move to a networked deployment we
       flip REDIS_URL to include a password.

    3. JSON-serialised by default. Callers pass plain dicts / lists;
       we handle encoding. Binary payloads not supported here by design.

    4. Key discipline: all keys are prefixed `anw:` (Anunnaki World) and
       namespaced by feature (`anw:bal:<user_id>`, `anw:screener:v1`, …).

Public API (keep intentionally tiny):

    cache_get(key)              -> Optional[dict|list|str|int]
    cache_set(key, val, ttl)    -> bool   (ttl seconds; 0 = no expiry)
    cache_del(key)              -> bool
    cache_healthcheck()         -> dict   ({"healthy": bool, "latency_ms": float})

Anything beyond these primitives belongs in a more specialised module.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

log = logging.getLogger("anw.redis_cache")

_REDIS = None          # module-level client; None means "unavailable, use fallback"
_REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
_KEY_PREFIX = "anw:"

try:
    import redis as _redis_lib
    import redis.asyncio as _async_redis_lib

    # Sync client for legacy/backward compat (if needed)
    _candidate = _redis_lib.Redis.from_url(
        _REDIS_URL,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        decode_responses=True,
        health_check_interval=30,
    )
    _candidate.ping()
    _REDIS = _candidate

    # Async client for non-blocking operations
    _ASYNC_REDIS = _async_redis_lib.Redis.from_url(
        _REDIS_URL,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        decode_responses=True,
        health_check_interval=30,
    )
    log.info(f"[redis_cache] connected to {_REDIS_URL} (Sync & Async)")
except Exception as e:
    log.warning(
        f"[redis_cache] Redis unavailable ({e!r}) — running in fallback "
        f"mode; all cache ops will no-op and return None."
    )
    _REDIS = None
    _ASYNC_REDIS = None

import decimal
import datetime
from collections import deque

class StrictRedisEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, deque):
            return list(obj)
        return str(obj)

def _k(key: str) -> str:
    """Normalise a caller key to the fully-prefixed form."""
    return key if key.startswith(_KEY_PREFIX) else _KEY_PREFIX + key

# ─── Async Helpers for Complex State Management ────────

async def set_signal(signal_id: str, data: dict):
    if _ASYNC_REDIS is None: return
    try:
        payload = json.dumps(data, cls=StrictRedisEncoder)
        await _ASYNC_REDIS.hset(_k("signals:active"), signal_id, payload)
    except Exception as e:
        log.error(f"set_signal error: {e}")

async def get_all_signals() -> dict:
    if _ASYNC_REDIS is None: return {}
    try:
        raw_dict = await _ASYNC_REDIS.hgetall(_k("signals:active"))
        return {k: json.loads(v) for k, v in raw_dict.items()}
    except Exception as e:
        log.error(f"get_all_signals error: {e}")
        return {}

async def delete_signal(signal_id: str):
    if _ASYNC_REDIS is None: return
    try:
        await _ASYNC_REDIS.hdel(_k("signals:active"), signal_id)
    except Exception as e:
        log.error(f"delete_signal error: {e}")

async def set_funding_oi(symbol: str, data: dict):
    if _ASYNC_REDIS is None: return
    try:
        payload = json.dumps(data, cls=StrictRedisEncoder)
        # 5-minute TTL as required
        await _ASYNC_REDIS.setex(_k(f"funding_oi:{symbol}"), 300, payload)
    except Exception as e:
        log.error(f"set_funding_oi error: {e}")

async def get_funding_oi(symbol: str) -> Optional[dict]:
    if _ASYNC_REDIS is None: return None
    try:
        raw = await _ASYNC_REDIS.get(_k(f"funding_oi:{symbol}"))
        return json.loads(raw) if raw else None
    except Exception as e:
        log.error(f"get_funding_oi error: {e}")
        return None

async def set_cvd_bucket(symbol: str, window: str, data: dict):
    if _ASYNC_REDIS is None: return
    try:
        payload = json.dumps(data, cls=StrictRedisEncoder)
        await _ASYNC_REDIS.hset(_k(f"cvd:{symbol}"), window, payload)
    except Exception as e:
        log.error(f"set_cvd_bucket error: {e}")


# ─── Circuit Breaker (distributed, process-safe) ────────

_CIRCUIT_BREAKER_KEY = "circuit_breaker:trading"
_CIRCUIT_BREAKER_TTL = 60  # seconds — auto Half-Open transition


async def set_circuit_breaker(open_state: bool, reason: str = "") -> bool:
    """
    Set the distributed circuit breaker state.

    open_state=True  → Trading HALTED (breaker OPEN)
    open_state=False → Trading HEALTHY (breaker CLOSED)

    When OPEN, a 60-second TTL is applied so Redis auto-expires the key,
    transitioning to Half-Open without manual intervention.
    Thread-safe and process-safe across all Uvicorn workers.
    """
    if _ASYNC_REDIS is None:
        return False
    try:
        if open_state:
            payload = json.dumps({"open": True, "reason": reason, "set_at": time.time()})
            await _ASYNC_REDIS.setex(_k(_CIRCUIT_BREAKER_KEY), _CIRCUIT_BREAKER_TTL, payload)
        else:
            payload = json.dumps({"open": False, "reason": "manual_reset", "set_at": time.time()})
            await _ASYNC_REDIS.set(_k(_CIRCUIT_BREAKER_KEY), payload)
        return True
    except Exception as e:
        log.error(f"set_circuit_breaker error: {e}")
        return False


async def get_circuit_breaker() -> bool:
    """
    Query the distributed circuit breaker.

    Returns True if the breaker is OPEN (trading halted), False if CLOSED (healthy).
    If Redis is unavailable, returns False (fail-open: allow trading).
    """
    if _ASYNC_REDIS is None:
        return False
    try:
        raw = await _ASYNC_REDIS.get(_k(_CIRCUIT_BREAKER_KEY))
        if raw is None:
            return False
        state = json.loads(raw)
        return state.get("open", False)
    except Exception as e:
        log.error(f"get_circuit_breaker error: {e}")
        return False


async def get_circuit_breaker_info() -> dict:
    """
    Return full circuit breaker metadata for observability.

    Returns {"open": bool, "reason": str, "set_at": float, "ttl_remaining": float}
    """
    if _ASYNC_REDIS is None:
        return {"open": False, "reason": "redis_unavailable", "set_at": 0, "ttl_remaining": 0}
    try:
        key = _k(_CIRCUIT_BREAKER_KEY)
        raw = await _ASYNC_REDIS.get(key)
        if raw is None:
            return {"open": False, "reason": "breaker_closed", "set_at": 0, "ttl_remaining": 0}
        state = json.loads(raw)
        ttl = await _ASYNC_REDIS.ttl(key)
        state["ttl_remaining"] = max(0, ttl)
        return state
    except Exception as e:
        log.error(f"get_circuit_breaker_info error: {e}")
        return {"open": False, "reason": str(e), "set_at": 0, "ttl_remaining": 0}


async def reset_circuit_breaker() -> bool:
    """
    Manually reset the circuit breaker to CLOSED (healthy).
    Useful for admin override after manual intervention.
    """
    return await set_circuit_breaker(False, reason="manual_reset")


def cache_get(key: str) -> Optional[Any]:
    """Return the deserialised value for `key`, or None on miss / error.

    NEVER raises. If Redis is down we behave like a cache miss so the
    caller falls through to its authoritative source (SQLite, upstream
    API, etc.) without any special-casing.
    """
    if _REDIS is None:
        return None
    try:
        raw = _REDIS.get(_k(key))
        if raw is None:
            return None
        # Values we set ourselves are JSON; raw strings pass through.
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw
    except Exception as e:
        log.debug(f"[redis_cache] get({key}) failed: {e!r}")
        return None


def cache_set(key: str, val: Any, ttl: int = 0) -> bool:
    """Set `key` → JSON-serialised `val` with optional TTL (seconds).

    `ttl=0` means no expiry (persistent until evicted or deleted).
    Returns True on success, False on any failure. NEVER raises.
    """
    if _REDIS is None:
        return False
    try:
        payload = json.dumps(val, default=str)   # default=str: handles datetime etc.
        if ttl and ttl > 0:
            return bool(_REDIS.setex(_k(key), ttl, payload))
        return bool(_REDIS.set(_k(key), payload))
    except Exception as e:
        log.debug(f"[redis_cache] set({key}) failed: {e!r}")
        return False


def cache_del(key: str) -> bool:
    """Delete `key`. Returns True if a key was removed, False otherwise.
    NEVER raises."""
    if _REDIS is None:
        return False
    try:
        return bool(_REDIS.delete(_k(key)))
    except Exception as e:
        log.debug(f"[redis_cache] del({key}) failed: {e!r}")
        return False


def cache_healthcheck() -> dict:
    """Return a snapshot of Redis connectivity + latency (for /api/stream/stats).

    Format::
        {"healthy": True,  "latency_ms": 0.34, "mode": "connected"}
        {"healthy": False, "latency_ms": None, "mode": "fallback",
         "reason": "<exception repr>"}
    """
    if _REDIS is None:
        return {"healthy": False, "latency_ms": None, "mode": "fallback",
                "reason": "not connected at import"}
    try:
        t0 = time.perf_counter()
        _REDIS.ping()
        dt_ms = round((time.perf_counter() - t0) * 1000, 3)
        return {"healthy": True, "latency_ms": dt_ms, "mode": "connected"}
    except Exception as e:
        return {"healthy": False, "latency_ms": None, "mode": "fallback",
                "reason": repr(e)}


# ─── Convenience wrappers for the first two migrated call-sites ────────
#
# These are the ONLY namespace-aware helpers we ship in v1. Add more as
# additional call-sites get migrated; keep each one tiny so the migration
# intent is obvious at the grep-site.

def bal_cache_get(user_id: int) -> Optional[dict]:
    """Return cached live-balance payload for `user_id` or None on miss."""
    return cache_get(f"bal:{user_id}")


def bal_cache_set(user_id: int, payload: dict, ttl_s: int = 8) -> bool:
    """Cache a live-balance payload. TTL defaults to 8s — longer than the
    typical 2-3s dashboard refresh, short enough that the cache never
    shows stale data across a cycle."""
    return cache_set(f"bal:{user_id}", payload, ttl=ttl_s)


def bal_cache_del(user_id: int) -> bool:
    """Invalidate balance cache — call on UDS account updates so the next
    frontend read sees the freshest data instead of a stale TTL remnant."""
    return cache_del(f"bal:{user_id}")


def screener_cache_get() -> Optional[dict]:
    return cache_get("screener:v1")


def screener_cache_set(payload: dict, ttl_s: int = 25) -> bool:
    """Screener TTL = 25s: TV data updates every ~60s, 25s caching keeps
    the cache hot across all concurrent users while staying fresh enough
    that no user ever sees data more than half a TV refresh cycle old."""
    return cache_set("screener:v1", payload, ttl=ttl_s)
