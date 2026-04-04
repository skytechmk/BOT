#!/usr/bin/env python3
"""
Test AI conversation with Ops team members - simulate real questions
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_ops_conversation():
    from telegram_chat_interface import CHAT_INTERFACE
    
    print('🤖 Testing AI conversation with Ops team...')
    
    # Simulate Ops team member asking about code audit
    try:
        ops_question1 = "Can you run a security audit on the main.py file?"
        ops_user_id = 999888777  # Simulated ops user
        chat_id = '-1003706659588'
        
        result1 = await CHAT_INTERFACE.analyze_user_message(
            chat_id=chat_id,
            user_id=ops_user_id,
            message_text=ops_question1
        )
        
        print(f'✅ Ops question 1 analyzed: {result1.get("success", False)}')
        
        if result1.get("success"):
            ai_response1 = result1.get("ai_response", "No response")
            print(f'\n🤖 AI Response to Ops:')
            print(f'   Ops asked: "{ops_question1}"')
            print(f'   AI replied: "{ai_response1[:200]}..."')
            
            # Send the AI response to show it works
            send_result1 = await CHAT_INTERFACE.send_message(
                chat_id=chat_id,
                text=f'💬 **AI Response to Ops Question:**\n\nQ: {ops_question1}\n\nA: {ai_response1}'
            )
            print(f'✅ AI response sent to Ops: {send_result1.get("success", False)}')
        
    except Exception as e:
        print(f'❌ Ops conversation test 1 error: {e}')
    
    # Simulate another Ops question about performance
    try:
        ops_question2 = "What's the current system performance and any bottlenecks?"
        
        result2 = await CHAT_INTERFACE.analyze_user_message(
            chat_id=chat_id,
            user_id=ops_user_id,
            message_text=ops_question2
        )
        
        print(f'✅ Ops question 2 analyzed: {result2.get("success", False)}')
        
        if result2.get("success"):
            ai_response2 = result2.get("ai_response", "No response")
            print(f'\n🤖 Second AI Response to Ops:')
            print(f'   Ops asked: "{ops_question2}"')
            print(f'   AI replied: "{ai_response2[:200]}..."')
        
    except Exception as e:
        print(f'❌ Ops conversation test 2 error: {e}')
    
    # Simulate Ops asking about trading signals
    try:
        ops_question3 = "How accurate are our current trading signals?"
        
        result3 = await CHAT_INTERFACE.analyze_user_message(
            chat_id=chat_id,
            user_id=ops_user_id,
            message_text=ops_question3
        )
        
        print(f'✅ Ops question 3 analyzed: {result3.get("success", False)}')
        
        if result3.get("success"):
            ai_response3 = result3.get("ai_response", "No response")
            print(f'\n🤖 Third AI Response to Ops:')
            print(f'   Ops asked: "{ops_question3}"')
            print(f'   AI replied: "{ai_response3[:200]}..."')
        
    except Exception as e:
        print(f'❌ Ops conversation test 3 error: {e}')
    
    print('\n🎯 Ops conversation testing completed!')

if __name__ == "__main__":
    asyncio.run(test_ops_conversation())
