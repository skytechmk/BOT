import json
import os
import time

class ChatMemoryManager:
    """Manages short-term conversation context for AI Chat"""
    def __init__(self, max_history=15):
        self.max_history = max_history
        self.memories = {} # chat_id -> [messages]
        self.memory_file = "performance_logs/chat_history.json"
        self.load_memory()

    def load_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r') as f:
                    self.memories = json.load(f)
            except Exception:
                self.memories = {}

    def save_memory(self):
        try:
            os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
            with open(self.memory_file, 'w') as f:
                json.dump(self.memories, f, indent=2)
        except Exception:
            pass

    def add_message(self, chat_id, role, content, **kwargs):
        chat_id = str(chat_id)
        if chat_id not in self.memories:
            self.memories[chat_id] = []
        
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.memories[chat_id].append(msg)
        
        # Keep only the last N messages
        if len(self.memories[chat_id]) > self.max_history:
            self.memories[chat_id] = self.memories[chat_id][-self.max_history:]
            
        self.save_memory()

    def get_messages(self, chat_id, system_prompt=None):
        chat_id = str(chat_id)
        history = self.memories.get(chat_id, [])
        
        if system_prompt:
            return [{"role": "system", "content": system_prompt}] + history
        return history

    def clear_memory(self, chat_id):
        chat_id = str(chat_id)
        if chat_id in self.memories:
            del self.memories[chat_id]
            self.save_memory()

# Singleton instance
CHAT_MEMORY = ChatMemoryManager()
