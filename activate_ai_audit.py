#!/usr/bin/env python3
"""
AI AUDIT TOOLS ACTIVATION SCRIPT
Execute this to activate all audit tools immediately
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def activate_audit_tools():
    """Activate all audit tools and demonstrate usage"""
    print("🚀 ACTIVATING AI AUDIT TOOLS...")
    
    # Import all tools
    from ai_audit_interface import (
        quick_security_scan,
        full_code_audit,
        analyze_specific_file,
        get_improvement_recommendations,
        save_audit_report
    )
    
    print("✅ All audit tools imported successfully!")
    
    # Make them globally available
    globals()['AUDIT_TOOLS'] = {
        'quick_security_scan': quick_security_scan,
        'full_code_audit': full_code_audit,
        'analyze_specific_file': analyze_specific_file,
        'get_improvement_recommendations': get_improvement_recommendations,
        'save_audit_report': save_audit_report
    }
    
    print("✅ Tools registered in global namespace!")
    
    # Execute quick scan as demo
    print("\n🔍 Executing quick security scan...")
    result = quick_security_scan()
    print("✅ Quick scan completed!")
    
    # Show available functions
    print("\n📋 AVAILABLE FUNCTIONS:")
    for name in AUDIT_TOOLS.keys():
        print(f"   - {name}()")
    
    print("\n🎯 AI AUDIT TOOLS ARE FULLY ACTIVE!")
    print("You can now call any audit function directly.")
    
    return AUDIT_TOOLS

if __name__ == "__main__":
    tools = activate_audit_tools()
    
    # Save activation confirmation
    with open('AI_AUDIT_ACTIVATED.txt', 'w') as f:
        f.write("AI AUDIT TOOLS ACTIVATED SUCCESSFULLY!\n")
        f.write(f"Available tools: {list(tools.keys())}\n")
        f.write("All functions are ready for immediate use.\n")
    
    print("\n✅ Activation confirmed! Check AI_AUDIT_ACTIVATED.txt")
