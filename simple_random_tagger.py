#!/usr/bin/env python3
"""
Simple Random Member Tagger - No Markdown formatting issues
"""

import asyncio
import os
import sys
import random
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class SimpleRandomMemberTagger:
    """Simple AI that can tag random Ops team members without formatting issues"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.known_ops_members = [
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
        
    def get_random_member(self):
        """Get a random Ops team member to tag"""
        available_members = [m for m in self.known_ops_members 
                            if m not in self.tagged_history[-3:]]
        
        if available_members:
            return random.choice(available_members)
        else:
            return random.choice(self.known_ops_members)
    
    async def tag_random_member_simple(self, conversation_type="general"):
        """Tag random member with simple text message"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            target_member = self.get_random_member()
            
            # Simple messages without formatting
            messages = {
                "general": [
                    f"Hey {target_member}! Random check-in from AI assistant. How's your day going with the trading operations? I'm here to help with trading signals, system diagnostics, and technical support. What do you need assistance with today?",
                    
                    f"Hi {target_member}! AI assistant here. I'd love to get your thoughts on our current trading system performance. How are the signals working from your perspective? Any system issues or improvements you'd suggest?",
                    
                    f"Hello {target_member}! Time for a quick strategy discussion. What's your take on our current market approach? I can help with signal analysis, risk management, and system optimization. Share your insights!"
                ],
                
                "technical": [
                    f"Technical support check-in {target_member}! Any system issues I can help with today? I can assist with bot performance, API connectivity, signal delays, and system diagnostics. What technical challenges are you facing?",
                    
                    f"System optimization time {target_member}! How's the trading system performing for you? I can help improve signal processing speed, data accuracy, and performance monitoring. What needs optimization in your workflow?",
                    
                    f"Diagnostics session {target_member}! Let me check if everything is running smoothly for you. I can monitor signal generation, market data connectivity, and API response times. Any issues or everything looking good?"
                ],
                
                "trading": [
                    f"Trading analysis session {target_member}! What's your current market analysis? I can help with signal performance, market trends, trading strategies, and risk management. Share your market insights!",
                    
                    f"Signal performance review {target_member}! How are our trading signals working from your perspective? I can analyze accuracy rates, entry/exit timing, and market conditions. What's your experience been?",
                    
                    f"Risk management check {target_member}! What's your approach to current market volatility? I can help with position sizing, stop-loss placement, and portfolio diversification. How are you managing risk?"
                ]
            }
            
            chosen_messages = messages.get(conversation_type, messages["general"])
            message = random.choice(chosen_messages)
            
            # Send without parse_mode to avoid formatting issues
            result = await CHAT_INTERFACE.send_message(
                chat_id=self.chat_id,
                text=message
            )
            
            if result.get("success"):
                self.tagged_history.append(target_member)
                
                return {
                    "success": True,
                    "action": "random_member_tagged",
                    "tagged_member": target_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}

# Global instance
SIMPLE_RANDOM_TAGGER = SimpleRandomMemberTagger()

# MCP function
async def tag_random_member_simple(conversation_type="general"):
    """MCP function to tag random Ops team member with simple message"""
    try:
        result = await SIMPLE_RANDOM_TAGGER.tag_random_member_simple(conversation_type)
        
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

if __name__ == "__main__":
    print("🎯 Simple Random Member Tagger Ready")
    print("=" * 50)
    
    async def test_simple_tagging():
        print("🧪 Testing simple random member tagging...")
        
        result = await SIMPLE_RANDOM_TAGGER.tag_random_member_simple("technical")
        
        if result.get("success"):
            print(f"✅ Successfully tagged {result['tagged_member']}!")
            print(f"   Conversation type: {result['conversation_type']}")
            print(f"   Message ID: {result.get('message_id')}")
            print(f"   Message: {result['message'][:100]}...")
        else:
            print(f"❌ Error: {result.get('error')}")
    
    asyncio.run(test_simple_tagging())
