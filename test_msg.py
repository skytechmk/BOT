import asyncio
from telegram_handler import send_telegram_message

msg = '''🛑 **TRAILING STOP HIT** 💰
Duration: 1.5 hours

import sys
import logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

if __name__ == '__main__':
    asyncio.run(send_telegram_message(msg))
