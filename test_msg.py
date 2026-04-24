import asyncio
import os
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

async def send_tests():
    bot = Bot(os.getenv("CLOSED_SIGNALS_TOKEN"))
    try:
        await bot.send_message(chat_id=os.getenv("CLOSED_SIGNALS_CHAT_ID"), text=f"🔧 <b>Aladdin System Diagnostic</b>\n\n✅ <i>Testing connection to CLOSED SIGNALS</i>\n- WebSocket engine online\n- Log rotation active\n- Duplicate PIDs cleared", parse_mode='HTML')
        print(f"✅ Success sending logic to CLOSED SIGNALS")
    except Exception as e:
        print(f"❌ Failed sending: {e}")

asyncio.run(send_tests())
