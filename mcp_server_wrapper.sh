#!/bin/bash
# Wrapper script for MCP server — ensures clean stdio for MCP protocol
# Redirects ALL Python stderr (import noise, GPU messages, etc.) to a log file
exec python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/mcp_server.py 2>/tmp/mcp_server_stderr.log
