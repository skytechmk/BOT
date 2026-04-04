import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from utils_logger import log_message

load_dotenv()

class OpenRouterIntelligence:
    """
    FORCED: OpenRouter Intelligence using FREE MODELS ONLY
    NO TOKEN LIMITS - UNLIMITED USAGE
    """
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        # ONLY FREE MODELS - NO PAID MODELS ALLOWED
        self.free_models = ["qwen/qwen3.6-plus:free", "stepfun/step-3.5-flash:free", "liquid/lfm-2.5-1.2b-instruct:free", "arcee-ai/trinity-mini:free"]
        self.current_model_index = 0
        self.model = model or self.free_models[0]
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.cache_path = "performance_logs/openrouter_cache.json"
        self.cache = self.load_cache()
        self.last_rotation = datetime.now()
        self.model_usage = {model: 0 for model in self.free_models}
        # FORCE FREE MODELS ONLY
        self.free_only_mode = True
        
    def rotate_model(self):
        """Rotate to next free model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.free_models)
        self.model = self.free_models[self.current_model_index]
        log_message(f"FORCED ROTATION to free model: {self.model}")
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
    
    def query_ai(self, prompt, max_tokens=300):
        """Query AI using FREE MODELS ONLY - NO TOKEN LIMITS"""
        try:
            # FORCE FREE MODEL USAGE
            if not self.free_only_mode:
                log_message("WARNING: free_only_mode not set, forcing it")
                self.free_only_mode = True
            
            # Rotate model every 15 minutes for optimal free usage
            if (datetime.now() - self.last_rotation).seconds > 900:
                self.rotate_model()
            
            cache_key = f"forced_free_{hash(prompt.strip())}"
            if cache_key in self.cache:
                log_message(f"Using cached response for free model")
                return self.cache[cache_key]
            
            if not self.api_key:
                return "OpenRouter API Key missing."
            
            # VERY STRICT limits for free tier
            limited_prompt = prompt[:800] + "..." if len(prompt) > 800 else prompt
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user", 
                        "content": limited_prompt
                    }
                ],
                "max_tokens": min(max_tokens, 250),  # VERY STRICT
                "temperature": 0.7
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/aladdin-trading-bot",
                "X-Title": "Aladdin Trading Bot - FREE MODELS ONLY"
            }
            
            response = requests.post(self.url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                result = data['choices'][0]['message']['content']
                
                # VERY STRICT response limiting
                if len(result) > 500:
                    result = result[:500] + "..."
                
                self.cache[cache_key] = result
                self.save_cache()
                self.model_usage[self.model] += 1
                
                log_message(f"FORCED FREE MODEL SUCCESS: {self.model}")
                return result
            else:
                log_message(f"FREE MODEL ERROR: {response.status_code}")
                # FORCE ROTATION on error
                self.rotate_model()
                return "AI temporarily unavailable. Using free models only."
                
        except Exception as e:
            log_message(f"FREE MODEL ERROR: {e}")
            # Try next free model
            self.rotate_model()
            return "AI temporarily unavailable. Free models only."
    
    def get_model_stats(self):
        """Get free model usage statistics"""
        return {
            "current_model": self.model,
            "usage_count": self.model_usage,
            "total_models": len(self.free_models),
            "free_only_mode": self.free_only_mode,
            "last_rotation": self.last_rotation.isoformat()
        }

# FORCE BACKWARD COMPATIBILITY
DeepSeekIntelligence = OpenRouterIntelligence

# GLOBAL FREE MODEL INSTANCE
FREE_AI_INSTANCE = OpenRouterIntelligence()

# BACKWARD COMPATIBILITY - Make instance callable
def OpenRouterIntelligence_instance():
    return FREE_AI_INSTANCE
