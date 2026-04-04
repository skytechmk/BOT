#!/usr/bin/env python3
"""
WORKING AUDIT TOOLS DEMO - AI CAN EXECUTE THIS DIRECTLY
"""

def run_audit_now():
    """Execute audit tools immediately - AI can run this function"""
    
    # Import the tools
    try:
        from ai_audit_interface import quick_security_scan, full_code_audit
        print("✅ Successfully imported audit tools")
    except ImportError as e:
        return f"❌ Import failed: {e}"
    
    # Execute quick scan
    try:
        print("\n🔍 Executing quick_security_scan...")
        result = quick_security_scan()
        print("✅ Quick scan completed successfully")
        return result
    except Exception as e:
        return f"❌ Quick scan failed: {e}"

# Execute immediately when run
if __name__ == "__main__":
    result = run_audit_now()
    print("\n📊 RESULT:")
    print(result[:1000] + "..." if len(result) > 1000 else result)
