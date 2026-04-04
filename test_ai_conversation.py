#!/usr/bin/env python3
"""
Test AI conversation by analyzing a user message
"""

import asyncio
import os
import sys

async def test_ai_conversation():
    from telegram_chat_interface import CHAT_INTERFACE
    
    print('🤖 Testing AI conversation capabilities...')
    
    # Simulate a user asking about trading signals
    try:
        user_message = "What are the current trading signals for BTC?"
        user_id = 123456789  # Simulated user ID
        chat_id = '-1002209928687'
        
        result = await CHAT_INTERFACE.analyze_user_message(
            chat_id=chat_id,
            user_id=user_id,
            message_text=user_message
        )
        
        print(f'✅ User message analyzed: {result.get("success", False)}')
        
        if result.get("success"):
            ai_response = result.get("ai_response", "No response")
            print(f'\n🤖 AI Response:')
            print(f'   User asked: "{user_message}"')
            print(f'   AI replied: "{ai_response[:200]}..."')
            
            # Send the AI response to show it works
            send_result = await CHAT_INTERFACE.send_message(
                chat_id=chat_id,
                text=f'💬 **AI Response to User Question:**\n\nQ: {user_message}\n\nA: {ai_response}'
            )
            print(f'✅ AI response sent to chat: {send_result.get("success", False)}')
        
    except Exception as e:
        print(f'❌ Conversation test error: {e}')
    
    # Test another user question
    try:
        user_message2 = "How does the Monte Carlo simulation work?"
        
        result2 = await CHAT_INTERFACE.analyze_user_message(
            chat_id=chat_id,
            user_id=123456789,
            message_text=user_message2
        )
        
        print(f'✅ Second message analyzed: {result2.get("success", False)}')
        
        if result2.get("success"):
            ai_response2 = result2.get("ai_response", "No response")
            print(f'\n🤖 Second AI Response:')
            print(f'   User asked: "{user_message2}"')
            print(f'   AI replied: "{ai_response2[:200]}..."')
        
    except Exception as e:
        print(f'❌ Second conversation test error: {e}')
    
    print('\n🎯 AI conversation testing completed!')

if __name__ == "__main__":
    asyncio.run(test_ai_conversation())
