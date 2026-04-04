#!/usr/bin/env python3
"""
AI Member Communication - Enable AI to talk to specific Ops group members
"""

import asyncio
import os
import sys
import random
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class OpsMemberCommunicator:
    """AI that can communicate with Ops group members without needing member list"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.engagement_history = {}
        self.communication_methods = [
            "general_question",
            "technical_help", 
            "system_status",
            "trading_discussion",
            "feedback_request"
        ]
        
    async def get_available_members(self):
        """Get available members through group info"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            # Get chat info to see if we can access member count
            chat_info = await GROUP_MANAGER.get_chat_info(self.chat_id)
            
            if chat_info.get("success"):
                member_count = chat_info.get("member_count", 0)
                return {
                    "success": True,
                    "member_count": member_count,
                    "chat_id": self.chat_id,
                    "method": "group_info"
                }
            else:
                return {"success": False, "error": "Cannot access group info"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def send_member_directed_message(self, member_identifier=None):
        """Send message directed at a specific member (by mention or general)"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Generate engagement type
            engagement_type = random.choice(self.communication_methods)
            
            # Create member-directed messages
            messages = {
                "general_question": [
                    "🤖 **Ops Team Member Check-in**\n\nHey team member! 👋\n\nHow's your day going with the trading systems?\n\n📊 **Quick questions:**\n• Any issues with signal performance?\n• System running smoothly?\n• Need help with any technical aspects?\n\nI'm here to help with trading signals, system diagnostics, or technical support!\n\n💬 **Reply with your username** and let me know how I can assist!",
                    
                    "🤖 **Ops Team Discussion**\n\nHello Ops team member! 👋\n\nI'd love to hear your thoughts on our current trading strategy:\n\n📈 **Discussion Topics:**\n• Signal accuracy lately\n• System performance\n• Market conditions\n• Improvement suggestions\n\n💭 **What's your experience been?** Reply with your insights!",
                    
                    "🤖 **Technical Check-in**\n\nGreetings Ops team member! 🔧\n\nTime for a quick system health check:\n\n🔍 **How are things on your end?**\n• Bot performance issues?\n• Signal delays?\n• API connectivity?\n• Data accuracy?\n\n🛠️ **I can help diagnose** any technical issues you're experiencing!\n\nReply with any concerns or just say 'All good!'"
                ],
                
                "technical_help": [
                    "🤖 **Technical Support Available**\n\nHey Ops team member! 👋\n\nI'm here to help with technical issues:\n\n🔧 **I can assist with:**\n• System diagnostics\n• Performance optimization\n• Error troubleshooting\n• Bot configuration\n• API connectivity\n\n💬 **What technical challenge** are you facing today?\n\nReply with your issue and I'll help resolve it!",
                    
                    "🤖 **System Optimization**\n\nHello Ops team member! ⚡\n\nLet's optimize our trading systems:\n\n🚀 **Areas I can help improve:**\n• Signal processing speed\n• Data accuracy\n• Error reduction\n• Performance monitoring\n• Automated diagnostics\n\n💬 **What needs optimization** in your workflow?\n\nShare your thoughts and let's make improvements!"
                ],
                
                "system_status": [
                    "🤖 **System Status Review**\n\nGreetings Ops team member! 📊\n\nLet's review our current system status:\n\n🔍 **Current Performance:**\n• Signal generation: Active\n• Market data: Real-time\n• System health: Monitoring\n• Error rate: Tracking\n\n💬 **What's your experience** with the current system?\n\nReply with any issues or observations!",
                    
                    "🤖 **Performance Check**\n\nHello Ops team member! 📈\n\nHow's our trading system performing for you?\n\n📊 **Metrics to discuss:**\n• Signal accuracy\n• Response times\n• Data reliability\n• User experience\n\n💬 **Share your feedback** - good or needs improvement!"
                ],
                
                "trading_discussion": [
                    "🤖 **Trading Strategy Discussion**\n\nHey Ops team member! 📈\n\nLet's discuss our trading approach:\n\n🎯 **Topics to explore:**\n• Current signal performance\n• Market conditions\n• Risk management\n• Strategy adjustments\n\n💬 **What's your trading insight** for today?\n\nReply with your market analysis or strategy thoughts!",
                    
                    "🤖 **Market Analysis Session**\n\nGreetings Ops team member! 💹\n\nTime for market analysis discussion:\n\n📊 **Current focus:**\n• BTC/ETH trends\n• Signal performance\n• Market volatility\n• Trading opportunities\n\n💬 **What's your market take** right now?\n\nShare your analysis and let's discuss!"
                ],
                
                "feedback_request": [
                    "🤖 **Ops Team Feedback**\n\nHello Ops team member! 🗣️\n\nYour feedback helps improve our systems:\n\n💬 **I'd love to know:**\n• How are the AI responses working?\n• Are the trading signals helpful?\n• Any system improvements needed?\n• Better ways I can assist?\n\n💭 **Share your honest feedback** - it helps me serve you better!",
                    
                    "🤖 **User Experience Check**\n\nGreetings Ops team member! ⭐\n\nHow's your experience with our trading systems?\n\n📋 **Rate your satisfaction:**\n• Signal quality: 1-5\n• System reliability: 1-5\n• AI assistance: 1-5\n• Overall experience: 1-5\n\n💬 **What would make it better?**\n\nReply with your ratings and suggestions!"
                ]
            }
            
            # Select random message from the chosen type
            chosen_messages = messages[engagement_type]
            message = random.choice(chosen_messages)
            
            # Add member targeting (without needing member list)
            if member_identifier:
                # Try to mention if we have a username
                targeted_message = f"@{member_identifier} {message}" if member_identifier else message
            else:
                # General call to any team member
                targeted_message = message
            
            # Send to Ops chat
            result = await CHAT_INTERFACE.send_message(
                chat_id=self.chat_id,
                text=targeted_message,
                parse_mode='Markdown'
            )
            
            if result.get("success"):
                # Track engagement
                engagement_id = f"engagement_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.engagement_history[engagement_id] = {
                    "type": engagement_type,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                    "member_targeted": member_identifier,
                    "message_id": result.get("message_id")
                }
                
                return {
                    "success": True,
                    "engagement_type": engagement_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def initiate_member_conversation(self, conversation_type="general"):
        """Initiate conversation with a random Ops team member"""
        try:
            # Get available members info
            member_info = await self.get_available_members()
            
            if member_info.get("success"):
                member_count = member_info.get("member_count", 0)
                
                # Create member-directed conversation
                result = await self.send_member_directed_message()
                
                if result.get("success"):
                    return {
                        "success": True,
                        "action": "member_conversation_initiated",
                        "member_count": member_count,
                        "conversation_type": conversation_type,
                        "details": result
                    }
                else:
                    return result
            else:
                # Fallback - send general message to Ops chat
                general_message = f"""🤖 **Ops Team Engagement**\n\nHello team! 👋\n\nI'm here to help with:\n\n📊 Trading signals and analysis\n🔧 System diagnostics and support\n📈 Market data processing\n🛠️ Technical assistance\n\n💬 **How can I help you today?**\n\nReply with your questions or let me know what you need assistance with!"""
                
                from telegram_chat_interface import CHAT_INTERFACE
                result = await CHAT_INTERFACE.send_message(
                    chat_id=self.chat_id,
                    text=general_message,
                    parse_mode='Markdown'
                )
                
                return {
                    "success": result.get("success", False),
                    "action": "general_team_engagement",
                    "fallback": True,
                    "message_id": result.get("message_id")
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def respond_to_member(self, member_username, response_text):
        """Respond to a specific member who replied"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            response = f"@{member_username} {response_text}"
            
            result = await CHAT_INTERFACE.send_message(
                chat_id=self.chat_id,
                text=response,
                parse_mode='Markdown'
            )
            
            return {
                "success": result.get("success", False),
                "member_responded": member_username,
                "response": response_text,
                "message_id": result.get("message_id")
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_engagement_stats(self):
        """Get statistics about member engagements"""
        return {
            "total_engagements": len(self.engagement_history),
            "engagement_types": list(set(e["type"] for e in self.engagement_history.values())),
            "recent_engagements": list(self.engagement_history.values())[-5:],
            "chat_id": self.chat_id
        }

# Global instance
OPS_MEMBER_COMMUNICATOR = OpsMemberCommunicator()

# MCP function for member communication
async def initiate_member_conversation(conversation_type="general"):
    """MCP function to initiate conversation with Ops team member"""
    try:
        result = await OPS_MEMBER_COMMUNICATOR.initiate_member_conversation(conversation_type)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "member_conversation_initiated",
                "chat_id": "-1003706659588",
                "conversation_type": conversation_type,
                "details": result,
                "timestamp": datetime.now().isoformat()
            }, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error", "Unknown error")
            }, indent=2)
            
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def respond_to_member(member_username, response_text):
    """MCP function to respond to specific member"""
    try:
        result = await OPS_MEMBER_COMMUNICATOR.respond_to_member(member_username, response_text)
        
        return json.dumps({
            "success": result.get("success", False),
            "member_responded": member_username,
            "response": response_text,
            "details": result,
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🤖 Ops Member Communicator Ready")
    print("=" * 50)
    
    async def test_member_communication():
        print("🧪 Testing member communication...")
        
        result = await OPS_MEMBER_COMMUNICATOR.initiate_member_conversation("technical")
        
        if result.get("success"):
            print("✅ Member communication initiated successfully!")
            print(f"   Action: {result['action']}")
            print(f"   Chat ID: {result.get('chat_id')}")
            print(f"   Message ID: {result.get('message_id')}")
        else:
            print(f"❌ Error: {result.get('error')}")
        
        stats = OPS_MEMBER_COMMUNICATOR.get_engagement_stats()
        print(f"📊 Engagement stats: {stats}")
    
    asyncio.run(test_member_communication())
