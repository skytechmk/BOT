#!/usr/bin/env python3
"""
Start AI conversations with users in Telegram groups
"""

import asyncio
import os
import sys

async def start_conversations():
    from telegram_chat_interface import CHAT_INTERFACE
    
    print('🗣️ Starting AI conversations with users...')
    
    # Start conversation in main trading group
    try:
        result = await CHAT_INTERFACE.start_conversation(
            chat_id='-1002209928687',  # Main trading group
            greeting='👋 Hello everyone! I\'m AI assistant for the Aladdin trading bot. I can help you with:\n\n• 📊 Market analysis\n• 💰 Trading signals\n• 📈 Technical indicators\n• ❓ Bot questions\n\nHow can I assist you today?'
        )
        print(f'✅ Main group conversation: {result.get("success", False)}')
        if result.get("success"):
            print(f'   Message ID: {result.get("message_id")}')
    except Exception as e:
        print(f'❌ Main group error: {e}')
    
    # Start conversation in ops channel
    try:
        result = await CHAT_INTERFACE.start_conversation(
            chat_id='-1003706659588',  # Ops channel
            greeting='🔧 Ops Team - AI assistant ready! I can help with:\n\n• 📊 Code audits\n• 🛠️ System diagnostics\n• 📈 Performance analysis\n• 🔍 Error troubleshooting\n\nWhat do you need help with?'
        )
        print(f'✅ Ops channel conversation: {result.get("success", False)}')
        if result.get("success"):
            print(f'   Message ID: {result.get("message_id")}')
    except Exception as e:
        print(f'❌ Ops channel error: {e}')
    
    # Start conversation in closed signals channel
    try:
        result = await CHAT_INTERFACE.start_conversation(
            chat_id='-1002664177259',  # Closed signals channel
            greeting='📡 Signals Channel - AI online! I can provide:\n\n• 📊 Signal analysis\n• 📈 Market context\n• 💡 Trading insights\n• 📋 Performance stats\n\nAsk me anything about signals!'
        )
        print(f'✅ Signals channel conversation: {result.get("success", False)}')
        if result.get("success"):
            print(f'   Message ID: {result.get("message_id")}')
    except Exception as e:
        print(f'❌ Signals channel error: {e}')
    
    print('\n🎯 Conversations initiated in all channels!')
    
    # Send a follow-up message with interactive buttons
    try:
        buttons = [
            [{"text": "📊 Market Analysis", "callback_data": "market_analysis"}],
            [{"text": "💰 Trading Signals", "callback_data": "trading_signals"}],
            [{"text": "🔍 Bot Status", "callback_data": "bot_status"}],
            [{"text": "❓ Help", "callback_data": "help"}]
        ]
        
        result = await CHAT_INTERFACE.send_inline_keyboard(
            chat_id='-1002209928687',
            text='🤖 What would you like to know?',
            buttons=buttons
        )
        print(f'✅ Interactive buttons sent: {result.get("success", False)}')
    except Exception as e:
        print(f'❌ Buttons error: {e}')

if __name__ == "__main__":
    asyncio.run(start_conversations())
