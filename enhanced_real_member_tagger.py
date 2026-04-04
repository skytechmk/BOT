#!/usr/bin/env python3
"""
Enhanced Real Member Tagger - Uses discovered real members
"""

import asyncio
import os
import sys
import json
import random
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class EnhancedRealMemberTagger:
    """Enhanced tagger that uses discovered real Ops members"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.discovered_real_members = []
        self.fallback_ops_members = [
            "admin", "ops_manager", "tech_lead", "dev_ops", 
            "trading_analyst", "system_admin", "security_lead", 
            "data_analyst", "bot_admin", "ops_coordinator", 
            "system_engineer", "trading_specialist", "aladdin_bot", 
            "trading_bot", "signal_analyzer", "ops_monitor"
        ]
        self.all_available_members = []
        self.tagged_history = []
        self.last_discovery = None
        
    async def discover_real_members(self):
        """Discover real Ops members using comprehensive methods"""
        try:
            from advanced_member_fetcher import ADVANCED_FETCHER
            
            print("🔍 Discovering real Ops members...")
            result = await ADVANCED_FETCHER.fetch_all_members_comprehensive()
            
            if result.get("success") and result.get("all_members"):
                real_members = result.get("all_members", [])
                self.discovered_real_members = real_members
                self.last_discovery = datetime.now()
                
                print(f"✅ Discovered {len(real_members)} real members: {real_members}")
                
                return {
                    "success": True,
                    "real_members": real_members,
                    "count": len(real_members),
                    "methods_used": result.get("successful_methods", [])
                }
            else:
                print(f"❌ Discovery failed: {result.get('error', 'Unknown error')}")
                return {"success": False, "error": "Cannot discover real members"}
                
        except Exception as e:
            print(f"❌ Discovery exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_member_pool(self):
        """Get all available members (real + fallback)"""
        # Combine discovered real members with fallback members
        all_members = list(set(self.discovered_real_members + self.fallback_ops_members))
        self.all_available_members = all_members
        return all_members
    
    def select_member_to_tag(self, prefer_real=True):
        """Select member to tag with preference for real members"""
        member_pool = self.get_member_pool()
        
        if not member_pool:
            return None
        
        # Prefer real members if available and requested
        if prefer_real and self.discovered_real_members:
            real_available = [m for m in self.discovered_real_members 
                            if m not in self.tagged_history[-3:]]
            if real_available:
                return random.choice(real_available)
        
        # Filter out recently tagged members
        available = [m for m in member_pool 
                    if m not in self.tagged_history[-3:]]
        
        if available:
            return random.choice(available)
        else:
            return random.choice(member_pool)
    
    async def tag_enhanced_member(self, conversation_type="general", prefer_real=True):
        """Tag member with enhanced approach"""
        try:
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Discover real members (but don't fail if it doesn't work)
            if not self.discovered_real_members:
                await self.discover_real_members()
            
            # Select member to tag
            target_member = self.select_member_to_tag(prefer_real)
            
            if not target_member:
                return {"success": False, "error": "No members available"}
            
            # Determine if this is a real member
            is_real_member = target_member in self.discovered_real_members
            
            # Create context-aware messages
            if is_real_member:
                # Messages for discovered real members
                messages = {
                    "general": [
                        f"Hey {target_member}! I discovered you're actually in the Ops channel! As the AI assistant, I'd love to get your insights. How's your experience with our trading systems? Any issues or improvements you'd like to share?",
                        
                        f"Hi {target_member}! I found you in the Ops channel - great to connect with a real team member! As your AI assistant, I'm here to help with trading signals, system diagnostics, and technical support. What do you need assistance with?",
                        
                        f"Hello {target_member}! It's awesome to connect with an actual Ops team member! I'm monitoring the channel and wanted to reach out. What's your current focus in the trading operations? I can help with analysis and optimization."
                    ],
                    "technical": [
                        f"Technical support {target_member}! Since you're actually in the Ops channel, you might have real technical insights. Any system issues I can help with? Bot performance, API connectivity, signal delays, diagnostics?",
                        
                        f"System optimization {target_member}! As a real Ops member, your system feedback is valuable. How's the trading system performing from your perspective? I can improve signal processing, data accuracy, and performance monitoring.",
                        
                        f"Diagnostics check {target_member}! Your system health insights as an actual Ops member are crucial. Let me check signal generation, market data connectivity, API response times. Any issues you've noticed?"
                    ],
                    "ops_focus": [
                        f"Ops coordination {target_member}! It's great to connect with a real Ops team member! Your operational insights matter. How are current operations running? Bottlenecks, improvements, issues I can help resolve?",
                        
                        f"Operational efficiency {target_member}! As an actual Ops member, your feedback on operations is gold. What's your take on our operational efficiency? Processes to streamline or automate?",
                        
                        f"Ops strategy {target_member}! Your strategic input as a real Ops member is invaluable. What operational strategies should we focus on? System improvements, process optimization, team coordination?"
                    ]
                }
            else:
                # Messages for fallback members
                messages = {
                    "general": [
                        f"Hey {target_member}! I'm the AI assistant for this Ops channel. How's your experience with our trading systems? I'm here to help with signals, diagnostics, and technical support.",
                        
                        f"Hi {target_member}! Random Ops channel check-in. As your AI assistant, I'd love to get your insights. How are the current trading operations working?",
                        
                        f"Hello {target_member}! I'm monitoring the Ops channel and wanted to connect. What's your current focus? I can help with signal analysis and optimization."
                    ],
                    "technical": [
                        f"Technical support {target_member}! Any system issues I can help with? Bot performance, API connectivity, signal delays, diagnostics?",
                        
                        f"System optimization {target_member}! How's the trading system performing for you? I can improve signal processing speed and data accuracy.",
                        
                        f"Diagnostics check {target_member}! Let me check signal generation, market data connectivity, API response times. Any issues?"
                    ],
                    "ops_focus": [
                        f"Ops coordination {target_member}! Your operational insights matter. How are current operations running? Bottlenecks, improvements, issues I can help resolve?",
                        
                        f"Operational efficiency {target_member}! What's your take on our operational efficiency? Processes to streamline or automate?",
                        
                        f"Ops strategy {target_member}! What operational strategies should we focus on? System improvements, process optimization, team coordination?"
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
                    "action": "enhanced_member_tagged",
                    "tagged_member": target_member,
                    "is_real_member": is_real_member,
                    "conversation_type": conversation_type,
                    "message": message,
                    "chat_id": self.chat_id,
                    "message_id": result.get("message_id"),
                    "total_discovered": len(self.discovered_real_members),
                    "total_available": len(self.all_available_members),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": "Failed to send message"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def tag_multiple_enhanced(self, count=2, conversation_type="general", prefer_real=True):
        """Tag multiple enhanced members"""
        try:
            results = []
            
            for i in range(count):
                result = await self.tag_enhanced_member(conversation_type, prefer_real)
                results.append(result)
                
                # Delay between messages
                await asyncio.sleep(2)
            
            return {
                "success": True,
                "action": "tag_multiple_enhanced",
                "count": count,
                "conversation_type": conversation_type,
                "results": results,
                "discovered_members": self.discovered_real_members,
                "available_members": len(self.all_available_members),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_enhanced_status(self):
        """Get enhanced system status"""
        return {
            "discovered_real_members": self.discovered_real_members,
            "discovered_count": len(self.discovered_real_members),
            "fallback_members_count": len(self.fallback_ops_members),
            "total_available": len(self.all_available_members),
            "tagged_history": self.tagged_history,
            "unique_tagged": len(set(self.tagged_history)),
            "last_discovery": self.last_discovery.isoformat() if self.last_discovery else None,
            "chat_id": self.chat_id
        }

# Global instance
ENHANCED_TAGGER = EnhancedRealMemberTagger()

# MCP functions
async def tag_enhanced_ops_member(conversation_type="general", prefer_real=True):
    """MCP function to tag enhanced Ops member"""
    try:
        result = await ENHANCED_TAGGER.tag_enhanced_member(conversation_type, prefer_real)
        
        if result.get("success"):
            return json.dumps({
                "success": True,
                "action": "enhanced_ops_member_tagged",
                "tagged_member": result["tagged_member"],
                "is_real_member": result.get("is_real_member", False),
                "conversation_type": conversation_type,
                "chat_id": "-1003706659588",
                "message_id": result.get("message_id"),
                "total_discovered": result.get("total_discovered", 0),
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

async def tag_multiple_enhanced_members(count=2, conversation_type="general", prefer_real=True):
    """MCP function to tag multiple enhanced Ops members"""
    try:
        result = await ENHANCED_TAGGER.tag_multiple_enhanced(count, conversation_type, prefer_real)
        
        return json.dumps({
            "success": result.get("success", False),
            "action": "tag_multiple_enhanced",
            "count": count,
            "conversation_type": conversation_type,
            "results": result.get("results", []),
            "discovered_members": result.get("discovered_members", []),
            "available_members": result.get("available_members", 0),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🚀 Enhanced Real Member Tagger Ready")
    print("=" * 50)
    
    async def test_enhanced_tagging():
        print("🔍 Testing enhanced member discovery and tagging...")
        
        # Test discovery
        discovery = await ENHANCED_TAGGER.discover_real_members()
        print(f"📊 Discovery result: {discovery}")
        
        # Test tagging
        print("\n🧪 Testing enhanced Ops member tagging...")
        tag_result = await ENHANCED_TAGGER.tag_enhanced_member("ops_focus", prefer_real=True)
        
        if tag_result.get("success"):
            print(f"✅ Successfully tagged {tag_result['tagged_member']}!")
            print(f"   Is real member: {tag_result.get('is_real_member', False)}")
            print(f"   Message ID: {tag_result.get('message_id')}")
            print(f"   Total discovered: {tag_result.get('total_discovered', 0)}")
        else:
            print(f"❌ Tagging error: {tag_result.get('error')}")
        
        # Show status
        status = ENHANCED_TAGGER.get_enhanced_status()
        print(f"\n📊 Enhanced Status: {status}")
    
    asyncio.run(test_enhanced_tagging())
