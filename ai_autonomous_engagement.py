#!/usr/bin/env python3
"""
AI Autonomous Communication - Improved random member engagement
"""

import asyncio
import os
import sys
import random
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def send_autonomous_engagement():
    """Send autonomous engagement message to group"""
    from telegram_chat_interface import CHAT_INTERFACE
    
    print('🤖 Sending AI autonomous engagement message...')
    
    # Generate engaging question
    engagement_questions = [
        "🤖 **AI Community Question:**\n\nWhat trading strategies are you most excited about right now?\n\n📊 Share your thoughts:\n• 📈 Technical Analysis\n• 💰 Risk Management\n• 🔍 Market Psychology\n• ⚡ Algorithmic Trading\n• 📚 Fundamental Analysis\n\nI'll create detailed guides based on your interests! 🚀",
        
        "🤖 **Market Discussion Time:**\n\nQuick poll: What's your current market outlook?\n\n🟢 **Bullish** - Expecting upward movement\n🔴 **Bearish** - Expecting downward movement\n🟡 **Neutral** - Waiting for clarity\n\nShare your reasoning and let's discuss! 💭",
        
        "🤖 **Trading Experience Check:**\n\nHow long have you been trading?\n\n🌟 **Newbie** (0-6 months)\n⭐ **Beginner** (6 months-2 years)\n🌠 **Intermediate** (2-5 years)\n⭐ **Advanced** (5+ years)\n\nI'd love to tailor my insights to your experience level! 📚",
        
        "🤖 **Signal Feedback Request:**\n\nHow are you finding our trading signals lately?\n\n✅ **Great** - Very helpful!\n👍 **Good** - Mostly accurate\n😐 **Okay** - Hit or miss\n👎 **Poor** - Need improvement\n\nYour feedback helps me improve! 🎯",
        
        "🤖 **Learning Opportunity:**\n\nWhat trading topic would you like me to explain?\n\n📈 **Chart Patterns**\n💹 **Indicators**\n⚖️ **Risk Management**\n🔍 **Market Analysis**\n🤖 **AI in Trading**\n\nI'll create a detailed explanation! 📚"
    ]
    
    # Choose random question
    chosen_question = random.choice(engagement_questions)
    
    # Send to Ops chat (not channel)
    try:
        result = await CHAT_INTERFACE.send_message(
            chat_id='-1003706659588',  # Ops chat where AI communicates
            text=chosen_question,
            parse_mode='Markdown'
        )
        
        if result.get("success"):
            print(f'✅ Autonomous engagement sent successfully!')
            print(f'   Message ID: {result.get("message_id")}')
            print(f'   Question type: {chosen_question.split(":")[1].split("\n")[0] if ":" in chosen_question else "General"}')
            return True
        else:
            print(f'❌ Failed to send engagement message')
            return False
            
    except Exception as e:
        print(f'❌ Error sending autonomous engagement: {e}')
        return False

async def schedule_autonomous_engagement():
    """Schedule periodic autonomous engagements"""
    print('🕐 Starting autonomous engagement scheduler...')
    
    engagement_count = 0
    
    # Ops chat only (where AI communicates with Ops team)
    ops_chat = '-1003706659588'
    
    while True:
        try:
            current_hour = datetime.now().hour
            
            # Only engage during Ops hours (9 AM - 8 PM UTC)
            if 9 <= current_hour <= 20:
                # Random chance to engage (25% chance each check)
                if random.random() < 0.25:
                    print(f"🎯 Attempting autonomous engagement in Ops chat {ops_chat}")
                    success = await send_autonomous_engagement()
                    
                    if success:
                        engagement_count += 1
                        print(f'📊 Total autonomous engagements: {engagement_count}')
                    
                # Wait 2-4 hours between engagements
                wait_time = random.randint(7200, 14400)  # 2-4 hours
                print(f'⏰ Next engagement in {wait_time/3600:.1f} hours')
                    # Check again in 30 minutes
                    wait_time = 1800
                    print(f'⏰ Checking again in 30 minutes...')
            else:
                # Outside active hours, check every hour
                wait_time = 3600
                if current_hour < 9:
                    print(f'🌙 Too early for engagement (current hour: {current_hour})')
                elif current_hour > 21:
                    print(f'🌙 Too late for engagement (current hour: {current_hour})')
                else:
                    print(f'🎉 Weekend - reduced engagement')
            
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f'❌ Error in scheduler: {e}')
            await asyncio.sleep(1800)  # Wait 30 minutes on error

async def test_immediate_engagement():
    """Test immediate autonomous engagement"""
    print('🧪 Testing immediate autonomous engagement...')
    
    success = await send_autonomous_engagement()
    
    if success:
        print('✅ Immediate engagement test successful!')
        print('🎯 Scheduler ready to start periodic engagements')
    else:
        print('❌ Immediate engagement test failed')
    
    return success

if __name__ == "__main__":
    # Test immediate engagement first
    success = asyncio.run(test_immediate_engagement())
    
    if success:
        print('\n🚀 Starting periodic autonomous engagement scheduler...')
        print('Press Ctrl+C to stop')
        try:
            asyncio.run(schedule_autonomous_engagement())
        except KeyboardInterrupt:
            print('\n🛑 Autonomous engagement stopped by user')
    else:
        print('\n❌ Fix issues before starting scheduler')
