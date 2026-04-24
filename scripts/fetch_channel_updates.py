#!/usr/bin/env python3
import os, asyncio, json, sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env')
import telegram

TOKEN = os.getenv('TELEGRAM_TOKEN').strip("'")
MAIN_CHAT = int(os.getenv('TELEGRAM_CHAT_ID').strip("'"))
OPS_CHAT = int(os.getenv('OPS_TELEGRAM_CHAT_ID').strip("'"))

async def fetch_recent(chat_id, token, limit=50):
    bot = telegram.Bot(token=token)
    try:
        # Use get_chat to get recent messages via get_updates? Actually we need messages from the channel itself.
        # Bots can only receive messages that are sent after they are added as an admin, and only if those messages
        # are updates. There's no direct "get history" for channels unless the bot is an admin and uses getChatMessages?
        # Actually the Bot API does not support fetching arbitrary history from a channel.
        # However, if we have stored updates in the database, we could show that.
        # Alternatively, we can read from the local log file if the bot logs messages.
        return None
    except Exception as e:
        print(f'Error: {e}')
        return None

async def main():
    # Check if we have a local messages log
    log_path = '/tmp/openclaw/openclaw-2026-04-06.log'
    if os.path.exists(log_path):
        print(f'=== Recent Bot Log ({log_path}) ===')
        with open(log_path, 'r') as f:
            lines = f.readlines()[-100:]
        for line in lines:
            print(line.rstrip())
    else:
        print('No log file found.')

    # Try to get updates from the bot's current update queue
    bot = telegram.Bot(token=TOKEN)
    try:
        updates = await bot.get_updates(limit=20)
        print(f'\n=== Recent Updates (via getUpdates) ===')
        for u in updates:
            if u.message and u.message.chat:
                chat = u.message.chat
                text = u.message.text or u.message.caption or ''
                date = u.message.date.strftime('%Y-%m-%d %H:%M:%S') if u.message.date else ''
                print(f'{date} [{chat.title}] {u.message.from_user.first_name}: {text[:80]}')
    except Exception as e:
        print(f'Error fetching updates: {e}')

asyncio.run(main())
