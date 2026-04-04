#!/usr/bin/env python3
"""
Real Members via Group Manager - Use existing group manager
"""

import asyncio
import os
import sys
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class RealMembersViaGroupManager:
    """Get real members using existing group manager"""
    
    def __init__(self):
        self.chat_id = '-1003706659588'  # Ops chat
        self.real_members = []
        
    async def get_real_members_via_manager(self):
        """Get real members using telegram_group_manager"""
        try:
            print("🔍 Using telegram_group_manager to get real members...")
            
            from telegram_group_manager import GROUP_MANAGER
            
            # Try all available methods
            methods_results = {}
            real_members_found = set()
            
            # Method 1: Get administrators
            print("   📡 Method 1: Get administrators...")
            try:
                admins_result = await GROUP_MANAGER.get_chat_administrators(self.chat_id)
                methods_results["admins"] = admins_result
                
                if admins_result.get("success"):
                    admins = admins_result.get("administrators", [])
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
                        
                        if username:
                            real_members_found.add(username)
                    
                    print(f"      ✅ Found {len(real_members_found)} admins")
                else:
                    print(f"      ❌ Admins failed: {admins_result.get('error', 'Unknown')}")
            except Exception as e:
                print(f"      ❌ Admins exception: {e}")
                methods_results["admins"] = {"success": False, "error": str(e)}
            
            # Method 2: Get chat info
            print("   📡 Method 2: Get chat info...")
            try:
                info_result = await GROUP_MANAGER.get_chat_info(self.chat_id)
                methods_results["info"] = info_result
                
                if info_result.get("success"):
                    member_count = info_result.get("member_count", 0)
                    print(f"      ✅ Chat info: {member_count} members")
                else:
                    print(f"      ❌ Info failed: {info_result.get('error', 'Unknown')}")
            except Exception as e:
                print(f"      ❌ Info exception: {e}")
                methods_results["info"] = {"success": False, "error": str(e)}
            
            # Method 3: Get member count
            print("   📡 Method 3: Get member count...")
            try:
                count_result = await GROUP_MANAGER.get_chat_member_count(self.chat_id)
                methods_results["count"] = count_result
                
                if count_result.get("success"):
                    count = count_result.get("count", 0)
                    print(f"      ✅ Member count: {count}")
                else:
                    print(f"      ❌ Count failed: {count_result.get('error', 'Unknown')}")
            except Exception as e:
                print(f"      ❌ Count exception: {e}")
                methods_results["count"] = {"success": False, "error": str(e)}
            
            # Convert to list
            final_real_members = list(real_members_found)
            self.real_members = final_real_members
            
            return {
                "success": len(final_real_members) > 0,
                "real_members": final_real_members,
                "count": len(final_real_members),
                "methods_results": methods_results,
                "note": "Real members via group manager",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def scan_messages_for_real_users(self):
        """Scan messages for real user mentions"""
        try:
            print("🔍 Scanning messages for real user mentions...")
            
            from telegram_chat_interface import CHAT_INTERFACE
            
            # Get message history
            history_result = await CHAT_INTERFACE.get_chat_history(
                chat_id=self.chat_id,
                limit=200  # More messages
            )
            
            if history_result.get("success"):
                messages = history_result.get("messages", [])
                real_users = set()
                
                for msg in messages:
                    # Extract usernames
                    if isinstance(msg, dict):
                        username = msg.get("from_username")
                        if username and username not in ["ai_assistant", "aladdin_bot"]:
                            real_users.add(username)
                    elif hasattr(msg, 'from_user') and msg.from_user:
                        if hasattr(msg.from_user, 'username') and msg.from_user.username:
                            if msg.from_user.username not in ["ai_assistant", "aladdin_bot"]:
                                real_users.add(msg.from_user.username)
                
                real_list = list(real_users)
                print(f"   ✅ Found {len(real_list)} real users in messages")
                
                return {
                    "success": len(real_list) > 0,
                    "real_users": real_list,
                    "count": len(real_list),
                    "source": "message_history"
                }
            
            return {"success": False, "error": "Cannot get message history"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_all_real_members_combined(self):
        """Combine all methods to get real members"""
        print("🎯 GETTING ALL REAL MEMBERS - COMBINED METHODS")
        print("=" * 60)
        
        # Method 1: Group manager
        manager_result = await self.get_real_members_via_manager()
        
        # Method 2: Message scanning
        message_result = await self.scan_messages_for_real_users()
        
        # Combine results
        all_real_members = set()
        
        # Add from group manager
        if manager_result.get("success"):
            all_real_members.update(manager_result.get("real_members", []))
        
        # Add from message scanning
        if message_result.get("success"):
            all_real_members.update(message_result.get("real_users", []))
        
        final_list = list(all_real_members)
        
        return {
            "success": len(final_list) > 0,
            "all_real_members": final_list,
            "count": len(final_list),
            "manager_result": manager_result,
            "message_result": message_result,
            "note": "ALL REAL MEMBERS - NO FAKES",
            "timestamp": datetime.now().isoformat()
        }

# Global instance
REAL_MEMBERS_MANAGER = RealMembersViaGroupManager()

# MCP function
async def get_real_members_combined():
    """MCP function to get all real members combined"""
    try:
        result = await REAL_MEMBERS_MANAGER.get_all_real_members_combined()
        
        return json.dumps({
            "success": result.get("success", False),
            "all_real_members": result.get("all_real_members", []),
            "count": result.get("count", 0),
            "manager_result": result.get("manager_result", {}),
            "message_result": result.get("message_result", {}),
            "note": "ALL REAL MEMBERS - NO FAKES",
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🎯 Real Members via Group Manager")
    print("=" * 50)
    
    async def test_real_members_manager():
        print("🔍 Testing real members via group manager...")
        
        result = await REAL_MEMBERS_MANAGER.get_all_real_members_combined()
        
        print(f"\n📊 COMBINED REAL MEMBERS RESULT:")
        print(f"✅ Success: {result.get('success')}")
        print(f"👥 All real members: {result.get('all_real_members', [])}")
        print(f"📊 Count: {result.get('count', 0)}")
        print(f"📝 Note: {result.get('note', 'Unknown')}")
        
        # Show manager result
        manager = result.get("manager_result", {})
        print(f"\n📋 Manager Result:")
        print(f"   Success: {manager.get('success', False)}")
        print(f"   Members: {manager.get('real_members', [])}")
        
        # Show message result
        message = result.get("message_result", {})
        print(f"\n📋 Message Result:")
        print(f"   Success: {message.get('success', False)}")
        print(f"   Users: {message.get('real_users', [])}")
    
    asyncio.run(test_real_members_manager())
