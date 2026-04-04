# 🤖 AI Code Audit Tools - User Guide

## Overview
The Aladdin trading bot now includes comprehensive code audit tools that provide AI agents with advanced capabilities for static analysis, dynamic analysis, security scanning, and performance profiling.

## 🛠️ Available Tools

### 1. **Static Analysis**
- **Purpose**: Analyze code without execution
- **Features**:
  - Cyclomatic complexity analysis
  - Security vulnerability scanning
  - Code quality metrics
  - Dependency analysis
  - Unused import detection
  - Potential bug identification

### 2. **Dynamic Analysis**
- **Purpose**: Monitor code while running
- **Features**:
  - Memory usage tracking
  - CPU utilization monitoring
  - Performance metrics
  - Resource consumption analysis

### 3. **Security Analysis**
- **Purpose**: Identify security vulnerabilities
- **Features**:
  - Hardcoded secrets detection
  - SQL injection patterns
  - Eval/exec usage scanning
  - File operation security
  - Network request analysis

### 4. **Performance Profiling**
- **Purpose**: Identify performance bottlenecks
- **Features**:
  - Function-level profiling
  - Execution time analysis
  - Memory profiling
  - Hotspot identification

## 🚀 Quick Start for AI Agents

### Installation
The tools are already integrated into the project. No additional installation required.

### Basic Usage

```python
# Import the AI auditor interface
from ai_audit_interface import AI_AUDITOR

# Quick security scan
quick_report = AI_AUDITOR.quick_scan()
print(quick_report)

# Full comprehensive audit
full_report = AI_AUDITOR.deep_audit()
print(full_report)

# Analyze specific file
file_analysis = AI_AUDITOR.analyze_file("main.py")
print(file_analysis)

# Get recommendations
recommendations = AI_AUDITOR.get_recommendations()
print(recommendations)
```

## 📊 API Reference

### Quick Functions

| Function | Description | Returns |
|----------|-------------|---------|
| `quick_security_scan()` | Fast security & complexity check | Markdown report |
| `full_code_audit()` | Comprehensive analysis | Detailed report |
| `analyze_specific_file(path)` | Analyze single file | File analysis |
| `get_improvement_recommendations()` | Actionable suggestions | Recommendations |
| `save_audit_report(filename)` | Export to file | Status message |

### Advanced API

```python
from audit_api import AUDIT_API

# Static analysis
static = AUDIT_API.static_analysis()

# Dynamic analysis (monitor for 60 seconds)
dynamic = AUDIT_API.dynamic_analysis(duration=60)

# Security scan
security = AUDIT_API.security_scan()

# Complexity analysis
complexity = AUDIT_API.complexity_analysis()

# Performance profiling
profile = AUDIT_API.performance_profile(code_snippet)
```

## 📈 What the Tools Can Do

### Static Analysis Capabilities
- ✅ Find security vulnerabilities (hardcoded secrets, SQL injection)
- ✅ Calculate cyclomatic complexity
- ✅ Detect code quality issues (long functions, deep nesting)
- ✅ Identify unused imports
- ✅ Find potential bugs (unreachable code, mutable defaults)
- ✅ Analyze dependency graph
- ✅ Count TODO comments and magic numbers

### Dynamic Analysis Capabilities
- ✅ Monitor memory usage in real-time
- ✅ Track CPU utilization
- ✅ Profile function execution time
- ✅ Identify memory leaks
- ✅ Measure performance bottlenecks

### Security Analysis
- ✅ **Critical Issues**: Hardcoded secrets, eval/exec usage
- ✅ **Medium Issues**: File operations, network requests
- ✅ **Low Issues**: Code patterns that could be improved

## 🎯 Example Outputs

### Quick Scan Summary
```
📊 QUICK CODE AUDIT SUMMARY
📁 Python Files: 62
🔒 Security Issues: 22 (7 Critical, 15 Medium)
📈 Top Complex Functions:
  - prepare_ml_features: Complexity 56
  - calculate_kicko_indicator: Complexity 50
```

### Security Issue Example
```
🔒 CRITICAL: main.py:123
Pattern: password = "secret123"
Type: Hardcoded credentials
Severity: HIGH
```

### Complexity Example
```
📈 Function: calculate_detailed_confidence
File: signal_generator.py
Complexity: 33
Lines: 44-200
Recommendation: Consider breaking into smaller functions
```

## 💡 Integration Tips

### For AI Agents
1. **Start with quick_scan()** to get overview
2. **Use deep_audit()** for comprehensive analysis
3. **Focus on critical security issues first**
4. **Check complexity before refactoring**
5. **Use file analysis for targeted fixes**

### Best Practices
1. Run audit before major changes
2. Check security after adding new features
3. Monitor complexity during development
4. Export reports for documentation
5. Address critical issues immediately

## 🔧 Configuration

### Customizing Analysis
```python
# Analyze specific file types
auditor = CodeAuditor()
auditor.python_files = [f for f in auditor.python_files if 'test' not in f]

# Adjust complexity threshold
analyzer = ComplexityAnalyzer()
analyzer.complexity_threshold = 15  # Default is 10
```

### Export Options
```python
# Save to custom filename
AI_AUDITOR.export_audit_report("security_audit_2024.md")

# Export JSON data
import json
audit_data = AUDIT_API.full_audit()
with open("audit_data.json", "w") as f:
    json.dump(audit_data, f, indent=2)
```

## 🚨 Limitations

- **Dynamic analysis** requires the bot to be running
- **Performance profiling** adds overhead to execution
- **Security scanning** uses pattern matching (may have false positives)
- **Complexity analysis** doesn't measure all aspects of maintainability

## 📚 Advanced Usage

### Custom Security Patterns
```python
# Add custom security patterns
security_patterns = {
    'custom_risk': [r'custom_pattern_here']
}
```

### Integration with CI/CD
```python
# In CI pipeline
if __name__ == "__main__":
    auditor = AI_AUDITOR
    report = auditor.deep_audit()
    
    # Fail build on critical issues
    if "critical" in report and report["critical"] > 0:
        sys.exit(1)
```

## 🤝 Support

The tools are designed to be extensible. For issues or feature requests:
1. Check the generated reports for errors
2. Review the code in `code_audit_tools.py`
3. Test with specific files to isolate issues
4. Export reports for debugging

---

**Note**: These tools provide analysis and recommendations. Always review suggested changes before applying them to production code.
