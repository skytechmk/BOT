#!/usr/bin/env python3
"""
Advanced Group Member Fetcher - Multiple approaches to get all members
"""

import asyncio
import os
import sys
import json
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class AdvancedMemberFetcher:
    """Advanced member fetching with multiple methods"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.all_members = []
        self.fetch_methods = []
        self.successful_methods = []
        
    async def method_1_get_chat_administrators(self):
        """Method 1: Get chat administrators"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            print("🔍 Method 1: Getting chat administrators...")
            result = await GROUP_MANAGER.get_chat_administrators(self.chat_id)
            
            if result.get("success"):
                admins = result.get("administrators", [])
                usernames = []
                
                for admin in admins:
                    username = None
                    
                    # Try multiple extraction methods
                    if isinstance(admin, dict):
                        username = admin.get("username")
                        if not username and "user" in admin:
                            username = admin["user"].get("username")
                    elif hasattr(admin, 'username'):
                        username = admin.username
                    elif hasattr(admin, 'user') and hasattr(admin.user, 'username'):
                        username = admin.user.username
                    elif hasattr(admin, 'user') and admin.user:
                        if hasattr(admin.user, 'username'):
                            username = admin.user.username
                    
                    if username and username not in usernames:
                        usernames.append(username)
                
                if usernames:
                    self.all_members.extend(usernames)
                    self.successful_methods.append("administrators")
                    return {
                        "success": True,
                        "method": "administrators",
                        "members": usernames,
                        "count": len(usernames)
                    }
            
            return {"success": False, "method": "administrators", "error": "No admins found"}
            
        except Exception as e:
            return {"success": False, "method": "administrators", "error": str(e)}
    
    async def method_2_get_chat_member_count(self):
        """Method 2: Get chat member count"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            print("🔍 Method 2: Getting chat member count...")
            result = await GROUP_MANAGER.get_chat_member_count(self.chat_id)
            
            if result.get("success"):
                count = result.get("count", 0)
                self.successful_methods.append("member_count")
                return {
                    "success": True,
                    "method": "member_count",
                    "count": count,
                    "note": "Only count available, not specific usernames"
                }
            
            return {"success": False, "method": "member_count", "error": "Cannot get count"}
            
        except Exception as e:
            return {"success": False, "method": "member_count", "error": str(e)}
    
    async def method_3_get_chat_info_detailed(self):
        """Method 3: Get detailed chat info"""
        try:
            from telegram_group_manager import GROUP_MANAGER
            
            print("🔍 Method 3: Getting detailed chat info...")
            result = await GROUP_MANAGER.get_chat_info(self.chat_id)
            
            if result.get("success"):
                info = result.get("chat_info", {})
                member_count = info.get("member_count", 0)
                title = info.get("title", "Unknown")
                username = info.get("username", "")
                
                self.successful_methods.append("chat_info")
                return {
                    "success": True,
                    "method": "chat_info",
                    "title": title,
                    "username": username,
                    "member_count": member_count,
                    "all_info": info
                }
            
            return {"success": False, "method": "chat_info", "error": "Cannot get info"}
            
        except Exception as e:
            return {"success": False, "method": "chat_info", "error": str(e)}
    
    async def method_4_try_direct_telegram_api(self):
        """Method 4: Try direct Telegram API calls"""
        try:
            print("🔍 Method 4: Direct Telegram API...")
            
            # Try to import and use direct telegram API
            try:
                from telegram import Bot
                bot_token = os.getenv('TELEGRAM_TOKEN')
                
                if bot_token:
                    bot = Bot(token=bot_token)
                    
                    # Try get_chat_members_count
                    try:
                        count = await bot.get_chat_members_count(self.chat_id)
                        self.successful_methods.append("direct_api_count")
                        return {
                            "success": True,
                            "method": "direct_api_count",
                            "count": count
                        }
                    except Exception as e:
                        print(f"   Direct API count failed: {e}")
                    
                    # Try get_chat_administrators
                    try:
                        admins = await bot.get_chat_administrators(self.chat_id)
                        usernames = []
                        for admin in admins:
                            if admin.user.username:
                                usernames.append(admin.user.username)
                        
                        if usernames:
                            self.all_members.extend(usernames)
                            self.successful_methods.append("direct_api_admins")
                            return {
                                "success": True,
                                "method": "direct_api_admins",
                                "members": usernames,
                                "count": len(usernames)
                            }
                    except Exception as e:
                        print(f"   Direct API admins failed: {e}")
                
                return {"success": False, "method": "direct_api", "error": "No token or API failed"}
                
            except ImportError:
                return {"success": False, "method": "direct_api", "error": "Telegram library not available"}
            
        except Exception as e:
            return {"success": False, "method": "direct_api", "error": str(e)}
    
    async def method_5_scan_recent_messages(self):
        """Method 5: Scan recent messages for active members"""
        try:
            print("🔍 Method 5: Scanning recent messages for active members...")
            
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Get chat history
            history_result = await CHAT_INTERFACE.get_chat_history(
                chat_id=self.chat_id,
                limit=50
            )
            
            if history_result.get("success"):
                messages = history_result.get("messages", [])
                active_members = set()
                
                for msg in messages:
                    # Extract username from message
                    if isinstance(msg, dict):
                        username = msg.get("from_username")
                        if username:
                            active_members.add(username)
                    elif hasattr(msg, 'from_user') and msg.from_user:
                        if hasattr(msg.from_user, 'username') and msg.from_user.username:
                            active_members.add(msg.from_user.username)
                
                if active_members:
                    active_list = list(active_members)
                    self.all_members.extend(active_list)
                    self.successful_methods.append("message_scan")
                    return {
                        "success": True,
                        "method": "message_scan",
                        "members": active_list,
                        "count": len(active_list),
                        "note": "Active members from recent messages"
                    }
            
            return {"success": False, "method": "message_scan", "error": "Cannot get history"}
            
        except Exception as e:
            return {"success": False, "method": "message_scan", "error": str(e)}
    
    async def method_6_try_get_chat_members_iterative(self):
        """Method 6: Try iterative member fetching"""
        try:
            print("🔍 Method 6: Iterative member fetching...")
            
            # This is a more advanced method that might work with proper permissions
            try:
                from telegram import Bot
                bot_token = os.getenv('TELEGRAM_TOKEN')
                
                if bot_token:
                    bot = Bot(token=bot_token)
                    
                    # Try to get chat members iteratively
                    members = []
                    try:
                        async for member in bot.get_chat_members(self.chat_id, limit=100):
                            if member.user.username:
                                members.append(member.user.username)
                            if len(members) >= 100:  # Limit to prevent infinite loops
                                break
                        
                        if members:
                            self.all_members.extend(members)
                            self.successful_methods.append("iterative_fetch")
                            return {
                                "success": True,
                                "method": "iterative_fetch",
                                "members": members,
                                "count": len(members)
                            }
                    
                    except Exception as e:
                        print(f"   Iterative fetch failed: {e}")
                
                return {"success": False, "method": "iterative_fetch", "error": "Cannot fetch iteratively"}
                
            except Exception as e:
                return {"success": False, "method": "iterative_fetch", "error": str(e)}
            
        except Exception as e:
            return {"success": False, "method": "iterative_fetch", "error": str(e)}
    
    async def fetch_all_members_comprehensive(self):
        """Try all methods to get as many members as possible"""
        print("🚀 COMPREHENSIVE MEMBER FETCH - Trying all methods...")
        print("=" * 60)
        
        methods = [
            self.method_1_get_chat_administrators,
            self.method_2_get_chat_member_count,
            self.method_3_get_chat_info_detailed,
            self.method_4_try_direct_telegram_api,
            self.method_5_scan_recent_messages,
            self.method_6_try_get_chat_members_iterative
        ]
        
        results = {}
        
        for i, method in enumerate(methods, 1):
            print(f"\n{i}. Trying method...")
            try:
                result = await method()
                results[f"method_{i}"] = result
                
                if result.get("success"):
                    print(f"   ✅ SUCCESS: {result.get('method', 'unknown')}")
                    if result.get("members"):
                        print(f"   📊 Found {len(result['members'])} members")
                    elif result.get("count"):
                        print(f"   📊 Count: {result['count']}")
                else:
                    print(f"   ❌ FAILED: {result.get('error', 'Unknown error')}")
                
                # Small delay between methods
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ❌ EXCEPTION: {e}")
                results[f"method_{i}"] = {"success": False, "error": str(e)}
        
        # Compile all unique members
        unique_members = list(set(self.all_members))
        
        return {
            "success": len(unique_members) > 0,
            "total_unique_members": len(unique_members),
            "all_members": unique_members,
            "successful_methods": self.successful_methods,
            "method_results": results,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_comprehensive_report(self):
        """Get detailed report of all fetch attempts"""
        return {
            "total_unique_members": len(set(self.all_members)),
            "all_members": list(set(self.all_members)),
            "successful_methods": self.successful_methods,
            "methods_tried": len(self.fetch_methods),
            "chat_id": self.chat_id
        }

# Global instance
ADVANCED_FETCHER = AdvancedMemberFetcher()

# MCP function
async def fetch_all_ops_members():
    """MCP function to fetch all Ops channel members using all methods"""
    try:
        result = await ADVANCED_FETCHER.fetch_all_members_comprehensive()
        
        return json.dumps({
            "success": result.get("success", False),
            "total_unique_members": result.get("total_unique_members", 0),
            "all_members": result.get("all_members", []),
            "successful_methods": result.get("successful_methods", []),
            "method_results": result.get("method_results", {}),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🔍 Advanced Member Fetcher Ready")
    print("=" * 50)
    
    async def test_comprehensive_fetch():
        print("🚀 Testing comprehensive member fetching...")
        
        result = await ADVANCED_FETCHER.fetch_all_members_comprehensive()
        
        print(f"\n📊 COMPREHENSIVE RESULT:")
        print(f"✅ Success: {result.get('success')}")
        print(f"📊 Total unique members: {result.get('total_unique_members', 0)}")
        print(f"📋 All members: {result.get('all_members', [])}")
        print(f"🔧 Successful methods: {result.get('successful_methods', [])}")
        
        print(f"\n📋 Method Details:")
        for method_name, method_result in result.get("method_results", {}).items():
            print(f"   {method_name}:")
            if method_result.get("success"):
                print(f"     ✅ {method_result.get('method', 'unknown')}")
                if method_result.get("members"):
                    print(f"     📊 {len(method_result['members'])} members")
                elif method_result.get("count"):
                    print(f"     📊 Count: {method_result['count']}")
            else:
                print(f"     ❌ {method_result.get('error', 'Unknown error')}")
    
    asyncio.run(test_comprehensive_fetch())
