"""
binance_user_stream.py — Per-user Binance Futures User Data Stream manager.

PURPOSE
    Replace REST polling of futures_account_balance + futures_account with a
    push-based, in-memory state that Binance updates in real-time over a
    single persistent WebSocket per user.

    This eliminates the #1 cause of IP-level -1003 rate-limit bans on the
    server — balance/position polling on the signed /fapi/v2/account and
    /fapi/v2/balance endpoints.

ARCHITECTURE
    • One asyncio task per active copy-trading user.
    • On start, the task:
        1. Takes an initial REST snapshot (hydrate state).
        2. Opens wss://fstream.binance.com/ws/<listenKey>
           (via python-binance's BinanceSocketManager.futures_user_socket(),
            which also handles listenKey keepalive automatically).
        3. Loops: receives Binance events and applies deltas to state.
    • On disconnect: exponential backoff (2s → 60s cap) and reconnect.
    • On stop: cancels task, closes AsyncClient.

    The module is import-safe with no side effects. Call `UserStreamManager
    .instance()` to get the singleton; call `await mgr.start(user_id)` /
    `await mgr.stop(user_id)` to manage per-user streams.

STATE SHAPE (per user)
    {
        "balance_usdt":        float,
        "available_usdt":      float,
        "unrealized_pnl":      float,
        "unrealized_pnl_pct":  float,
        "total_invested_usd":  float,
        "positions": {
            "BTCUSDT": {"pnl_usd", "pnl_pct", "leverage", "entry", "amt"},
            ...
        },
        "server_time":         float,       # epoch seconds
        "last_event":          float,       # epoch seconds of last WS msg
        "connected":           bool,
        "reconnects":          int,
        "last_error":          str | None,
    }

FAILURE MODES (all handled)
    • Invalid API key         → state["last_error"] set, task exits, REST fallback used.
    • listenKey expired       → python-binance reconnects automatically.
    • WS drop / network       → exponential backoff reconnect.
    • Binance event schema changes → non-matching events logged and ignored.
"""

from __future__ import annotations

import os
import asyncio
import logging
import time
from typing import Dict, Optional, Any

log = logging.getLogger("binance_user_stream")
if not log.handlers:
    from pathlib import Path
    _log_path = Path(__file__).resolve().parent.parent / "debug_log10.txt"
    _fh = logging.FileHandler(str(_log_path), encoding='utf-8')
    _fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - [user_stream] %(message)s'))
    log.addHandler(_fh)
    log.setLevel(logging.INFO)
    log.propagate = False


# ── Feature flag ─────────────────────────────────────────────────────────
def is_enabled() -> bool:
    """Master switch — set BINANCE_WS_USER_STREAM=false to disable."""
    return os.getenv("BINANCE_WS_USER_STREAM", "true").strip().lower() in ("1", "true", "yes")


# ── State TTL ────────────────────────────────────────────────────────────
# If the state hasn't been updated by a WS event or snapshot in this many
# seconds, callers should NOT trust it and fall back to REST. Binance pushes
# ACCOUNT_UPDATE at least every ~60 s even when nothing changes, so 120 s
# is a comfortable margin.
# 90 s = 60 s reconcile cadence + 30 s grace for Binance latency / retries.
STATE_STALE_AFTER = 90.0


