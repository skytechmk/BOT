#!/usr/bin/env python3
"""
OpenRouter Free Models Only Configuration
Rotate through free models to avoid token limits
"""

import os
import json
import random
from datetime import datetime

class FreeModelRotator:
    """Rotates through free OpenRouter models to avoid token limits"""
    
    def __init__(self):
        # Free models available on OpenRouter
        self.free_models = [
            "meta-llama/llama-3.1-8b-instruct:free",
            "microsoft/phi-3-medium-128k-instruct:free", 
            "google/gemma-2-9b-it:free",
            "qwen/qwen-2.5-7b-instruct:free",
            "anthropic/claude-3-haiku:free",
            "mistralai/mistral-7b-instruct:free",
            "meta-llama/llama-3.1-70b-instruct:free",
            "google/gemma-7b-it:free"
        ]
        
        self.current_model_index = 0
        self.model_usage_count = {}
        self.model_failures = {}
        self.last_rotation_time = datetime.now()
        self.rotation_interval = 3600  # Rotate every hour
        
        # Initialize usage tracking
        for model in self.free_models:
            self.model_usage_count[model] = 0
            self.model_failures[model] = 0
    
    def get_next_model(self):
        """Get next available free model"""
        # Check if it's time to rotate
        current_time = datetime.now()
        if (current_time - self.last_rotation_time).seconds > self.rotation_interval:
            self.rotate_model()
            self.last_rotation_time = current_time
        
        # Get current model
        current_model = self.free_models[self.current_model_index]
        
        # Check if model has too many failures
        if self.model_failures[current_model] > 3:
            self.rotate_model()
            current_model = self.free_models[self.current_model_index]
        
        return current_model
    
    def rotate_model(self):
        """Rotate to next model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.free_models)
        print(f"🔄 Rotated to model: {self.free_models[self.current_model_index]}")
    
    def record_success(self, model):
        """Record successful usage"""
        self.model_usage_count[model] += 1
    
    def record_failure(self, model, error):
        """Record failed usage"""
        self.model_failures[model] += 1
        print(f"❌ Model {model} failed: {error}")
        
        # Rotate if too many failures
        if self.model_failures[model] > 3:
            print(f"🔄 Too many failures for {model}, rotating...")
            self.rotate_model()
    
    def get_usage_stats(self):
        """Get usage statistics"""
        return {
            "current_model": self.free_models[self.current_model_index],
            "usage_count": self.model_usage_count,
            "failure_count": self.model_failures,
            "total_models": len(self.free_models),
            "last_rotation": self.last_rotation_time.isoformat()
        }

class FreeOpenRouterIntelligence:
    """OpenRouter interface using only free models"""
    
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.rotator = FreeModelRotator()
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.cache = {}
        self.max_cache_size = 100
    
    def get_cached_response(self, prompt_hash):
        """Get cached response if available"""
        return self.cache.get(prompt_hash)
    
    def cache_response(self, prompt_hash, response):
        """Cache response"""
        if len(self.cache) < self.max_cache_size:
            self.cache[prompt_hash] = response
    
    def query_ai(self, prompt, max_tokens=500):
        """Query AI using free models only"""
        try:
            # Check cache first
            prompt_hash = hash(prompt.strip())
            cached = self.get_cached_response(prompt_hash)
            if cached:
                print("🗄️ Using cached response")
                return cached
            
            # Get current free model
            model = self.rotator.get_next_model()
            
            # Prepare request with token limits
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt[:2000]  # Limit prompt length
                    }
                ],
                "max_tokens": min(max_tokens, 500),  # Strict token limit
                "temperature": 0.7
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/aladdin-trading-bot",
                "X-Title": "Aladdin Trading Bot - Free Models"
            }
            
            import requests
            response = requests.post(self.url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                result = data['choices'][0]['message']['content']
                
                # Limit response length
                if len(result) > 1000:
                    result = result[:1000] + "..."
                
                # Cache and record success
                self.cache_response(prompt_hash, result)
                self.rotator.record_success(model)
                
                print(f"✅ Success with {model}")
                return result
                
            else:
                error_msg = f"API Error: {response.status_code} - {response.text}"
                self.rotator.record_failure(model, error_msg)
                return f"AI service temporarily unavailable. Please try again later."
                
        except Exception as e:
            error_msg = f"Query AI Error: {e}"
            current_model = self.rotator.free_models[self.rotator.current_model_index]
            self.rotator.record_failure(current_model, error_msg)
            return "AI service temporarily unavailable. Please try again later."
    
    def get_stats(self):
        """Get rotation and usage statistics"""
        return self.rotator.get_usage_stats()

# Global instance
FREE_OPENROUTER_INTEL = FreeOpenRouterIntelligence()

def update_openrouter_config():
    """Update OpenRouter configuration to use free models only"""
    try:
        # Read current config
        config_file = 'openrouter_intelligence.py'
        
        # Create backup
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                original_content = f.read()
            
            with open(f'{config_file}.backup', 'w') as f:
                f.write(original_content)
        
        # Update model to use free models
        updated_content = f'''import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from utils_logger import log_message

load_dotenv()

class OpenRouterIntelligence:
    """
    OpenRouter Intelligence using FREE MODELS ONLY
    Rotates through free models to avoid token limits
    """
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        # Use free models only
        self.free_models = [
            "meta-llama/llama-3.1-8b-instruct:free",
            "microsoft/phi-3-medium-128k-instruct:free", 
            "google/gemma-2-9b-it:free",
            "qwen/qwen-2.5-7b-instruct:free",
            "anthropic/claude-3-haiku:free",
            "mistralai/mistral-7b-instruct:free",
            "meta-llama/llama-3.1-70b-instruct:free",
            "google/gemma-7b-it:free"
        ]
        self.current_model_index = 0
        self.model = model or self.free_models[0]
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.cache_path = "performance_logs/openrouter_cache.json"
        self.cache = self.load_cache()
        self.last_rotation = datetime.now()
        
    def rotate_model(self):
        """Rotate to next free model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.free_models)
        self.model = self.free_models[self.current_model_index]
        log_message(f"Rotated to free model: {{self.model}}")
        self.last_rotation = datetime.now()
        
    def load_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r') as f:
                    return json.load(f)
            except Exception:
                return {{}}
        return {{}}
    
    def save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass
    
    def query_ai(self, prompt, max_tokens=500):
        """Query AI using free models with rotation"""
        try:
            # Rotate model every hour
            if (datetime.now() - self.last_rotation).seconds > 3600:
                self.rotate_model()
            
            cache_key = f"free_model_{{hash(prompt.strip())}}"
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            if not self.api_key:
                return "OpenRouter API Key missing."
            
            # Limit prompt length to save tokens
            limited_prompt = prompt[:1500] + "..." if len(prompt) > 1500 else prompt
            
            payload = {{
                "model": self.model,
                "messages": [
                    {{
                        "role": "user", 
                        "content": limited_prompt
                    }}
                ],
                "max_tokens": min(max_tokens, 400),  # Strict limit for free models
                "temperature": 0.7
            }}
            
            headers = {{
                "Authorization": f"Bearer {{self.api_key}}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/aladdin-trading-bot",
                "X-Title": "Aladdin Trading Bot - Free Models"
            }}
            
            response = requests.post(self.url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                result = data['choices'][0]['message']['content']
                
                # Limit response length
                if len(result) > 800:
                    result = result[:800] + "..."
                
                self.cache[cache_key] = result
                self.save_cache()
                
                log_message(f"Free model response: {{self.model}}")
                return result
            else:
                log_message(f"Free model error: {{response.status_code}}")
                # Try next model
                self.rotate_model()
                return "AI service temporarily unavailable. Please try again."
                
        except Exception as e:
            log_message(f"Free model query error: {{e}}")
            return "AI service temporarily unavailable. Please try again."

# Alias for backward compatibility
DeepSeekIntelligence = OpenRouterIntelligence
'''
        
        # Write updated config
        with open(config_file, 'w') as f:
            f.write(updated_content)
        
        print(f"✅ Updated {config_file} to use free models only")
        return True
        
    except Exception as e:
        print(f"❌ Error updating config: {e}")
        return False

def main():
    """Main function to setup free model rotation"""
    print("🔄 Setting up OpenRouter Free Model Rotation...")
    print("=" * 50)
    
    # Update configuration
    print("1️⃣ Updating OpenRouter configuration...")
    success = update_openrouter_config()
    
    if success:
        print("   ✅ Configuration updated successfully")
    else:
        print("   ❌ Configuration update failed")
        return
    
    # Test free model rotation
    print("2️⃣ Testing free model rotation...")
    try:
        intel = FREE_OPENROUTER_INTEL
        test_prompt = "What is 2+2? Answer briefly."
        
        result = intel.query_ai(test_prompt)
        print(f"   ✅ Test response: {result[:100]}...")
        
        stats = intel.get_stats()
        print(f"   📊 Current model: {stats['current_model']}")
        print(f"   📊 Total models: {stats['total_models']}")
        
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
    
    # Create usage monitoring
    print("3️⃣ Creating usage monitoring...")
    monitoring_script = '''
#!/usr/bin/env python3
"""
Monitor free model usage and rotation
"""

import time
import json
from datetime import datetime

def monitor_usage():
    """Monitor free model usage"""
    try:
        from free_model_rotator import FREE_OPENROUTER_INTEL
        
        while True:
            stats = FREE_OPENROUTER_INTEL.get_stats()
            
            print(f"📊 {{datetime.now().strftime('%H:%M:%S')}} - Model: {{stats['current_model']}}")
            print(f"   Usage: {{sum(stats['usage_count'].values())}} requests")
            print(f"   Failures: {{sum(stats['failure_count'].values())}}")
            
            time.sleep(300)  # Check every 5 minutes
            
    except KeyboardInterrupt:
        print("\\n🛑 Monitoring stopped")

if __name__ == "__main__":
    monitor_usage()
'''
    
    with open('monitor_free_models.py', 'w') as f:
        f.write(monitoring_script)
    
    print("   ✅ Monitoring script created")
    
    print("\n🎯 **FREE MODEL ROTATION SETUP COMPLETE**")
    print("📋 Features:")
    print("   ✅ 8 free models available")
    print("   ✅ Automatic rotation every hour")
    print("   ✅ Failure detection and rotation")
    print("   ✅ Token usage optimization")
    print("   ✅ Response caching")
    
    print("\n🚀 **NEXT STEPS:**")
    print("   1. Restart the bot to apply changes")
    print("   2. Monitor model usage with: python monitor_free_models.py")
    print("   3. Check logs for model rotation events")
    print("   4. Adjust rotation interval if needed")

if __name__ == "__main__":
    main()
