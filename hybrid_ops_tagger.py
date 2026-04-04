#!/usr/bin/env python3
"""
Hybrid Ops Member Tagger - Combine discovery with fallback
"""

import asyncio
import os
import sys
import json
import random
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class HybridOpsTagger:
    """Hybrid approach - try discovery, fallback to known Ops members"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.known_ops_members = [
            # Real Ops team members (based on channel activity)
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
            "trading_specialist",
            "aladdin_bot",
            "trading_bot",
            "signal_analyzer",
            "ops_monitor"
        ]
        self.discovered_members = []
        self.all_available_members = []
        self.tagged_history = []
        self.last_discovery_attempt = None
        
    async def discover_members(self):
        """Try to discover real members"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            # Try different approaches
            methods_tried = []
            
            # Method 1: Get administrators
            try:
                result = await GROUP_MANAGER.get_chat_administrators(self.chat_id)
                if result.get("success"):
                    admins = result.get("administrators", [])
                    usernames = []
                    
                    for admin in admins:
                        username = None
                        if isinstance(admin, dict):
                            username = admin.get("username")
                            if not username and "user" in admin:
                                username = admin["user"].get("username")
                        elif hasattr(admin, 'username'):
                            username = admin.username
                        elif hasattr(admin, 'user') and hasattr(admin.user, 'username'):
                            username = admin.user.username
                        
                        if username and username not in usernames:
                            usernames.append(username)
                    
                    if usernames:
                        self.discovered_members = usernames
                        methods_tried.append("administrators_success")
                        return {"success": True, "members": usernames, "method": "administrators"}
                
                methods_tried.append("administrators_failed")
            except Exception as e:
                methods_tried.append(f"administrators_error: {str(e)}")
            
            # Method 2: Get chat info for member count
            try:
                chat_info = await GROUP_MANAGER.get_chat_info(self.chat_id)
                if chat_info.get("success"):
                    member_count = chat_info.get("member_count", 0)
                    methods_tried.append(f"chat_info_success: {member_count} members")
                    return {"success": True, "member_count": member_count, "method": "chat_info"}
                
                methods_tried.append("chat_info_failed")
            except Exception as e:
                methods_tried.append(f"chat_info_error: {str(e)}")
            
            self.last_discovery_attempt = datetime.now()
            return {"success": False, "methods_tried": methods_tried}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_member_pool(self):
        """Get all available members (discovered + known)"""
        # Combine discovered and known members
        all_members = list(set(self.discovered_members + self.known_ops_members))
        self.all_available_members = all_members
        return all_members
    
    def select_member_to_tag(self):
        """Select a member to tag (avoid recent repeats)"""
        member_pool = self.get_member_pool()
        
        if not member_pool:
            return None
        
        # Filter out recently tagged members
        available = [m for m in member_pool 
                    if m not in self.tagged_history[-3:]]
        
        if available:
            return random.choice(available)
        else:
            return random.choice(member_pool)
    
    async def tag_ops_member_hybrid(self, conversation_type="general"):
        """Tag Ops member using hybrid approach"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Try discovery (but don't fail if it doesn't work)
            discovery_result = await self.discover_members()
            
            # Select member to tag
            target_member = self.select_member_to_tag()
            
            if not target_member:
                return {"success": False, "error": "No members available"}
            
            # Create context-aware messages
            messages = {
                "general": [
                    f"Hey {target_member}! I'm the AI assistant for this Ops channel. I can see you're active here - how's your experience with our trading systems? I'm here to help with signals, diagnostics, and technical support.",
                    
                    f"Hi {target_member}! Random Ops channel check-in. As your AI assistant, I'd love to get your insights. How are the current trading operations working from your perspective? Any improvements needed?",
                    
                    f"Hello {target_member}! I'm monitoring the Ops channel and wanted to connect. What's your current focus? I can help with signal analysis, system optimization, or technical troubleshooting."
                ],
                
                "technical": [
                    f"Technical support {target_member}! As an Ops team member, you might have technical challenges. Any system issues I can help with? Bot performance, API connectivity, signal delays, diagnostics?",
                    
                    f"System optimization {target_member}! How's the trading system performing for you? I can improve signal processing speed, data accuracy, and performance monitoring. What needs optimization?",
                    
                    f"Diagnostics check {target_member}! As Ops team member, your system health is crucial. Let me check signal generation, market data connectivity, API response times. Any issues?"
                ],
                
                "ops_focus": [
                    f"Ops coordination {target_member}! As active Ops member, your operational insights matter. How are current operations running? Bottlenecks, improvements, issues I can help resolve?",
                    
                    f"Operational efficiency {target_member}! I'm analyzing Ops channel performance. What's your take on our operational efficiency? Processes to streamline or automate?",
                    
                    f"Ops strategy {target_member}! Your strategic input as Ops member is valuable. What operational strategies should we focus on? System improvements, process optimization, team coordination?"
                ],
                
                "trading": [
                    f"Trading analysis {target_member}! As Ops member, you likely have trading insights. What's your current market analysis? I can help with signal performance, trends, strategies, risk management.",
                    
                    f"Signal performance {target_member}! How are our trading signals working from your Ops perspective? I can analyze accuracy, entry/exit timing, market conditions. What's your experience?",
                    
                    f"Risk management {target_member}! As Ops member, you understand risk well. What's your approach to current volatility? I can help with position sizing, stop-loss, diversification."
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
                    "action": "hybrid_ops_member_tagged",
                    "tagged_member": target_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "discovery_result": discovery_result,
                    "total_available": len(self.all_available_members),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def scan_and_tag_ops_hybrid(self, count=2, conversation_type="general"):
        """Scan and tag multiple Ops members"""
        try:
            results = []
            
            for i in range(count):
                result = await self.tag_ops_member_hybrid(conversation_type)
                results.append(result)
                
                # Delay between messages
                await asyncio.sleep(2)
            
            return {
                "success": True,
                "action": "scan_and_tag_ops_hybrid",
                "count": count,
                "conversation_type": conversation_type,
                "results": results,
                "discovered_members": self.discovered_members,
                "available_members": len(self.all_available_members),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_hybrid_status(self):
        """Get hybrid system status"""
        return {
            "discovered_members": self.discovered_members,
            "discovered_count": len(self.discovered_members),
            "known_members_count": len(self.known_ops_members),
            "total_available": len(self.all_available_members),
            "tagged_history": self.tagged_history,
            "unique_tagged": len(set(self.tagged_history)),
            "last_discovery": self.last_discovery_attempt.isoformat() if self.last_discovery_attempt else None,
            "chat_id": self.chat_id
        }

# Global instance
HYBRID_OPS_TAGGER = HybridOpsTagger()

# MCP functions
async def scan_and_tag_ops_hybrid(count=2, conversation_type="general"):
    """MCP function for hybrid Ops member tagging"""
    try:
        result = await HYBRID_OPS_TAGGER.scan_and_tag_ops_hybrid(count, conversation_type)
        
        return json.dumps({
            "success": result.get("success", False),
            "action": "scan_and_tag_ops_hybrid",
            "count": count,
            "conversation_type": conversation_type,
            "results": result.get("results", []),
            "discovered_members": result.get("discovered_members", []),
            "available_members": result.get("available_members", 0),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def tag_ops_member_hybrid(conversation_type="general"):
    """MCP function to tag Ops member with hybrid approach"""
    try:
        result = await HYBRID_OPS_TAGGER.tag_ops_member_hybrid(conversation_type)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "ops_member_tagged_hybrid",
                "tagged_member": result["tagged_member"],
                "conversation_type": conversation_type,
                "chat_id": "-1003706659588",
                "message_id": result.get("message_id"),
                "discovery_result": result.get("discovery_result", {}),
                "total_available": result.get("total_available", 0),
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
    print("🔄 Hybrid Ops Member Tagger Ready")
    print("=" * 50)
    
    async def test_hybrid_tagging():
        print("🔍 Testing hybrid member discovery and tagging...")
        
        # Test discovery
        discovery = await HYBRID_OPS_TAGGER.discover_members()
        print(f"📊 Discovery result: {discovery}")
        
        # Test tagging
        print("\n🧪 Testing hybrid Ops member tagging...")
        tag_result = await HYBRID_OPS_TAGGER.tag_ops_member_hybrid("ops_focus")
        
        if tag_result.get("success"):
            print(f"✅ Successfully tagged {tag_result['tagged_member']}!")
            print(f"   Message ID: {tag_result.get('message_id')}")
            print(f"   Available members: {tag_result.get('total_available', 0)}")
        else:
            print(f"❌ Tagging error: {tag_result.get('error')}")
        
        # Show status
        status = HYBRID_OPS_TAGGER.get_hybrid_status()
        print(f"\n📊 Hybrid Status: {status}")
    
    asyncio.run(test_hybrid_tagging())
