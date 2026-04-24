"""
Telegram Group Management Module
Provides functionality to view and manipulate Telegram group members
"""

import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from telegram import Bot, Update
from telegram.ext import Application
from telegram.request import HTTPXRequest
from shared_state import log_message

# Shared HTTPXRequest with larger pool for all Telegram operations
_TG_REQUEST = HTTPXRequest(connection_pool_size=30, connect_timeout=30.0, read_timeout=30.0)

class TelegramGroupManager:
    """Advanced Telegram group management capabilities"""
    
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_TOKEN')
        self.ops_token = os.getenv('OPS_TELEGRAM_TOKEN')
        self.main_bot = Bot(token=self.bot_token, request=_TG_REQUEST) if self.bot_token else None
        self.ops_bot = Bot(token=self.ops_token, request=_TG_REQUEST) if self.ops_token else None
        
    async def get_chat_administrators(self, chat_id: str, use_ops_bot: bool = False) -> List[Dict[str, Any]]:
        """
        Get list of chat administrators
        
        Args:
            chat_id: Telegram chat ID
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            List of administrator information
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            chat = await bot.get_chat(chat_id)
            admins = await chat.get_administrators()
            
            admin_list = []
            for admin in admins:
                admin_info = {
                    'user_id': admin.user.id,
                    'username': admin.user.username,
                    'first_name': admin.user.first_name,
                    'last_name': admin.user.last_name,
                    'is_anonymous': getattr(admin, 'is_anonymous', False),
                    'status': admin.status,
                    'can_be_edited': getattr(admin, 'can_be_edited', False),
                    'can_manage_chat': getattr(admin, 'can_manage_chat', False),
                    'can_change_info': getattr(admin, 'can_change_info', False),
                    'can_delete_messages': getattr(admin, 'can_delete_messages', False),
                    'can_invite_users': getattr(admin, 'can_invite_users', False),
                    'can_restrict_members': getattr(admin, 'can_restrict_members', False),
                    'can_pin_messages': getattr(admin, 'can_pin_messages', False),
                    'can_promote_members': getattr(admin, 'can_promote_members', False),
                }
                
                # Add custom title if exists
                if hasattr(admin, 'custom_title') and admin.custom_title:
                    admin_info['custom_title'] = admin.custom_title
                
                admin_list.append(admin_info)
            
            log_message(f"Retrieved {len(admin_list)} administrators for chat {chat_id}")
            return {"success": True, "administrators": admin_list, "count": len(admin_list)}
            
        except Exception as e:
            log_message(f"Error getting administrators: {e}")
            return {"success": False, "error": str(e), "administrators": []}
    
    async def get_chat_member(self, chat_id: str, user_id: int, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Get specific member information
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Member information
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            member = await bot.get_chat_member(chat_id, user_id)
            
            member_info = {
                'user_id': member.user.id,
                'username': member.user.username,
                'first_name': member.user.first_name,
                'last_name': member.user.last_name,
                'status': member.status,
                'joined_date': getattr(member, 'joined_date', None),
                'until_date': getattr(member, 'until_date', None)
            }
            
            # Add permissions if member has them
            if hasattr(member, 'can_post_messages'):
                member_info['can_post_messages'] = member.can_post_messages
            if hasattr(member, 'can_edit_messages'):
                member_info['can_edit_messages'] = member.can_edit_messages
            if hasattr(member, 'can_delete_messages'):
                member_info['can_delete_messages'] = member.can_delete_messages
            if hasattr(member, 'can_invite_users'):
                member_info['can_invite_users'] = member.can_invite_users
            if hasattr(member, 'can_restrict_members'):
                member_info['can_restrict_members'] = member.can_restrict_members
            if hasattr(member, 'can_pin_messages'):
                member_info['can_pin_messages'] = member.can_pin_messages
            if hasattr(member, 'can_promote_members'):
                member_info['can_promote_members'] = member.can_promote_members
            
            log_message(f"Retrieved member info for user {user_id} in chat {chat_id}")
            return member_info
            
        except Exception as e:
            log_message(f"Error getting member info: {e}")
            return {"error": str(e)}
    
    async def get_chat_member_count(self, chat_id: str, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Get total number of members in chat
        
        Args:
            chat_id: Telegram chat ID
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Member count information
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            chat = await bot.get_chat(chat_id)
            member_count = await chat.get_member_count()
            
            result = {
                'chat_id': chat_id,
                'member_count': member_count,
                'timestamp': datetime.now().isoformat()
            }
            
            log_message(f"Chat {chat_id} has {member_count} members")
            return result
            
        except Exception as e:
            log_message(f"Error getting member count: {e}")
            return {"error": str(e)}
    
    async def ban_chat_member(self, chat_id: str, user_id: int, 
                           until_date: Optional[int] = None,
                           revoke_messages: bool = True,
                           use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Ban a member from the chat
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID to ban
            until_date: Date when ban will be lifted (None for permanent)
            revoke_messages: Whether to delete all messages from user
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Operation result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            # Check if bot has permission to ban
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if not bot_member.can_restrict_members:
                return {"error": "Bot doesn't have permission to restrict members"}
            
            await bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=until_date,
                revoke_messages=revoke_messages
            )
            
            log_message(f"Banned user {user_id} from chat {chat_id}")
            return {
                "success": True,
                "user_id": user_id,
                "chat_id": chat_id,
                "until_date": until_date,
                "revoke_messages": revoke_messages
            }
            
        except Exception as e:
            log_message(f"Error banning member: {e}")
            return {"error": str(e)}
    
    async def unban_chat_member(self, chat_id: str, user_id: int, 
                              only_if_banned: bool = True,
                              use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Unban a member from the chat
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID to unban
            only_if_banned: Only unban if user is currently banned
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Operation result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            await bot.unban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                only_if_banned=only_if_banned
            )
            
            log_message(f"Unbanned user {user_id} from chat {chat_id}")
            return {
                "success": True,
                "user_id": user_id,
                "chat_id": chat_id
            }
            
        except Exception as e:
            log_message(f"Error unbanning member: {e}")
            return {"error": str(e)}
    
    async def restrict_chat_member(self, chat_id: str, user_id: int,
                                permissions: Dict[str, Any],
                                use_independent_chat_permissions: bool = False,
                                use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Restrict a member's permissions
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID to restrict
            permissions: Dictionary of permissions
            use_independent_chat_permissions: Use independent chat permissions
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Operation result
        """
        try:
            from telegram import ChatPermissions
            
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            # Create ChatPermissions object
            chat_permissions = ChatPermissions(
                can_send_messages=permissions.get('can_send_messages', True),
                can_send_media_messages=permissions.get('can_send_media_messages', True),
                can_send_polls=permissions.get('can_send_polls', True),
                can_send_other_messages=permissions.get('can_send_other_messages', True),
                can_add_web_page_previews=permissions.get('can_add_web_page_previews', True),
                can_change_info=permissions.get('can_change_info', False),
                can_invite_users=permissions.get('can_invite_users', True),
                can_pin_messages=permissions.get('can_pin_messages', False),
                can_manage_topics=permissions.get('can_manage_topics', False)
            )
            
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=chat_permissions,
                use_independent_chat_permissions=use_independent_chat_permissions
            )
            
            log_message(f"Restricted permissions for user {user_id} in chat {chat_id}")
            return {
                "success": True,
                "user_id": user_id,
                "chat_id": chat_id,
                "permissions": permissions
            }
            
        except Exception as e:
            log_message(f"Error restricting member: {e}")
            return {"error": str(e)}
    
    async def promote_chat_member(self, chat_id: str, user_id: int,
                                permissions: Dict[str, Any],
                                use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Promote a member to administrator
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID to promote
            permissions: Dictionary of admin permissions
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Operation result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            await bot.promote_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                can_change_info=permissions.get('can_change_info', False),
                can_post_messages=permissions.get('can_post_messages', False),
                can_edit_messages=permissions.get('can_edit_messages', False),
                can_delete_messages=permissions.get('can_delete_messages', False),
                can_invite_users=permissions.get('can_invite_users', False),
                can_restrict_members=permissions.get('can_restrict_members', False),
                can_pin_messages=permissions.get('can_pin_messages', False),
                can_promote_members=permissions.get('can_promote_members', False),
                can_manage_chat=permissions.get('can_manage_chat', False),
                can_manage_video_chats=permissions.get('can_manage_video_chats', False),
                can_manage_topics=permissions.get('can_manage_topics', False),
                custom_title=permissions.get('custom_title', '')
            )
            
            log_message(f"Promoted user {user_id} to admin in chat {chat_id}")
            return {
                "success": True,
                "user_id": user_id,
                "chat_id": chat_id,
                "permissions": permissions
            }
            
        except Exception as e:
            log_message(f"Error promoting member: {e}")
            return {"error": str(e)}
    
    async def demote_chat_member(self, chat_id: str, user_id: int,
                               use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Demote an administrator to regular member
        
        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID to demote
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Operation result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            await bot.promote_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                can_change_info=False,
                can_post_messages=False,
                can_edit_messages=False,
                can_delete_messages=False,
                can_invite_users=False,
                can_restrict_members=False,
                can_pin_messages=False,
                can_promote_members=False,
                can_manage_chat=False,
                can_manage_video_chats=False,
                can_manage_topics=False
            )
            
            log_message(f"Demoted user {user_id} from admin in chat {chat_id}")
            return {
                "success": True,
                "user_id": user_id,
                "chat_id": chat_id
            }
            
        except Exception as e:
            log_message(f"Error demoting member: {e}")
            return {"error": str(e)}
    
    async def get_chat_info(self, chat_id: str, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Get comprehensive chat information
        
        Args:
            chat_id: Telegram chat ID
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Chat information
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            chat = await bot.get_chat(chat_id)
            
            chat_info = {
                'id': chat.id,
                'type': chat.type,
                'title': chat.title,
                'username': chat.username,
                'first_name': chat.first_name,
                'last_name': chat.last_name,
                'description': chat.description,
                'invite_link': chat.invite_link,
                'pinned_message': None,
                'permissions': None,
                'slow_mode_delay': getattr(chat, 'slow_mode_delay', None),
                'message_auto_delete_time': getattr(chat, 'message_auto_delete_time', None),
                'has_protected_content': getattr(chat, 'has_protected_content', None),
                'sticker_set_name': getattr(chat, 'sticker_set_name', None),
                'can_set_sticker_set': getattr(chat, 'can_set_sticker_set', None),
                'linked_chat_id': getattr(chat, 'linked_chat_id', None),
                'location': getattr(chat, 'location', None),
                'bio': getattr(chat, 'bio', None)
            }
            
            # Get member count
            try:
                member_count = await chat.get_member_count()
                chat_info['member_count'] = member_count
            except:
                chat_info['member_count'] = None
            
            log_message(f"Retrieved chat info for {chat_id}")
            return chat_info
            
        except Exception as e:
            log_message(f"Error getting chat info: {e}")
            return {"error": str(e)}


# Global instance
GROUP_MANAGER = TelegramGroupManager()


# MCP Tool Functions for AI integration
async def get_chat_administrators_mcp(chat_id: str, use_ops_bot: bool = False) -> str:
    """MCP function to get chat administrators"""
    result = await GROUP_MANAGER.get_chat_administrators(chat_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def get_chat_member_mcp(chat_id: str, user_id: int, use_ops_bot: bool = False) -> str:
    """MCP function to get chat member info"""
    result = await GROUP_MANAGER.get_chat_member(chat_id, user_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def get_chat_member_count_mcp(chat_id: str, use_ops_bot: bool = False) -> str:
    """MCP function to get chat member count"""
    result = await GROUP_MANAGER.get_chat_member_count(chat_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def get_chat_info_mcp(chat_id: str, use_ops_bot: bool = False) -> str:
    """MCP function to get chat information"""
    result = await GROUP_MANAGER.get_chat_info(chat_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def ban_chat_member_mcp(chat_id: str, user_id: int, 
                             until_date: Optional[int] = None,
                             revoke_messages: bool = True,
                             use_ops_bot: bool = False) -> str:
    """MCP function to ban chat member"""
    result = await GROUP_MANAGER.ban_chat_member(chat_id, user_id, until_date, revoke_messages, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def unban_chat_member_mcp(chat_id: str, user_id: int, 
                               only_if_banned: bool = True,
                               use_ops_bot: bool = False) -> str:
    """MCP function to unban chat member"""
    result = await GROUP_MANAGER.unban_chat_member(chat_id, user_id, only_if_banned, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def restrict_chat_member_mcp(chat_id: str, user_id: int,
                                  permissions: Dict[str, Any],
                                  use_independent_chat_permissions: bool = False,
                                  use_ops_bot: bool = False) -> str:
    """MCP function to restrict chat member"""
    result = await GROUP_MANAGER.restrict_chat_member(chat_id, user_id, permissions, 
                                                    use_independent_chat_permissions, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def promote_chat_member_mcp(chat_id: str, user_id: int,
                                  permissions: Dict[str, Any],
                                  use_ops_bot: bool = False) -> str:
    """MCP function to promote chat member"""
    result = await GROUP_MANAGER.promote_chat_member(chat_id, user_id, permissions, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def demote_chat_member_mcp(chat_id: str, user_id: int,
                                use_ops_bot: bool = False) -> str:
    """MCP function to demote chat member"""
    result = await GROUP_MANAGER.demote_chat_member(chat_id, user_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)
