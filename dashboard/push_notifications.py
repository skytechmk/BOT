"""
push_notifications.py — Browser Web Push (VAPID) subscriptions + sender.
=======================================================================

Phase 2 deliverable from proposals/2026-04-24_native-push-alerts.md.

Design:
    * Uses the W3C Web Push API with VAPID — NO Firebase / FCM account
      required. Works in Chrome, Firefox, Edge, Opera, Samsung Internet.
      Safari requires iOS 16.4+ / macOS 13+ and a PWA-install first;
      we gracefully no-op on unsupported browsers.

    * INERT until VAPID env vars are present. When VAPID_PRIVATE_KEY
      / VAPID_PUBLIC_KEY are not set, all functions return degraded
      results but never raise. This lets us ship the full scaffold
      today and the operator flips it on by running:

          python3 scripts/generate_vapid_keys.py >> .env

    * Subscriptions live in the existing `dashboard.db` SQLite file —
      single new table, no schema migration on any existing table.

Public API:
    is_push_enabled()                           -> bool
    get_public_key()                            -> Optional[str]
    subscribe(user_id, subscription_json)       -> dict
    unsubscribe(user_id, endpoint)              -> bool
    send_push(user_id, title, body, url=None)   -> dict   # fan-out to all user's devices
    broadcast_to_tier(tier, title, body, url=None) -> dict
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("anw.push")

_DB_PATH = Path(__file__).parent / "dashboard.db"
_VAPID_PUB  = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_VAPID_PRIV = os.getenv("VAPID_PRIVATE_KEY", "").strip()
_VAPID_SUB  = os.getenv("VAPID_SUBJECT", "mailto:security@anunnakiworld.com").strip()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _init_table() -> None:
    """Idempotent schema creation. One row per (user_id, endpoint)."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                endpoint    TEXT    NOT NULL,
                p256dh      TEXT    NOT NULL,
                auth        TEXT    NOT NULL,
                user_agent  TEXT,
                created_at  REAL    NOT NULL,
                last_sent   REAL,
                send_count  INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, endpoint)
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_push_user_id "
            "ON push_subscriptions(user_id);"
        )
        conn.commit()
    finally:
        conn.close()


_init_table()


def is_push_enabled() -> bool:
    """True iff VAPID keys are configured in the environment.
    When False, all send operations no-op (but storage still works)."""
    return bool(_VAPID_PRIV and _VAPID_PUB)


def get_public_key() -> Optional[str]:
    """The URL-safe base64 VAPID public key to hand to the browser.
    None when push is not configured (so UI can hide the subscribe CTA)."""
    return _VAPID_PUB or None


def subscribe(user_id: int, subscription: Dict[str, Any],
              user_agent: Optional[str] = None) -> Dict[str, Any]:
    """Persist a browser PushSubscription payload.

    `subscription` is the JSON returned by ServiceWorkerRegistration
    .pushManager.subscribe(...) on the client — shape::

        {
          "endpoint": "https://…",
          "keys": { "p256dh": "…", "auth": "…" }
        }
    """
    try:
        endpoint = str(subscription.get("endpoint", "")).strip()
        keys = subscription.get("keys") or {}
        p256dh = str(keys.get("p256dh", "")).strip()
        auth   = str(keys.get("auth", "")).strip()
        if not endpoint or not p256dh or not auth:
            return {"ok": False, "error": "malformed subscription"}
        conn = _get_db()
        try:
            conn.execute(
                """INSERT INTO push_subscriptions
                   (user_id, endpoint, p256dh, auth, user_agent, created_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(user_id, endpoint) DO UPDATE SET
                      p256dh=excluded.p256dh,
                      auth=excluded.auth,
                      user_agent=excluded.user_agent""",
                (user_id, endpoint, p256dh, auth, user_agent, time.time())
            )
            conn.commit()
        finally:
            conn.close()
        log.info(f"[push] user={user_id} subscribed (endpoint ends …{endpoint[-24:]})")
        return {"ok": True}
    except Exception as e:
        log.exception("[push] subscribe failed")
        return {"ok": False, "error": str(e)}


def unsubscribe(user_id: int, endpoint: str) -> bool:
    """Remove a specific device's subscription (called on browser unsubscribe)."""
    try:
        conn = _get_db()
        try:
            cur = conn.execute(
                "DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?",
                (user_id, endpoint)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception as e:
        log.debug(f"[push] unsubscribe failed: {e!r}")
        return False


def _list_subscriptions(user_id: int) -> List[sqlite3.Row]:
    conn = _get_db()
    try:
        return conn.execute(
            "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
            "WHERE user_id=?",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()


def _purge(sub_id: int) -> None:
    """Drop a subscription row (called when the endpoint returns 404/410)."""
    try:
        conn = _get_db()
        conn.execute("DELETE FROM push_subscriptions WHERE id=?", (sub_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def send_push(user_id: int, title: str, body: str,
              url: Optional[str] = None,
              data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fan-out a push to every device subscribed for `user_id`.

    Returns a summary dict::
        {"ok": True, "sent": 3, "skipped": 0, "removed": 1}

    Behaviour on no-VAPID env: returns `{"ok": False, "reason":
    "not_configured"}` without touching the network. Callers should
    check `is_push_enabled()` first if they want to avoid this.
    """
    if not is_push_enabled():
        return {"ok": False, "reason": "not_configured"}
    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        return {"ok": False, "reason": f"pywebpush missing: {e!r}"}

    subs = _list_subscriptions(user_id)
    if not subs:
        return {"ok": True, "sent": 0, "skipped": 0, "removed": 0}

    payload = json.dumps({
        "title": title,
        "body":  body,
        "url":   url or "/app",
        "data":  data or {},
        "ts":    int(time.time()),
    })
    sent = skipped = removed = 0
    for row in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": row["endpoint"],
                    "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
                },
                data=payload,
                vapid_private_key=_VAPID_PRIV,
                vapid_claims={"sub": _VAPID_SUB},
                ttl=60,  # 1-minute TTL — signals go stale fast
            )
            sent += 1
        except WebPushException as e:
            # 404 / 410 = endpoint gone; drop silently so we don't
            # keep pinging dead subscriptions forever.
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                _purge(row["id"])
                removed += 1
            else:
                log.warning(f"[push] send failed (user={user_id}): {e}")
                skipped += 1
        except Exception as e:
            log.warning(f"[push] unexpected send error: {e!r}")
            skipped += 1
    return {"ok": True, "sent": sent, "skipped": skipped, "removed": removed}


def broadcast_to_tier(tier: str, title: str, body: str,
                      url: Optional[str] = None) -> Dict[str, Any]:
    """Send the same push to every subscribed user whose effective tier
    is >= `tier`. Stub for now — the tier join requires the main auth DB
    and is better done via a small helper that caller constructs.
    Returns a list of per-user summaries so the admin UI can surface
    failures.
    """
    # Intentionally left minimal — the caller (admin panel) already
    # has the auth DB open and can do the tier filter, then loop
    # over user IDs calling send_push() directly. We avoid coupling
    # this module to the user DB.
    return {"ok": False, "reason": "call send_push per user_id"}
