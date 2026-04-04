#!/usr/bin/env python3
"""
Token-Optimized Chat Interface to prevent API limit exceeded errors
"""

import asyncio
import os
import json
from datetime import datetime
from collections import deque

class TokenOptimizedChatInterface:
    """Chat interface with strict token limits and optimization"""
    
    def __init__(self):
        self.max_history_length = 3  # Reduced from 10
        self.max_response_length = 300  # Limit AI responses
        self.response_cache = {}  # Cache common responses
        self.request_queue = deque()  # Queue for batching
        self.last_request_time = {}
        self.rate_limit = {
            "max_requests_per_minute": 5,
            "max_tokens_per_hour": 10000
        }
        self.current_hour_usage = 0
        self.current_minute_requests = 0
        self.chat_memory = {}  # Initialize chat memory
        
    def count_tokens(self, text):
        """Simple token counting (rough estimate: 1 token ≈ 4 characters)"""
        return len(text) // 4
    
    def check_rate_limit(self, user_id):
        """Check if user is within rate limits"""
        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        # Reset counters if needed
        if current_hour != self.last_request_time.get('hour'):
            self.current_hour_usage = 0
            self.last_request_time['hour'] = current_hour
            
        if current_minute != self.last_request_time.get('minute'):
            self.current_minute_requests = 0
            self.last_request_time['minute'] = current_minute
        
        # Check limits
        if self.current_hour_usage >= self.rate_limit['max_tokens_per_hour']:
            return False, "Hourly token limit exceeded"
        
        if self.current_minute_requests >= self.rate_limit['max_requests_per_minute']:
            return False, "Minute request limit exceeded"
        
        return True, "OK"
    
    def get_cached_response(self, message_hash):
        """Get cached response if available"""
        return self.response_cache.get(message_hash)
    
    def cache_response(self, message_hash, response):
        """Cache response for future use"""
        if len(self.response_cache) < 100:  # Limit cache size
            self.response_cache[message_hash] = response
    
    def truncate_history(self, history):
        """Truncate history to stay within token limits"""
        if len(history) > self.max_history_length:
            return history[-self.max_history_length:]
        return history
    
    async def optimized_analyze_message(self, chat_id, user_id, message_text):
        """Optimized message analysis with token limits"""
        try:
            # Check rate limits
            can_proceed, reason = self.check_rate_limit(user_id)
            if not can_proceed:
                return {
                    "success": False,
                    "error": f"Rate limit exceeded: {reason}",
                    "suggestion": "Please wait before making another request"
                }
            
            # Check cache first
            message_hash = hash(message_text.lower().strip())
            cached = self.get_cached_response(message_hash)
            if cached:
                return {
                    "success": True,
                    "response": cached,
                    "cached": True,
                    "tokens_saved": self.count_tokens(cached)
                }
            
            # Truncate history to save tokens
            if chat_id not in self.chat_memory:
                self.chat_memory[chat_id] = []
            
            self.chat_memory[chat_id] = self.truncate_history(self.chat_memory[chat_id])
            
            # Create minimal prompt
            minimal_prompt = f"""
            Brief trading question: {message_text}
            Give short, helpful answer (max {self.max_response_length} characters).
            Focus on practical advice.
            """
            
            # Count tokens before request
            prompt_tokens = self.count_tokens(minimal_prompt)
            
            if prompt_tokens > 500:  # Safety check
                return {
                    "success": False,
                    "error": "Prompt too long",
                    "suggestion": "Please shorten your question"
                }
            
            # Make AI request
            from openrouter_intelligence import OpenRouterIntelligence
            ai = OpenRouterIntelligence()
            
            try:
                response = ai.query_ai(minimal_prompt)
                
                # Truncate response if too long
                if len(response) > self.max_response_length:
                    response = response[:self.max_response_length] + "..."
                
                # Cache the response
                self.cache_response(message_hash, response)
                
                # Update usage counters
                self.current_hour_usage += prompt_tokens + self.count_tokens(response)
                self.current_minute_requests += 1
                
                return {
                    "success": True,
                    "response": response,
                    "tokens_used": prompt_tokens + self.count_tokens(response),
                    "cached": False
                }
                
            except Exception as e:
                if "limit exceeded" in str(e).lower():
                    return {
                        "success": False,
                        "error": "API token limit exceeded",
                        "suggestion": "Please upgrade your OpenRouter plan or wait for reset",
                        "upgrade_link": "https://openrouter.ai/settings/credits"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"AI service error: {e}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": f"Chat interface error: {e}"
            }
    
    def get_usage_stats(self):
        """Get current usage statistics"""
        return {
            "current_hour_usage": self.current_hour_usage,
            "current_minute_requests": self.current_minute_requests,
            "cache_size": len(self.response_cache),
            "rate_limits": self.rate_limit,
            "memory_usage": len(self.chat_memory)
        }

# Global optimized instance
OPTIMIZED_CHAT_INTERFACE = TokenOptimizedChatInterface()

# Update the original chat interface to use optimized version
async def send_optimized_message(chat_id, text, **kwargs):
    """Send message with token optimization"""
    from telegram_chat_interface import CHAT_INTERFACE
    
    # Check if message is too long
    if len(text) > 1000:
        text = text[:1000] + "... (truncated to save tokens)"
    
    return await CHAT_INTERFACE.send_message(chat_id, text, **kwargs)

async def analyze_user_message_optimized(chat_id, user_id, message_text, use_ops_bot=False):
    """Optimized user message analysis"""
    result = await OPTIMIZED_CHAT_INTERFACE.optimized_analyze_message(
        chat_id, user_id, message_text
    )
    
    if result.get("success"):
        # Send optimized response
        response_text = result["response"]
        if result.get("cached"):
            response_text = f"🤖 (Cached Response)\n\n{response_text}"
        
        await send_optimized_message(chat_id, response_text, use_ops_bot=use_ops_bot)
    
    return result

if __name__ == "__main__":
    print("🔧 Token-Optimized Chat Interface Ready")
    print("📊 Usage Stats:", json.dumps(OPTIMIZED_CHAT_INTERFACE.get_usage_stats(), indent=2))
