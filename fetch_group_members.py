#!/usr/bin/env python3
"""
Fetch all members from a Telegram group using Telethon (user account).

Requires:
- Telethon: pip install telethon
- Config file: telethon_config.env with API_ID, API_HASH, GROUP_ID, SESSION

First run will ask for phone number and verification code.
Subsequent runs will reuse the session file.
"""

import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    ChatAdminRequiredError,
)

BASE = Path(__file__).parent
CONFIG_PATH = BASE / 'telethon_config.env'
OUTPUT_DIR = BASE / 'telethon_members'
OUTPUT_DIR.mkdir(exist_ok=True)

load_dotenv(CONFIG_PATH)

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
GROUP_ID = os.getenv('GROUP_ID')
SESSION = os.getenv('SESSION', 'spectre_user')

if not API_ID or not API_HASH or not GROUP_ID:
    print("❌ Missing config. Edit telethon_config.env with your API_ID, API_HASH, GROUP_ID")
    sys.exit(1)

# Convert GROUP_ID to int (may be negative)
try:
    GROUP_ID = int(GROUP_ID)
except ValueError:
    print("❌ GROUP_ID must be an integer (e.g., -1003706659588)")
    sys.exit(1)

client = TelegramClient(BASE / SESSION, API_ID, API_HASH)

async def main():
    print("🔌 Connecting...")
    await client.start()
    if not await client.is_user_authorized():
        print("📱 First run: need to sign in")
        await client.send_code_request(API_ID)  # Actually need phone number; fallback to interactive
        # Let Telethon handle interactive login
        print("⚠️  Please complete login in the terminal (phone number & code)")
        # client.connect() already started; the client will prompt via input()
        # We'll just let the connection proceed; if not authorized, it will raise
    # Ensure we are authorized
    if not await client.is_user_authorized():
        print("❌ Authorization failed. Try again.")
        return

    print(f"👥 Fetching members of group {GROUP_ID}...")
    all_participants = []
    try:
        async for user in client.iter_participants(GROUP_ID, limit=None):
            all_participants.append(user)
    except ChatAdminRequiredError:
        print("❌ I need to be an admin in the group to fetch members.")
        return
    except FloodWaitError as e:
        print(f"❌ Flood wait: {e.seconds} seconds. Try later.")
        return
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print(f"✅ Fetched {len(all_participants)} members")

    # Build output
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    out_json = OUTPUT_DIR / f'members_{GROUP_ID}_{timestamp}.json'
    out_csv = OUTPUT_DIR / f'members_{GROUP_ID}_{timestamp}.csv'

    # JSON
    data = []
    for u in all_participants:
        data.append({
            'id': u.id,
            'username': u.username,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'phone': u.phone,
            'is_bot': u.bot,
            'is_admin': u.premium or getattr(u, 'admin_rights', None) is not None,
            'restricted': u.restricted,
            'deleted': u.deleted,
        })
    with open(out_json, 'w') as f:
        json.dump(data, f, indent=2)

    # CSV
    import csv
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'username', 'first_name', 'last_name', 'phone', 'is_bot', 'is_admin', 'restricted', 'deleted'])
        writer.writeheader()
        for row in data:
            writer.writerow(row)

    print(f"📄 Saved JSON: {out_json}")
    print(f"📄 Saved CSV: {out_csv}")

if __name__ == '__main__':
    import time
    with client:
        client.loop.run_until_complete(main())
