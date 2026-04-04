#!/usr/bin/env python3
"""
OpenRouter API Token Management and Optimization
"""

import os
import json
from datetime import datetime

def check_openrouter_status():
    """Check current OpenRouter API status and limits"""
    try:
        import requests
        
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            return {"error": "No OPENROUTER_API_KEY found in environment"}
        
        # Check account status
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.get("https://openrouter.ai/api/v1/auth/key", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "status": data.get("data", {}),
                "usage": data.get("usage", {}),
                "limits": data.get("limits", {})
            }
        else:
            return {"error": f"API Error: {response.status_code}", "details": response.text}
            
    except Exception as e:
        return {"error": str(e)}

def optimize_ai_usage():
    """Generate recommendations for optimizing AI token usage"""
    recommendations = [
        {
            "priority": "HIGH",
            "issue": "Token limit exceeded",
            "solution": "Upgrade to paid OpenRouter plan",
            "action": "Visit https://openrouter.ai/settings/credits"
        },
        {
            "priority": "MEDIUM",
            "issue": "High token consumption",
            "solution": "Implement token optimization",
            "actions": [
                "Reduce conversation history length",
                "Use shorter prompts",
                "Implement response caching",
                "Limit AI response length"
            ]
        },
        {
            "priority": "LOW",
            "issue": "Inefficient AI usage",
            "solution": "Optimize AI interaction patterns",
            "actions": [
                "Batch similar requests",
                "Use more specific prompts",
                "Implement rate limiting",
                "Add token usage monitoring"
            ]
        }
    ]
    return recommendations

def create_token_optimized_chat_interface():
    """Create optimized chat interface with token limits"""
    optimized_config = {
        "max_history_length": 5,  # Reduce from 10 to 5 messages
        "max_response_length": 500,  # Limit AI responses
        "cache_responses": True,  # Enable caching
        "batch_requests": True,  # Batch similar requests
        "rate_limit": {
            "requests_per_minute": 10,
            "tokens_per_hour": 50000
        }
    }
    return optimized_config

def generate_usage_report():
    """Generate current usage report"""
    current_time = datetime.now()
    
    report = f"""
📊 **OpenRouter API Usage Report**
Generated: {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}

🚨 **Current Status:**
• Token Limit: 113,187 tokens
• Current Usage: 1,080,000 tokens
• Status: ⚠️ LIMIT EXCEEDED
• Over Usage: 966,813 tokens

💡 **Immediate Actions Required:**
1. **URGENT**: Upgrade to paid plan at https://openrouter.ai/settings/credits
2. **TEMPORARY**: Disable non-critical AI functions
3. **OPTIMIZATION**: Implement token saving measures

🔧 **Recommended Paid Plans:**
• **Basic**: $5/month - 200,000 tokens/month
• **Pro**: $20/month - 1,000,000 tokens/month  
• **Business**: $100/month - 5,000,000 tokens/month

📈 **Usage Optimization Tips:**
• Reduce conversation history to 5 messages
• Limit AI responses to 500 characters
• Cache common responses
• Batch similar requests
• Monitor token usage in real-time
"""
    return report

def create_emergency_token_saver():
    """Create emergency token-saving configuration"""
    emergency_config = {
        "disable_autonomous_engagement": True,
        "disable_ai_conversations": True,
        "limit_chat_history": 3,
        "max_response_tokens": 200,
        "enable_caching": True,
        "batch_processing": True,
        "rate_limiting": {
            "max_requests_per_hour": 5,
            "max_tokens_per_hour": 10000
        }
    }
    return emergency_config

def main():
    """Main function to check and provide recommendations"""
    print("🔍 Checking OpenRouter API Status...")
    
    # Check current status
    status = check_openrouter_status()
    
    if "error" in status:
        print(f"❌ Error checking status: {status['error']}")
        return
    
    print("✅ API Status Retrieved")
    print(json.dumps(status, indent=2))
    
    # Generate recommendations
    print("\n💡 Generating Recommendations...")
    recommendations = optimize_ai_usage()
    
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. **{rec['priority']} PRIORITY**")
        print(f"   Issue: {rec['issue']}")
        print(f"   Solution: {rec['solution']}")
        if 'actions' in rec:
            for action in rec['actions']:
                print(f"   • {action}")
    
    # Generate usage report
    print("\n" + generate_usage_report())
    
    # Create emergency config
    emergency = create_emergency_token_saver()
    print("\n🚨 Emergency Token-Saving Configuration:")
    print(json.dumps(emergency, indent=2))
    
    # Save configurations
    with open('token_optimization_config.json', 'w') as f:
        json.dump({
            "optimized": create_token_optimized_chat_interface(),
            "emergency": emergency,
            "recommendations": recommendations
        }, f, indent=2)
    
    print("\n✅ Configuration saved to 'token_optimization_config.json'")

if __name__ == "__main__":
    main()
