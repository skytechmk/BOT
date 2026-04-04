#!/usr/bin/env python3
"""
Direct AI Code Audit Access
Run this to perform comprehensive code audit immediately
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_audit():
    """Run comprehensive code audit now"""
    try:
        # Import the audit interface
        from ai_audit_interface import AI_AUDITOR
        
        print("🔍 STARTING COMPREHENSIVE CODE AUDIT")
        print("=" * 50)
        
        # 1. Quick scan first
        print("\n1️⃣ Performing quick security and complexity scan...")
        quick_report = AI_AUDITOR.quick_scan()
        print(quick_report)
        
        # 2. Get recommendations
        print("\n2️⃣ Getting actionable recommendations...")
        recommendations = AI_AUDITOR.get_recommendations()
        print(recommendations)
        
        # 3. Save report
        print("\n3️⃣ Saving audit report...")
        export_result = AI_AUDITOR.export_audit_report()
        print(f"   {export_result}")
        
        # 4. Show most critical issues
        print("\n4️⃣ Critical issues summary:")
        from audit_api import AUDIT_API
        security = AUDIT_API.security_scan()
        
        critical = security.get('categorized', {}).get('critical', [])
        if critical:
            print(f"   🚨 Found {len(critical)} CRITICAL issues:")
            for issue in critical[:5]:
                print(f"      - {os.path.basename(issue['file'])}:{issue['line']} - {issue['category']}")
        else:
            print("   ✅ No critical security issues found!")
        
        print("\n✅ AUDIT COMPLETE!")
        print("   All tools are now available for continued analysis.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during audit: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_audit()
    if success:
        print("\n🎯 AI can now use these functions:")
        print("   - quick_security_scan()")
        print("   - full_code_audit()")
        print("   - analyze_specific_file('filename.py')")
        print("   - get_improvement_recommendations()")
        print("   - save_audit_report()")
    else:
        print("\n❌ Audit failed. Check error messages above.")
