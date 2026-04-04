import asyncio
import os
from dotenv import load_dotenv

# Load all constants and environment parameters
load_dotenv("/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env")

from utils_logger import log_message, clear_console
from telegram_handler import setup_telegram_listener

async def main():
    clear_console()
    log_message("Starting Dedicated Telegram Microservice...")
    
    app = await setup_telegram_listener()
    if not app:
        log_message("Failed to initialize Telegram listener. Missing Tokens?")
        return
        
    log_message("Telegram Service is ONLINE and polling independently.")
    
    # Keep the asyncio event loop alive indefinitely so Telegram polling runs
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log_message(f"Telegram Service encountered an error: {e}")
    finally:
        log_message("Telegram Service gracefully shutting down...")
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_message("Operator terminated Telegram Service.")
