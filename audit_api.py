"""
AI Code Audit API Interface
Provides programmatic access to advanced code analysis tools for AI agents
"""

import os
import sys
import json
import subprocess
import importlib.util
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

class AuditAPI:
    """API interface for AI agents to perform comprehensive code audits"""
    
    def __init__(self, project_root: str = "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA"):
        self.project_root = project_root
        self.audit_tools = None
        self.load_audit_tools()
    
    def load_audit_tools(self):
        """Load the audit tools module"""
        try:
            spec = importlib.util.spec_from_file_location(
                "code_audit_tools", 
                os.path.join(self.project_root, "code_audit_tools.py")
            )
            self.audit_tools = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.audit_tools)
            return True
        except Exception as e:
            print(f"Failed to load audit tools: {e}")
            return False
    
    def get_available_tools(self) -> Dict[str, str]:
        """Get list of available audit tools and their descriptions"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        return {
            "static_analysis": "Comprehensive static code analysis including complexity, security, and quality checks",
            "dynamic_analysis": "Runtime analysis monitoring memory, CPU, and performance metrics",
            "security_scan": "Focused security vulnerability scanning for common issues",
            "complexity_analysis": "Cyclomatic complexity analysis for maintainability assessment",
            "dependency_analysis": "Import and dependency graph analysis",
            "performance_profile": "Code profiling for performance bottlenecks",
            "full_audit": "Complete comprehensive audit report combining all analyses"
        }
    
    def static_analysis(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Perform static code analysis"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            if file_path:
                # Analyze specific file
                auditor = self.audit_tools.CodeAuditor()
                auditor.python_files = [file_path] if os.path.exists(file_path) else []
            
            # Run full static analysis
            results = self.audit_tools.CodeAuditor().static_analysis()
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "static",
                "results": results
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def dynamic_analysis(self, duration: int = 60, target_process: Optional[str] = None) -> Dict[str, Any]:
        """Perform dynamic analysis while monitoring the bot"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            results = auditor.dynamic_analysis(duration=duration)
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "dynamic",
                "duration": duration,
                "results": results
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def security_scan(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Perform focused security vulnerability scan"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            if file_path:
                auditor.python_files = [file_path] if os.path.exists(file_path) else []
            
            security_issues = auditor.security_scan()
            
            # Categorize by severity
            categorized = {
                "critical": [i for i in security_issues if i.get("severity") == "HIGH"],
                "medium": [i for i in security_issues if i.get("severity") == "MEDIUM"],
                "low": [i for i in security_issues if i.get("severity") == "LOW"],
                "info": [i for i in security_issues if i.get("severity") == "LOW"]
            }
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "security",
                "total_issues": len(security_issues),
                "categorized": categorized,
                "all_issues": security_issues
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def complexity_analysis(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Analyze code complexity"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            if file_path:
                auditor.python_files = [file_path] if os.path.exists(file_path) else []
            
            complexity = auditor.analyze_complexity()
            
            # Find most complex functions
            all_functions = []
            for file_path, data in complexity.items():
                if "complex_functions" in data:
                    for func in data["complex_functions"]:
                        func["file"] = file_path
                        all_functions.append(func)
            
            # Sort by complexity
            most_complex = sorted(all_functions, key=lambda x: x["complexity"], reverse=True)[:10]
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "complexity",
                "results": complexity,
                "most_complex_functions": most_complex,
                "summary": {
                    "total_functions": len(all_functions),
                    "max_complexity": max([f["complexity"] for f in all_functions]) if all_functions else 0,
                    "avg_complexity": sum([f["complexity"] for f in all_functions]) / len(all_functions) if all_functions else 0
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def dependency_analysis(self) -> Dict[str, Any]:
        """Analyze project dependencies"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            deps = auditor.analyze_dependencies()
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "dependencies",
                "results": deps
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def performance_profile(self, code_snippet: str, mode: str = "code") -> Dict[str, Any]:
        """Profile code performance"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            results = auditor.performance_profile(code_snippet, mode)
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "performance",
                "results": results
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def full_audit(self) -> Dict[str, Any]:
        """Perform comprehensive full audit"""
        if not self.audit_tools:
            return {"error": "Audit tools not loaded"}
        
        try:
            auditor = self.audit_tools.CodeAuditor()
            report = auditor.generate_audit_report()
            
            # Also get structured data
            static_results = auditor.static_analysis()
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "analysis_type": "full_audit",
                "report": report,
                "structured_data": static_results,
                "summary": {
                    "files_analyzed": len(auditor.python_files),
                    "security_issues": len(static_results.get("security_issues", [])),
                    "complex_functions": len([f for data in static_results.get("complexity_analysis", {}).values() 
                                           for f in data.get("complex_functions", [])]),
                    "todo_comments": len(static_results.get("code_quality", {}).get("todo_comments", []))
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_file_list(self) -> Dict[str, Any]:
        """Get list of all Python files in the project"""
        try:
            auditor = self.audit_tools.CodeAuditor()
            files = auditor.python_files
            
            # Get file sizes and modification times
            file_info = []
            for file_path in files:
                try:
                    stat = os.stat(file_path)
                    file_info.append({
                        "path": file_path,
                        "relative_path": os.path.relpath(file_path, self.project_root),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "lines": self._count_lines(file_path)
                    })
                except:
                    file_info.append({
                        "path": file_path,
                        "relative_path": os.path.relpath(file_path, self.project_root),
                        "error": "Could not read file stats"
                    })
            
            return {
                "status": "success",
                "total_files": len(files),
                "files": file_info
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _count_lines(self, file_path: str) -> int:
        """Count lines in a file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return len(f.readlines())
        except:
            return 0
    
    def run_tests(self) -> Dict[str, Any]:
        """Run any available tests"""
        test_files = []
        for root, dirs, files in os.walk(self.project_root):
            for file in files:
                if file.startswith('test_') and file.endswith('.py'):
                    test_files.append(os.path.join(root, file))
                elif file == '__init__.py' and 'test' in root:
                    test_files.append(os.path.join(root, file))
        
        if not test_files:
            return {"status": "info", "message": "No test files found"}
        
        results = {}
        for test_file in test_files:
            try:
                # Run the test file
                result = subprocess.run(
                    [sys.executable, test_file],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                results[test_file] = {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "success": result.returncode == 0
                }
            except subprocess.TimeoutExpired:
                results[test_file] = {
                    "error": "Test timed out after 30 seconds"
                }
            except Exception as e:
                results[test_file] = {
                    "error": str(e)
                }
        
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "test_files": test_files,
            "results": results,
            "summary": {
                "total_tests": len(test_files),
                "passed": sum(1 for r in results.values() if r.get("success", False)),
                "failed": sum(1 for r in results.values() if not r.get("success", False) and "error" not in r)
            }
        }


# Global instance for easy access
AUDIT_API = AuditAPI()

# Convenience functions for AI agents
def get_audit_capabilities():
    """Get all available audit capabilities"""
    return AUDIT_API.get_available_tools()

def perform_full_audit():
    """Perform a complete code audit"""
    return AUDIT_API.full_audit()

def scan_security_issues():
    """Scan for security vulnerabilities"""
    return AUDIT_API.security_scan()

def analyze_code_complexity():
    """Analyze code complexity"""
    return AUDIT_API.complexity_analysis()

def get_project_files():
    """Get list of all project files"""
    return AUDIT_API.get_file_list()

def run_project_tests():
    """Run available tests"""
    return AUDIT_API.run_tests()

if __name__ == "__main__":
    # Demo the API
    print("🔍 Aladdin Code Audit API Demo")
    print("=" * 40)
    
    # Show available tools
    tools = get_audit_capabilities()
    print("\nAvailable Tools:")
    for tool, desc in tools.items():
        print(f"- {tool}: {desc}")
    
    # Get file list
    files = get_project_files()
    print(f"\nFound {files['total_files']} Python files")
    
    # Quick security scan
    security = scan_security_issues()
    print(f"\nSecurity Issues Found: {security.get('total_issues', 0)}")
    
    if security.get('total_issues', 0) > 0:
        print(f"  Critical: {len(security.get('categorized', {}).get('critical', []))}")
        print(f"  Medium: {len(security.get('categorized', {}).get('medium', []))}")
        print(f"  Low: {len(security.get('categorized', {}).get('low', []))}")
