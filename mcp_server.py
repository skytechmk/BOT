#!/usr/bin/env python3
"""
MCP Server for OpenClaw Gateway — exposes Aladdin Trading Bot tools
via the Model Context Protocol (stdio transport).

This wraps the existing MCPBridge class so OpenClaw's S.P.E.C.T.R.E.
agent can access live market data, open signals, system diagnostics,
internet search, memory, and Telegram management.
"""

import os
import sys
import json
import ast
import asyncio
import threading
from typing import Optional

# Set SSE port early so FastMCP Settings picks it up
os.environ.setdefault("FASTMCP_PORT", "8819")
os.environ.setdefault("FASTMCP_HOST", "127.0.0.1")

# Ensure the bot directory is on the path
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

# Load .env before any bot imports
from dotenv import load_dotenv
load_dotenv(os.path.join(BOT_DIR, ".env"))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "aladdin",
    instructions=(
        "Aladdin Trading Bot tools. Use these to query live market data, "
        "check open signals, run diagnostics, search the internet, and "
        "manage long-term memory."
    ),
)

# ---------------------------------------------------------------------------
# Helper: lazy-import MCPBridge (heavy imports — pre-warmed in background)
# ---------------------------------------------------------------------------
_bridge = None
_bridge_lock = threading.Lock()

def _get_bridge():
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                from ai_mcp_bridge import MCPBridge
                _bridge = MCPBridge
    return _bridge

_prewarm_started = False

def _schedule_prewarm():
    """Start background MCPBridge import after first tool call (not at startup)."""
    global _prewarm_started
    if not _prewarm_started:
        _prewarm_started = True
        def _do():
            try:
                _get_bridge()
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()


