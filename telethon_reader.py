"""
Telethon Channel Reader
Reads messages from Telegram channels using the existing user-account session
(spectre_user.session). Provides both async and sync-safe interfaces.

Channels:
  signals  → TELEGRAM_CHAT_ID        (-1002209928687)
  closed   → CLOSED_SIGNALS_CHAT_ID  (-1002664177259)
  ops      → OPS_TELEGRAM_CHAT_ID    (-1003706659588)
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).parent
load_dotenv(BASE / 'telethon_config.env')
load_dotenv(BASE / '.env', override=False)

API_ID   = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
SESSION  = str(BASE / os.getenv('SESSION', 'spectre_user'))

# Channel map — aliased for easy lookup by SPECTRE
CHANNEL_MAP = {
    'signals':  int(os.getenv('TELEGRAM_CHAT_ID',       '-1002209928687')),
    'closed':   int(os.getenv('CLOSED_SIGNALS_CHAT_ID', '-1002664177259')),
    'ops':      int(os.getenv('OPS_TELEGRAM_CHAT_ID',   '-1003706659588').strip("'")),
}


async def _fetch_messages_async(channel_id: int, limit: int = 20, search: str = None) -> list:
    """
    Core async reader.  Opens a Telethon client, fetches `limit` recent messages
    from `channel_id`, and disconnects.  Uses the existing session so no login
    prompt is needed.
    """
    try:
        from telethon import TelegramClient
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return [{"error": "Telethon session not authorized. Run member_monitor.py once interactively to log in."}]

        messages = []
        kwargs = {"limit": limit}
        if search:
            kwargs["search"] = search

        async for msg in client.iter_messages(channel_id, **kwargs):
            media_type = None
            if msg.media:
                if isinstance(msg.media, MessageMediaPhoto):
                    media_type = "photo"
                elif isinstance(msg.media, MessageMediaDocument):
                    media_type = "document"
                else:
                    media_type = "other"

            messages.append({
                "id":         msg.id,
                "date":       msg.date.strftime("%Y-%m-%d %H:%M UTC") if msg.date else None,
                "sender_id":  msg.sender_id,
                "text":       msg.text or "",
                "media":      media_type,
                "views":      getattr(msg, "views", None),
                "replies":    getattr(msg.replies, "replies", None) if msg.replies else None,
                "forwarded":  msg.forward is not None,
            })

        await client.disconnect()
        return messages

    except ImportError:
        return [{"error": "telethon not installed. Run: pip install telethon"}]
    except Exception as e:
        return [{"error": str(e)}]


def fetch_channel_messages(channel: str = "signals", limit: int = 20, search: str = None) -> str:
    """
    Sync-safe wrapper — can be called from synchronous MCP tools or bridge methods.
    `channel` can be 'signals', 'closed', 'ops', or a raw integer chat_id string.
    Returns a JSON string.
    """
    # Resolve channel alias or raw ID
    if channel in CHANNEL_MAP:
        channel_id = CHANNEL_MAP[channel]
    else:
        try:
            channel_id = int(channel)
        except ValueError:
            return json.dumps({"error": f"Unknown channel '{channel}'. Use: signals, closed, ops, or a numeric chat_id."})

    limit = max(1, min(limit, 100))  # hard cap

    # Run in a fresh event loop so it is safe to call from sync context
    try:
        loop = asyncio.new_event_loop()
        msgs = loop.run_until_complete(_fetch_messages_async(channel_id, limit, search))
        loop.close()
    except Exception as e:
        return json.dumps({"error": str(e)})

    channel_name = {v: k for k, v in CHANNEL_MAP.items()}.get(channel_id, str(channel_id))

    return json.dumps({
        "channel":      channel_name,
        "channel_id":   channel_id,
        "fetched":      len(msgs),
        "messages":     msgs,
    }, indent=2, ensure_ascii=False)
