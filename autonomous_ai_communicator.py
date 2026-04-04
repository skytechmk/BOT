#!/usr/bin/env python3
"""
AI Autonomous Communication - Random member engagement
"""

import asyncio
import os
import sys
import random
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class AutonomousAICommunicator:
    """AI that initiates conversations with random group members"""
    
    def __init__(self):
        self.last_engagement_time = {}
        self.engagement_interval = 3600  # 1 hour between engagements
        self.engaged_members = set()
        
    async def get_random_member(self, chat_id):
        """Get a random active member from the group"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            from telegram_group_manager import GROUP_MANAGER
            
            # Get chat info and member count
            chat_info = await GROUP_MANAGER.get_chat_info(chat_id)
            if not chat_info.get("success"):
                return None
            
            member_count = chat_info.get("member_count", 0)
            if member_count < 10:  # Don't engage in very small groups
                return None
            
            # Try to get a random member (simplified approach)
            # In real implementation, you'd get member list
            # For now, we'll simulate with a random ID range
            random_member_id = random.randint(100000000, 999999999)
            
            return {
                'user_id': random_member_id,
                'chat_id': chat_id,
                'engagement_time': datetime.now()
            }
            
        except Exception as e:
            print(f"Error getting random member: {e}")
            return None
    
    async def generate_engagement_message(self, member_context):
        """Generate personalized engagement message"""
        engagement_types = [
            "trading_help",
            "market_question", 
            "technical_assistance",
            "general_checkin",
            "signal_inquiry"
        ]
        
        chosen_type = random.choice(engagement_types)
        
        messages = {
            "trading_help": [
                "Hey! I noticed you're active in our trading group. Are you looking for any specific trading insights or help with analysis?",
                "Hi there! I'm the AI assistant for this group. Anything about trading signals or market analysis you'd like to discuss?",
                "Hello! I'm here to help with trading questions. What markets are you currently following?"
            ],
            "market_question": [
                "Quick market check: What's your take on the current BTC movement? Bullish or bearish?",
                "Market sentiment question: Which altcoin do you think has the most potential right now?",
                "Trading strategy question: Are you more of a day trader or long-term holder?"
            ],
            "technical_assistance": [
                "Hey! Need help with any technical indicators or chart analysis?",
                "Hi! I can help with trading bot setup or signal interpretation. Anything you're stuck on?",
                "Hello! Having any issues with the trading system or need technical guidance?"
            ],
            "general_checkin": [
                "Hey! How's your trading going today? Any wins or lessons learned?",
                "Hi there! Just checking in - how are you finding the trading signals lately?",
                "Hello! What's been your most interesting trading experience this week?"
            ],
            "signal_inquiry": [
                "Hey! Are you finding our trading signals helpful? Any feedback or suggestions?",
                "Hi there! Have you been following our recent signals? How's the performance?",
                "Hello! I'd love to hear your thoughts on our signal accuracy and timing."
            ]
        }
        
        return random.choice(messages[chosen_type])
    
    async def engage_random_member(self, chat_id):
        """Engage a random member in conversation"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Check if enough time has passed since last engagement
            current_time = time.time()
            if chat_id in self.last_engagement_time:
                if current_time - self.last_engagement_time[chat_id] < self.engagement_interval:
                    return {"success": False, "reason": "Too soon since last engagement"}
            
            # Get random member
            member = await self.get_random_member(chat_id)
            if not member:
                return {"success": False, "reason": "No suitable member found"}
            
            # Check if we've recently engaged this member
            member_key = f"{chat_id}_{member['user_id']}"
            if member_key in self.engaged_members:
                return {"success": False, "reason": "Member recently engaged"}
            
            # Generate engagement message
            message = await self.generate_engagement_message(member)
            
            # Send message (this would normally be a direct message, but we'll send to group)
            result = await CHAT_INTERFACE.send_message(
                chat_id=chat_id,
                text=f"🤖 **AI Random Engagement**\n\n{message}\n\n*This is an automated engagement to foster community discussion!*",
                parse_mode='Markdown'
            )
            
            if result.get("success"):
                # Update tracking
                self.last_engagement_time[chat_id] = current_time
                self.engaged_members.add(member_key)
                
                # Clean up old engagements (keep only last 50)
                if len(self.engaged_members) > 50:
                    self.engaged_members = set(list(self.engaged_members)[-40:])
                
                return {
                    "success": True,
                    "member_id": member['user_id'],
                    "chat_id": chat_id,
                    "message": message,
                    "engagement_time": datetime.now().isoformat()
                }
            else:
                return {"success": False, "reason": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "reason": str(e)}
    
    async def start_autonomous_engagement(self):
        """Start the autonomous engagement loop"""
        print('🤖 Starting AI autonomous engagement system...')
        
        # Main trading group
        main_chat = '-1002209928687'
        ops_chat = '-1003706659588'
        
        while True:
            try:
                current_hour = datetime.now().hour
                
                # Only engage during active hours (8 AM - 10 PM UTC)
                if 8 <= current_hour <= 22:
                    # Random chance to engage (30% chance each check)
                    if random.random() < 0.3:
                        # Choose which chat to engage
                        chat_to_engage = random.choice([main_chat, ops_chat])
                        
                        print(f"🎯 Attempting autonomous engagement in {chat_to_engage}")
                        result = await self.engage_random_member(chat_to_engage)
                        
                        if result.get("success"):
                            print(f"✅ Successfully engaged member {result['member_id']}")
                            print(f"   Message: {result['message'][:100]}...")
                        else:
                            print(f"❌ Engagement failed: {result['reason']}")
                
                # Wait before next check (30 minutes)
                await asyncio.sleep(1800)  # 30 minutes
                
            except Exception as e:
                print(f"❌ Error in autonomous engagement: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error

# Global instance
AUTONOMOUS_COMMUNICATOR = AutonomousAICommunicator()

async def test_autonomous_engagement():
    """Test the autonomous engagement system"""
    print('🧪 Testing AI autonomous engagement...')
    
    # Test engagement
    result = await AUTONOMOUS_COMMUNICATOR.engage_random_member('-1002209928687')
    
    if result.get("success"):
        print(f'✅ Test engagement successful:')
        print(f'   Member ID: {result["member_id"]}')
        print(f'   Chat: {result["chat_id"]}')
        print(f'   Message: {result["message"]}')
        print(f'   Time: {result["engagement_time"]}')
    else:
        print(f'❌ Test engagement failed: {result["reason"]}')
    
    return result

if __name__ == "__main__":
    # Run test
    asyncio.run(test_autonomous_engagement())
