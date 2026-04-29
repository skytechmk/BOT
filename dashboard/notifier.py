"""
notifier.py — Asynchronous alerting microservice for trade execution
and dynamic stop-loss events.

Architecture:
    Trading Engine ──► Redis Pub/Sub (fire-and-forget)
                            │
                     notification_listener()  (background coroutine)
                            │
                     NotificationManager ──► Telegram Bot API
                                          └─► Discord Webhook

Key properties:
    • HTTP dispatch is NEVER awaited inside the trading loop — engines
      publish lightweight JSON to Redis and move on immediately.
    • All I/O is async (aiohttp); failures are caught and logged, never
      propagated to the main loop.
    • Rate-limiting (HTTP 429) is handled with exponential back-off.
    • If Redis is down at boot, the listener is silently skipped.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import html
from typing import Any, Dict, Optional

import aiohttp

log = logging.getLogger("anw.notifier")

# ─── Configuration ─────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip("'\"")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip("'\"")
DISCORD_WEBHOOK    = os.getenv("DISCORD_WEBHOOK_URL", "").strip("'\"")
REDIS_URL          = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# Channels the listener subscribes to
_CHANNELS = ["anw:alerts", "anw:signals"]

# Rate-limit back-off: base delay, max delay, max retries
_RATE_BASE   = 2.0   # seconds
_RATE_MAX    = 60.0
_RATE_RETRIES = 5

# Telegram API endpoint
_TG_URL = "https://api.telegram.org/bot{token}/sendMessage"

# aiohttp session reused across all dispatches
_session: Optional[aiohttp.ClientSession] = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300),
        )
    return _session


# ─── HTML formatting helpers ───────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape text for Telegram HTML parse_mode."""
    return html.escape(str(text), quote=False)


def _format_signal(payload: Dict[str, Any]) -> str:
    """Format a signal event into readable HTML."""
    pair      = _esc(payload.get("pair", "UNKNOWN"))
    direction = payload.get("direction", "").upper()
    entry     = payload.get("entry", 0)
    stop      = payload.get("stop_loss", 0)
    targets   = payload.get("targets", [])
    leverage  = payload.get("leverage", 1)
    sqi       = payload.get("sqi_score", 0)
    signal_id = payload.get("signal_id", "?")[:8]

    emoji = "🟢" if direction == "LONG" else "🔴" if direction == "SHORT" else "⚪"
    dir_label = f"<b>{direction}</b>"

    lines = [
        f"{emoji} <b>NEW SIGNAL</b> <code>{pair}</code> {dir_label}",
        f"▸ Entry:  <b>{entry:.6g}</b>",
        f"▸ SL:    <b>{stop:.6g}</b>",
    ]
    for i, tp in enumerate(targets, 1):
        lines.append(f"▸ TP{i}:  <b>{tp:.6g}</b>")
    lines.extend([
        f"▸ Leverage: <b>{leverage}×</b>  |  SQI: <b>{sqi:.1f}</b>",
        f"▸ ID: <code>{signal_id}</code>",
    ])
    return "\n".join(lines)


def _format_trail_sl(payload: Dict[str, Any]) -> str:
    """Format a trailing stop adjustment event."""
    pair   = _esc(payload.get("pair", "UNKNOWN"))
    old_sl = payload.get("old_sl", 0)
    new_sl = payload.get("new_sl", 0)
    choke  = payload.get("funding_choke", False)
    emoji  = "🟢" if new_sl > old_sl else "🔴"

    tag = "🪝 <b>FUNDING CHOKE</b>" if choke else f"{emoji} <b>TRAIL SL</b>"
    return (
        f"{tag} <code>{pair}</code>\n"
        f"▸ SL: <b>{old_sl:.6g}</b> → <b>{new_sl:.6g}</b>"
    )