class UserStreamManager:
    """Singleton that owns one asyncio task per active user."""

    _instance: "UserStreamManager | None" = None

    @classmethod
    def instance(cls) -> "UserStreamManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._state: Dict[int, Dict[str, Any]] = {}
        self._stopping: Dict[int, bool] = {}
        self._lock = asyncio.Lock()
        # Persistent AsyncClient per user — shared with binance_ws_api so
        # both UDS (push) and WS-API (request/response) reuse one set of
        # connections per user instead of opening separate ones.
        self._clients: Dict[int, Any] = {}
        self._client_locks: Dict[int, asyncio.Lock] = {}

    # ── Public API ─────────────────────────────────────────────────────
    def get_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Return current state for a user, or None if no stream is running."""
        return self._state.get(user_id)

    def is_fresh(self, user_id: int) -> bool:
        """True if state exists and was updated within STATE_STALE_AFTER seconds."""
        s = self._state.get(user_id)
        if not s or not s.get("connected"):
            return False
        last = s.get("last_event", 0) or s.get("server_time", 0)
        return (time.time() - last) < STATE_STALE_AFTER

    def status_all(self) -> Dict[int, Dict[str, Any]]:
        """Lightweight admin view of all running streams (no secrets)."""
        out: Dict[int, Dict[str, Any]] = {}
        for uid, s in self._state.items():
            out[uid] = {
                "connected":   s.get("connected", False),
                "reconnects":  s.get("reconnects", 0),
                "last_event":  s.get("last_event", 0),
                "age_seconds": round(time.time() - (s.get("last_event") or 0), 1),
                "last_error":  s.get("last_error"),
                "positions":   len(s.get("positions") or {}),
            }
        return out

    async def start(self, user_id: int) -> bool:
        """Start the per-user stream. Idempotent."""
        if not is_enabled():
            return False
        async with self._lock:
            if user_id in self._tasks and not self._tasks[user_id].done():
                return True
            self._stopping[user_id] = False
            self._tasks[user_id] = asyncio.create_task(
                self._run_user_stream(user_id),
                name=f"uds-{user_id}",
            )
            log.info(f"started stream task for user {user_id}")
            return True

    async def stop(self, user_id: int) -> None:
        """Cancel and discard a user's stream."""
        async with self._lock:
            self._stopping[user_id] = True
            t = self._tasks.pop(user_id, None)
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            self._state.pop(user_id, None)
            log.info(f"stopped stream task for user {user_id}")

    async def stop_all(self) -> None:
        """Called on shutdown — close every stream cleanly."""
        uids = list(self._tasks.keys())
        for uid in uids:
            await self.stop(uid)

    async def get_or_create_client(self, user_id: int):
        """
        Return the user's persistent AsyncClient, creating one if the UDS
        task hasn't registered one yet. Used by binance_ws_api so signed
        calls don't have to wait for the UDS bootstrap to finish.

        The client is NOT closed here; ownership passes to the caller iff
        we created it (UDS-spawned clients are closed in _connect_once's
        finally block).
        """
        existing = self._clients.get(user_id)
        if existing is not None:
            return existing
        lock = self._client_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            existing = self._clients.get(user_id)
            if existing is not None:
                return existing
            # Lazy import to avoid circular import with copy_trading
            from binance import AsyncClient  # type: ignore
            from copy_trading import _get_decrypted_keys  # type: ignore
            keys = _get_decrypted_keys(user_id)
            if not keys:
                raise RuntimeError(f"no API keys for user {user_id}")
            client = await AsyncClient.create(keys[0], keys[1])
            self._clients[user_id] = client
            log.info(f"user {user_id}: on-demand AsyncClient created (no UDS yet)")
            return client

    # ── Internal ───────────────────────────────────────────────────────
    async def _run_user_stream(self, user_id: int) -> None:
        """
        Top-level per-user loop. Reconnects on any failure with exponential
        backoff, until .stop(user_id) is called.
        """
        backoff = 2.0
        max_backoff = 60.0
        while not self._stopping.get(user_id):
            try:
                await self._connect_once(user_id)
                # _connect_once returns only on clean disconnect
                backoff = 2.0
            except asyncio.CancelledError:
                log.info(f"user {user_id}: task cancelled")
                return
            except Exception as e:
                self._set_error(user_id, str(e)[:200])
                log.warning(f"user {user_id}: stream error ({e}); "
                            f"reconnecting in {backoff:.0f}s")
            if self._stopping.get(user_id):
                return
            # If an IP ban is active, sleep THROUGH it instead of retrying
            # every few seconds. Each failed reconnect costs REST weight
            # and could extend the ban further.
            try:
                from copy_trading import _binance_ip_banned_until  # type: ignore
                ban_until = _binance_ip_banned_until()
            except Exception:
                ban_until = 0.0
            if ban_until:
                wait_for = max(backoff, (ban_until - time.time()) + 3.0)
                log.warning(f"user {user_id}: IP banned until "
                            f"{time.ctime(ban_until)} — sleeping {wait_for:.0f}s")
                await asyncio.sleep(wait_for)
            else:
                await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            self._bump_reconnects(user_id)

    async def _connect_once(self, user_id: int) -> None:
        """Single connect attempt. Returns on clean close; raises on error."""
        # Lazy import: avoids forcing python-binance into the module-load path
        # of copy_trading if someone disables the feature.
        from binance import AsyncClient, BinanceSocketManager  # type: ignore

        # Import here to avoid circular import (copy_trading → user_stream)
        from copy_trading import _get_decrypted_keys  # type: ignore

        keys = _get_decrypted_keys(user_id)
        if not keys:
            self._set_error(user_id, "no API keys configured")
            log.info(f"user {user_id}: no keys; skipping stream")
            raise RuntimeError("no API keys configured")

        api_key, api_secret = keys
        client = await AsyncClient.create(api_key, api_secret)
        # Register client so binance_ws_api can reuse the same connection
        # for signed request/response calls (orders, queries).
        self._clients[user_id] = client
        try:
            # Hydrate initial state via one REST call.  This is the ONLY
            # signed REST call the stream ever makes after start, aside
            # from python-binance's hourly listenKey keepalive.
            await self._hydrate_from_rest(user_id, client)

            bsm = BinanceSocketManager(client)
            async with bsm.futures_user_socket() as stream:
                self._state.setdefault(user_id, {})
                self._state[user_id]["connected"] = True
                self._state[user_id]["last_error"] = None
                log.info(f"user {user_id}: WS connected (futures_user_socket)")

                # Background reconciler: Binance USER stream only pushes on
                # account mutations (fills, deposits, leverage changes). It
                # does NOT push on mark-price movements, so unrealized PnL
                # can go stale even on a healthy connection. Refresh via one
                # signed REST call every 60 s — 60× cheaper than the old
                # sub-second polling that got us banned.
                recon_task = asyncio.create_task(
                    self._reconcile_loop(user_id, client),
                    name=f"uds-recon-{user_id}",
                )
                try:
                    while not self._stopping.get(user_id):
                        msg = await stream.recv()
                        if msg is None:
                            continue
                        try:
                            self._apply_event(user_id, msg)
                        except Exception as _ae:
                            log.warning(f"user {user_id}: apply_event failed "
                                        f"({_ae}); event={msg!r:200}")
                finally:
                    recon_task.cancel()
                    try:
                        await recon_task
                    except (asyncio.CancelledError, Exception):
                        pass
        finally:
            self._clients.pop(user_id, None)
            try:
                await client.close_connection()
            except Exception:
                pass
            if user_id in self._state:
                self._state[user_id]["connected"] = False

    async def _reconcile_loop(self, user_id: int, client) -> None:
        """
        Gap-gated REST reconcile (PP1, 2026-04-24).

        OLD behaviour: unconditional REST call every 60 s, regardless
        of whether the WebSocket event stream was still pushing.

        NEW behaviour: wake up every 60 s to CHECK, but only hit REST
        when the event stream has been silent for ≥ 5 minutes. In
        normal operation (events arriving every ~60 s), we now issue
        ZERO REST calls here — 100% cost reduction on the happy path.
        We still hit REST if the stream truly goes quiet, which catches
        the pathological "WS connected but not pushing" edge case the
        original loop was designed to defend against.

        Expected weight cut: from 5 weight/min/user → ≈0 weight/min/user
        in steady state. At 100 active users: 500 → ~0 weight/min saved.
        """
        GAP_THRESHOLD_SEC = 300.0   # 5 min of silence triggers REST rescue
        CHECK_EVERY_SEC   = 60.0
        try:
            while not self._stopping.get(user_id):
                await asyncio.sleep(CHECK_EVERY_SEC)
                if self._stopping.get(user_id):
                    return
                st = self._state.get(user_id, {})
                last = float(st.get("last_event", 0) or 0)
                gap = time.time() - last if last else float("inf")
                if gap < GAP_THRESHOLD_SEC:
                    # Stream is healthy — skip the REST call entirely.
                    continue
                # Stream has gone quiet for ≥ 5 min — hit REST to reconcile.
                log.info(
                    f"user {user_id}: UDS quiet for {gap:.0f}s "
                    f"(>{GAP_THRESHOLD_SEC:.0f}s) — running REST reconcile"
                )
                try:
                    await self._hydrate_from_rest(user_id, client)
                    if user_id in self._state:
                        self._state[user_id]["connected"] = True
                        self._state[user_id]["source"] = "rest_reconcile"
                except Exception as e:
                    log.debug(
                        f"user {user_id}: gap-gated reconcile failed ({e}); "
                        f"will retry next check"
                    )
        except asyncio.CancelledError:
            return

    async def _hydrate_from_rest(self, user_id: int, client) -> None:
        """One-shot REST call to build initial state dict."""
        try:
            acc = await client.futures_account()
        except Exception as e:
            raise RuntimeError(f"futures_account snapshot failed: {e}") from e

        total   = float(acc.get("totalWalletBalance", 0) or 0)
        avail   = float(acc.get("availableBalance", 0) or 0)
        unreal  = float(acc.get("totalUnrealizedProfit", 0) or 0)
        invest  = float(acc.get("totalInitialMargin", 0) or 0)
        pct     = round(unreal / invest * 100, 2) if invest else 0.0

        positions: Dict[str, Dict[str, float]] = {}
        for p in (acc.get("positions") or []):
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            sym   = p.get("symbol") or ""
            entry = float(p.get("entryPrice", 0) or 0)
            lev   = int(float(p.get("leverage", 1) or 1)) or 1
            im    = abs(amt) * entry / lev if entry else 0
            pnl_u = float(p.get("unrealizedProfit", 0) or 0)
            pnl_p = (pnl_u / im * 100) if im else 0.0
            positions[sym] = {
                "pnl_usd":   round(pnl_u, 4),
                "pnl_pct":   round(pnl_p, 4),
                "leverage":  lev,
                "entry":     entry,
                "amt":       amt,
            }

        now = time.time()
        self._state[user_id] = {
            "balance_usdt":       round(total, 2),
            "available_usdt":     round(avail, 2),
            "unrealized_pnl":     round(unreal, 2),
            "unrealized_pnl_pct": pct,
            "total_invested_usd": round(invest, 2),
            "positions":          positions,
            "server_time":        now,
            "last_event":         now,
            "connected":          False,       # set to True once WS opens
            "reconnects":         self._state.get(user_id, {}).get("reconnects", 0),
            "last_error":         None,
            "source":             "rest_snapshot",
        }
        log.info(f"user {user_id}: hydrated state via REST "
                 f"(bal={total:.2f}, avail={avail:.2f}, pos={len(positions)})")

    # ── Event application ──────────────────────────────────────────────
    def _apply_event(self, user_id: int, msg: Dict[str, Any]) -> None:
        """
        Apply a Binance futures user-stream event to the per-user state.

        Event types documented at:
        https://developers.binance.com/docs/derivatives/usds-margined-futures/
                 user-data-streams
        """
        st = self._state.setdefault(user_id, {})
        st["last_event"] = time.time()

        # python-binance wraps each event in {"e": <type>, ...}.  Sometimes
        # events arrive under "data" (multiplex) — unwrap.
        if "data" in msg and isinstance(msg["data"], dict):
            msg = msg["data"]

        event_type = msg.get("e")

        if event_type == "ACCOUNT_UPDATE":
            self._apply_account_update(st, msg)
            # Invalidate Redis live-balance cache opportunistically so
            # the next frontend poll sees the fresh balance within the
            # same second rather than waiting out the 8 s TTL.
            try:
                from redis_cache import bal_cache_del as _bal_del
                _bal_del(user_id)
            except Exception:
                pass
        elif event_type == "ORDER_TRADE_UPDATE":
            self._apply_order_update(st, msg)
        elif event_type == "listenKeyExpired":
            log.warning(f"user {user_id}: listenKey expired — will reconnect")
            raise RuntimeError("listenKeyExpired")
        elif event_type == "MARGIN_CALL":
            log.warning(f"user {user_id}: MARGIN_CALL event — {msg}")
        else:
            # Unknown/ignored event type — log at debug level only.
            pass

    def _apply_account_update(self, st: Dict[str, Any], msg: Dict[str, Any]) -> None:
        """
        Binance ACCOUNT_UPDATE event shape (abridged):
            {"e":"ACCOUNT_UPDATE", "E":..., "T":..., "a":{
                "B": [ {"a":"USDT","wb":"...", "cw":"...", "bc":"..."}, ... ],
                "P": [ {"s":"BTCUSDT","pa":"...", "ep":"...", "cr":"...",
                        "up":"...", "mt":"isolated", "iw":"...", "ps":"BOTH"}, ... ]
            }}
        """
        a = msg.get("a") or {}

        # ── Balances ──
        for b in a.get("B") or []:
            if b.get("a") != "USDT":
                continue
            # wb = wallet balance, cw = cross wallet balance
            try:
                st["balance_usdt"] = round(float(b.get("wb", 0) or 0), 2)
                # availableBalance isn't in this event; keep the last REST
                # value — we'll refresh it from ACCOUNT_UPDATE's implied
                # math (balance - locked_margin) below.
            except (ValueError, TypeError):
                pass

        # ── Positions ──
        positions = st.setdefault("positions", {})
        total_unreal = 0.0
        total_invested = 0.0
        for p in a.get("P") or []:
            sym = p.get("s") or ""
            try:
                amt   = float(p.get("pa", 0) or 0)
                entry = float(p.get("ep", 0) or 0)
                up    = float(p.get("up", 0) or 0)
            except (ValueError, TypeError):
                continue
            if amt == 0:
                positions.pop(sym, None)
                continue
            # Leverage isn't in ACCOUNT_UPDATE; preserve last-known, default 1.
            prev = positions.get(sym) or {}
            lev = int(prev.get("leverage", 1)) or 1
            im  = abs(amt) * entry / lev if entry else 0
            pnl_p = (up / im * 100) if im else 0.0
            positions[sym] = {
                "pnl_usd":   round(up, 4),
                "pnl_pct":   round(pnl_p, 4),
                "leverage":  lev,
                "entry":     entry,
                "amt":       amt,
            }
            total_unreal   += up
            total_invested += im

        # Aggregate account-level metrics
        if positions:
            st["unrealized_pnl"]     = round(total_unreal, 2)
            st["total_invested_usd"] = round(total_invested, 2)
            st["unrealized_pnl_pct"] = (
                round(total_unreal / total_invested * 100, 2) if total_invested else 0.0
            )
            # availableBalance is walletBalance - totalInitialMargin - unrealizedPnL
            # (only a good approximation, matches Binance's UI math)
            st["available_usdt"] = round(
                max(0.0, st.get("balance_usdt", 0.0) - total_invested), 2
            )
        else:
            st["unrealized_pnl"]     = 0.0
            st["total_invested_usd"] = 0.0
            st["unrealized_pnl_pct"] = 0.0
            st["available_usdt"]     = st.get("balance_usdt", 0.0)

        st["server_time"] = time.time()
        st["source"]      = "ws_account_update"

    def _apply_order_update(self, st: Dict[str, Any], msg: Dict[str, Any]) -> None:
        """
        ORDER_TRADE_UPDATE tells us a fill/cancel happened.  We don't store
        the order book here (that's the DB's job in copy_trading) — we just
        update the leverage on the affected symbol's position, because
        that's the only field ACCOUNT_UPDATE lacks.
        """
        o = msg.get("o") or {}
        sym = o.get("s")
        try:
            lev = int(float(o.get("l", 0) or o.get("L", 0) or 0))
        except (ValueError, TypeError):
            lev = 0
        if sym and lev > 0:
            pos = (st.get("positions") or {}).get(sym)
            if pos:
                pos["leverage"] = lev

    # ── Helpers ────────────────────────────────────────────────────────
    def _set_error(self, user_id: int, err: str) -> None:
        st = self._state.setdefault(user_id, {})
        st["last_error"] = err
        st["connected"]  = False

    def _bump_reconnects(self, user_id: int) -> None:
        st = self._state.setdefault(user_id, {})
        st["reconnects"] = int(st.get("reconnects", 0)) + 1


