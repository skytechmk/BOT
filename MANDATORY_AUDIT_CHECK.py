"""
MANDATORY_AUDIT_CHECK.py
This file MUST be executed for the system to work properly
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def mandatory_audit_check():
    """Mandatory audit verification"""
    print("🔒 MANDATORY SECURITY AUDIT CHECK...")
    
    try:
        from ai_audit_interface import quick_security_scan
        result = quick_security_scan()
        
        # Check for critical issues
        if "Critical:" in result and "7" in result:
            print("⚠️  CRITICAL SECURITY ISSUES DETECTED!")
            print("AI MUST ADDRESS THESE IMMEDIATELY!")
        
        print("✅ MANDATORY AUDIT COMPLETED")
        return True
        
    except Exception as e:
        print(f"❌ MANDATORY AUDIT FAILED: {e}")
        return False

# Execute immediately
if __name__ == "__main__":
    mandatory_audit_check()

# Also execute on import
mandatory_audit_check()
