#!/usr/bin/env python3
"""
Archives ANUNNAKI_OPS Telegram group messages to memory store.
Fetches messages from the bot's update stream and writes them to memory/YYYY-MM-DD.md.
Intended to be run daily via cron (e.g., 00:05) to capture previous day's conversation.
"""

import os
import json
import datetime
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
TOKEN = os.getenv('OPS_TELEGRAM_TOKEN') or os.getenv('TELEGRAM_TOKEN')
print(f"Using token: {TOKEN[:10]}...")  # debug
CHAT_ID = os.getenv('OPS_TELEGRAM_CHAT_ID') or '-1003706659588'

def fetch_updates(limit=200):
    if not TOKEN:
        print("Missing TELEGRAM_TOKEN or OPS_TELEGRAM_TOKEN")
        return []
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?limit={limit}"
    try:
        r = requests.get(url, timeout=15)
        d = r.json()
        if d.get('ok'):
            return d.get('result', [])
    except Exception as e:
        print(f"Error fetching updates: {e}")
    return []

def filter_by_chat_and_day(posts, target_chat_id, target_date):
    """target_date is a date object (UTC). Telegram timestamps are in seconds."""
    matched = []
    for u in posts:
        msg = u.get('message') or u.get('channel_post')
        if not msg:
            continue
        chat = msg.get('chat', {})
        if str(chat.get('id')) != str(target_chat_id):
            continue
        # Convert timestamp to date (UTC)
        ts = msg.get('date')
        if not ts:
            continue
        msg_date = datetime.datetime.utcfromtimestamp(ts).date()
        if msg_date != target_date:
            continue
        matched.append(msg)
    return matched

def main():
    # For testing: archive today's messages
    from datetime import timezone
    target_date = datetime.datetime.now(timezone.utc).date()  # same day
    print(f"DEBUG: Archiving for {target_date}")
    print(f"Archiving messages for {target_date} from ANUNNAKI_OPS")

    updates = fetch_updates(limit=500)
    messages = filter_by_chat_and_day(updates, CHAT_ID, target_date)

    if not messages:
        print("No messages found for that date.")
        return

    # Build output
    out_lines = [f"# Conversation Archive — {target_date} (ANUNNAKI_OPS)\n"]
    # Sort by message_id ascending for chronological order
    messages.sort(key=lambda m: m.get('message_id', 0))
    for m in messages:
        sender = m.get('from', {})
        sender_name = sender.get('username') or f"{sender.get('first_name','')} {sender.get('last_name','')}".strip()
        if not sender_name:
            sender_name = "unknown"
        text = m.get('text', '').strip() or '[media]'
        dt = datetime.datetime.utcfromtimestamp(m.get('date')).strftime('%H:%M UTC')
        out_lines.append(f"[{dt}] <{sender_name}> {text}\n")

    # Write to memory file
    mem_path = BASE / 'memory' / f"{target_date}.md"
    mem_path.parent.mkdir(exist_ok=True)
    with open(mem_path, 'a') as f:
        f.write('\n'.join(out_lines) + '\n')
    print(f"Wrote {len(messages)} messages to {mem_path}")

if __name__ == '__main__':
    main()