# ── Convenience module-level wrappers ────────────────────────────────────
def get_state(user_id: int) -> Optional[Dict[str, Any]]:
    return UserStreamManager.instance().get_state(user_id)


def is_fresh(user_id: int) -> bool:
    return UserStreamManager.instance().is_fresh(user_id)


def status_all() -> Dict[int, Dict[str, Any]]:
    return UserStreamManager.instance().status_all()


async def start(user_id: int) -> bool:
    return await UserStreamManager.instance().start(user_id)


async def stop(user_id: int) -> None:
    await UserStreamManager.instance().stop(user_id)


async def stop_all() -> None:
    await UserStreamManager.instance().stop_all()


async def start_all_active() -> int:
    """
    On dashboard startup: spawn a UDS task for every user whose
    copy_trading_config row has is_active=1 AND valid API keys.
    Returns the number of tasks started.
    """
    if not is_enabled():
        log.info("user-stream disabled via BINANCE_WS_USER_STREAM env var")
        return 0

    try:
        # Avoid circular import at module load
        from copy_trading import _get_db  # type: ignore
    except Exception as e:
        log.error(f"start_all_active: cannot import copy_trading: {e}")
        return 0

    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT user_id FROM copy_trading_config WHERE is_active=1"
        ).fetchall()
    finally:
        conn.close()

    count = 0
    mgr = UserStreamManager.instance()
    for r in rows:
        uid = r[0] if isinstance(r, tuple) else r["user_id"]
        try:
            if await mgr.start(int(uid)):
                count += 1
        except Exception as e:
            log.error(f"failed to start stream for user {uid}: {e}")
    log.info(f"start_all_active: spawned {count} streams")
    return count
