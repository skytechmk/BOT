#!/usr/bin/env python3
"""
AUTO-EXECUTE AUDIT TOOLS - This runs automatically when imported!
"""

# Auto-execution block - runs immediately when file is imported
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🚀 AUTO-AUDIT TRIGGERED!")

try:
    # Import and execute immediately
    from ai_audit_interface import quick_security_scan
    
    print("🔍 EXECUTING AUDIT NOW...")
    result = quick_security_scan()
    
    print("✅ AUDIT COMPLETED!")
    print("AI TOOLS ARE WORKING!")
    print("=" * 50)
    print(result[:500] + "...")
    print("=" * 50)
    
    # Save proof that it worked
    with open('AUDIT_AUTO_EXECUTED.txt', 'w') as f:
        f.write("AUDIT TOOLS AUTO-EXECUTED SUCCESSFULLY!\n")
        f.write(f"Timestamp: {__import__('datetime').datetime.now()}\n")
        f.write(f"Result length: {len(result)} characters\n")
    
    print("\n📄 Proof saved to AUDIT_AUTO_EXECUTED.txt")
    
except Exception as e:
    print(f"❌ Auto-execution failed: {e}")

# Force execution even if just imported
if __name__ != "__main__":
    print("⚠️  File was imported - audit already executed above!")
