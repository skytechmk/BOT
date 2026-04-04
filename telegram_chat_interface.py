"""
Telegram Chat Interface Module
Allows AI to have conversations with users in Telegram groups
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from shared_state import log_message

class TelegramChatInterface:
    """Advanced chat interface for AI to interact with users"""
    
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_TOKEN')
        self.ops_token = os.getenv('OPS_TELEGRAM_TOKEN')
        self.main_bot = Bot(token=self.bot_token) if self.bot_token else None
        self.ops_bot = Bot(token=self.ops_token) if self.ops_token else None
        
        # Chat memory for context
        self.chat_memory = {}
        self.user_context = {}
        
    async def send_message(self, chat_id: str, text: str, 
                          reply_to_message_id: Optional[int] = None,
                          parse_mode: Optional[str] = None,
                          use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Send a message to chat
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            reply_to_message_id: Reply to specific message
            parse_mode: HTML/Markdown formatting
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Message sending result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode
            )
            
            # Store in memory
            if chat_id not in self.chat_memory:
                self.chat_memory[chat_id] = []
            
            self.chat_memory[chat_id].append({
                'type': 'ai_message',
                'text': text,
                'message_id': message.message_id,
                'timestamp': datetime.now().isoformat(),
                'bot': 'ops' if use_ops_bot else 'main'
            })
            
            log_message(f"AI sent message to chat {chat_id}")
            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
                "text": text
            }
            
        except Exception as e:
            log_message(f"Error sending message: {e}")
            return {"error": str(e)}
    
    async def send_reply(self, chat_id: str, reply_to_message_id: int, 
                        text: str, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Reply to a specific message
        
        Args:
            chat_id: Telegram chat ID
            reply_to_message_id: Message ID to reply to
            text: Reply text
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Reply result
        """
        return await self.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
            use_ops_bot=use_ops_bot
        )
    
    async def send_inline_keyboard(self, chat_id: str, text: str, 
                                 buttons: List[List[Dict[str, str]]],
                                 use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Send message with inline keyboard buttons
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            buttons: List of button rows [[{text: "Button1", callback_data: "data1"}]]
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Message result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            # Create inline keyboard
            keyboard_buttons = []
            for row in buttons:
                button_row = []
                for button in row:
                    button_row.append(
                        InlineKeyboardButton(
                            text=button['text'],
                            callback_data=button.get('callback_data', ''),
                            url=button.get('url', '')
                        )
                    )
                keyboard_buttons.append(button_row)
            
            reply_markup = InlineKeyboardMarkup(keyboard_buttons)
            
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup
            )
            
            log_message(f"AI sent inline keyboard to chat {chat_id}")
            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
                "text": text,
                "buttons": buttons
            }
            
        except Exception as e:
            log_message(f"Error sending inline keyboard: {e}")
            return {"error": str(e)}
    
    async def forward_message(self, from_chat_id: str, to_chat_id: str,
                            message_id: int, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Forward a message from one chat to another
        
        Args:
            from_chat_id: Source chat ID
            to_chat_id: Destination chat ID
            message_id: Message ID to forward
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Forward result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            message = await bot.forward_message(
                chat_id=to_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            
            log_message(f"AI forwarded message from {from_chat_id} to {to_chat_id}")
            return {
                "success": True,
                "message_id": message.message_id,
                "from_chat_id": from_chat_id,
                "to_chat_id": to_chat_id
            }
            
        except Exception as e:
            log_message(f"Error forwarding message: {e}")
            return {"error": str(e)}
    
    async def edit_message(self, chat_id: str, message_id: int, 
                         text: str, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Edit an existing message
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to edit
            text: New message text
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Edit result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            message = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text
            )
            
            log_message(f"AI edited message {message_id} in chat {chat_id}")
            return {
                "success": True,
                "message_id": message_id,
                "chat_id": chat_id,
                "new_text": text
            }
            
        except Exception as e:
            log_message(f"Error editing message: {e}")
            return {"error": str(e)}
    
    async def delete_message(self, chat_id: str, message_id: int,
                           use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Delete a message
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to delete
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Delete result
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            
            log_message(f"AI deleted message {message_id} in chat {chat_id}")
            return {
                "success": True,
                "message_id": message_id,
                "chat_id": chat_id
            }
            
        except Exception as e:
            log_message(f"Error deleting message: {e}")
            return {"error": str(e)}
    
    async def get_chat_history(self, chat_id: str, limit: int = 50,
                             use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Get recent chat history
        
        Args:
            chat_id: Telegram chat ID
            limit: Number of messages to retrieve
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Chat history
        """
        try:
            bot = self.ops_bot if use_ops_bot else self.main_bot
            if not bot:
                return {"error": "Bot not available"}
            
            # Get chat
            chat = await bot.get_chat(chat_id)
            
            # Get recent messages (this is simplified - in real implementation
            # you'd need to use get_chat_history or store messages)
            
            # For now, return stored memory
            stored_messages = self.chat_memory.get(chat_id, [])
            recent_messages = stored_messages[-limit:] if stored_messages else []
            
            return {
                "success": True,
                "chat_id": chat_id,
                "messages": recent_messages,
                "total_stored": len(stored_messages)
            }
            
        except Exception as e:
            log_message(f"Error getting chat history: {e}")
            return {"error": str(e)}
    
    async def analyze_user_message(self, chat_id: str, user_id: int, 
                                   message_text: str, use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Analyze user message and generate AI response
        
        Args:
            chat_id: Telegram chat ID
            user_id: User ID who sent message
            message_text: The message text
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            AI analysis and response
        """
        try:
            # Store user message
            if chat_id not in self.chat_memory:
                self.chat_memory[chat_id] = []
            
            self.chat_memory[chat_id].append({
                'type': 'user_message',
                'user_id': user_id,
                'text': message_text,
                'timestamp': datetime.now().isoformat()
            })
            
            # Get context
            recent_messages = self.chat_memory[chat_id][-10:]  # Last 10 messages
            
            # Generate AI response
            from openrouter_intelligence import FREE_AI_INSTANCE
            OPENROUTER_INTEL = FREE_AI_INSTANCE
            
            context = "\n".join([
                f"{'AI' if msg['type'] == 'ai_message' else 'User'}: {msg['text']}"
                for msg in recent_messages
            ])
            
            prompt = f"""
            You are a helpful AI assistant in a trading group. 
            Analyze this user message and provide a helpful response:
            
            Recent conversation context:
            {context}
            
            Current message: {message_text}
            
            Provide a helpful, friendly response. If it's about trading, be informative.
            If it's a question, answer clearly. Keep it concise but helpful.
            """
            
            ai_response = OPENROUTER_INTEL.query_ai(prompt)
            
            # Store AI response
            self.chat_memory[chat_id].append({
                'type': 'ai_message',
                'text': ai_response,
                'timestamp': datetime.now().isoformat(),
                'bot': 'ops' if use_ops_bot else 'main'
            })
            
            return {
                "success": True,
                "user_message": message_text,
                "ai_response": ai_response,
                "context_used": len(recent_messages)
            }
            
        except Exception as e:
            log_message(f"Error analyzing user message: {e}")
            return {"error": str(e)}
    
    async def start_conversation(self, chat_id: str, greeting: str = None,
                               use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        Start a conversation with the chat
        
        Args:
            chat_id: Telegram chat ID
            greeting: Custom greeting message
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Conversation start result
        """
        try:
            if not greeting:
                greeting = "👋 Hello! I'm AI assistant. How can I help you today?"
            
            result = await self.send_message(chat_id, greeting, use_ops_bot=use_ops_bot)
            
            if result.get("success"):
                # Initialize chat memory
                if chat_id not in self.chat_memory:
                    self.chat_memory[chat_id] = []
                
                self.chat_memory[chat_id].append({
                    'type': 'conversation_start',
                    'greeting': greeting,
                    'timestamp': datetime.now().isoformat()
                })
            
            return result
            
        except Exception as e:
            log_message(f"Error starting conversation: {e}")
            return {"error": str(e)}
    
    async def end_conversation(self, chat_id: str, farewell: str = None,
                              use_ops_bot: bool = False) -> Dict[str, Any]:
        """
        End a conversation with the chat
        
        Args:
            chat_id: Telegram chat ID
            farewell: Custom farewell message
            use_ops_bot: Use OPS bot instead of main bot
            
        Returns:
            Conversation end result
        """
        try:
            if not farewell:
                farewell = "👋 Goodbye! Feel free to ask if you need help again."
            
            result = await self.send_message(chat_id, farewell, use_ops_bot=use_ops_bot)
            
            if result.get("success"):
                # Mark conversation as ended
                if chat_id in self.chat_memory:
                    self.chat_memory[chat_id].append({
                        'type': 'conversation_end',
                        'farewell': farewell,
                        'timestamp': datetime.now().isoformat()
                    })
            
            return result
            
        except Exception as e:
            log_message(f"Error ending conversation: {e}")
            return {"error": str(e)}
    
    def get_chat_context(self, chat_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get conversation context for AI
        
        Args:
            chat_id: Telegram chat ID
            limit: Number of recent messages
            
        Returns:
            List of recent messages
        """
        if chat_id not in self.chat_memory:
            return []
        
        return self.chat_memory[chat_id][-limit:]
    
    def clear_chat_memory(self, chat_id: str) -> bool:
        """
        Clear chat memory
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            Success status
        """
        if chat_id in self.chat_memory:
            del self.chat_memory[chat_id]
            log_message(f"Cleared chat memory for {chat_id}")
            return True
        return False


# Global instance
CHAT_INTERFACE = TelegramChatInterface()


# MCP Tool Functions for AI integration
async def send_message_mcp(chat_id: str, text: str, 
                          reply_to_message_id: Optional[int] = None,
                          parse_mode: Optional[str] = None,
                          use_ops_bot: bool = False) -> str:
    """MCP function to send message"""
    result = await CHAT_INTERFACE.send_message(chat_id, text, reply_to_message_id, parse_mode, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def send_reply_mcp(chat_id: str, reply_to_message_id: int, 
                        text: str, use_ops_bot: bool = False) -> str:
    """MCP function to send reply"""
    result = await CHAT_INTERFACE.send_reply(chat_id, reply_to_message_id, text, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def send_inline_keyboard_mcp(chat_id: str, text: str, 
                                 buttons: List[List[Dict[str, str]]],
                                 use_ops_bot: bool = False) -> str:
    """MCP function to send inline keyboard"""
    result = await CHAT_INTERFACE.send_inline_keyboard(chat_id, text, buttons, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def forward_message_mcp(from_chat_id: str, to_chat_id: str,
                            message_id: int, use_ops_bot: bool = False) -> str:
    """MCP function to forward message"""
    result = await CHAT_INTERFACE.forward_message(from_chat_id, to_chat_id, message_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def edit_message_mcp(chat_id: str, message_id: int, 
                         text: str, use_ops_bot: bool = False) -> str:
    """MCP function to edit message"""
    result = await CHAT_INTERFACE.edit_message(chat_id, message_id, text, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def delete_message_mcp(chat_id: str, message_id: int,
                           use_ops_bot: bool = False) -> str:
    """MCP function to delete message"""
    result = await CHAT_INTERFACE.delete_message(chat_id, message_id, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def get_chat_history_mcp(chat_id: str, limit: int = 50,
                             use_ops_bot: bool = False) -> str:
    """MCP function to get chat history"""
    result = await CHAT_INTERFACE.get_chat_history(chat_id, limit, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def analyze_user_message_mcp(chat_id: str, user_id: int, 
                                   message_text: str, use_ops_bot: bool = False) -> str:
    """MCP function to analyze user message"""
    result = await CHAT_INTERFACE.analyze_user_message(chat_id, user_id, message_text, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def start_conversation_mcp(chat_id: str, greeting: str = None,
                               use_ops_bot: bool = False) -> str:
    """MCP function to start conversation"""
    result = await CHAT_INTERFACE.start_conversation(chat_id, greeting, use_ops_bot)
    return json.dumps(result, indent=2, default=str)

async def end_conversation_mcp(chat_id: str, farewell: str = None,
                              use_ops_bot: bool = False) -> str:
    """MCP function to end conversation"""
    result = await CHAT_INTERFACE.end_conversation(chat_id, farewell, use_ops_bot)
    return json.dumps(result, indent=2, default=str)
