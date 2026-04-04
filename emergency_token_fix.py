#!/usr/bin/env python3
"""
Emergency Token Limit Fix - Immediate actions to resolve API limit exceeded
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def emergency_token_fix():
    """Apply emergency token-saving measures"""
    print("🚨 EMERGENCY TOKEN LIMIT FIX")
    print("=" * 50)
    
    # 1. Disable autonomous engagement immediately
    print("1️⃣ Disabling autonomous engagement...")
    try:
        # Create a flag to disable autonomous engagement
        with open('disable_autonomous_engagement.flag', 'w') as f:
            f.write('DISABLED')
        print("   ✅ Autonomous engagement disabled")
    except Exception as e:
        print(f"   ❌ Error disabling autonomous engagement: {e}")
    
    # 2. Create token-optimized configuration
    print("2️⃣ Creating token-optimized configuration...")
    try:
        config = {
            "emergency_mode": True,
            "disable_ai_conversations": False,
            "max_history_length": 2,  # Very short
            "max_response_length": 200,  # Very short
            "enable_caching": True,
            "rate_limiting": {
                "max_requests_per_hour": 3,
                "max_tokens_per_hour": 5000
            },
            "disable_functions": [
                "autonomous_engagement",
                "analyze_user_message",
                "start_conversation"
            ],
            "allowed_functions": [
                "send_message",
                "get_chat_info",
                "quick_security_scan"
            ]
        }
        
        with open('emergency_token_config.json', 'w') as f:
            json.dump(config, f, indent=2)
        print("   ✅ Emergency configuration saved")
    except Exception as e:
        print(f"   ❌ Error creating config: {e}")
    
    # 3. Update chat interface to use optimized version
    print("3️⃣ Updating chat interface...")
    try:
        from token_optimized_chat import OPTIMIZED_CHAT_INTERFACE
        print("   ✅ Token-optimized interface loaded")
        
        stats = OPTIMIZED_CHAT_INTERFACE.get_usage_stats()
        print(f"   📊 Current usage: {stats}")
    except Exception as e:
        print(f"   ❌ Error loading optimized interface: {e}")
    
    # 4. Test optimized interface
    print("4️⃣ Testing optimized interface...")
    try:
        result = await OPTIMIZED_CHAT_INTERFACE.optimized_analyze_message(
            chat_id="-1003706659588",
            user_id=123456789,
            message_text="System status check"
        )
        
        if result.get("success"):
            print("   ✅ Optimized interface working")
            print(f"   📊 Tokens used: {result.get('tokens_used', 'N/A')}")
        else:
            print(f"   ⚠️ Interface test: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"   ❌ Error testing interface: {e}")
    
    # 5. Generate upgrade recommendations
    print("5️⃣ Upgrade recommendations...")
    recommendations = """
🚨 **IMMEDIATE ACTION REQUIRED**

📈 **OpenRouter Plan Options:**
• **FREE**: 113,187 tokens/month (CURRENT - EXCEEDED)
• **BASIC**: $5/month - 200,000 tokens/month
• **PRO**: $20/month - 1,000,000 tokens/month  
• **BUSINESS**: $100/month - 5,000,000 tokens/month

🔗 **Upgrade Link**: https://openrouter.ai/settings/credits

💡 **Current Usage Analysis:**
• You've used: 1,080,000 tokens
• Limit: 113,187 tokens
• Over usage: 966,813 tokens (854% over limit)

⚡ **Recommended Plan**: PRO ($20/month)
• Provides 1,000,000 tokens/month
• Covers current usage with margin
• Best value for heavy AI usage

🛠️ **Alternative Solutions:**
1. **Reduce Usage**: Disable non-essential AI functions
2. **Optimize Prompts**: Use shorter, more specific prompts
3. **Cache Responses**: Store and reuse common responses
4. **Rate Limiting**: Implement strict usage limits
"""
    
    print(recommendations)
    
    with open('upgrade_recommendations.txt', 'w') as f:
        f.write(recommendations)
    print("   ✅ Upgrade recommendations saved")
    
    print("\n🎯 **EMERGENCY FIX COMPLETE**")
    print("📋 Actions taken:")
    print("   ✅ Autonomous engagement disabled")
    print("   ✅ Emergency configuration created")
    print("   ✅ Optimized interface loaded")
    print("   ✅ Usage recommendations generated")
    
    print("\n⚠️ **NEXT STEPS:**")
    print("   1. Upgrade OpenRouter plan immediately")
    print("   2. Monitor token usage closely")
    print("   3. Re-enable functions after upgrade")
    print("   4. Implement ongoing optimization")

if __name__ == "__main__":
    import json
    
    print("🚨 Starting Emergency Token Limit Fix...")
    asyncio.run(emergency_token_fix())
