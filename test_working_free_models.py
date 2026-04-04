#!/usr/bin/env python3
"""
Test and identify working free OpenRouter models
"""

import os
import requests
import json
from datetime import datetime

def test_free_models():
    """Test which free models are actually working"""
    
    # Updated list of potentially working free models
    test_models = [
        "meta-llama/llama-3.1-8b-instruct:free",
        "microsoft/phi-3-medium-128k-instruct:free", 
        "google/gemma-2-9b-it:free",
        "qwen/qwen-2.5-7b-instruct:free",
        "anthropic/claude-3-haiku:free",
        "mistralai/mistral-7b-instruct:free",
        "meta-llama/llama-3.1-70b-instruct:free",
        "google/gemma-7b-it:free",
        "huggingfaceh4/zephyr-7b-beta:free",
        "openchat/openchat-7b:free",
        "teknium/openhermes-2.5-mistral-7b:free"
    ]
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ No API key found")
        return []
    
    working_models = []
    failed_models = []
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/aladdin-trading-bot",
        "X-Title": "Aladdin Trading Bot - Model Testing"
    }
    
    print("🔍 Testing free models...")
    print("=" * 50)
    
    for model in test_models:
        try:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Say 'Hello' in one word."
                    }
                ],
                "max_tokens": 10,
                "temperature": 0.1
            }
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data['choices'][0]['message']['content']
                working_models.append(model)
                print(f"✅ {model} - Working: '{result.strip()}'")
            else:
                failed_models.append((model, response.status_code))
                print(f"❌ {model} - Error {response.status_code}")
                
        except Exception as e:
            failed_models.append((model, str(e)))
            print(f"❌ {model} - Exception: {e}")
    
    print(f"\n📊 Results:")
    print(f"✅ Working models: {len(working_models)}")
    print(f"❌ Failed models: {len(failed_models)}")
    
    if working_models:
        print(f"\n🎯 **WORKING FREE MODELS:**")
        for i, model in enumerate(working_models, 1):
            print(f"   {i}. {model}")
    
    if failed_models:
        print(f"\n❌ **FAILED MODELS:**")
        for model, error in failed_models:
            print(f"   • {model}: {error}")
    
    return working_models

def create_working_config(working_models):
    """Create configuration with only working models"""
    if not working_models:
        print("❌ No working models found")
        return False
    
    config_content = f'''import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from utils_logger import log_message

load_dotenv()

class OpenRouterIntelligence:
    """
    OpenRouter Intelligence using WORKING FREE MODELS ONLY
    Rotates through verified free models to avoid token limits
    """
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        # Only use verified working free models
        self.free_models = {json.dumps([model.strip() for model in working_models])}
        self.current_model_index = 0
        self.model = model or self.free_models[0]
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.cache_path = "performance_logs/openrouter_cache.json"
        self.cache = self.load_cache()
        self.last_rotation = datetime.now()
        self.model_usage = {{model: 0 for model in self.free_models}}
        
    def rotate_model(self):
        """Rotate to next working free model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.free_models)
        self.model = self.free_models[self.current_model_index]
        log_message(f"Rotated to working free model: {{self.model}}")
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
    
    def query_ai(self, prompt, max_tokens=400):
        """Query AI using verified working free models"""
        try:
            # Rotate model every 30 minutes for free tier
            if (datetime.now() - self.last_rotation).seconds > 1800:
                self.rotate_model()
            
            cache_key = f"working_free_{{hash(prompt.strip())}}"
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            if not self.api_key:
                return "OpenRouter API Key missing."
            
            # Strict limits for free models
            limited_prompt = prompt[:1000] + "..." if len(prompt) > 1000 else prompt
            
            payload = {{
                "model": self.model,
                "messages": [
                    {{
                        "role": "user", 
                        "content": limited_prompt
                    }}
                ],
                "max_tokens": min(max_tokens, 300),  # Very strict limit
                "temperature": 0.7
            }}
            
            headers = {{
                "Authorization": f"Bearer {{self.api_key}}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/aladdin-trading-bot",
                "X-Title": "Aladdin Trading Bot - Working Free Models"
            }}
            
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
                
                log_message(f"Working free model response: {{self.model}}")
                return result
            else:
                log_message(f"Working free model error: {{response.status_code}}")
                # Try next working model
                self.rotate_model()
                return "AI service temporarily unavailable. Please try again."
                
        except Exception as e:
            log_message(f"Working free model query error: {{e}}")
            return "AI service temporarily unavailable. Please try again."
    
    def get_model_stats(self):
        """Get usage statistics for working models"""
        return {{
            "current_model": self.model,
            "usage_count": self.model_usage,
            "total_models": len(self.free_models),
            "last_rotation": self.last_rotation.isoformat()
        }}

# Alias for backward compatibility
DeepSeekIntelligence = OpenRouterIntelligence
'''
    
    # Write the updated configuration
    with open('openrouter_intelligence.py', 'w') as f:
        f.write(config_content)
    
    print(f"✅ Updated configuration with {len(working_models)} working free models")
    return True

def main():
    """Main function to test and setup working free models"""
    print("🔍 Testing OpenRouter Free Models...")
    print("=" * 50)
    
    # Test which models work
    working_models = test_free_models()
    
    if working_models:
        # Create configuration with working models
        print(f"\n🔧 Creating configuration with working models...")
        success = create_working_config(working_models)
        
        if success:
            print(f"✅ Configuration updated successfully")
            print(f"📊 Using {len(working_models)} verified working free models")
            
            # Test the new configuration
            print(f"\n🧪 Testing updated configuration...")
            try:
                from openrouter_intelligence import OpenRouterIntelligence
                intel = OpenRouterIntelligence()
                
                result = intel.query_ai("What is 2+2? Answer with just the number.")
                print(f"✅ Test result: {result}")
                
                stats = intel.get_model_stats()
                print(f"📊 Current model: {stats['current_model']}")
                print(f"📊 Available models: {stats['total_models']}")
                
            except Exception as e:
                print(f"❌ Configuration test failed: {e}")
        else:
            print("❌ Failed to create configuration")
    else:
        print("❌ No working free models found")
        print("💡 You may need to upgrade to a paid plan")

if __name__ == "__main__":
    main()
