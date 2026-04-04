#!/usr/bin/env python3
"""
AI Random Member Tagger - Enable AI to tag random Ops team members
"""

import asyncio
import os
import sys
import random
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class RandomMemberTagger:
    """AI that can tag random Ops team members for communication"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.known_ops_members = [
            # Common Ops team usernames (can be updated)
            "admin",
            "ops_manager", 
            "tech_lead",
            "dev_ops",
            "trading_analyst",
            "system_admin",
            "security_lead",
            "data_analyst"
        ]
        self.tagged_history = []
        self.communication_attempts = 0
        
    def get_random_member(self):
        """Get a random Ops team member to tag"""
        # Filter out recently tagged members to avoid repetition
        available_members = [m for m in self.known_ops_members 
                            if m not in self.tagged_history[-3:]]  # Avoid last 3
        
        if available_members:
            return random.choice(available_members)
        else:
            # If all members were recently tagged, pick any
            return random.choice(self.known_ops_members)
    
    async def tag_random_member(self, conversation_type="general"):
        """Tag a random Ops team member and start conversation"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Get random member
            target_member = self.get_random_member()
            
            # Create member-specific messages (without @ to avoid parsing issues)
            messages = {
                "general": [
                    f"👋 Hey {target_member}! I'd love to get your thoughts on our current trading system performance!\n\n📊 **Quick questions for you:**\n• How are the signals working from your perspective?\n• Any system issues you've noticed?\n• What improvements would you suggest?\n\n💬 Your feedback helps me serve the team better!",
                    
                    f"🤖 Random check-in {target_member}! How's your day going with the trading operations?\n\n🔍 **I'm here to help with:**\n• Trading signal analysis\n• System diagnostics\n• Performance optimization\n• Technical support\n\n💬 What's on your mind today?",
                    
                    f"📈 Time for a quick strategy discussion {target_member}! What's your take on our current market approach?\n\n🎯 **Topics:**\n• Signal accuracy\n• Risk management\n• System performance\n• Market conditions\n\n💭 Share your insights!"
                ],
                
                "technical": [
                    f"🔧 Technical support check-in {target_member}! Any system issues I can help with today?\n\n🛠️ **I can assist with:**\n• Bot performance issues\n• API connectivity problems\n• Signal delays\n• System diagnostics\n• Error troubleshooting\n\n💬 What technical challenges are you facing?",
                    
                    f"⚡ System optimization time {target_member}! How's the trading system performing for you?\n\n📊 **Areas I can improve:**\n• Signal processing speed\n• Data accuracy\n• Error reduction\n• Performance monitoring\n\n💬 What needs optimization in your workflow?",
                    
                    f"🔍 Diagnostics session {target_member}! Let me check if everything is running smoothly for you.\n\n🔧 **System health check:**\n• Signal generation status\n• Market data connectivity\n• API response times\n• Error rates\n\n💬 Any issues or everything looking good?"
                ],
                
                "trading": [
                    f"📈 Trading analysis session {target_member}! What's your current market analysis?\n\n💹 **Let's discuss:**\n• Current signal performance\n• Market trends you're seeing\n• Trading strategy adjustments\n• Risk management approaches\n\n💬 Share your market insights!",
                    
                    f"🎯 Signal performance review {target_member}! How are our trading signals working from your perspective?\n\n📊 **Discussion points:**\n• Signal accuracy rates\n• Entry/exit timing\n• Market conditions impact\n• Improvement suggestions\n\n💬 What's your experience been?",
                    
                    f"💰 Risk management check {target_member}! What's your approach to current market volatility?\n\n⚖️ **Topics:**\n• Position sizing strategies\n• Stop-loss placement\n• Market risk assessment\n• Portfolio diversification\n\n💬 How are you managing risk?"
                ],
                
                "feedback": [
                    f"⭐ Feedback time {target_member}! How can I improve my assistance to the Ops team?\n\n🗣️ **I'd love your thoughts on:**\n• AI response quality\n• Technical support effectiveness\n• Trading analysis usefulness\n• Communication style\n\n💬 Your feedback helps me serve you better!",
                    
                    f"📋 User experience check {target_member}! How's your experience with our AI systems?\n\n📊 **Rate your satisfaction:**\n• Signal quality: 1-5\n• Response speed: 1-5\n• Technical help: 1-5\n• Overall experience: 1-5\n\n💬 What would make it better?",
                    
                    f"🚀 Feature request time {target_member}! What new capabilities would help you most?\n\n💡 **Potential improvements:**\n• Better signal analysis\n• Faster diagnostics\n• More detailed reports\n• Automated monitoring\n\n💬 What features do you need?"
                ]
            }
            
            # Select random message from the chosen type
            chosen_messages = messages.get(conversation_type, messages["general"])
            message = random.choice(chosen_messages)
            
            # Send to Ops chat
            result = await CHAT_INTERFACE.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            
            if result.get("success"):
                # Track this tagging
                self.tagged_history.append(target_member)
                self.communication_attempts += 1
                
                tag_id = f"tag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                return {
                    "success": True,
                    "action": "random_member_tagged",
                    "tagged_member": target_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "tag_id": tag_id,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def tag_multiple_members(self, count=2, conversation_type="general"):
        """Tag multiple random members for broader engagement"""
        results = []
        
        for i in range(count):
            result = await self.tag_random_member(conversation_type)
            results.append(result)
            
            # Small delay between messages
            await asyncio.sleep(2)
        
        return {
            "success": True,
            "action": "multiple_members_tagged",
            "count": count,
            "conversation_type": conversation_type,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_tagging_stats(self):
        """Get statistics about member tagging"""
        return {
            "total_attempts": self.communication_attempts,
            "tagged_members": self.tagged_history,
            "unique_members_tagged": len(set(self.tagged_history)),
            "most_tagged": max(set(self.tagged_history), key=self.tagged_history.count) if self.tagged_history else None,
            "available_members": self.known_ops_members,
            "chat_id": self.chat_id
        }
    
    def add_known_member(self, username):
        """Add a new known Ops team member"""
        if username not in self.known_ops_members:
            self.known_ops_members.append(username)
            return True
        return False
    
    def update_known_members(self, member_list):
        """Update the known members list"""
        self.known_ops_members = list(set(member_list))
        return len(self.known_ops_members)

# Global instance
RANDOM_MEMBER_TAGGER = RandomMemberTagger()

# MCP functions for random member tagging
async def tag_random_member(conversation_type="general"):
    """MCP function to tag random Ops team member"""
    try:
        result = await RANDOM_MEMBER_TAGGER.tag_random_member(conversation_type)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "random_member_tagged",
                "tagged_member": result["tagged_member"],
                "conversation_type": conversation_type,
                "chat_id": "-1003706659588",
                "message_id": result.get("message_id"),
                "timestamp": datetime.now().isoformat()
            }, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error", "Unknown error")
            }, indent=2)
            
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def tag_multiple_members(count=2, conversation_type="general"):
    """MCP function to tag multiple random Ops team members"""
    try:
        result = await RANDOM_MEMBER_TAGGER.tag_multiple_members(count, conversation_type)
        
        return json.dumps({
            "success": result.get("success", False),
            "action": "multiple_members_tagged",
            "count": count,
            "conversation_type": conversation_type,
            "results": result.get("results", []),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🎯 Random Member Tagger Ready")
    print("=" * 50)
    
    async def test_random_tagging():
        print("🧪 Testing random member tagging...")
        
        # Test single member tagging
        result = await RANDOM_MEMBER_TAGGER.tag_random_member("technical")
        
        if result.get("success"):
            print(f"✅ Successfully tagged @{result['tagged_member']}!")
            print(f"   Conversation type: {result['conversation_type']}")
            print(f"   Message ID: {result.get('message_id')}")
        else:
            print(f"❌ Error: {result.get('error')}")
        
        # Test multiple member tagging
        print("\n🧪 Testing multiple member tagging...")
        result2 = await RANDOM_MEMBER_TAGGER.tag_multiple_members(2, "general")
        
        if result2.get("success"):
            print(f"✅ Tagged {result2['count']} members!")
            for i, res in enumerate(result2.get("results", []), 1):
                if res.get("success"):
                    print(f"   {i}. @{res.get('tagged_member', 'unknown')}")
        else:
            print(f"❌ Error: {result2.get('error')}")
        
        # Show stats
        stats = RANDOM_MEMBER_TAGGER.get_tagging_stats()
        print(f"\n📊 Tagging Stats: {stats}")
    
    asyncio.run(test_random_tagging())
