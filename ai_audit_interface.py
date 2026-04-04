"""
AI Agent Integration for Code Audit
Provides easy-to-use interface for AI agents to perform comprehensive code audits
"""

import json
from datetime import datetime
from audit_api import AUDIT_API

class AICodeAuditor:
    """Simplified interface for AI agents to audit the Aladdin codebase"""
    
    def __init__(self):
        self.api = AUDIT_API
        self.last_audit = None
    
    def quick_scan(self) -> str:
        """Perform a quick security and complexity scan"""
        print("🔍 Starting quick code scan...")
        
        # Get file overview
        files = self.api.get_file_list()
        total_files = files.get('total_files', 0)
        
        # Security scan
        security = self.api.security_scan()
        critical_issues = len(security.get('categorized', {}).get('critical', []))
        medium_issues = len(security.get('categorized', {}).get('medium', []))
        
        # Complexity analysis
        complexity = self.api.complexity_analysis()
        most_complex = complexity.get('most_complex_functions', [])[:5]
        
        # Generate summary
        summary = f"""
## 📊 QUICK CODE AUDIT SUMMARY
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

### 📁 Project Overview
- **Python Files:** {total_files}
- **Total Lines:** {sum(f.get('lines', 0) for f in files.get('files', []))}

### 🔒 Security Issues
- **Critical:** {critical_issues}
- **Medium:** {medium_issues}
- **Total:** {security.get('total_issues', 0)}

### 📈 Top Complex Functions
"""
        for func in most_complex:
            summary += f"- {func['name']}: Complexity {func['complexity']} (line {func['line']})\n"
        
        if critical_issues > 0:
            summary += "\n⚠️ **CRITICAL SECURITY ISSUES FOUND:**\n"
            for issue in security.get('categorized', {}).get('critical', [])[:3]:
                summary += f"- {issue['file']}:{issue['line']} - {issue['category']}\n"
        
        self.last_audit = {
            'type': 'quick',
            'timestamp': datetime.now().isoformat(),
            'files': total_files,
            'security_issues': security.get('total_issues', 0),
            'critical_issues': critical_issues
        }
        
        return summary
    
    def deep_audit(self) -> str:
        """Perform comprehensive full audit"""
        print("🔍 Starting comprehensive code audit...")
        
        # Run full audit
        audit = self.api.full_audit()
        
        if audit.get('status') != 'success':
            return f"❌ Audit failed: {audit.get('message', 'Unknown error')}"
        
        # Parse the report
        report = audit.get('report', '')
        summary = audit.get('summary', {})
        
        # Add executive summary
        executive = f"""
## 🎯 EXECUTIVE SUMMARY
**Files Analyzed:** {summary.get('files_analyzed', 0)}
**Security Issues:** {summary.get('security_issues', 0)}
**Complex Functions:** {summary.get('complex_functions', 0)}
**TODO Comments:** {summary.get('todo_comments', 0)}

### 🚨 Immediate Actions Required
"""
        
        if summary.get('security_issues', 0) > 0:
            executive += f"- 🔴 Fix {summary.get('security_issues', 0)} security issues\n"
        if summary.get('complex_functions', 0) > 5:
            executive += f"- 🟡 Refactor {summary.get('complex_functions', 0)} complex functions\n"
        if summary.get('todo_comments', 0) > 10:
            executive += f"- 🟠 Address {summary.get('todo_comments', 0)} TODO comments\n"
        
        self.last_audit = {
            'type': 'full',
            'timestamp': datetime.now().isoformat(),
            'summary': summary
        }
        
        return executive + "\n\n" + report
    
    def analyze_file(self, file_path: str) -> str:
        """Analyze a specific file"""
        print(f"🔍 Analyzing file: {file_path}")
        
        # Security scan for file
        security = self.api.security_scan(file_path)
        
        # Complexity for file
        complexity = self.api.complexity_analysis(file_path)
        
        result = f"""
## 📄 FILE ANALYSIS: {file_path}
**Analyzed:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

### 🔒 Security Issues
"""
        
        if security.get('status') == 'success':
            total = security.get('total_issues', 0)
            result += f"- Total Issues: {total}\n"
            
            for severity, issues in security.get('categorized', {}).items():
                if issues:
                    result += f"- {severity.upper()}: {len(issues)}\n"
                    for issue in issues[:2]:  # Show top 2
                        result += f"  - Line {issue['line']}: {issue['category']}\n"
        else:
            result += f"- Error: {security.get('message', 'Unknown error')}\n"
        
        result += "\n### 📈 Complexity\n"
        if complexity.get('status') == 'success':
            results = complexity.get('results', {})
            if file_path in results:
                data = results[file_path]
                result += f"- Max Function Complexity: {data.get('max_function_complexity', 0)}\n"
                result += f"- Total Complexity: {data.get('total_complexity', 0)}\n"
                result += f"- Function Count: {data.get('function_count', 0)}\n"
                
                if data.get('complex_functions'):
                    result += "\nMost Complex Functions:\n"
                    for func in data['complex_functions'][:3]:
                        result += f"- {func['name']}: {func['complexity']}\n"
        else:
            result += f"- Error: {complexity.get('message', 'Unknown error')}\n"
        
        return result
    
    def get_recommendations(self) -> str:
        """Get actionable recommendations based on last audit"""
        if not self.last_audit:
            return "❌ No audit has been performed yet. Run quick_scan() or deep_audit() first."
        
        audit_type = self.last_audit.get('type')
        timestamp = self.last_audit.get('timestamp')
        
        recommendations = f"""
## 💡 RECOMMENDATIONS
**Based on:** {audit_type} audit from {timestamp}

### 🚨 High Priority (Fix Immediately)
"""
        
        if audit_type == 'quick':
            if self.last_audit.get('critical_issues', 0) > 0:
                recommendations += f"1. 🔴 Fix {self.last_audit.get('critical_issues')} critical security vulnerabilities\n"
                recommendations += "   - Review hardcoded secrets, API keys, or passwords\n"
                recommendations += "   - Remove eval() or exec() calls\n"
                recommendations += "   - Fix potential SQL injection patterns\n"
            
            if self.last_audit.get('security_issues', 0) > 5:
                recommendations += "2. 🟡 Address multiple security issues\n"
                recommendations += "   - Implement proper input validation\n"
                recommendations += "   - Use parameterized queries for database operations\n"
                recommendations += "   - Review file operation security\n"
        
        else:  # full audit
            summary = self.last_audit.get('summary', {})
            if summary.get('security_issues', 0) > 0:
                recommendations += f"1. 🔴 Security: Fix {summary.get('security_issues')} vulnerabilities\n"
            if summary.get('complex_functions', 0) > 10:
                recommendations += f"2. 🟡 Complexity: Refactor {summary.get('complex_functions')} complex functions\n"
            if summary.get('todo_comments', 0) > 0:
                recommendations += f"3. 🟠 Maintenance: Resolve {summary.get('todo_comments')} TODO items\n"
        
        recommendations += """
### 📋 Medium Priority (Next Sprint)
1. **Code Quality**
   - Add comprehensive docstrings
   - Implement type hints
   - Set up automated linting (flake8, pylint)
   - Add unit tests for critical functions

2. **Performance**
   - Profile slow functions
   - Optimize database queries
   - Implement caching where appropriate
   - Review algorithm efficiency

3. **Maintainability**
   - Break down large functions (>50 lines)
   - Reduce nesting depth (>4 levels)
   - Extract common patterns into utilities
   - Improve error handling

### 🔮 Low Priority (Future Improvements)
1. **Documentation**
   - Create API documentation
   - Add README with setup instructions
   - Document architecture decisions
   - Create developer onboarding guide

2. **Testing**
   - Increase test coverage to >80%
   - Add integration tests
   - Implement performance benchmarks
   - Set up CI/CD pipeline

3. **Monitoring**
   - Add logging for critical operations
   - Implement error tracking
   - Set up performance monitoring
   - Create health check endpoints
"""
        
        return recommendations
    
    def export_audit_report(self, filename: str = None) -> str:
        """Export the last audit to a file"""
        if not self.last_audit:
            return "❌ No audit data to export"
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"audit_report_{timestamp}.md"
        
        try:
            with open(filename, 'w') as f:
                if self.last_audit.get('type') == 'full':
                    f.write(self.deep_audit())
                else:
                    f.write(self.quick_scan())
                    f.write("\n\n")
                    f.write(self.get_recommendations())
            
            return f"✅ Audit report exported to {filename}"
        except Exception as e:
            return f"❌ Export failed: {e}"


# Global instance for AI agents
AI_AUDITOR = AICodeAuditor()

# Easy-to-use functions for AI agents
def quick_security_scan():
    """Quick security and complexity scan"""
    return AI_AUDITOR.quick_scan()

def full_code_audit():
    """Comprehensive code audit"""
    return AI_AUDITOR.deep_audit()

def analyze_specific_file(file_path):
    """Analyze a single file"""
    return AI_AUDITOR.analyze_file(file_path)

def get_improvement_recommendations():
    """Get actionable recommendations"""
    return AI_AUDITOR.get_recommendations()

def save_audit_report(filename=None):
    """Save audit report to file"""
    return AI_AUDITOR.export_audit_report(filename)

if __name__ == "__main__":
    # Demo for AI agents
    print("🤖 AI Code Auditor Demo")
    print("=" * 30)
    
    # Quick scan
    print("\n1. Performing quick scan...")
    quick = quick_security_scan()
    print(quick[:500] + "\n...")
    
    # Get recommendations
    print("\n2. Getting recommendations...")
    recs = get_improvement_recommendations()
    print(recs[:300] + "\n...")
    
    # Export report
    print("\n3. Exporting report...")
    export_result = save_audit_report()
    print(export_result)
