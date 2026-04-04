#!/usr/bin/env python3
"""
Add autonomous engagement to MCP bridge
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def autonomous_engagement_mcp(chat_id: str = None, force: bool = False) -> str:
    """MCP function for autonomous engagement"""
    try:
        from ai_autonomous_engagement import send_autonomous_engagement
        
        if not chat_id:
            chat_id = '-1002209928687'  # Default to main group
        
        if force:
            result = await send_autonomous_engagement()
            return json.dumps({
                "success": result,
                "chat_id": chat_id,
                "action": "forced_autonomous_engagement",
                "timestamp": datetime.now().isoformat()
            }, indent=2)
        else:
            return json.dumps({
                "success": True,
                "message": "Autonomous engagement scheduler is running",
                "chat_id": chat_id,
                "status": "scheduler_active"
            }, indent=2)
            
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)

# Test the MCP function
if __name__ == "__main__":
    import json
    from datetime import datetime
    
    print('🧪 Testing autonomous engagement MCP function...')
    
    # Test forced engagement
    result = asyncio.run(autonomous_engagement_mcp(chat_id='-1002209928687', force=True))
    print('Result:', result)
    
    # Test status check
    status_result = asyncio.run(autonomous_engagement_mcp())
    print('Status:', status_result)
