#!/usr/bin/env python3
"""
Force AI to discover audit tools
This script will make the audit tools visible to the AI system
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def register_audit_tools():
    """Register audit tools in the AI system"""
    try:
        # Import and expose audit functions
        from ai_audit_interface import (
            quick_security_scan, 
            full_code_audit, 
            analyze_specific_file, 
            get_improvement_recommendations, 
            save_audit_report
        )
        
        # Make them globally available
        globals()['quick_security_scan'] = quick_security_scan
        globals()['full_code_audit'] = full_code_audit
        globals()['analyze_specific_file'] = analyze_specific_file
        globals()['get_improvement_recommendations'] = get_improvement_recommendations
        globals()['save_audit_report'] = save_audit_report
        
        # Also expose via a registry
        audit_registry = {
            'quick_security_scan': quick_security_scan,
            'full_code_audit': full_code_audit,
            'analyze_specific_file': analyze_specific_file,
            'get_improvement_recommendations': get_improvement_recommendations,
            'save_audit_report': save_audit_report
        }
        
        # Save registry to file so AI can discover it
        with open('audit_tools_registry.json', 'w') as f:
            import json
            json.dump({
                'available_tools': list(audit_registry.keys()),
                'description': 'Code audit tools for comprehensive analysis',
                'access_method': 'Direct function calls or MCP bridge'
            }, f, indent=2)
        
        print("✅ Audit tools registered and discoverable")
        print("Available tools:", list(audit_registry.keys()))
        
        return audit_registry
        
    except Exception as e:
        print(f"❌ Error registering audit tools: {e}")
        return {}

if __name__ == "__main__":
    registry = register_audit_tools()
    
    # Test one function to prove it works
    if 'quick_security_scan' in registry:
        print("\n🧪 Testing quick_security_scan...")
        try:
            result = registry['quick_security_scan']()
            print("✅ Function works! AI can now use it.")
        except Exception as e:
            print(f"❌ Test failed: {e}")
