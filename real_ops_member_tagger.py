#!/usr/bin/env python3
"""
Real Ops Member Tagger - Read actual Ops channel members and tag them
"""

import asyncio
import os
import sys
import random
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class RealOpsMemberTagger:
    """AI that reads actual Ops channel members and tags them"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.cached_members = []
        self.tagged_history = []
        self.last_cache_update = None
        self.cache_duration = 3600  # Cache for 1 hour
        
    async def get_chat_members(self):
        """Get actual members from Ops chat"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            # Try to get chat administrators first (more reliable)
            admins_result = await GROUP_MANAGER.get_chat_administrators(self.chat_id)
            
            if admins_result.get("success"):
                admins = admins_result.get("administrators", [])
                # Extract usernames from admin data
                member_usernames = []
                for admin in admins:
                    if isinstance(admin, dict):
                        username = admin.get("username")
                        if username:
                            member_usernames.append(username)
                        elif "user" in admin:
                            user_info = admin["user"]
                            username = user_info.get("username")
                            if username:
                                member_usernames.append(username)
                
                if member_usernames:
                    self.cached_members = member_usernames
                    self.last_cache_update = datetime.now()
                    return {
                        "success": True,
                        "members": member_usernames,
                        "source": "administrators",
                        "count": len(member_usernames),
                        "timestamp": datetime.now().isoformat()
                    }
            
            # Fallback: Try chat member count (without specific usernames)
            chat_info = await GROUP_MANAGER.get_chat_info(self.chat_id)
            if chat_info.get("success"):
                member_count = chat_info.get("member_count", 0)
                return {
                    "success": True,
                    "member_count": member_count,
                    "source": "chat_info",
                    "note": "Only count available, not specific usernames"
                }
            
            return {"success": False, "error": "Cannot access member information"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_chat_member_list(self):
        """Try to get detailed member list"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            # This might require admin permissions
            result = await GROUP_MANAGER.get_chat_member_count(self.chat_id)
            
            if result.get("success"):
                return {
                    "success": True,
                    "member_count": result.get("count", 0),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_random_real_member(self):
        """Get random real member from cached list"""
        if not self.cached_members:
            return None
        
        # Filter out recently tagged members
        available_members = [m for m in self.cached_members 
                            if m not in self.tagged_history[-3:]]
        
        if available_members:
            return random.choice(available_members)
        else:
            return random.choice(self.cached_members)
    
    async def tag_real_member(self, conversation_type="general"):
        """Tag a real Ops channel member"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Get fresh member list if cache is old
            if (not self.last_cache_update or 
                (datetime.now() - self.last_cache_update).seconds > self.cache_duration):
                
                print("🔄 Refreshing member cache...")
                members_result = await self.get_chat_members()
                
                if not members_result.get("success"):
                    return {"success": False, "error": "Cannot get member list"}
            
            # Get random real member
            target_member = self.get_random_real_member()
            
            if not target_member:
                return {"success": False, "error": "No members available"}
            
            # Create personalized messages for real members
            messages = {
                "general": [
                    f"Hey {target_member}! Random check-in from your AI assistant. I noticed you're active in the Ops channel - how's your day going with the trading operations? I'm here to help with trading signals, system diagnostics, and technical support. What do you need assistance with today?",
                    
                    f"Hi {target_member}! AI assistant here. I can see you're part of the Ops team. I'd love to get your thoughts on our current trading system performance. How are the signals working from your perspective? Any system issues or improvements you'd suggest?",
                    
                    f"Hello {target_member}! Time for a quick strategy discussion. As an Ops team member, your insights are valuable. What's your take on our current market approach? I can help with signal analysis, risk management, and system optimization. Share your insights!"
                ],
                
                "technical": [
                    f"Technical support check-in {target_member}! As an Ops team member, you're probably dealing with technical challenges. Any system issues I can help with today? I can assist with bot performance, API connectivity, signal delays, and system diagnostics. What technical challenges are you facing?",
                    
                    f"System optimization time {target_member}! I see you're active in Ops - how's the trading system performing for you? I can help improve signal processing speed, data accuracy, and performance monitoring. What needs optimization in your workflow?",
                    
                    f"Diagnostics session {target_member}! Let me check if everything is running smoothly for you. As an Ops team member, your system health is crucial. I can monitor signal generation, market data connectivity, and API response times. Any issues or everything looking good?"
                ],
                
                "trading": [
                    f"Trading analysis session {target_member}! As an Ops team member, you likely have trading insights. What's your current market analysis? I can help with signal performance, market trends, trading strategies, and risk management. Share your market insights!",
                    
                    f"Signal performance review {target_member}! How are our trading signals working from your Ops perspective? I can analyze accuracy rates, entry/exit timing, and market conditions. What's your experience been with the current signals?",
                    
                    f"Risk management check {target_member}! As an Ops team member, you understand risk management well. What's your approach to current market volatility? I can help with position sizing, stop-loss placement, and portfolio diversification. How are you managing risk?"
                ],
                
                "ops_focus": [
                    f"Ops team check-in {target_member}! As an active Ops member, your operational insights are valuable. How are our current operations running? Any bottlenecks, improvements needed, or issues I can help resolve?",
                    
                    f"Operational efficiency review {target_member}! I see you're contributing to the Ops channel. What's your take on our current operational efficiency? Are there processes we can streamline or automate?",
                    
                    f"Ops strategy discussion {target_member}! As a key Ops team member, your strategic input matters. What operational strategies should we focus on next? System improvements, process optimization, or team coordination?"
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
                    "action": "real_member_tagged",
                    "tagged_member": target_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "total_members": len(self.cached_members),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def scan_and_tag_members(self, count=2, conversation_type="general"):
        """Scan for real members and tag multiple ones"""
        try:
            # First, get member list
            members_result = await self.get_chat_members()
            
            if not members_result.get("success"):
                return {"success": False, "error": "Cannot scan members"}
            
            # Tag multiple members
            results = []
            for i in range(count):
                result = await self.tag_real_member(conversation_type)
                results.append(result)
                
                # Small delay between messages
                await asyncio.sleep(2)
            
            return {
                "success": True,
                "action": "scan_and_tag_members",
                "count": count,
                "conversation_type": conversation_type,
                "scanned_members": members_result.get("members", []),
                "results": results,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_member_stats(self):
        """Get statistics about real member tagging"""
        return {
            "cached_members": self.cached_members,
            "total_cached": len(self.cached_members),
            "tagged_history": self.tagged_history,
            "unique_tagged": len(set(self.tagged_history)),
            "last_cache_update": self.last_cache_update.isoformat() if self.last_cache_update else None,
            "chat_id": self.chat_id
        }

# Global instance
REAL_OPS_TAGGER = RealOpsMemberTagger()

# MCP functions
async def scan_and_tag_real_members(count=2, conversation_type="general"):
    """MCP function to scan Ops channel and tag real members"""
    try:
        result = await REAL_OPS_TAGGER.scan_and_tag_members(count, conversation_type)
        
        return json.dumps({
            "success": result.get("success", False),
            "action": "scan_and_tag_real_members",
            "count": count,
            "conversation_type": conversation_type,
            "scanned_members": result.get("scanned_members", []),
            "results": result.get("results", []),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def tag_real_ops_member(conversation_type="general"):
    """MCP function to tag a real Ops channel member"""
    try:
        result = await REAL_OPS_TAGGER.tag_real_member(conversation_type)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "real_ops_member_tagged",
                "tagged_member": result["tagged_member"],
                "conversation_type": conversation_type,
                "total_members": result.get("total_members", 0),
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

async def get_ops_member_list():
    """MCP function to get current Ops channel members"""
    try:
        result = await REAL_OPS_TAGGER.get_chat_members()
        
        return json.dumps({
            "success": result.get("success", False),
            "members": result.get("members", []),
            "member_count": result.get("count", 0),
            "source": result.get("source", "unknown"),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🎯 Real Ops Member Tagger Ready")
    print("=" * 50)
    
    async def test_real_member_tagging():
        print("🔍 Scanning for real Ops channel members...")
        
        # First, get member list
        members_result = await REAL_OPS_TAGGER.get_chat_members()
        print(f"📊 Member scan result: {members_result}")
        
        if members_result.get("success"):
            print(f"✅ Found {members_result.get('count', 0)} members")
            
            # Test tagging a real member
            print("\n🧪 Testing real member tagging...")
            tag_result = await REAL_OPS_TAGGER.tag_real_member("technical")
            
            if tag_result.get("success"):
                print(f"✅ Successfully tagged {tag_result['tagged_member']}!")
                print(f"   Message ID: {tag_result.get('message_id')}")
                print(f"   Total members: {tag_result.get('total_members')}")
            else:
                print(f"❌ Tagging error: {tag_result.get('error')}")
        else:
            print(f"❌ Cannot get members: {members_result.get('error')}")
        
        # Show stats
        stats = REAL_OPS_TAGGER.get_member_stats()
        print(f"\n📊 Member Stats: {stats}")
    
    asyncio.run(test_real_member_tagging())