def _first_non_empty(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ===========================================================================
# TRADING TOOLS
# ===========================================================================

@mcp.tool()
def get_open_signals() -> str:
    """Get all currently active trading signals with entry, targets, stop-loss, and PnL."""
    return _get_bridge().get_open_signals()


@mcp.tool()
def get_market_context(pair: str = "", symbol: str = "", interval: str = "1h") -> str:
    """Fetch current market data (price + recent candles) for a Binance USDT perpetual pair.

    Args:
        pair: Trading pair symbol, e.g. BTCUSDT
        interval: Candle interval — 1m, 5m, 15m, 1h, 4h, 1d
    """
    pair = _first_non_empty(pair, symbol)
    if not pair:
        return json.dumps({"success": False, "error": "Missing required parameter: pair/symbol"}, indent=2)
    return _get_bridge().get_market_context(pair, interval)


@mcp.tool()
def cancel_trade_signal(signal_id: str, reason: str) -> str:
    """Propose cancellation of an active signal.

    Args:
        signal_id: UUID of the signal to cancel
        reason: Justification for the cancellation
    """
    return _get_bridge().cancel_trade_signal(signal_id, reason)


# ===========================================================================
# BINANCE MARKET METRICS
# ===========================================================================

@mcp.tool()
async def get_funding_rate(pair: str = "", symbol: str = "") -> str:
    """Get current Binance funding rate analysis for a USDT perpetual pair.

    Args:
        pair: Trading pair symbol, e.g. BTCUSDT
    """
    _schedule_prewarm()
    pair = _first_non_empty(pair, symbol)
    print(f"[MCP] get_funding_rate called: {pair}", file=sys.stderr)
    if not pair:
        return json.dumps({"success": False, "error": "Missing required parameter: pair/symbol"}, indent=2)
    from data_fetcher import analyze_funding_rate_sentiment

    analysis = await asyncio.to_thread(analyze_funding_rate_sentiment, pair)
    return json.dumps(analysis, indent=2, sort_keys=True)


@mcp.tool()
async def get_open_interest(pair: str = "", symbol: str = "") -> str:
    """Get current Binance open interest snapshot and recent change context.

    Args:
        pair: Trading pair symbol, e.g. BTCUSDT
    """
    _schedule_prewarm()
    pair = _first_non_empty(pair, symbol)
    print(f"[MCP] get_open_interest called: {pair}", file=sys.stderr)
    if not pair:
        return json.dumps({"success": False, "error": "Missing required parameter: pair/symbol"}, indent=2)
    from data_fetcher import get_open_interest as _get_open_interest

    oi_data = await asyncio.to_thread(_get_open_interest, pair)
    return json.dumps(oi_data, indent=2, sort_keys=True)


# ===========================================================================
# SYSTEM DIAGNOSTICS
# ===========================================================================

@mcp.tool()
async def run_system_diagnostic(command_key: str = "", command: str = "") -> str:
    """Run a read-only diagnostic on the Linux server.

    Args:
        command_key: One of: uptime, disk_space, memory_usage, cpu_processes, whoami, date, os_info
    """
    command_key = _first_non_empty(command_key, command)
    if not command_key:
        return json.dumps({"success": False, "error": "Missing required parameter: command_key/command"}, indent=2)
    return await _get_bridge().run_system_diagnostic(command_key)


# ===========================================================================
# INTERNET SEARCH
# ===========================================================================

@mcp.tool()
async def search_internet(query: str, engine: str = "duckduckgo", max_results: int = 5) -> str:
    """Search the internet for general information.

    Args:
        query: Search query string
        engine: Search engine — duckduckgo, brave, or searx
        max_results: Maximum number of results to return
    """
    return await _get_bridge().search_internet(query, engine, max_results)


@mcp.tool()
async def search_trading_news(query: str = "trading signals") -> str:
    """Search for trading-related news and analysis.

    Args:
        query: Trading search query
    """
    return await _get_bridge().search_trading_news(query)


@mcp.tool()
async def search_market_data(symbol: str = "BTC") -> str:
    """Search for current market data and analysis from the web.

    Args:
        symbol: Trading symbol — BTC, ETH, SOL, etc.
    """
    return await _get_bridge().search_market_data(symbol)


# ===========================================================================
# LONG-TERM MEMORY
# ===========================================================================

@mcp.tool()
async def store_core_belief(topic: str, fact: str) -> str:
    """Store an overriding rule or preference (overwrites if topic exists).

    Args:
        topic: The subject/topic of the belief
        fact: The actual rule or preference
    """
    return await _get_bridge().store_core_belief(topic, fact)


@mcp.tool()
async def recall_core_beliefs() -> str:
    """Retrieve all stored overriding rules and preferences."""
    return await _get_bridge().recall_core_beliefs()


@mcp.tool()
async def store_memory(event: str) -> str:
    """Store a memory or conversation snippet for long-term recall.

    Args:
        event: The event or information to remember
    """
    return await _get_bridge().store_memory(event)


@mcp.tool()
async def recall_memory(query: str) -> str:
    """Semantically retrieve relevant memories using free-text search.

    Args:
        query: What to search for in memory
    """
    return await _get_bridge().recall_memory(query)


# ===========================================================================
# CODE AUDIT
# ===========================================================================

@mcp.tool()
def quick_security_scan() -> str:
    """Perform a quick security and complexity scan of the codebase."""
    return _get_bridge().quick_security_scan()


@mcp.tool()
def analyze_specific_file(file_path: str) -> str:
    """Analyze a specific file for security and complexity issues.

    Args:
        file_path: Path to the file to analyze
    """
    return _get_bridge().analyze_specific_file(file_path)


# ===========================================================================
# TELEGRAM MANAGEMENT (read-only + messaging)
# ===========================================================================

@mcp.tool()
async def get_chat_info(chat_id: str) -> str:
    """Get comprehensive information about a Telegram chat/group/channel.

    Args:
        chat_id: Telegram chat ID
    """
    return await _get_bridge().get_chat_info(chat_id)


@mcp.tool()
async def get_chat_administrators(chat_id: str) -> str:
    """Get list of administrators in a Telegram chat.

    Args:
        chat_id: Telegram chat ID
    """
    return await _get_bridge().get_chat_administrators(chat_id)


@mcp.tool()
async def get_chat_member_count(chat_id: str) -> str:
    """Get total number of members in a Telegram chat.

    Args:
        chat_id: Telegram chat ID
    """
    return await _get_bridge().get_chat_member_count(chat_id)


@mcp.tool()
async def send_message(chat_id: str, text: str, parse_mode: str = None) -> str:
    """Send a message to a Telegram chat.

    Args:
        chat_id: Telegram chat ID
        text: Message text to send
        parse_mode: Optional formatting — HTML or Markdown
    """
    return await _get_bridge().send_message(chat_id, text, parse_mode=parse_mode)


@mcp.tool()
async def get_ops_member_list() -> str:
    """Get current members of the Ops channel."""
    return await _get_bridge().get_ops_member_list()


@mcp.tool()
def read_channel_messages(channel: str = "signals", limit: int = 20, search: Optional[str] = None) -> str:
    """Read recent messages directly from a Telegram channel using the Telethon user session.

    Args:
        channel: Channel alias — 'signals' (main signals), 'closed' (closed signals),
                 'ops' (ops group), or a raw numeric chat_id.
        limit:   Number of recent messages to fetch (1-100, default 20).
        search:  Optional keyword to filter messages (e.g. 'BTCUSDT', 'SHORT').
    """
    try:
        from telethon_reader import fetch_channel_messages
        return fetch_channel_messages(channel=channel, limit=limit, search=search)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ===========================================================================
# FILE OPERATIONS — standalone, no MCPBridge dependency (instant response)
# ===========================================================================

_WORKSPACE = BOT_DIR

def _resolve_path(file_path: str) -> str:
    """Resolve relative paths against workspace root."""
    if not os.path.isabs(file_path):
        return os.path.join(_WORKSPACE, file_path)
    return file_path


@mcp.tool()
def read_file(file_path: str, limit: int = 0) -> str:
    """Read a project file. Path can be relative to workspace or absolute.

    Args:
        file_path: Path to the file to read
        limit: Optional max number of lines to return (0 = full file)
    """
    _schedule_prewarm()
    print(f"[MCP] read_file called: {file_path} limit={limit}", file=sys.stderr)
    try:
        resolved = _resolve_path(file_path)
        if not os.path.exists(resolved):
            return f"Error: File {resolved} not found."
        with open(resolved, 'r') as f:
            content = f.read()
        if limit and limit > 0:
            lines = content.splitlines()
            content = "\n".join(lines[:limit])
            if len(lines) > limit:
                content += f"\n... ({len(lines) - limit} more lines truncated)"
        return f"SUCCESS: Read {len(content)} bytes from {resolved}.\nCONTENT:\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def edit_file(file_path: str, content: str) -> str:
    """Write a file — restricted to safe extensions (.md, .txt, .json, .py).
    For code changes, write a proposal as a markdown file in proposals/ with diff format.
    Parent directories are created automatically.

    Args:
        file_path: Path to the file to write (use proposals/ directory for code changes)
        content: Full file content to write
    """
    print(f"[MCP] edit_file called: {file_path} ({len(content)} bytes)", file=sys.stderr)
    try:
        resolved = _resolve_path(file_path)
        if not resolved.endswith(('.py', '.json', '.env', '.txt', '.md')):
            return "REJECTED: Unauthorized file extension."
        if resolved.endswith('.py'):
            try:
                ast.parse(content)
            except SyntaxError as e:
                return f"REJECTED: Syntax error in proposal: {e}"
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, 'w') as f:
            f.write(content)
        return f"SUCCESS: File {resolved} written ({len(content)} bytes)."
    except Exception as e:
        return f"Error writing file: {e}"


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8819)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if args.transport == "sse":
        os.environ["FASTMCP_HOST"] = args.host
        os.environ["FASTMCP_PORT"] = str(args.port)
        print(f"[MCP] Starting SSE server on http://{args.host}:{args.port}/sse", file=sys.stderr)
    mcp.run(transport=args.transport)
