#!/usr/bin/env python3
"""
System Monitor: Strictly read-only system diagnostic capabilities for the AI Agent.
"""

import subprocess
import json

class SystemMonitor:
    """Provides safe, read-only system diagnostic commands"""
    
    # 100% STRICT WHITELIST
    WHITELISTED_COMMANDS = {
        "uptime": ["uptime"],
        "disk_space": ["df", "-h"],
        "memory_usage": ["free", "-m"],
        "cpu_processes": ["top", "-b", "-n", "1"],
        "whoami": ["whoami"],
        "date": ["date"],
        "os_info": ["uname", "-a"]
    }
    
    @classmethod
    def run_system_diagnostic(cls, command_key):
        """Run a whitelisted command safely"""
        if command_key not in cls.WHITELISTED_COMMANDS:
            return json.dumps({
                "success": False,
                "error": f"Command '{command_key}' is NOT on the strict read-only whitelist.",
                "allowed_commands": list(cls.WHITELISTED_COMMANDS.keys())
            }, indent=2)
            
        try:
            cmd = cls.WHITELISTED_COMMANDS[command_key]
            # Use subprocess to run strictly read-only diagnostics safely
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            # Truncate output if it's too long (e.g. top command)
            stdout_output = result.stdout
            if len(stdout_output) > 2000:
                stdout_output = stdout_output[:2000] + "\n...[Output Truncated]..."
                
            return json.dumps({
                "success": result.returncode == 0,
                "command": cmd,
                "output": stdout_output.strip(),
                "error": result.stderr.strip() if result.stderr else None
            }, indent=2)
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)

# MCP Function Export
async def run_system_diagnostic(command_key="uptime"):
    """MCP function for system diagnostic tool executing read-only commands."""
    return SystemMonitor.run_system_diagnostic(command_key)

if __name__ == "__main__":
    print(SystemMonitor.run_system_diagnostic("uptime"))
