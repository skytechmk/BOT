#!/usr/bin/env python3
"""
Telegram Group Member Monitor with Welcome Bot
Uses Telethon (user API) to track members and welcome new ones.

Requirements:
- Telethon: pip install telethon
- Config: telethon_config.env with valid API_ID, API_HASH, GROUP_ID

Get API credentials from: https://my.telegram.org/apps
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    ChatAdminRequiredError,
)

BASE = Path(__file__).parent
CONFIG_PATH = BASE / 'telethon_config.env'
DATA_DIR = BASE / 'telethon_data'
DATA_DIR.mkdir(exist_ok=True)

# State files
MEMBERS_FILE = DATA_DIR / 'members.json'
WELCOMED_FILE = DATA_DIR / 'welcomed.json'
LOG_FILE = DATA_DIR / 'member_log.txt'

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

# Load config
if not CONFIG_PATH.exists():
    log(f"❌ Config file not found: {CONFIG_PATH}")
    sys.exit(1)

load_dotenv(CONFIG_PATH)

API_ID = os.getenv('API_ID', '').strip()
API_HASH = os.getenv('API_HASH', '').strip()
GROUP_ID = os.getenv('GROUP_ID', '').strip()
SESSION = os.getenv('SESSION', 'spectre_user')
WELCOME_MESSAGE = os.getenv('WELCOME_MESSAGE', 
    "👋 Welcome to ANUNNAKI OPS! I'm S.P.E.C.T.R.E., your AI trading companion. "
    "Ask me anything about signals, market analysis, or bot operations.")

# Validate config
if not API_ID or API_ID == 'your_api_id_here':
    log("❌ API_ID not set. Get it from https://my.telegram.org/apps")
    sys.exit(1)
if not API_HASH or API_HASH == 'your_api_hash_here':
    log("❌ API_HASH not set. Get it from https://my.telegram.org/apps")
    sys.exit(1)
if not GROUP_ID:
    log("❌ GROUP_ID not set")
    sys.exit(1)

# Convert to proper types
try:
    API_ID = int(API_ID)
except ValueError:
    log(f"❌ API_ID must be an integer, got: {API_ID}")
    sys.exit(1)

try:
    GROUP_ID = int(GROUP_ID)
except ValueError:
    log(f"❌ GROUP_ID must be an integer, got: {GROUP_ID}")
    sys.exit(1)

# Load state
def load_json(path, default=None):
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

known_members = load_json(MEMBERS_FILE, {})
welcomed_users = load_json(WELCOMED_FILE, [])

client = TelegramClient(BASE / SESSION, API_ID, API_HASH)

async def fetch_and_update_members():
    """Fetch current members and detect new ones."""
    global known_members
    
    log(f"👥 Fetching members of group {GROUP_ID}...")
    
    try:
        current_members = {}
        async for user in client.iter_participants(GROUP_ID, limit=None):
            current_members[str(user.id)] = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone': user.phone,
                'is_bot': user.bot,
                'joined': time.time(),
            }
        
        # Detect new members
        new_members = []
        for uid, data in current_members.items():
            if uid not in known_members:
                new_members.append(data)
        
        if new_members:
            log(f"🆕 {len(new_members)} new member(s) detected!")
            for m in new_members:
                name = m['first_name'] or m['username'] or f"User{m['id']}"
                log(f"   → New: {name} (ID: {m['id']})")
        else:
            log(f"✅ No new members (total: {len(current_members)})")
        
        # Save updated member list
        known_members = current_members
        save_json(MEMBERS_FILE, known_members)
        
        return new_members
        
    except ChatAdminRequiredError:
        log("❌ Need to be an admin to fetch members")
        return []
    except FloodWaitError as e:
        log(f"❌ Flood wait: {e.seconds}s")
        return []
    except Exception as e:
        log(f"❌ Error fetching members: {e}")
        return []

async def welcome_new_member(user_id, user_data):
    """Send welcome message to a new member."""
    try:
        user_id_int = int(user_id)
        
        # Check if already welcomed
        if user_id_int in welcomed_users:
            return
        
        # Get user info
        name = user_data.get('first_name') or user_data.get('username') or f"User{user_id}"
        
        # Personalize welcome
        welcome = f"👋 Welcome to ANUNNAKI OPS, **{name}**!\n\n{WELCOME_MESSAGE}"
        
        # Send welcome message
        await client.send_message(GROUP_ID, welcome)
        log(f"💌 Welcome sent to {name} (ID: {user_id})")
        
        # Track welcomed users
        welcomed_users.append(user_id_int)
        save_json(WELCOMED_FILE, welcomed_users)
        
    except Exception as e:
        log(f"❌ Failed to welcome {user_id}: {e}")

async def monitor_loop():
    """Continuous monitoring loop."""
    log("🔍 Starting member monitor...")
    log(f"   Group: {GROUP_ID}")
    log(f"   Known members: {len(known_members)}")
    log(f"   Previously welcomed: {len(welcomed_users)}")
    
    while True:
        try:
            new_members = await fetch_and_update_members()
            
            for member_data in new_members:
                await welcome_new_member(str(member_data['id']), member_data)
            
            # Wait before next check
            log("⏳ Sleeping 60s...")
            await asyncio.sleep(60)
            
        except Exception as e:
            log(f"❌ Monitor error: {e}")
            await asyncio.sleep(60)

async def initial_setup():
    """First run: establish session and show status."""
    log("🔌 Connecting to Telegram...")
    await client.connect()
    
    if not await client.is_user_authorized():
        log("📱 Authorization required")
        log("   You'll need to enter your phone number and verification code")
        await client.start()
    
    me = await client.get_me()
    log(f"✅ Connected as: {me.first_name} (@{me.username})")
    
    # Verify group access
    try:
        entity = await client.get_entity(GROUP_ID)
        log(f"✅ Group access: {entity.title}")
        return True
    except Exception as e:
        log(f"❌ Cannot access group {GROUP_ID}: {e}")
        return False

async def main():
    """Main entry point."""
    # Initial setup (login if needed)
    if not await initial_setup():
        return
    
    # Start monitoring
    await monitor_loop()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
