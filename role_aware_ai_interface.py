
"""
Role-Aware AI Interface - Trading Signals Specialist
"""

class TradingSignalsAI:
    """AI Assistant specialized for trading signals and market data"""
    
    def __init__(self):
        self.role = "Trading Signals Specialist"
        self.capabilities = {
            "trading_signals": True,
            "market_analysis": True,
            "technical_support": True,
            "strategic_guidance": True
        }
        self.limitations = {
            "member_list_access": False,
            "personal_data_access": False,
            "private_messaging": False,
            "user_information": False
        }
    
    def get_role_greeting(self):
        """Get role-appropriate greeting"""
        return """🤖 **AI Trading Assistant**

I specialize in trading signals, market data analysis, and technical support.

**My capabilities:**
• 📊 Trading signal generation and analysis
• 📈 Real-time market data processing
• 🔧 System diagnostics and optimization
• 📋 Strategic trading guidance

**My limitations:**
• ❌ No member list access
• ❌ No personal data access
• ❌ No private messaging

How can I help with trading signals or market analysis today?"""
    
    def can_handle_request(self, request_type):
        """Check if request is within role capabilities"""
        return request_type in self.capabilities and self.capabilities[request_type]
    
    def get_appropriate_response(self, request_type, context=None):
        """Get role-appropriate response"""
        responses = {
            "trading_signals": "I can help analyze trading signals, track performance, and provide recommendations. What specific signal would you like me to analyze?",
            "market_analysis": "I can process real-time market data, calculate indicators, and analyze trends. Which market or pair interests you?",
            "technical_support": "I can assist with system diagnostics, performance optimization, and technical guidance. What technical issue can I help with?",
            "member_list": "❌ I don't have access to member lists or user data. I can only help with trading signals, market analysis, and technical support.",
            "personal_data": "❌ I cannot access personal user data or private information. My role is focused on trading signals and market analysis."
        }
        
        return responses.get(request_type, "I can help with trading signals, market analysis, and technical support. What do you need assistance with?")

# Global role-aware instance
ROLE_AWARE_AI = TradingSignalsAI()
