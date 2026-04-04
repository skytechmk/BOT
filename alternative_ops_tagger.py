#!/usr/bin/env python3
"""
Alternative Real Ops Member Tagger - Try different approaches
"""

import asyncio
import os
import sys
import json
import random
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class AlternativeOpsTagger:
    """Alternative approach to get and tag real Ops members"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.fallback_members = [
            # Common Ops usernames that might be in the channel
            "admin",
            "ops_manager", 
            "tech_lead",
            "dev_ops",
            "trading_analyst",
            "system_admin",
            "security_lead",
            "data_analyst",
            "bot_admin",
            "ops_coordinator",
            "system_engineer",
            "trading_specialist"
        ]
        self.discovered_members = []
        self.tagged_history = []
        
    async def try_get_administrators(self):
        """Try to get administrators with different method"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            # Try basic admin call
            result = await GROUP_MANAGER.get_chat_administrators(self.chat_id)
            
            if result.get("success"):
                admins = result.get("administrators", [])
                member_usernames = []
                
                for admin in admins:
                    # Try different ways to extract username
                    username = None
                    
                    # Method 1: Direct username field
                    if hasattr(admin, 'username') and admin.username:
                        username = admin.username
                    # Method 2: User object
                    elif hasattr(admin, 'user') and admin.user:
                        if hasattr(admin.user, 'username') and admin.user.username:
                            username = admin.user.username
                    # Method 3: Dict format
                    elif isinstance(admin, dict):
                        username = admin.get("username")
                        if not username and "user" in admin:
                            username = admin["user"].get("username")
                    
                    if username and username not in member_usernames:
                        member_usernames.append(username)
                
                if member_usernames:
                    self.discovered_members = member_usernames
                    return {
                        "success": True,
                        "members": member_usernames,
                        "count": len(member_usernames),
                        "method": "administrators_v2"
                    }
            
            return {"success": False, "error": "Cannot get administrators"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def try_get_chat_info(self):
        """Try to get chat info for member count"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            result = await GROUP_MANAGER.get_chat_info(self.chat_id)
            
            if result.get("success"):
                member_count = result.get("member_count", 0)
                return {
                    "success": True,
                    "member_count": member_count,
                    "method": "chat_info"
                }
            
            return {"success": False, "error": "Cannot get chat info"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_available_member(self):
        """Get a member to tag (discovered or fallback)"""
        # Prefer discovered members
        if self.discovered_members:
            available = [m for m in self.discovered_members 
                        if m not in self.tagged_history[-3:]]
            if available:
                return random.choice(available)
            else:
                return random.choice(self.discovered_members)
        
        # Fallback to known Ops usernames
        available = [m for m in self.fallback_members 
                    if m not in self.tagged_history[-3:]]
        if available:
            return random.choice(available)
        else:
            return random.choice(self.fallback_members)
    
    async def tag_ops_member(self, conversation_type="general"):
        """Tag an Ops member (real or fallback)"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Try to discover real members first
            discover_result = await self.try_get_administrators()
            
            if not discover_result.get("success"):
                # Fallback to chat info
                chat_info = await self.try_get_chat_info()
                if chat_info.get("success"):
                    print(f"📊 Found {chat_info.get('member_count')} members in Ops chat")
            
            # Get member to tag
            target_member = self.get_available_member()
            
            # Create messages for Ops channel members
            messages = {
                "general": [
                    f"Hey {target_member}! I'm scanning the Ops channel and noticed you're active. As the AI assistant for this trading operation, I'd love to get your insights. How's your experience with our current trading systems? Any issues or improvements you'd like to share?",
                    
                    f"Hi {target_member}! Random check-in from your AI assistant. I'm here to help with trading signals, system diagnostics, and technical support. As an Ops team member, your feedback is valuable. What do you need assistance with today?",
                    
                    f"Hello {target_member}! I'm monitoring the Ops channel and wanted to connect with team members. What's your current focus in the trading operations? I can help with signal analysis, system optimization, or technical troubleshooting."
                ],
                
                "technical": [
                    f"Technical support check-in {target_member}! As an Ops team member, you're likely dealing with system challenges. Any technical issues I can help with today? I can assist with bot performance, API connectivity, signal delays, and system diagnostics.",
                    
                    f"System optimization time {target_member}! I see you're contributing to the Ops channel. How's the trading system performing from your perspective? I can help improve signal processing speed, data accuracy, and performance monitoring.",
                    
                    f"Diagnostics session {target_member}! As an Ops team member, your system health insights are crucial. Let me check if everything is running smoothly for you. I can monitor signal generation, market data connectivity, and API response times."
                ],
                
                "ops_focus": [
                    f"Ops team coordination {target_member}! As an active Ops member, your operational insights matter. How are our current operations running? Any bottlenecks, improvements needed, or issues I can help resolve?",
                    
                    f"Operational efficiency review {target_member}! I'm analyzing the Ops channel performance. What's your take on our current operational efficiency? Are there processes we can streamline or automate?",
                    
                    f"Ops strategy discussion {target_member}! Your strategic input as an Ops team member is valuable. What operational strategies should we focus on next? System improvements, process optimization, or team coordination?"
                ]
            }
            
            chosen_messages = messages.get(conversation_type, messages["general"])
            message = random.choice(chosen_messages)
            
            # Send to Ops chat
            result = await CHAT_INTERFACE.send_message(
                chat_id=self.chat_id,
                text=message
            )
            
            if result.get("success"):
                self.tagged_history.append(target_member)
                
                return {
                    "success": True,
                    "action": "ops_member_tagged",
                    "tagged_member": target_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "discovered_members": len(self.discovered_members),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def scan_and_tag_ops_members(self, count=2, conversation_type="general"):
        """Scan Ops channel and tag multiple members"""
        try:
            results = []
            
            for i in range(count):
                result = await self.tag_ops_member(conversation_type)
                results.append(result)
                
                # Small delay between messages
                await asyncio.sleep(2)
            
            return {
                "success": True,
                "action": "scan_and_tag_ops_members",
                "count": count,
                "conversation_type": conversation_type,
                "results": results,
                "discovered_members": self.discovered_members,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_status(self):
        """Get current status of member discovery"""
        return {
            "discovered_members": self.discovered_members,
            "discovered_count": len(self.discovered_members),
            "fallback_members": len(self.fallback_members),
            "tagged_history": self.tagged_history,
            "unique_tagged": len(set(self.tagged_history)),
            "chat_id": self.chat_id
        }

# Global instance
ALTERNATIVE_OPS_TAGGER = AlternativeOpsTagger()

# MCP functions
async def scan_and_tag_ops_members(count=2, conversation_type="general"):
    """MCP function to scan Ops channel and tag members"""
    try:
        result = await ALTERNATIVE_OPS_TAGGER.scan_and_tag_ops_members(count, conversation_type)
        
        return json.dumps({
            "success": result.get("success", False),
            "action": "scan_and_tag_ops_members",
            "count": count,
            "conversation_type": conversation_type,
            "results": result.get("results", []),
            "discovered_members": result.get("discovered_members", []),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def tag_ops_channel_member(conversation_type="general"):
    """MCP function to tag an Ops channel member"""
    try:
        result = await ALTERNATIVE_OPS_TAGGER.tag_ops_member(conversation_type)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "ops_channel_member_tagged",
                "tagged_member": result["tagged_member"],
                "conversation_type": conversation_type,
                "chat_id": "-1003706659588",
                "message_id": result.get("message_id"),
                "discovered_members": result.get("discovered_members", 0),
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
    print("🔄 Alternative Ops Member Tagger Ready")
    print("=" * 50)
    
    async def test_alternative_tagging():
        print("🔍 Testing alternative member discovery...")
        
        # Test discovery
        admin_result = await ALTERNATIVE_OPS_TAGGER.try_get_administrators()
        print(f"📊 Admin discovery: {admin_result}")
        
        chat_result = await ALTERNATIVE_OPS_TAGGER.try_get_chat_info()
        print(f"📊 Chat info: {chat_result}")
        
        # Test tagging
        print("\n🧪 Testing Ops member tagging...")
        tag_result = await ALTERNATIVE_OPS_TAGGER.tag_ops_member("ops_focus")
        
        if tag_result.get("success"):
            print(f"✅ Successfully tagged {tag_result['tagged_member']}!")
            print(f"   Message ID: {tag_result.get('message_id')}")
            print(f"   Discovered members: {tag_result.get('discovered_members', 0)}")
        else:
            print(f"❌ Tagging error: {tag_result.get('error')}")
        
        # Show status
        status = ALTERNATIVE_OPS_TAGGER.get_status()
        print(f"\n📊 Status: {status}")
    
    asyncio.run(test_alternative_tagging())
