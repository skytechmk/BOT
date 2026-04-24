#!/usr/bin/env python3
import os, asyncio, sys, json
from dotenv import load_dotenv
load_dotenv('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env')
import telegram

TOKEN = os.getenv('TELEGRAM_TOKEN').strip("'")
OPS_TOKEN = os.getenv('OPS_TELEGRAM_TOKEN').strip("'")
MAIN_CHAT = int(os.getenv('TELEGRAM_CHAT_ID').strip("'"))
OPS_CHAT = int(os.getenv('OPS_TELEGRAM_CHAT_ID').strip("'"))

async def get_active_members(chat_id, token, limit=200):
    bot = telegram.Bot(token=token)
    try:
        updates = await bot.get_updates(limit=limit)
        members = {}
        for u in updates:
            if u.message and u.message.chat and u.message.chat.id == chat_id:
                user = u.message.from_user
                uid = user.id
                if uid not in members:
                    members[uid] = {
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or '',
                        'username': user.username or '',
                        'last_msg_date': u.message.date.isoformat() if u.message.date else ''
                    }
                else:
                    if u.message.date and u.message.date.isoformat() < members[uid]['last_msg_date']:
                        members[uid]['last_msg_date'] = u.message.date.isoformat()
        return members
    except Exception as e:
        print(f'Error for chat {chat_id}: {e}')
        return {}

async def main():
    print('Fetching active members from recent updates...')
    main_mems = await get_active_members(MAIN_CHAT, TOKEN, limit=200)
    ops_mems = await get_active_members(OPS_CHAT, OPS_TOKEN or TOKEN, limit=200)

    print(f'\\n=== AnunnakiWorld (Main Signals) — Active Senders ({len(main_mems)} unique) ===')
    for uid, info in sorted(main_mems.items(), key=lambda x: x[1]['last_msg_date'], reverse=True)[:20]:
        uname = f'@{info["username"]}' if info['username'] else '(no username)'
        print(f'{uid}: {info["first_name"]} {info["last_name"]} — {uname}  last: {info["last_msg_date"][:10]}')

    print(f'\\n=== ANUNNAKI_OPS — Active Senders ({len(ops_mems)} unique) ===')
    for uid, info in sorted(ops_mems.items(), key=lambda x: x[1]['last_msg_date'], reverse=True)[:20]:
        uname = f'@{info["username"]}' if info['username'] else '(no username)'
        print(f'{uid}: {info["first_name"]} {info["last_name"]} — {uname}  last: {info["last_msg_date"][:10]}')

    main_ids = set(main_mems.keys())
    ops_ids = set(ops_mems.keys())
    overlap = main_ids & ops_ids
    print(f'\\nOverlap (active in both): {len(overlap)} users')
    if overlap:
        print('Users active in both groups:')
        for uid in overlap:
            info = main_mems[uid]
            uname = f'@{info["username"]}' if info['username'] else '(no username)'
            print(f'  {uid}: {info["first_name"]} — {uname}')

if __name__ == '__main__':
    asyncio.run(main())