def _format_exit(payload: Dict[str, Any]) -> str:
    """Format a trade close / exit event."""
    pair      = _esc(payload.get("pair", "UNKNOWN"))
    direction = payload.get("direction", "").upper()
    pnl       = payload.get("pnl_pct", 0)
    reason    = _esc(payload.get("reason", "unknown"))
    emoji     = "🟢" if pnl > 0 else "🔴"
    sign      = "+" if pnl > 0 else ""
    return (
        f"{emoji} <b>CLOSED</b> <code>{pair}</code> <b>{direction}</b>\n"
        f"▸ PnL:  <b>{sign}{pnl:.2f}%</b>\n"
        f"▸ Reason: <b>{reason}</b>"
    )


_FORMATTERS = {
    "signal":    _format_signal,
    "trail_sl":  _format_trail_sl,
    "exit":      _format_exit,
}


def _format_message(payload: Dict[str, Any]) -> str:
    """Dispatch to the appropriate formatter, or use a generic fallback."""
    kind = payload.get("type", "generic")
    formatter = _FORMATTERS.get(kind)
    if formatter:
        return formatter(payload)
    # Generic fallback: pretty-print key/value pairs
    kv = "\n".join(
        f"▸ {_esc(k)}: <b>{_esc(str(v))}</b>"
        for k, v in payload.items()
        if k not in ("type",)
    )
    return f"📡 <b>{_esc(kind).upper()}</b>\n{kv}"


# ─── HTTP dispatch ─────────────────────────────────────────────────────

