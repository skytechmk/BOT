import os
import json
import ast
import asyncio
import pandas as pd
from datetime import datetime
from shared_state import SIGNAL_REGISTRY, OPEN_SIGNALS_TRACKER
from data_fetcher import fetch_data, client
from utils_logger import log_message

# MCP Tool Definitions (OpenAI-compatible Schema)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a specific file in the bot directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to the file."}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Overwrite a file with new content. Use with caution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to the file."},
                    "content": {"type": "string", "description": "Full new content for the file."}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_signals",
            "description": "Get a list of all currently active trading signals.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_context",
            "description": "Fetch current market data (price, recent candles) for a specific pair.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pair": {"type": "string", "description": "Trading pair (e.g., BTCUSDT)."},
                    "interval": {"type": "string", "description": "Candle interval (e.g., 1h, 15m).", "default": "1h"}
                },
                "required": ["pair"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_trade_signal",
            "description": "Propose the cancellation of an active signal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "signal_id": {"type": "string", "description": "UUID of the signal."},
                    "reason": {"type": "string", "description": "The logic behind canceling the signal."}
                },
                "required": ["signal_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "quick_security_scan",
            "description": "Perform quick security and complexity scan of the codebase.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "full_code_audit",
            "description": "Perform comprehensive code audit with detailed analysis.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_specific_file",
            "description": "Analyze a specific file for security and complexity issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to analyze."}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_audit_recommendations",
            "description": "Get actionable recommendations based on code audit.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_audit_report",
            "description": "Save audit report to a markdown file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Optional filename for the report."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_administrators",
            "description": "Get list of chat administrators",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_member",
            "description": "Get specific member information",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_member_count",
            "description": "Get total number of members in chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_info",
            "description": "Get comprehensive chat information",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ban_chat_member",
            "description": "Ban a member from the chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID to ban"},
                    "until_date": {"type": "integer", "description": "Date when ban will be lifted (Unix timestamp)"},
                    "revoke_messages": {"type": "boolean", "description": "Whether to delete all messages from user", "default": True},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unban_chat_member",
            "description": "Unban a member from the chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID to unban"},
                    "only_if_banned": {"type": "boolean", "description": "Only unban if user is currently banned", "default": True},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restrict_chat_member",
            "description": "Restrict a member's permissions",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID to restrict"},
                    "permissions": {"type": "object", "description": "Dictionary of permissions"},
                    "use_independent_chat_permissions": {"type": "boolean", "description": "Use independent chat permissions", "default": False},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id", "permissions"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "promote_chat_member",
            "description": "Promote a member to administrator",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID to promote"},
                    "permissions": {"type": "object", "description": "Dictionary of admin permissions"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id", "permissions"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "demote_chat_member",
            "description": "Demote an administrator to regular member",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "Telegram user ID to demote"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message to chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "text": {"type": "string", "description": "Message text"},
                    "reply_to_message_id": {"type": "integer", "description": "Reply to specific message"},
                    "parse_mode": {"type": "string", "description": "HTML/Markdown formatting"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_reply",
            "description": "Reply to a specific message",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "reply_to_message_id": {"type": "integer", "description": "Message ID to reply to"},
                    "text": {"type": "string", "description": "Reply text"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "reply_to_message_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_inline_keyboard",
            "description": "Send message with inline keyboard buttons",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "text": {"type": "string", "description": "Message text"},
                    "buttons": {"type": "array", "description": "List of button rows [[{text: 'Button1', callback_data: 'data1'}]]"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "text", "buttons"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "forward_message",
            "description": "Forward a message from one chat to another",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_chat_id": {"type": "string", "description": "Source chat ID"},
                    "to_chat_id": {"type": "string", "description": "Destination chat ID"},
                    "message_id": {"type": "integer", "description": "Message ID to forward"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["from_chat_id", "to_chat_id", "message_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_message",
            "description": "Edit an existing message",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "message_id": {"type": "integer", "description": "Message ID to edit"},
                    "text": {"type": "string", "description": "New message text"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "message_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_message",
            "description": "Delete a message",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "message_id": {"type": "integer", "description": "Message ID to delete"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "message_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_history",
            "description": "Get recent chat history",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "limit": {"type": "integer", "description": "Number of messages to retrieve", "default": 50},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_user_message",
            "description": "Analyze user message and generate AI response",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "user_id": {"type": "integer", "description": "User ID who sent message"},
                    "message_text": {"type": "string", "description": "The message text"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id", "user_id", "message_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_conversation",
            "description": "Start a conversation with the chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "greeting": {"type": "string", "description": "Custom greeting message"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "end_conversation",
            "description": "End a conversation with the chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "farewell": {"type": "string", "description": "Custom farewell message"},
                    "use_ops_bot": {"type": "boolean", "description": "Use OPS bot instead of main bot", "default": False}
                },
                "required": ["chat_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "autonomous_engagement",
            "description": "Initiate autonomous engagement with random group members",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID (default: main group)"},
                    "force": {"type": "boolean", "description": "Force immediate engagement", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_member_conversation",
            "description": "Initiate conversation with Ops team members",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_type": {"type": "string", "description": "Type of conversation (general, technical, trading, feedback)", "default": "general"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "respond_to_member",
            "description": "Respond to specific Ops team member",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_username": {"type": "string", "description": "Username of member to respond to"},
                    "response_text": {"type": "string", "description": "Response message"}
                },
                "required": ["member_username", "response_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tag_random_member",
            "description": "Tag random Ops team member and start conversation",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_type": {"type": "string", "description": "Type of conversation (general, technical, trading, feedback)", "default": "general"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tag_multiple_members",
            "description": "Tag multiple random Ops team members",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of members to tag (1-5)", "default": 2},
                    "conversation_type": {"type": "string", "description": "Type of conversation (general, technical, trading, feedback)", "default": "general"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_ops_member_list",
            "description": "Get current members of Ops channel",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tag_real_ops_member",
            "description": "Tag a real Ops channel member for conversation",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_type": {"type": "string", "description": "Type of conversation (general, technical, trading, ops_focus)", "default": "general"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_and_tag_real_members",
            "description": "Scan Ops channel and tag multiple real members",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of members to tag (1-5)", "default": 2},
                    "conversation_type": {"type": "string", "description": "Type of conversation (general, technical, trading, ops_focus)", "default": "general"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_all_ops_members",
            "description": "Fetch all Ops channel members using comprehensive methods",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_real_members_combined",
            "description": "Get all real group members combined - no fakes",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_internet",
            "description": "Search the internet for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "engine": {"type": "string", "description": "Search engine (duckduckgo, brave, searx)", "default": "duckduckgo"},
                    "max_results": {"type": "integer", "description": "Maximum number of results", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_trading_news",
            "description": "Search for trading-related news and analysis",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Trading search query", "default": "trading signals"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_market_data",
            "description": "Search for current market data and analysis",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Trading symbol (BTC, ETH, etc.)", "default": "BTC"}
                },
                "required": []
            }
        }
    }
]

class MCPBridge:
    """Executes tools requested by the AI"""
    
    @staticmethod
    def log_expert_action(action_type, details):
        """Persistent audit log for AI developer actions"""
        try:
            log_file = "logs/ai_developer_actions.json"
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": action_type,
                "details": details
            }
            
            history = []
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    try: history = json.load(f)
                    except: history = []
            
            history.append(entry)
            with open(log_file, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            log_message(f"Audit Log Error: {e}")

    @staticmethod
    def read_file(file_path):
        try:
            if not os.path.exists(file_path): return f"Error: File {file_path} not found."
            with open(file_path, 'r') as f:
                content = f.read()
                return f"SUCCESS: Read {len(content)} bytes from {file_path}.\nCONTENT:\n{content}"
        except Exception as e:
            return f"Error reading file: {e}"

    @staticmethod
    def edit_file(file_path, content):
        try:
            # Safety: Ensure it's not trying to delete the OS or sensitive dirs
            if not file_path.endswith(('.py', '.json', '.env', '.txt', '.md')):
                return "REJECTED: Unauthorized file extension."
            
            # Simple AST Validation
            if file_path.endswith('.py'):
                try: ast.parse(content)
                except SyntaxError as e: return f"REJECTED: Syntax error in proposal: {e}"

            with open(file_path, 'w') as f:
                f.write(content)
            
            MCPBridge.log_expert_action("CODE_EDIT", {"file": file_path, "len": len(content)})
            return f"SUCCESS: File {file_path} has been overwritten and verified."
        except Exception as e:
            return f"Error writing file: {e}"

    @staticmethod
    def get_open_signals():
        return json.dumps(OPEN_SIGNALS_TRACKER, indent=2)

    @staticmethod
    def get_market_context(pair, interval='1h'):
        try:
            df = fetch_data(pair, interval=interval)
            if df.empty: return f"Error: No data found for {pair}."
            
            last_candles = df.tail(5).to_dict('records')
            current_price = df.iloc[-1]['close']
            
            return json.dumps({
                "pair": pair,
                "current_price": current_price,
                "recent_candles": last_candles
            }, indent=2)
        except Exception as e:
            return f"Error fetching market data: {e}"

    @staticmethod
    def cancel_trade_signal(signal_id, reason):
        try:
            if signal_id in OPEN_SIGNALS_TRACKER:
                del OPEN_SIGNALS_TRACKER[signal_id]
                MCPBridge.log_expert_action("TRADE_CANCEL", {"id": signal_id, "reason": reason})
                return f"SUCCESS: Signal {signal_id} removed from open tracker. Reason: {reason}"
            return f"Error: Signal {signal_id} not found in active tracker."
        except Exception as e:
            return f"Error canceling trade: {e}"

    @staticmethod
    def quick_security_scan():
        try:
            from ai_audit_interface import quick_security_scan
            result = quick_security_scan()
            MCPBridge.log_expert_action("AUDIT_QUICK", {"type": "security_scan"})
            return f"SUCCESS: Quick security scan completed.\n\n{result}"
        except Exception as e:
            return f"Error during security scan: {e}"

    @staticmethod
    def full_code_audit():
        try:
            from ai_audit_interface import full_code_audit
            result = full_code_audit()
            MCPBridge.log_expert_action("AUDIT_FULL", {"type": "comprehensive"})
            return f"SUCCESS: Full code audit completed.\n\n{result}"
        except Exception as e:
            return f"Error during full audit: {e}"

    @staticmethod
    def analyze_specific_file(file_path):
        try:
            from ai_audit_interface import analyze_specific_file
            result = analyze_specific_file(file_path)
            MCPBridge.log_expert_action("AUDIT_FILE", {"file": file_path})
            return f"SUCCESS: File analysis completed for {file_path}.\n\n{result}"
        except Exception as e:
            return f"Error analyzing file {file_path}: {e}"

    @staticmethod
    def get_audit_recommendations():
        try:
            from ai_audit_interface import get_improvement_recommendations
            result = get_improvement_recommendations()
            MCPBridge.log_expert_action("AUDIT_RECOMMENDATIONS", {"type": "recommendations"})
            return f"SUCCESS: Audit recommendations generated.\n\n{result}"
        except Exception as e:
            return f"Error generating recommendations: {e}"

    @staticmethod
    def save_audit_report(filename=None):
        try:
            from ai_audit_interface import save_audit_report
            result = save_audit_report(filename)
            MCPBridge.log_expert_action("AUDIT_SAVE", {"filename": filename})
            return f"SUCCESS: Audit report saved.\n\n{result}"
        except Exception as e:
            return f"Error saving audit report: {e}"

    @staticmethod
    async def get_chat_administrators(chat_id, use_ops_bot=False):
        try:
            from telegram_group_manager import get_chat_administrators_mcp
            result = await get_chat_administrators_mcp(chat_id, use_ops_bot)
            MCPBridge.log_expert_action("GET_ADMINS", {"chat_id": chat_id})
            return f"SUCCESS: Retrieved administrators.\n\n{result}"
        except Exception as e:
            return f"Error getting administrators: {e}"

    @staticmethod
    async def get_chat_member(chat_id, user_id, use_ops_bot=False):
        try:
            from telegram_group_manager import get_chat_member_mcp
            result = await get_chat_member_mcp(chat_id, user_id, use_ops_bot)
            MCPBridge.log_expert_action("GET_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Retrieved member info.\n\n{result}"
        except Exception as e:
            return f"Error getting member info: {e}"

    @staticmethod
    async def get_chat_member_count(chat_id, use_ops_bot=False):
        try:
            from telegram_group_manager import get_chat_member_count_mcp
            result = await get_chat_member_count_mcp(chat_id, use_ops_bot)
            MCPBridge.log_expert_action("GET_MEMBER_COUNT", {"chat_id": chat_id})
            return f"SUCCESS: Retrieved member count.\n\n{result}"
        except Exception as e:
            return f"Error getting member count: {e}"

    @staticmethod
    async def get_chat_info(chat_id, use_ops_bot=False):
        try:
            from telegram_group_manager import get_chat_info_mcp
            result = await get_chat_info_mcp(chat_id, use_ops_bot)
            MCPBridge.log_expert_action("GET_CHAT_INFO", {"chat_id": chat_id})
            return f"SUCCESS: Retrieved chat info.\n\n{result}"
        except Exception as e:
            return f"Error getting chat info: {e}"

    @staticmethod
    async def ban_chat_member(chat_id, user_id, until_date=None, revoke_messages=True, use_ops_bot=False):
        try:
            from telegram_group_manager import ban_chat_member_mcp
            result = await ban_chat_member_mcp(chat_id, user_id, until_date, revoke_messages, use_ops_bot)
            MCPBridge.log_expert_action("BAN_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Member banned.\n\n{result}"
        except Exception as e:
            return f"Error banning member: {e}"

    @staticmethod
    async def unban_chat_member(chat_id, user_id, only_if_banned=True, use_ops_bot=False):
        try:
            from telegram_group_manager import unban_chat_member_mcp
            result = await unban_chat_member_mcp(chat_id, user_id, only_if_banned, use_ops_bot)
            MCPBridge.log_expert_action("UNBAN_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Member unbanned.\n\n{result}"
        except Exception as e:
            return f"Error unbanning member: {e}"

    @staticmethod
    async def restrict_chat_member(chat_id, user_id, permissions, use_independent_chat_permissions=False, use_ops_bot=False):
        try:
            from telegram_group_manager import restrict_chat_member_mcp
            result = await restrict_chat_member_mcp(chat_id, user_id, permissions, use_independent_chat_permissions, use_ops_bot)
            MCPBridge.log_expert_action("RESTRICT_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Member restricted.\n\n{result}"
        except Exception as e:
            return f"Error restricting member: {e}"

    @staticmethod
    async def promote_chat_member(chat_id, user_id, permissions, use_ops_bot=False):
        try:
            from telegram_group_manager import promote_chat_member_mcp
            result = await promote_chat_member_mcp(chat_id, user_id, permissions, use_ops_bot)
            MCPBridge.log_expert_action("PROMOTE_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Member promoted.\n\n{result}"
        except Exception as e:
            return f"Error promoting member: {e}"

    @staticmethod
    async def demote_chat_member(chat_id, user_id, use_ops_bot=False):
        try:
            from telegram_group_manager import demote_chat_member_mcp
            result = await demote_chat_member_mcp(chat_id, user_id, use_ops_bot)
            MCPBridge.log_expert_action("DEMOTE_MEMBER", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Member demoted.\n\n{result}"
        except Exception as e:
            return f"Error demoting member: {e}"

    @staticmethod
    async def send_message(chat_id, text, reply_to_message_id=None, parse_mode=None, use_ops_bot=False):
        try:
            from telegram_chat_interface import send_message_mcp
            result = await send_message_mcp(chat_id, text, reply_to_message_id, parse_mode, use_ops_bot)
            MCPBridge.log_expert_action("SEND_MESSAGE", {"chat_id": chat_id})
            return f"SUCCESS: Message sent.\n\n{result}"
        except Exception as e:
            return f"Error sending message: {e}"

    @staticmethod
    async def send_reply(chat_id, reply_to_message_id, text, use_ops_bot=False):
        try:
            from telegram_chat_interface import send_reply_mcp
            result = await send_reply_mcp(chat_id, reply_to_message_id, text, use_ops_bot)
            MCPBridge.log_expert_action("SEND_REPLY", {"chat_id": chat_id, "reply_to": reply_to_message_id})
            return f"SUCCESS: Reply sent.\n\n{result}"
        except Exception as e:
            return f"Error sending reply: {e}"

    @staticmethod
    async def send_inline_keyboard(chat_id, text, buttons, use_ops_bot=False):
        try:
            from telegram_chat_interface import send_inline_keyboard_mcp
            result = await send_inline_keyboard_mcp(chat_id, text, buttons, use_ops_bot)
            MCPBridge.log_expert_action("SEND_KEYBOARD", {"chat_id": chat_id})
            return f"SUCCESS: Inline keyboard sent.\n\n{result}"
        except Exception as e:
            return f"Error sending inline keyboard: {e}"

    @staticmethod
    async def forward_message(from_chat_id, to_chat_id, message_id, use_ops_bot=False):
        try:
            from telegram_chat_interface import forward_message_mcp
            result = await forward_message_mcp(from_chat_id, to_chat_id, message_id, use_ops_bot)
            MCPBridge.log_expert_action("FORWARD_MESSAGE", {"from": from_chat_id, "to": to_chat_id})
            return f"SUCCESS: Message forwarded.\n\n{result}"
        except Exception as e:
            return f"Error forwarding message: {e}"

    @staticmethod
    async def edit_message(chat_id, message_id, text, use_ops_bot=False):
        try:
            from telegram_chat_interface import edit_message_mcp
            result = await edit_message_mcp(chat_id, message_id, text, use_ops_bot)
            MCPBridge.log_expert_action("EDIT_MESSAGE", {"chat_id": chat_id, "message_id": message_id})
            return f"SUCCESS: Message edited.\n\n{result}"
        except Exception as e:
            return f"Error editing message: {e}"

    @staticmethod
    async def delete_message(chat_id, message_id, use_ops_bot=False):
        try:
            from telegram_chat_interface import delete_message_mcp
            result = await delete_message_mcp(chat_id, message_id, use_ops_bot)
            MCPBridge.log_expert_action("DELETE_MESSAGE", {"chat_id": chat_id, "message_id": message_id})
            return f"SUCCESS: Message deleted.\n\n{result}"
        except Exception as e:
            return f"Error deleting message: {e}"

    @staticmethod
    async def get_chat_history(chat_id, limit=50, use_ops_bot=False):
        try:
            from telegram_chat_interface import get_chat_history_mcp
            result = await get_chat_history_mcp(chat_id, limit, use_ops_bot)
            MCPBridge.log_expert_action("GET_CHAT_HISTORY", {"chat_id": chat_id})
            return f"SUCCESS: Chat history retrieved.\n\n{result}"
        except Exception as e:
            return f"Error getting chat history: {e}"

    @staticmethod
    async def analyze_user_message(chat_id, user_id, message_text, use_ops_bot=False):
        try:
            from telegram_chat_interface import analyze_user_message_mcp
            result = await analyze_user_message_mcp(chat_id, user_id, message_text, use_ops_bot)
            MCPBridge.log_expert_action("ANALYZE_MESSAGE", {"chat_id": chat_id, "user_id": user_id})
            return f"SUCCESS: Message analyzed.\n\n{result}"
        except Exception as e:
            return f"Error analyzing user message: {e}"

    @staticmethod
    async def start_conversation(chat_id, greeting=None, use_ops_bot=False):
        try:
            from telegram_chat_interface import start_conversation_mcp
            result = await start_conversation_mcp(chat_id, greeting, use_ops_bot)
            MCPBridge.log_expert_action("START_CONVERSATION", {"chat_id": chat_id})
            return f"SUCCESS: Conversation started.\n\n{result}"
        except Exception as e:
            return f"Error starting conversation: {e}"

    @staticmethod
    async def end_conversation(chat_id, farewell=None, use_ops_bot=False):
        try:
            from telegram_chat_interface import end_conversation_mcp
            result = await end_conversation_mcp(chat_id, farewell, use_ops_bot)
            MCPBridge.log_expert_action("END_CONVERSATION", {"chat_id": chat_id})
            return f"SUCCESS: Conversation ended.\n\n{result}"
        except Exception as e:
            return f"Error ending conversation: {e}"

    @staticmethod
    async def autonomous_engagement(chat_id=None, force=False):
        try:
            from ops_autonomous_engagement import send_ops_autonomous_engagement
            import json
            from datetime import datetime
            
            if not chat_id:
                chat_id = '-1003706659588'  # Default to Ops chat
            
            if force:
                result = await send_ops_autonomous_engagement()
                MCPBridge.log_expert_action("OPS_AUTONOMOUS_ENGAGEMENT", {"chat_id": chat_id, "forced": force})
                return json.dumps({
                    "success": result,
                    "chat_id": chat_id,
                    "action": "forced_ops_autonomous_engagement",
                    "timestamp": datetime.now().isoformat()
                }, indent=2)
            else:
                return json.dumps({
                    "success": True,
                    "message": "Ops autonomous engagement scheduler is running",
                    "chat_id": chat_id,
                    "status": "ops_scheduler_active"
                }, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @staticmethod
    async def initiate_member_conversation(conversation_type="general"):
        try:
            from ops_member_communicator import initiate_member_conversation
            result = await initiate_member_conversation(conversation_type)
            MCPBridge.log_expert_action("MEMBER_CONVERSATION_INITIATED", {"conversation_type": conversation_type})
            return result
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @staticmethod
    async def respond_to_member(member_username, response_text):
        try:
            from ops_member_communicator import respond_to_member
            result = await respond_to_member(member_username, response_text)
            MCPBridge.log_expert_action("MEMBER_RESPONSE_SENT", {"member_username": member_username})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def tag_random_member(conversation_type="general"):
        try:
            from simple_random_tagger import tag_random_member_simple
            result = await tag_random_member_simple(conversation_type)
            MCPBridge.log_expert_action("RANDOM_MEMBER_TAGGED", {"conversation_type": conversation_type})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def tag_multiple_members(count=2, conversation_type="general"):
        try:
            from random_member_tagger import tag_multiple_members
            result = await tag_multiple_members(count, conversation_type)
            MCPBridge.log_expert_action("MULTIPLE_MEMBERS_TAGGED", {"count": count, "conversation_type": conversation_type})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def get_ops_member_list():
        try:
            from real_ops_member_tagger import get_ops_member_list
            result = await get_ops_member_list()
            MCPBridge.log_expert_action("OPS_MEMBER_LIST_RETRIEVED", {})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def tag_real_ops_member(conversation_type="general"):
        try:
            from hybrid_ops_tagger import tag_ops_member_hybrid
            result = await tag_ops_member_hybrid(conversation_type)
            MCPBridge.log_expert_action("REAL_OPS_MEMBER_TAGGED", {"conversation_type": conversation_type})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def scan_and_tag_real_members(count=2, conversation_type="general"):
        try:
            from real_ops_member_tagger import scan_and_tag_real_members
            result = await scan_and_tag_real_members(count, conversation_type)
            MCPBridge.log_expert_action("SCAN_AND_TAG_REAL_MEMBERS", {"count": count, "conversation_type": conversation_type})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def fetch_all_ops_members():
        try:
            from advanced_member_fetcher import fetch_all_ops_members
            result = await fetch_all_ops_members()
            MCPBridge.log_expert_action("ALL_OPS_MEMBERS_FETCHED", {})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def get_real_members_combined():
        try:
            from real_members_group_manager import get_real_members_combined
            result = await get_real_members_combined()
            MCPBridge.log_expert_action("REAL_MEMBERS_COMBINED_FETCHED", {})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def search_internet(query, engine="duckduckgo", max_results=5):
        try:
            from ai_internet_search import search_internet
            result = await search_internet(query, engine, max_results)
            MCPBridge.log_expert_action("INTERNET_SEARCH_PERFORMED", {"query": query, "engine": engine})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def search_trading_news(query="trading signals"):
        try:
            from ai_internet_search import search_trading_news
            result = await search_trading_news(query)
            MCPBridge.log_expert_action("TRADING_NEWS_SEARCHED", {"query": query})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    async def search_market_data(symbol="BTC"):
        try:
            from ai_internet_search import search_market_data
            result = await search_market_data(symbol)
            MCPBridge.log_expert_action("MARKET_DATA_SEARCHED", {"symbol": symbol})
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @staticmethod
    def _run_async(coro):
        """Safely run an async coroutine from sync context.
        
        Handles the 'Event loop is closed' error by always creating
        a fresh loop when needed, without polluting the global state.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
            if loop.is_running():
                # We're inside an already-running loop (e.g. Jupyter, nested call).
                # Spin up a background thread to run the coroutine.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No loop or loop closed – create a brand-new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    # Sync tools (no event loop needed)
    _SYNC_TOOLS = {
        "read_file", "edit_file", "get_open_signals", "get_market_context",
        "cancel_trade_signal", "quick_security_scan", "full_code_audit",
        "analyze_specific_file", "get_audit_recommendations", "save_audit_report",
    }

    @classmethod
    def execute_tool(cls, name, args):
        """Dynamic tool execution router"""
        log_message(f"AI Tool Call: {name}({args})")
        
        # Sync tools — call directly
        if name in cls._SYNC_TOOLS:
            method = getattr(cls, name, None)
            if method:
                return method(**args) if args else method()
            return f"Error: Tool {name} not implemented."

        # Async tools — look up method and run via _run_async
        method = getattr(cls, name, None)
        if method is None:
            return f"Error: Tool {name} not implemented."

        try:
            coro = method(**args) if args else method()
            return cls._run_async(coro)
        except Exception as e:
            log_message(f"Error executing tool {name}: {e}")
            return json.dumps({"success": False, "error": str(e)})

def get_mcp_tools_schema():
    return TOOLS
