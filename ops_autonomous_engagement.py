#!/usr/bin/env python3
"""
Ops-specific autonomous engagement for Ops team
"""

import asyncio
import os
import sys
import random
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def send_ops_autonomous_engagement():
    """Send Ops-specific autonomous engagement message"""
    from telegram_chat_interface import CHAT_INTERFACE
    
    print('🔧 Sending Ops autonomous engagement message...')
    
    # Ops-specific engagement questions
    ops_engagement_questions = [
        "🔧 **Ops Team Check-in:**\n\nHow's the system running today? Any issues or improvements needed?\n\n📊 **Areas to discuss:**\n• 🐛 Bug reports or errors\n• ⚡ Performance optimizations\n• 🔍 Security concerns\n• 📈 System metrics\n• 🛠️ Maintenance tasks\n\nLet's keep everything running smoothly! 🚀",
        
        "🔧 **Technical Discussion:**\n\nWhat system component should we focus on improving next?\n\n🎯 **Priority Areas:**\n• 📊 Trading signal accuracy\n• ⚡ API performance\n• 🗄️ Database optimization\n• 🔍 Error handling\n• 📈 Monitoring systems\n\nYour input helps prioritize improvements! 💡",
        
        "🔧 **System Health Review:**\n\nQuick status check - how are things looking?\n\n✅ **Green:** Everything running smoothly\n🟡 **Yellow:** Minor issues to watch\n🔴 **Red:** Problems needing attention\n\nShare your observations and let's address any concerns! 📋",
        
        "🔧 **Ops Planning Session:**\n\nWhat improvements would you like to see in the next sprint?\n\n🚀 **Potential Enhancements:**\n• 🤖 AI automation features\n• 📊 Advanced analytics\n• 🔍 Better error tracking\n• ⚡ Performance boosts\n• 🛡️ Security upgrades\n\nLet's plan our next moves! 📅",
        
        "🔧 **Knowledge Sharing:**\n\nWhat's the most interesting technical challenge you've solved recently?\n\n💡 **Share your experience:**\n• 🐛 Bug fixes\n• ⚡ Optimizations\n• 🔍 Debugging wins\n• 📈 Performance gains\n• 🛡️ Security improvements\n\nLet's learn from each other! 🎓"
    ]
    
    # Choose random Ops question
    chosen_question = random.choice(ops_engagement_questions)
    
    # Send to Ops chat
    try:
        result = await CHAT_INTERFACE.send_message(
            chat_id='-1003706659588',  # Ops chat where AI communicates
            text=chosen_question,
            parse_mode='Markdown'
        )
        
        if result.get("success"):
            print(f'✅ Ops autonomous engagement sent successfully!')
            print(f'   Message ID: {result.get("message_id")}')
            print(f'   Question type: {chosen_question.split(":")[1].split("\n")[0] if ":" in chosen_question else "Ops General"}')
            return True
        else:
            print(f'❌ Failed to send Ops engagement message')
            return False
            
    except Exception as e:
        print(f'❌ Error sending Ops autonomous engagement: {e}')
        return False

async def schedule_ops_autonomous_engagement():
    """Schedule periodic Ops autonomous engagements"""
    print('🕐 Starting Ops autonomous engagement scheduler...')
    
    engagement_count = 0
    
    while True:
        try:
            current_hour = datetime.now().hour
            current_day = datetime.now().weekday()
            
            # Ops hours (8 AM - 8 PM UTC, weekdays only)
            if 8 <= current_hour <= 20 and current_day < 5:
                # Higher chance for Ops team (40% chance)
                if random.random() < 0.4:
                    print(f'🎯 Initiating Ops autonomous engagement #{engagement_count + 1}')
                    
                    success = await send_ops_autonomous_engagement()
                    
                    if success:
                        engagement_count += 1
                        print(f'📊 Total Ops engagements: {engagement_count}')
                    
                    # Wait 1-3 hours between Ops engagements (more frequent)
                    wait_time = random.randint(3600, 10800)  # 1-3 hours
                    print(f'⏰ Next Ops engagement in {wait_time/3600:.1f} hours')
                else:
                    # Check again in 20 minutes
                    wait_time = 1200
                    print(f'⏰ Checking Ops again in 20 minutes...')
            else:
                # Outside Ops hours, check every hour
                wait_time = 3600
                if current_hour < 8:
                    print(f'🌙 Too early for Ops engagement (current hour: {current_hour})')
                elif current_hour > 20:
                    print(f'🌙 Too late for Ops engagement (current hour: {current_hour})')
                else:
                    print(f'🎉 Weekend - Ops reduced engagement')
            
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f'❌ Error in Ops scheduler: {e}')
            await asyncio.sleep(1800)  # Wait 30 minutes on error

async def test_ops_autonomous_engagement():
    """Test immediate Ops autonomous engagement"""
    print('🧪 Testing immediate Ops autonomous engagement...')
    
    success = await send_ops_autonomous_engagement()
    
    if success:
        print('✅ Immediate Ops engagement test successful!')
        print('🎯 Ops scheduler ready to start periodic engagements')
    else:
        print('❌ Immediate Ops engagement test failed')
    
    return success

if __name__ == "__main__":
    # Test immediate engagement first
    success = asyncio.run(test_ops_autonomous_engagement())
    
    if success:
        print('\n🚀 Starting periodic Ops autonomous engagement scheduler...')
        print('Press Ctrl+C to stop')
        try:
            asyncio.run(schedule_ops_autonomous_engagement())
        except KeyboardInterrupt:
            print('\n🛑 Ops autonomous engagement stopped by user')
    else:
        print('\n❌ Fix issues before starting Ops scheduler')