async def _send_telegram(text: str, max_retries: int = _RATE_RETRIES) -> bool:
    """Send HTML-formatted message to Telegram with rate-limit retry."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = _TG_URL.format(token=TELEGRAM_BOT_TOKEN)
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    delay = _RATE_BASE

    for attempt in range(max_retries + 1):
        try:
            async with _get_session().post(url, json=data) as resp:
                if resp.status == 200:
                    return True
                if resp.status == 429:
                    # Telegram 429 includes a Retry-After header; honour it
                    try:
                        retry_after = float(resp.headers.get("Retry-After", delay))
                    except (TypeError, ValueError):
                        retry_after = delay
                    log.warning(
                        f"[notifier] Telegram 429 — waiting {retry_after:.1f}s "
                        f"(attempt {attempt+1}/{max_retries+1})"
                    )
                    await asyncio.sleep(retry_after)
                    delay = min(delay * 2, _RATE_MAX)
                    continue
                # Other errors (400, 500, etc.) — log and give up
                body = await resp.text()
                log.error(f"[notifier] Telegram HTTP {resp.status}: {body[:200]}")
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning(f"[notifier] Telegram dispatch error: {exc}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RATE_MAX)
            else:
                return False
    return False


async def _send_discord(text: str, max_retries: int = _RATE_RETRIES) -> bool:
    """Send plain-text message to Discord webhook with rate-limit retry."""
    if not DISCORD_WEBHOOK:
        return False

    # Strip HTML tags for Discord
    import re
    clean = re.sub(r"<[^>]+>", "", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    data = {"content": clean[:2000]}  # Discord limit
    delay = _RATE_BASE

    for attempt in range(max_retries + 1):
        try:
            async with _get_session().post(DISCORD_WEBHOOK, json=data) as resp:
                if resp.status in (200, 204):
                    return True
                if resp.status == 429:
                    try:
                        retry_after = float(resp.headers.get("Retry-After", delay))
                    except (TypeError, ValueError):
                        retry_after = delay
                    log.warning(
                        f"[notifier] Discord 429 — waiting {retry_after:.1f}s "
                        f"(attempt {attempt+1}/{max_retries+1})"
                    )
                    await asyncio.sleep(retry_after)
                    delay = min(delay * 2, _RATE_MAX)
                    continue
                body = await resp.text()
                log.error(f"[notifier] Discord HTTP {resp.status}: {body[:200]}")
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning(f"[notifier] Discord dispatch error: {exc}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RATE_MAX)
            else:
                return False
    return False


# ─── NotificationManager ───────────────────────────────────────────────

class NotificationManager:
    """
    High-level facade used by engine code to publish alerts to Redis.
    The engine does NOT await HTTP — it calls :meth:`publish` and moves on.
    """

    @staticmethod
    async def publish(payload: Dict[str, Any], channel: str = "anw:alerts") -> None:
        """
        Fire-and-forget: publish a JSON payload to a Redis channel.

        The payload must be serialisable.  A ``type`` key is recommended
        so the listener can pick the right formatter::

            {"type": "signal", "pair": "BTCUSDT", "direction": "LONG", ...}
            {"type": "trail_sl", "pair": "ETHUSDT", "old_sl": ..., "new_sl": ...}
            {"type": "exit", "pair": "SOLUSDT", "pnl_pct": -2.3, "reason": "sl_hit"}
        """
        try:
            import redis.asyncio as aioredis
            r = aioredis.Redis.from_url(
                REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5,
                decode_responses=True,
            )
            await r.publish(channel, json.dumps(payload))
        except Exception as exc:
            log.debug(f"[notifier] Redis publish failed ({channel}): {exc!r}")
        finally:
            try:
                await r.close()
            except Exception:
                pass

    @staticmethod
    async def publish_signal(**kwargs: Any) -> None:
        payload = {"type": "signal", **kwargs}
        await NotificationManager.publish(payload)

    @staticmethod
    async def publish_trail_sl(**kwargs: Any) -> None:
        payload = {"type": "trail_sl", **kwargs}
        await NotificationManager.publish(payload)

    @staticmethod
    async def publish_exit(**kwargs: Any) -> None:
        payload = {"type": "exit", **kwargs}
        await NotificationManager.publish(payload)


# ─── Redis Pub/Sub listener (background coroutine) ─────────────────────

async def notification_listener() -> None:
    """
    Persistent background coroutine that subscribes to Redis alert channels
    and dispatches each message to Telegram and/or Discord.

    Designed to be injected into the main event loop::

        asyncio.create_task(notification_listener())

    If Redis is unavailable at boot, logs a warning and exits cleanly —
    never crashes the trading loop.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.warning("[notifier] redis package not installed — listener disabled")
        return

    try:
        r = aioredis.Redis.from_url(
            REDIS_URL,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            decode_responses=True,
        )
        # Verify connectivity
        await r.ping()
    except Exception as exc:
        log.warning(f"[notifier] Redis unavailable at boot ({exc!r}) — listener disabled")
        return

    log.info(f"[notifier] listener started — subscribed to {_CHANNELS}")

    try:
        pubsub = r.pubsub()
        await pubsub.subscribe(*_CHANNELS)

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except json.JSONDecodeError:
                log.debug(f"[notifier] malformed payload: {message['data'][:120]}")
                continue

            formatted = _format_message(payload)

            # Fire both destinations concurrently
            tg_task = asyncio.create_task(_send_telegram(formatted))
            dc_task = asyncio.create_task(_send_discord(formatted))
            await asyncio.gather(tg_task, dc_task, return_exceptions=True)

    except asyncio.CancelledError:
        log.info("[notifier] listener cancelled — shutting down")
    except Exception as exc:
        log.error(f"[notifier] listener fatal error: {exc!r}", exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.close()
            await r.close()
        except Exception:
            pass


# ─── Convenience: direct send (bypasses Redis) ─────────────────────────
# Useful for one-off alerts from non-trading code (e.g., boot messages).

async def send_alert(type: str = "generic", **kwargs: Any) -> None:
    """
    Format and dispatch an alert directly (no Redis intermediary).

    Usage::

        await send_alert("signal", pair="BTCUSDT", direction="LONG", ...)
        await send_alert("trail_sl", pair="ETHUSDT", old_sl=..., new_sl=...)
    """
    payload = {"type": type, **kwargs}
    formatted = _format_message(payload)
    tg = asyncio.create_task(_send_telegram(formatted))
    dc = asyncio.create_task(_send_discord(formatted))
    await asyncio.gather(tg, dc, return_exceptions=True)
