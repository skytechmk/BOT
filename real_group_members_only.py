#!/usr/bin/env python3
"""
Real Group Members Only - Get actual members, no fakes
"""

import asyncio
import os
import sys
import json
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class RealGroupMembersOnly:
    """Get ONLY real group members, no fallback/fake members"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.real_members = []
        self.all_attempts = []
        
    async def method_1_direct_admin_api(self):
        """Method 1: Direct admin API call"""
        try:
            print("🔍 Method 1: Direct admin API...")
            
            from telegram import Bot
            bot_token = os.getenv('TELEGRAM_TOKEN')
            
            if bot_token:
                bot = Bot(token=bot_token)
                
                try:
                    admins = await bot.get_chat_administrators(self.chat_id)
                    real_admins = []
                    
                    for admin in admins:
                        if admin.user and admin.user.username:
                            real_admins.append(admin.user.username)
                    
                    if real_admins:
                        self.real_members.extend(real_admins)
                        return {
                            "success": True,
                            "method": "direct_admin_api",
                            "real_members": real_admins,
                            "count": len(real_admins),
                            "note": "Real administrators only"
                        }
                
                except Exception as e:
                    return {"success": False, "method": "direct_admin_api", "error": str(e)}
            
            return {"success": False, "method": "direct_admin_api", "error": "No token"}
            
        except Exception as e:
            return {"success": False, "method": "direct_admin_api", "error": str(e)}
    
    async def method_2_chat_member_count(self):
        """Method 2: Get exact member count"""
        try:
            print("🔍 Method 2: Exact member count...")
            
            from telegram import Bot
            bot_token = os.getenv('TELEGRAM_TOKEN')
            
            if bot_token:
                bot = Bot(token=bot_token)
                
                try:
                    count = await bot.get_chat_members_count(self.chat_id)
                    return {
                        "success": True,
                        "method": "member_count",
                        "count": count,
                        "note": f"Real member count: {count}"
                    }
                
                except Exception as e:
                    return {"success": False, "method": "member_count", "error": str(e)}
            
            return {"success": False, "method": "member_count", "error": "No token"}
            
        except Exception as e:
            return {"success": False, "method": "member_count", "error": str(e)}
    
    async def method_3_scan_messages_for_users(self):
        """Method 3: Scan recent messages for real usernames"""
        try:
            print("🔍 Method 3: Scan messages for real users...")
            
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Get recent messages
            result = await CHAT_INTERFACE.get_chat_history(
                chat_id=self.chat_id,
                limit=100  # More messages to find real users
            )
            
            if result.get("success"):
                messages = result.get("messages", [])
                real_users = set()
                
                for msg in messages:
                    # Extract real usernames from messages
                    if isinstance(msg, dict):
                        username = msg.get("from_username")
                        if username and username != "ai_assistant":
                            real_users.add(username)
                    elif hasattr(msg, 'from_user') and msg.from_user:
                        if hasattr(msg.from_user, 'username') and msg.from_user.username:
                            if msg.from_user.username != "ai_assistant":
                                real_users.add(msg.from_user.username)
                
                if real_users:
                    real_list = list(real_users)
                    self.real_members.extend(real_list)
                    return {
                        "success": True,
                        "method": "message_scan",
                        "real_members": real_list,
                        "count": len(real_list),
                        "note": "Real users from message history"
                    }
            
            return {"success": False, "method": "message_scan", "error": "Cannot get history"}
            
        except Exception as e:
            return {"success": False, "method": "message_scan", "error": str(e)}
    
    async def method_4_try_get_chat_members_sample(self):
        """Method 4: Try to get sample of chat members"""
        try:
            print("🔍 Method 4: Sample chat members...")
            
            from telegram import Bot
            bot_token = os.getenv('TELEGRAM_TOKEN')
            
            if bot_token:
                bot = Bot(token=bot_token)
                
                try:
                    # Try to get a few members
                    members = []
                    count = 0
                    limit = 50  # Try up to 50 members
                    
                    async for member in bot.get_chat_members(self.chat_id, limit=limit):
                        if member.user.username:
                            members.append(member.user.username)
                            count += 1
                        if count >= limit:
                            break
                    
                    if members:
                        self.real_members.extend(members)
                        return {
                            "success": True,
                            "method": "sample_members",
                            "real_members": members,
                            "count": len(members),
                            "note": f"Sample of {len(members)} real members"
                        }
                
                except Exception as e:
                    return {"success": False, "method": "sample_members", "error": str(e)}
            
            return {"success": False, "method": "sample_members", "error": "No token"}
            
        except Exception as e:
            return {"success": False, "method": "sample_members", "error": str(e)}
    
    async def method_5_chat_info_with_details(self):
        """Method 5: Get detailed chat info"""
        try:
            print("🔍 Method 5: Detailed chat info...")
            
            from telegram import Bot
            bot_token = os.getenv('TELEGRAM_TOKEN')
            
            if bot_token:
                bot = Bot(token=bot_token)
                
                try:
                    chat = await bot.get_chat(self.chat_id)
                    
                    info = {
                        "id": chat.id,
                        "title": chat.title,
                        "username": getattr(chat, 'username', None),
                        "type": chat.type,
                        "member_count": getattr(chat, 'member_count', None)
                    }
                    
                    return {
                        "success": True,
                        "method": "detailed_info",
                        "chat_info": info,
                        "note": "Real chat information"
                    }
                
                except Exception as e:
                    return {"success": False, "method": "detailed_info", "error": str(e)}
            
            return {"success": False, "method": "detailed_info", "error": "No token"}
            
        except Exception as e:
            return {"success": False, "method": "detailed_info", "error": str(e)}
    
    async def get_only_real_members(self):
        """Get ONLY real members, no fakes"""
        print("🎯 GETTING ONLY REAL GROUP MEMBERS - NO FAKES!")
        print("=" * 60)
        
        methods = [
            self.method_1_direct_admin_api,
            self.method_2_chat_member_count,
            self.method_3_scan_messages_for_users,
            self.method_4_try_get_chat_members_sample,
            self.method_5_chat_info_with_details
        ]
        
        results = {}
        real_members_found = set()
        
        for i, method in enumerate(methods, 1):
            print(f"\n{i}. 📡 Trying method...")
            
            try:
                result = await method()
                results[f"method_{i}"] = result
                
                if result.get("success"):
                    print(f"   ✅ SUCCESS: {result.get('method', 'unknown')}")
                    
                    # Collect real members
                    if result.get("real_members"):
                        members = result["real_members"]
                        real_members_found.update(members)
                        print(f"   👥 Real members found: {len(members)}")
                    
                    if result.get("count"):
                        print(f"   📊 Count: {result['count']}")
                    
                    if result.get("chat_info"):
                        info = result["chat_info"]
                        print(f"   📋 Chat: {info.get('title', 'Unknown')}")
                        if info.get("member_count"):
                            print(f"   👥 Total members: {info['member_count']}")
                else:
                    print(f"   ❌ FAILED: {result.get('error', 'Unknown error')}")
                
                # Small delay
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ❌ EXCEPTION: {e}")
                results[f"method_{i}"] = {"success": False, "error": str(e)}
        
        # Final real members list
        final_real_members = list(real_members_found)
        self.real_members = final_real_members
        
        return {
            "success": len(final_real_members) > 0,
            "real_members_only": final_real_members,
            "count": len(final_real_members),
            "methods_tried": len(methods),
            "method_results": results,
            "note": "ONLY REAL MEMBERS - NO FAKES/FALLBACKS",
            "timestamp": datetime.now().isoformat()
        }
    
    def tag_real_member_only(self, conversation_type="general"):
        """Tag only real members"""
        if not self.real_members:
            return {"success": False, "error": "No real members available"}
        
        import random
        target_member = random.choice(self.real_members)
        
        # Create messages for real members only
        messages = {
            "general": [
                f"Hey {target_member}! I found you're actually in the Ops channel - not a fake member! As the real AI assistant, I'd love to get your genuine insights. How's your experience with our trading systems?",
                
                f"Hi {target_member}! You're a real Ops channel member! I can confirm you're not a fallback/fake user. As your AI assistant, I'm here to help with real trading signals, system diagnostics, and technical support.",
                
                f"Hello {target_member}! Real member detected in Ops channel! I'm the actual AI assistant monitoring this channel. What's your current focus in our trading operations? I can provide real assistance."
            ],
            "technical": [
                f"Technical support {target_member}! As a real Ops member, you might have actual technical challenges. Any real system issues I can help with? Bot performance, API connectivity, signal delays?",
                
                f"System check {target_member}! You're a genuine Ops team member. How's the trading system performing from your real perspective? I can help with actual optimization and diagnostics.",
                
                f"Diagnostics {target_member}! Real Ops member detected! Let me check if everything is running smoothly for you. I can monitor real signal generation and API response times."
            ]
        }
        
        chosen_messages = messages.get(conversation_type, messages["general"])
        message = random.choice(chosen_messages)
        
        return {
            "success": True,
            "action": "real_member_only_tagged",
            "real_member": target_member,
            "conversation_type": conversation_type,
            "message": message,
            "note": "REAL MEMBER ONLY - NO FAKE/FALLBACK"
        }

# Global instance
REAL_MEMBERS_ONLY = RealGroupMembersOnly()

# MCP function
async def get_real_group_members_only():
    """MCP function to get only real group members"""
    try:
        result = await REAL_MEMBERS_ONLY.get_only_real_members()
        
        return json.dumps({
            "success": result.get("success", False),
            "real_members_only": result.get("real_members_only", []),
            "count": result.get("count", 0),
            "methods_tried": result.get("methods_tried", 0),
            "method_results": result.get("method_results", {}),
            "note": "ONLY REAL MEMBERS - NO FAKES",
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🎯 Real Group Members Only - NO FAKES")
    print("=" * 50)
    
    async def test_real_members_only():
        print("🔍 Testing real members only...")
        
        result = await REAL_MEMBERS_ONLY.get_only_real_members()
        
        print(f"\n📊 REAL MEMBERS ONLY RESULT:")
        print(f"✅ Success: {result.get('success')}")
        print(f"👥 Real members only: {result.get('real_members_only', [])}")
        print(f"📊 Count: {result.get('count', 0)}")
        print(f"📝 Note: {result.get('note', 'Unknown')}")
        
        print(f"\n📋 Method Details:")
        for method_name, method_result in result.get("method_results", {}).items():
            print(f"   {method_name}:")
            if method_result.get("success"):
                print(f"     ✅ {method_result.get('method', 'unknown')}")
                if method_result.get("real_members"):
                    print(f"     👥 {len(method_result['real_members'])} real members")
            else:
                print(f"     ❌ {method_result.get('error', 'Unknown error')}")
    
    asyncio.run(test_real_members_only())
