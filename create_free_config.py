#!/usr/bin/env python3
"""
Create working free models configuration
"""

import os
import json

def create_working_free_config():
    """Create configuration with working free models"""
    
    # Working free models from testing
    working_models = [
        "qwen/qwen3.6-plus:free",
        "stepfun/step-3.5-flash:free", 
        "liquid/lfm-2.5-1.2b-instruct:free",
        "arcee-ai/trinity-mini:free"
    ]
    
    config_content = '''import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from utils_logger import log_message

load_dotenv()

class OpenRouterIntelligence:
    """
    OpenRouter Intelligence using VERIFIED FREE MODELS
    Rotates through working free models to avoid token limits
    """
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        # Verified working free models
        self.free_models = ''' + json.dumps(working_models) + '''
        self.current_model_index = 0
        self.model = model or self.free_models[0]
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.cache_path = "performance_logs/openrouter_cache.json"
        self.cache = self.load_cache()
        self.last_rotation = datetime.now()
        self.model_usage = {model: 0 for model in self.free_models}
        
    def rotate_model(self):
        """Rotate to next working free model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.free_models)
        self.model = self.free_models[self.current_model_index]
        log_message(f"Rotated to working free model: {self.model}")
        self.last_rotation = datetime.now()
        
    def load_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass
    
    def query_ai(self, prompt, max_tokens=400):
        """Query AI using verified working free models"""
        try:
            # Rotate model every 30 minutes for free tier
            if (datetime.now() - self.last_rotation).seconds > 1800:
                self.rotate_model()
            
            cache_key = f"verified_free_{hash(prompt.strip())}"
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            if not self.api_key:
                return "OpenRouter API Key missing."
            
            # Strict limits for free models
            limited_prompt = prompt[:1000] + "..." if len(prompt) > 1000 else prompt
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user", 
                        "content": limited_prompt
                    }
                ],
                "max_tokens": min(max_tokens, 300),  # Very strict limit
                "temperature": 0.7
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/aladdin-trading-bot",
                "X-Title": "Aladdin Trading Bot - Verified Free Models"
            }
            
            response = requests.post(self.url, json=payload, headers=headers, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                result = data['choices'][0]['message']['content']
                
                # Limit response length to save tokens
                if len(result) > 600:
                    result = result[:600] + "..."
                
                self.cache[cache_key] = result
                self.save_cache()
                self.model_usage[self.model] += 1
                
                log_message(f"Verified free model response: {self.model}")
                return result
            else:
                log_message(f"Verified free model error: {response.status_code}")
                # Try next working model
                self.rotate_model()
                return "AI service temporarily unavailable. Please try again."
                
        except Exception as e:
            log_message(f"Verified free model query error: {e}")
            return "AI service temporarily unavailable. Please try again."
    
    def get_model_stats(self):
        """Get usage statistics for working models"""
        return {
            "current_model": self.model,
            "usage_count": self.model_usage,
            "total_models": len(self.free_models),
            "last_rotation": self.last_rotation.isoformat()
        }

# Alias for backward compatibility
DeepSeekIntelligence = OpenRouterIntelligence
'''
    
    # Write the configuration
    with open('openrouter_intelligence.py', 'w') as f:
        f.write(config_content)
    
    print(f"✅ Configuration updated with {len(working_models)} working free models")
    return True

if __name__ == "__main__":
    create_working_free_config()
