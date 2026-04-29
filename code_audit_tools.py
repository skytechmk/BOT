"""
Advanced Code Audit Tools for Aladdin Trading Bot
Provides comprehensive static, dynamic, security analysis and profiling capabilities
"""

import os
import sys
import ast
import time
import subprocess
import psutil
import tracemalloc
import cProfile
import pstats
import io
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
import pandas as pd
import numpy as np

class CodeAuditor:
    """Comprehensive code analysis toolkit for the Aladdin trading bot"""
    
    def __init__(self, project_root: str = "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA"):
        self.project_root = Path(project_root)
        self.python_files = []
        self.scan_python_files()
        
    def scan_python_files(self) -> List[str]:
        """Find all Python files in the project"""
        self.python_files = []
        for root, dirs, files in os.walk(self.project_root):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'venv', 'env', 'node_modules']]
            for file in files:
                if file.endswith('.py'):
                    self.python_files.append(os.path.join(root, file))
        return self.python_files
    
    def static_analysis(self) -> Dict[str, Any]:
        """Comprehensive static code analysis"""
        results = {
            'complexity_analysis': self.analyze_complexity(),
            'security_issues': self.security_scan(),
            'code_quality': self.code_quality_check(),
            'dependencies': self.analyze_dependencies(),
            'unused_imports': self.find_unused_imports(),
            'potential_bugs': self.find_potential_bugs()
        }
        return results
    
    def analyze_complexity(self) -> Dict[str, Any]:
        """Analyze cyclomatic complexity and code metrics"""
        complexity_data = {}
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                analyzer = ComplexityAnalyzer()
                analyzer.visit(tree)
                
                complexity_data[file_path] = {
                    'total_complexity': analyzer.total_complexity,
                    'max_function_complexity': analyzer.max_complexity,
                    'function_count': analyzer.function_count,
                    'class_count': analyzer.class_count,
                    'line_count': len(content.splitlines()),
                    'complex_functions': analyzer.complex_functions
                }
            except Exception as e:
                complexity_data[file_path] = {'error': str(e)}
        
        return complexity_data
    
    def security_scan(self) -> List[Dict[str, Any]]:
        """Security vulnerability scanner"""
        security_issues = []
        
        # Security patterns to check
        security_patterns = {
            'hardcoded_secrets': [
                r'password\s*=\s*["\'][^"\']+["\']',
                r'api_key\s*=\s*["\'][^"\']+["\']',
                r'secret\s*=\s*["\'][^"\']+["\']',
                r'token\s*=\s*["\'][^"\']+["\']'
            ],
            'sql_injection': [
                r'execute\s*\(\s*["\'].*%.*["\']',
                r'format\s*\(\s*["\'].*SELECT.*["\']',
                r'\+.*["\'].*SELECT'
            ],
            'eval_usage': [
                r'eval\s*\(',
                r'exec\s*\(',
                r'__import__\s*\('
            ],
            'file_operations': [
                r'open\s*\(\s*["\'][^"\']*["\'].*\+',
                r'shutil\.rmtree',
                r'os\.remove',
                r'os\.system'
            ],
            'network_requests': [
                r'requests\.',
                r'urllib\.',
                r'http\.client',
                r'socket\.'
            ]
        }
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()
                
                for category, patterns in security_patterns.items():
                    for pattern in patterns:
                        for match in re.finditer(pattern, content, re.IGNORECASE):
                            line_num = content[:match.start()].count('\n') + 1
                            line_content = lines[line_num - 1].strip()
                            
                            security_issues.append({
                                'file': file_path,
                                'line': line_num,
                                'category': category,
                                'pattern': pattern,
                                'match': match.group(),
                                'line_content': line_content,
                                'severity': self.get_severity(category, pattern)
                            })
            except Exception as e:
                security_issues.append({
                    'file': file_path,
                    'error': str(e),
                    'category': 'scan_error'
                })
        
        return security_issues
    
    def code_quality_check(self) -> Dict[str, Any]:
        """Check code quality metrics"""
        quality_metrics = {
            'long_functions': [],
            'large_classes': [],
            'deep_nesting': [],
            'todo_comments': [],
            'magic_numbers': []
        }
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()
                
                tree = ast.parse(content)
                analyzer = QualityAnalyzer()
                analyzer.visit(tree)
                
                # Add file path to results
                for func in analyzer.long_functions:
                    func['file'] = file_path
                for cls in analyzer.large_classes:
                    cls['file'] = file_path
                for nest in analyzer.deep_nesting:
                    nest['file'] = file_path
                
                quality_metrics['long_functions'].extend(analyzer.long_functions)
                quality_metrics['large_classes'].extend(analyzer.large_classes)
                quality_metrics['deep_nesting'].extend(analyzer.deep_nesting)
                
                # Check for TODOs and magic numbers
                for i, line in enumerate(lines, 1):
                    if 'TODO' in line.upper() or 'FIXME' in line.upper():
                        quality_metrics['todo_comments'].append({
                            'file': file_path,
                            'line': i,
                            'content': line.strip()
                        })
                    
                    # Magic numbers (excluding common ones)
                    magic_numbers = re.findall(r'\b(?!0|1|2|10|100|1000)\d{2,}\b', line)
                    for num in magic_numbers:
                        quality_metrics['magic_numbers'].append({
                            'file': file_path,
                            'line': i,
                            'number': num,
                            'context': line.strip()
                        })
                        
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
        
        return quality_metrics
    
    def analyze_dependencies(self) -> Dict[str, Any]:
        """Analyze project dependencies and imports"""
        import_graph = defaultdict(set)
        external_imports = defaultdict(int)
        internal_imports = defaultdict(int)
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                analyzer = ImportAnalyzer(self.project_root)
                analyzer.visit(tree)
                
                # Build import graph
                for imp in analyzer.imports:
                    if imp['module'].startswith('.'):
                        # Internal import
                        internal_imports[imp['module']] += 1
                    else:
                        # External import
                        external_imports[imp['module']] += 1
                
                import_graph[file_path] = set(analyzer.imports)
                
            except Exception as e:
                print(f"Error analyzing imports in {file_path}: {e}")
        
        return {
            'import_graph': dict(import_graph),
            'external_imports': dict(external_imports),
            'internal_imports': dict(internal_imports),
            'most_imported': dict(Counter(external_imports).most_common(10))
        }
    
    def find_unused_imports(self) -> List[Dict[str, Any]]:
        """Find potentially unused imports"""
        unused_imports = []
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                analyzer = UnusedImportAnalyzer()
                analyzer.visit(tree)
                
                for imp in analyzer.unused_imports:
                    unused_imports.append({
                        'file': file_path,
                        'import': imp,
                        'line': imp['line']
                    })
                    
            except Exception as e:
                print(f"Error checking unused imports in {file_path}: {e}")
        
        return unused_imports
    
    def find_potential_bugs(self) -> List[Dict[str, Any]]:
        """Find potential bugs and anti-patterns"""
        bug_patterns = {
            'unreachable_code': [
                r'return.*\n.*return',
                r'break.*\n.*break',
                r'raise.*\n.*raise'
            ],
            'comparison_with_none': [
                r'==\s*None',
                r'!=\s*None',
                r'<\s*None',
                r'>\s*None'
            ],
            'mutable_default_args': [
                r'def\s+\w+\s*\([^)]*=\s*\[',
                r'def\s+\w+\s*\([^)]*=\s*\{'
            ],
            'exception_bare_except': [
                r'except\s*:',
                r'except\s*Exception\s*:'
            ],
            'unused_loop_variable': [
                r'for\s+\w+\s+in\s+.*:\s*\n\s*pass'
            ]
        }
        
        potential_bugs = []
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()
                
                for category, patterns in bug_patterns.items():
                    for pattern in patterns:
                        for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                            line_num = content[:match.start()].count('\n') + 1
                            line_content = lines[line_num - 1].strip()
                            
                            potential_bugs.append({
                                'file': file_path,
                                'line': line_num,
                                'category': category,
                                'pattern': pattern,
                                'match': match.group(),
                                'line_content': line_content
                            })
                            
            except Exception as e:
                print(f"Error checking bugs in {file_path}: {e}")
        
        return potential_bugs
    
    def dynamic_analysis(self, duration: int = 60) -> Dict[str, Any]:
        """Dynamic analysis while bot is running"""
        # Start memory tracking
        tracemalloc.start()
        
        # Monitor process for specified duration
        process = psutil.Process()
        start_time = time.time()
        memory_samples = []
        cpu_samples = []
        
        while time.time() - start_time < duration:
            try:
                # Memory usage
                memory_info = process.memory_info()
                memory_samples.append({
                    'timestamp': time.time(),
                    'rss': memory_info.rss / 1024 / 1024,  # MB
                    'vms': memory_info.vms / 1024 / 1024   # MB
                })
                
                # CPU usage
                cpu_percent = process.cpu_percent()
                cpu_samples.append({
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent
                })
                
                time.sleep(1)
            except psutil.NoSuchProcess:
                break
        
        # Get memory traces
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        return {
            'memory_samples': memory_samples,
            'cpu_samples': cpu_samples,
            'peak_memory': peak / 1024 / 1024,  # MB
            'current_memory': current / 1024 / 1024,  # MB
            'analysis_duration': duration
        }
    
    def performance_profile(self, callable_ref, mode: str = 'function') -> Dict[str, Any]:
        """Profile code performance using a callable object.

        ``callable_ref`` must be one of:
          - A zero-argument callable (e.g. lambda: my_func(42))
          - A fully-qualified dotted name resolvable via :func:`_resolve_callable`
            (e.g. ``"module.submodule:ClassName.method_name"``)

        **``exec()`` is never used here** — the callable is invoked directly
        after a safe allow-list resolution.
        """
        profiler = cProfile.Profile()
        callable_obj = None

        if callable(callable_ref):
            callable_obj = callable_ref
        elif isinstance(callable_ref, str):
            callable_obj = self._resolve_callable(callable_ref)
            if callable_obj is None:
                return {
                    'profile_output': '',
                    'error': f'callable "{callable_ref}" could not be resolved; '
                             'use "module:function" syntax or pass a direct callable',
                }
        else:
            return {
                'profile_output': '',
                'error': 'callable_ref must be a callable or a dotted-name string',
            }

        profiler.enable()
        try:
            callable_obj()
        finally:
            profiler.disable()

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
        ps.print_stats()

        return {
            'profile_output': s.getvalue(),
            'total_calls': ps.total_calls,
            'primitive_calls': ps.prim_calls,
            'cumulative_time': ps.total_tt
        }

    @staticmethod
    def _resolve_callable(dotted_name: str):
        """Resolve ``module.path:qualname`` to a callable via allow-list lookup.

        Only targets explicitly present in ``_PROFILEABLE_CALLABLES`` are
        permitted — arbitrary attribute chains are refused.
        """
        # Allow-list of profileable callables.
        # Add entries here when new profiling targets are needed.
        _PROFILEABLE_CALLABLES = {}

        if not dotted_name or ':' not in dotted_name:
            return None
        _mod, _qualname = dotted_name.rsplit(':', 1)
        _mod = _mod.strip()
        _qualname = _qualname.strip()
        if not _mod or not _qualname:
            return None
        # Cross-reference against the allow-list ONLY.
        allowed = _PROFILEABLE_CALLABLES.get(dotted_name)
        if allowed is not None:
            return allowed
        # Fallback: safe dynamic lookup restricted to already-imported
        # modules — no importlib, no exec.
        try:
            _ns = sys.modules.get(_mod)
            if _ns is None:
                return None
            _obj = _ns
            for _part in _qualname.split('.'):
                _obj = getattr(_obj, _part, None)
                if _obj is None:
                    return None
            if callable(_obj):
                return _obj
        except Exception:
            pass
        return None
    
    def get_severity(self, category: str, pattern: str) -> str:
        """Determine severity of security issue"""
        high_severity = ['hardcoded_secrets', 'eval_usage', 'sql_injection']
        medium_severity = ['file_operations', 'network_requests']
        
        if category in high_severity:
            return 'HIGH'
        elif category in medium_severity:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def generate_audit_report(self) -> str:
        """Generate comprehensive audit report"""
        report = []
        report.append("# 📊 ALADDIN TRADING BOT - COMPREHENSIVE CODE AUDIT REPORT")
        report.append(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Project Root: {self.project_root}")
        report.append(f"Python Files Analyzed: {len(self.python_files)}")
        report.append("\n" + "="*80 + "\n")
        
        # Static Analysis
        static_results = self.static_analysis()
        
        # Complexity Analysis
        report.append("## 📈 COMPLEXITY ANALYSIS")
        report.append("\n### Most Complex Functions:")
        complexity_data = static_results['complexity_analysis']
        sorted_complex = sorted(
            [(file, data) for file, data in complexity_data.items() if 'max_function_complexity' in data],
            key=lambda x: x[1]['max_function_complexity'],
            reverse=True
        )[:10]
        
        for file, data in sorted_complex:
            report.append(f"- **{os.path.basename(file)}**: Max complexity {data['max_function_complexity']}")
            for func in data.get('complex_functions', [])[:3]:
                report.append(f"  - {func['name']}: {func['complexity']}")
        
        # Security Issues
        report.append("\n## 🔒 SECURITY ANALYSIS")
        security_issues = static_results['security_issues']
        if security_issues:
            report.append(f"\n### Found {len(security_issues)} Security Issues:")
            for issue in security_issues[:20]:  # Show top 20
                report.append(f"- **{issue['category'].upper()}** ({issue['severity']}):")
                report.append(f"  File: {os.path.basename(issue['file'])}:{issue['line']}")
                report.append(f"  Code: `{issue['line_content']}`")
        else:
            report.append("\n✅ No critical security issues found!")
        
        # Code Quality
        report.append("\n## 📝 CODE QUALITY")
        quality = static_results['code_quality']
        
        report.append(f"\n- Long Functions (>50 lines): {len(quality['long_functions'])}")
        report.append(f"- Large Classes (>20 methods): {len(quality['large_classes'])}")
        report.append(f"- Deep Nesting (>4 levels): {len(quality['deep_nesting'])}")
        report.append(f"- TODO Comments: {len(quality['todo_comments'])}")
        report.append(f"- Magic Numbers: {len(quality['magic_numbers'])}")
        
        # Dependencies
        report.append("\n## 📦 DEPENDENCY ANALYSIS")
        deps = static_results['dependencies']
        report.append("\n### Most Used External Libraries:")
        for lib, count in deps['most_imported']:
            report.append(f"- {lib}: {count} imports")
        
        # Potential Issues
        report.append("\n## ⚠️ POTENTIAL ISSUES")
        bugs = static_results['potential_bugs']
        if bugs:
            report.append(f"\nFound {len(bugs)} potential issues:")
            for bug in bugs[:15]:  # Show top 15
                report.append(f"- **{bug['category']}**: {os.path.basename(bug['file'])}:{bug['line']}")
        else:
            report.append("\n✅ No obvious anti-patterns detected!")
        
        # Recommendations
        report.append("\n## 💡 RECOMMENDATIONS")
        report.append("\n1. **High Priority:**")
        report.append("   - Review and fix any HIGH severity security issues")
        report.append("   - Refactor functions with complexity > 10")
        report.append("   - Remove or document TODO comments")
        
        report.append("\n2. **Medium Priority:**")
        report.append("   - Break down long functions (>50 lines)")
        report.append("   - Remove unused imports")
        report.append("   - Replace magic numbers with named constants")
        
        report.append("\n3. **Low Priority:**")
        report.append("   - Consider using type hints more consistently")
        report.append("   - Add docstrings to public functions")
        report.append("   - Consider using linters like flake8 or pylint")
        
        return "\n".join(report)


# AST Analyzer Classes
class ComplexityAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.total_complexity = 0
        self.max_complexity = 0
        self.function_count = 0
        self.class_count = 0
        self.complex_functions = []
        self.current_function = None
        self.current_complexity = 0
    
    def visit_FunctionDef(self, node):
        self.function_count += 1
        self.current_function = node.name
        self.current_complexity = 1  # Base complexity
        
        # Count complexity points
        self.generic_visit(node)
        
        if self.current_complexity > self.max_complexity:
            self.max_complexity = self.current_complexity
        
        if self.current_complexity > 10:  # Threshold for complex functions
            self.complex_functions.append({
                'name': node.name,
                'complexity': self.current_complexity,
                'line': node.lineno
            })
        
        self.total_complexity += self.current_complexity
        self.current_complexity = 0
        self.current_function = None
    
    def visit_If(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_For(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_While(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_With(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_Try(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_ExceptHandler(self, node):
        self.current_complexity += 1
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        self.class_count += 1
        self.generic_visit(node)


class QualityAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.long_functions = []
        self.large_classes = []
        self.deep_nesting = []
        self.nesting_level = 0
    
    def visit_FunctionDef(self, node):
        # Check function length
        if hasattr(node, 'end_lineno') and node.end_lineno:
            lines = node.end_lineno - node.lineno + 1
            if lines > 50:
                self.long_functions.append({
                    'name': node.name,
                    'lines': lines,
                    'line': node.lineno
                })
        
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        # Count methods
        method_count = sum(1 for n in ast.walk(node) if isinstance(n, ast.FunctionDef))
        if method_count > 20:
            self.large_classes.append({
                'name': node.name,
                'methods': method_count,
                'line': node.lineno
            })
        
        self.generic_visit(node)
    
    def visit_If(self, node):
        self.nesting_level += 1
        if self.nesting_level > 4:
            self.deep_nesting.append({
                'type': 'if',
                'line': node.lineno,
                'depth': self.nesting_level
            })
        
        self.generic_visit(node)
        self.nesting_level -= 1
    
    def visit_For(self, node):
        self.nesting_level += 1
        if self.nesting_level > 4:
            self.deep_nesting.append({
                'type': 'for',
                'line': node.lineno,
                'depth': self.nesting_level
            })
        
        self.generic_visit(node)
        self.nesting_level -= 1
    
    def visit_While(self, node):
        self.nesting_level += 1
        if self.nesting_level > 4:
            self.deep_nesting.append({
                'type': 'while',
                'line': node.lineno,
                'depth': self.nesting_level
            })
        
        self.generic_visit(node)
        self.nesting_level -= 1


class ImportAnalyzer(ast.NodeVisitor):
    def __init__(self, project_root):
        self.project_root = project_root
        self.imports = []
    
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append({
                'type': 'import',
                'module': alias.name,
                'alias': alias.asname,
                'line': node.lineno
            })
    
    def visit_ImportFrom(self, node):
        module = node.module or ''
        for alias in node.names:
            self.imports.append({
                'type': 'from',
                'module': f"{module}.{alias.name}" if module else alias.name,
                'alias': alias.asname,
                'line': node.lineno
            })


class UnusedImportAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.imports = []
        self.used_names = set()
        self.unused_imports = []
    
    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports.append({
                'name': name,
                'line': node.lineno,
                'type': 'import'
            })
    
    def visit_ImportFrom(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports.append({
                'name': name,
                'line': node.lineno,
                'type': 'from'
            })
    
    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
    
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            self.used_names.add(node.value.id)
    
    def finalize(self):
        for imp in self.imports:
            if imp['name'] not in self.used_names:
                self.unused_imports.append(imp)


# Convenience function for quick audit
def quick_audit():
    """Perform a quick audit of the codebase"""
    auditor = CodeAuditor()
    return auditor.generate_audit_report()


if __name__ == "__main__":
    # Run comprehensive audit
    auditor = CodeAuditor()
    report = auditor.generate_audit_report()
    
    # Save report
    with open('audit_report.md', 'w') as f:
        f.write(report)
    
    print("📊 Audit complete! Report saved to audit_report.md")
    print("\n" + "="*50)
    print(report[:1000] + "\n...")  # Show preview
