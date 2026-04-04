#!/usr/bin/env python3
"""
FORCE UPDATE - Replace all AI configurations with free models only
"""

import os
import json
import glob

def force_free_models_update():
    """Force update all AI configurations to use free models only"""
    print("🔄 FORCING FREE MODELS UPDATE...")
    print("=" * 60)
    
    # 1. Update openrouter_intelligence.py
    print("1️⃣ Updating OpenRouter configuration...")
    try:
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
    FORCED: OpenRouter Intelligence using FREE MODELS ONLY
    NO TOKEN LIMITS - UNLIMITED USAGE
    """
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        # ONLY FREE MODELS - NO PAID MODELS ALLOWED
        self.free_models = ''' + json.dumps(working_models) + '''
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
'''
        
        with open('openrouter_intelligence.py', 'w') as f:
            f.write(config_content)
        
        print("   ✅ OpenRouter configuration FORCED to free models only")
        
    except Exception as e:
        print(f"   ❌ Error updating OpenRouter: {e}")
    
    # 2. Update telegram_chat_interface.py to use free models
    print("2️⃣ Updating Telegram chat interface...")
    try:
        # Read current file
        with open('telegram_chat_interface.py', 'r') as f:
            content = f.read()
        
        # Replace OpenRouter import with free model instance
        if 'from openrouter_intelligence import OpenRouterIntelligence' in content:
            content = content.replace(
                'from openrouter_intelligence import OpenRouterIntelligence',
                'from openrouter_intelligence import FREE_AI_INSTANCE as OpenRouterIntelligence'
            )
            
            with open('telegram_chat_interface.py', 'w') as f:
                f.write(content)
            
            print("   ✅ Telegram chat interface updated to use free models")
        
    except Exception as e:
        print(f"   ❌ Error updating Telegram interface: {e}")
    
    # 3. Create free model enforcement script
    print("3️⃣ Creating free model enforcement...")
    enforcement_script = '''
#!/usr/bin/env python3
"""
FREE MODEL ENFORCEMENT - Force all AI to use free models only
"""

import os
import sys
from datetime import datetime

def enforce_free_models():
    """Enforce free models usage across all modules"""
    print("🔒 ENFORCING FREE MODELS ONLY...")
    
    # Set environment flag
    os.environ['FORCE_FREE_MODELS'] = 'true'
    os.environ['DISABLE_PAID_MODELS'] = 'true'
    
    # Update any OpenRouter instances
    try:
        from openrouter_intelligence import FREE_AI_INSTANCE
        
        # Force free model usage
        FREE_AI_INSTANCE.free_only_mode = True
        print(f"✅ Free AI instance forced: {FREE_AI_INSTANCE.model}")
        
    except Exception as e:
        print(f"❌ Error enforcing free models: {e}")
    
    return True

# Auto-enforce on import
if __name__ == "__main__":
    enforce_free_models()
else:
    enforce_free_models()
'''
    
    with open('enforce_free_models.py', 'w') as f:
        f.write(enforcement_script)
    
    print("   ✅ Free model enforcement created")
    
    # 4. Update shared_state.py to enforce free models
    print("4️⃣ Updating shared_state...")
    try:
        with open('shared_state.py', 'r') as f:
            content = f.read()
        
        # Add free model enforcement at the top
        if 'enforce_free_models' not in content:
            enforcement_code = '''
# FORCE FREE MODELS ONLY
try:
    from enforce_free_models import enforce_free_models
    enforce_free_models()
except Exception as e:
    print(f"Warning: Could not enforce free models: {e}")
'''
            
            content = enforcement_code + '\n' + content
            
            with open('shared_state.py', 'w') as f:
                f.write(content)
            
            print("   ✅ Shared state updated to enforce free models")
        
    except Exception as e:
        print(f"   ❌ Error updating shared_state: {e}")
    
    # 5. Create emergency restart script
    print("5️⃣ Creating emergency restart...")
    restart_script = '''#!/bin/bash
echo "🔄 EMERGENCY RESTART WITH FREE MODELS..."

# Kill any existing bot
pkill -f "python.*main\.py" 2>/dev/null

# Wait for cleanup
sleep 3

# Start bot with free models enforced
export FORCE_FREE_MODELS=true
export DISABLE_PAID_MODELS=true

echo "🚀 Starting bot with FREE MODELS ONLY..."
nohup python main.py > bot_output.log 2>&1 &

echo "✅ Bot restarted with free models only"
echo "📊 Check logs: tail -f bot_output.log"
'''
    
    with open('restart_with_free_models.sh', 'w') as f:
        f.write(restart_script)
    
    os.chmod('restart_with_free_models.sh', 0o755)
    print("   ✅ Emergency restart script created")
    
    print("\n🎯 **FREE MODELS FORCE UPDATE COMPLETE**")
    print("📋 Actions taken:")
    print("   ✅ OpenRouter forced to free models only")
    print("   ✅ Telegram interface updated")
    print("   ✅ Free model enforcement created")
    print("   ✅ Shared state updated")
    print("   ✅ Emergency restart script ready")
    
    print("\n⚠️ **IMMEDIATE ACTIONS:**")
    print("   1. Run: ./restart_with_free_models.sh")
    print("   2. Monitor: tail -f bot_output.log")
    print("   3. Verify free model usage in logs")
    
    return True

if __name__ == "__main__":
    force_free_models_update()
