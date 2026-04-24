import asyncio
import os
import sys
import time
from telegram import Bot
from telegram.error import Forbidden, RetryAfter, BadRequest
from dotenv import load_dotenv

# Load credentials
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip("'\"")
# TARGET_CHAT = os.getenv('TELEGRAM_CHAT_ID', '').strip("'\"") # Default: Main Channel
TARGET_CHAT = "-1002209928687" # Hardcoded for safety during this specific request

async def clear_channel(depth=2000):
    if not TELEGRAM_TOKEN or not TARGET_CHAT:
        print("❌ Error: Missing Telegram Token or Chat ID.")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    
    print(f"🚀 Initiating cleanup for chat {TARGET_CHAT} (Depth: {depth})...")
    
    # 1. Send a sentinel message to find the "current" high ID
    try:
        sentinel = await bot.send_message(chat_id=TARGET_CHAT, text="🧹 **INITIATING CHANNEL CLEANUP**\n*Suppressing recent noise...*")
        start_id = sentinel.message_id
        print(f"✅ Sentinel message sent. Starting from ID: {start_id}")
    except Exception as e:
        print(f"❌ Failed to send sentinel: {e}")
        return

    deleted_count = 0
    failed_count = 0
    forbidden_count = 0

    # 2. Iterate backwards
    for msg_id in range(start_id, start_id - depth, -1):
        try:
            await bot.delete_message(chat_id=TARGET_CHAT, message_id=msg_id)
            deleted_count += 1
            if deleted_count % 10 == 0:
                 print(f"🧹 Deleted {deleted_count} messages...")
            # Slight delay to avoid immediate flood limits
            await asyncio.sleep(0.05)
            
        except RetryAfter as e:
            print(f"🛑 Rate limit hit. Sleeping for {e.retry_after} seconds...")
            await asyncio.sleep(e.retry_after)
            # Retry this ID
            try:
                await bot.delete_message(chat_id=TARGET_CHAT, message_id=msg_id)
                deleted_count += 1
            except:
                pass
                
        except Forbidden:
            # Likely too old (> 48h) or bot lacks permissions
            forbidden_count += 1
            if forbidden_count < 5: # Only log first few
                 print(f"⚠️ ID {msg_id}: Forbidden (Too old or no permission)")
        
        except BadRequest as b:
            # Likely already deleted or non-existent ID
            failed_count += 1
            # print(f"ℹ️ ID {msg_id}: Bad Request ({b})")

    print("\n" + "="*30)
    print(f"✨ CLEANUP COMPLETE")
    print(f"✅ Successfully deleted: {deleted_count}")
    print(f"⚠️ Forbidden (too old):  {forbidden_count}")
    print(f"ℹ️ Already deleted/empty: {failed_count}")
    print("="*30)

if __name__ == "__main__":
    depth_val = 1000 # Default depth
    if len(sys.argv) > 1:
        try:
            depth_val = int(sys.argv[1])
        except:
            pass
            
    asyncio.run(clear_channel(depth=depth_val))
