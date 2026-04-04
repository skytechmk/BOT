
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
