# Proposal: Implementation — Fix MCP Parameter Issues & Missing Systemic Fragility Method

**Date**: 2026-04-06  
**Priority**: CRITICAL  
**Type**: Implementation Patch  
**Estimated Time**: 2-3 hours  
**Status**: Ready for Approval

---

## Executive Summary

Two blocking bugs are crippling the Aladdin Trading Bot:

1. **MCP tools inaccessible** — All `aladdin__*` tool calls fail with `-32602 Invalid request parameters`
2. **Main loop crashes** — `OpenRouterIntelligence` missing `analyze_systemic_fragility` method

This proposal provides **exact code changes** to fix both issues and restore full functionality.

---

## Problem Details

### Issue 1: MCP Parameter Schema Mismatch

**Symptom**: Every MCP tool call from OpenClaw returns:
```
MCP error -32602: Invalid request parameters
```

**Root Cause**: FastMCP server expects parameters named `pair` (str), but the OpenClaw MCP client may be sending `symbol` or using a different JSON schema structure. Additionally, parameter validation may be too strict.

**Impact**:
- ❌ `get_funding_rate()` inaccessible
- ❌ `get_open_interest()` inaccessible
- ❌ `get_market_context()` inaccessible
- ❌ All internet search, memory, and system tools broken
- 🔴 **AI agent cannot make trading decisions** without these tools

---

### Issue 2: Missing `analyze_systemic_fragility` Method

**Symptom**: Every minute in `main.log`:
```
'OpenRouterIntelligence' object has no attribute 'analyze_systemic_fragility'
```

**Root Cause**: `main.py` calls:
```python
fragility = self.openrouter.analyze_systemic_fragility(market_data)
```
But `OpenRouterIntelligence` class has no such method.

**Impact**:
- 🔴 Systemic fragility & stress tests never run
- ⚠️ Signal generation may be incomplete
- ⚠️ Risk assessment compromised
- ⚠️ Main loop enters error state repeatedly

---

## Proposed Changes (Diffs)

---

### **Change 1: Add Stub Method to `openrouter_intelligence.py`**

**File**: `openrouter_intelligence.py`  
**Location**: Inside `OpenRouterIntelligence` class

```python
<<<<<<< SEARCH
    # ... existing methods ...
=======
    def analyze_systemic_fragility(self, market_data: Dict) -> Dict:
        """
        Analyze systemic fragility across multiple assets and timeframes.
        Returns fragility score and risk level.

        TODO: Implement full analysis using:
        - Cross-asset correlation spikes
        - Funding rate extremes
        - Open interest anomalies
        - Liquidity vacuum detection
        """
        try:
            # Safe defaults until full implementation
            return {
                "fragility_score": 0.5,  # 0-1 scale, 0.5 = neutral
                "risk_level": "moderate",
                "signals": [],
                "timestamp": datetime.utcnow().isoformat(),
                "note": "stub implementation - pending full analysis"
            }
        except Exception as e:
            log_message(f"Error in analyze_systemic_fragility: {e}")
            return {
                "fragility_score": 0.5,
                "risk_level": "moderate",
                "error": str(e)
            }
>>>>>>> REPLACE
```

**Why this works**: Provides the missing method with safe defaults. Main loop stops crashing immediately. Full implementation can be added later without breaking the system.

---

### **Change 2: Add MCP Debug Echo Tool (Temporary)**

**File**: `mcp_server.py`  
**Location**: Add near other tool definitions (after `get_market_context`)

```python
<<<<<<< SEARCH
@mcp.tool()
def get_funding_rate(pair: str) -> str:
    ...
=======
@mcp.tool()
async def mcp_debug_echo(**kwargs) -> str:
    """
    DEBUG TOOL: Echo back received parameters to diagnose schema mismatch.
    Remove after MCP issues resolved.
    """
    import json
    return json.dumps({
        "received": kwargs,
        "keys": list(kwargs.keys()),
        "types": {k: type(v).__name__ for k, v in kwargs.items()}
    }, indent=2)
>>>>>>> REPLACE
```

**Why this works**: Allows us to see exactly what OpenClaw is sending. Call it:
```python
aladdin__mcp_debug_echo(pair="BTCUSDT", foo="bar")
```
and check response. Then we can adjust parameter names accordingly.

---

### **Change 3: Fix Parameter Name Inconsistency (If Needed)**

After running `mcp_debug_echo`, we may discover OpenClaw sends `symbol` instead of `pair`. If so, we must:

**Option A (Preferred)**: Make all MCP tool parameters accept both names:

```python
@mcp.tool()
async def get_funding_rate(pair: str = None, symbol: str = None) -> str:
    """Get current Binance funding rate analysis.

    Args:
        pair: Trading pair symbol, e.g. BTCUSDT
        symbol: Alias for pair (for compatibility)
    """
    _schedule_prewarm()
    print(f"[MCP] get_funding_rate called: pair={pair}, symbol={symbol}", file=sys.stderr)
    from data_fetcher import analyze_funding_rate_sentiment

    # Use whichever parameter was provided
    target = pair or symbol
    if not target:
        return json.dumps({"error": "Must provide pair or symbol"})

    analysis = await asyncio.to_thread(analyze_funding_rate_sentiment, target)
    return json.dumps(analysis, indent=2, sort_keys=True)
```

Apply same pattern to:
- `get_open_interest(pair: str = None, symbol: str = None)`
- `get_market_context(pair: str = None, symbol: str = None, interval: str = "1h")`

**Option B**: Force OpenClaw client to use `pair` (not possible if we don't control client)

**Recommended**: Use Option A for maximum compatibility.

---

### **Change 4: Add Robust Error Handling to MCP Tools**

Wrap each MCP tool call in try/except to prevent server crashes and return meaningful errors:

```python
@mcp.tool()
async def get_funding_rate(pair: str = None, symbol: str = None) -> str:
    """..."""
    _schedule_prewarm()
    try:
        target = pair or symbol
        if not target:
            return json.dumps({"error": "Missing required parameter: pair or symbol"})

        from data_fetcher import analyze_funding_rate_sentiment
        analysis = await asyncio.to_thread(analyze_funding_rate_sentiment, target)
        return json.dumps(analysis, indent=2, sort_keys=True)
    except Exception as e:
        log_message(f"MCP get_funding_rate error: {e}")
        return json.dumps({"error": str(e), "tool": "get_funding_rate"})
```

Apply to all tools for consistency.

---

### **Change 5: Restart MCP Server with Debug Logging**

**Shell command** (run after code changes):

```bash
cd /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA
pkill -f "mcp_server.py"  # kill old process
FASTMCP_DEBUG=1 nohup python3 mcp_server.py --transport sse --port 8819 > mcp_debug.log 2>&1 &
```

This enables FastMCP debug output to catch schema issues.

---

## Implementation Steps

### **Step 1: Apply Change 1 (Stub Method)** — 15 min

1. Open `openrouter_intelligence.py`
2. Find class `OpenRouterIntelligence`
3. Insert stub method at end (before `__init__` or after last method)
4. Import needed: `from datetime import datetime` if not already present
5. Test import: `python3 -c "from openrouter_intelligence import OpenRouterIntelligence; print(OpenRouterIntelligence().analyze_systemic_fragility({}))"`

---

### **Step 2: Apply Change 2 (Debug Echo Tool)** — 10 min

1. Open `mcp_server.py`
2. Add `mcp_debug_echo` tool after line ~95 (after `get_market_context`)
3. Restart MCP server with `FASTMCP_DEBUG=1`
4. Verify tool available: check log or call from OpenClaw

---

### **Step 3: Test & Diagnose** — 20 min

1. From OpenClaw, call:
   ```python
   aladdin__mcp_debug_echo(test_param="value", pair="BTCUSDT")
   ```
2. Observe response format. Does it show `{"received": {...}}` or error?
3. If error, check `mcp_debug.log` for FastMCP validation messages.
4. Identify correct parameter structure.

---

### **Step 4: Apply Change 3 (Parameter Flexibility)** — 30 min

Based on Step 3 findings, modify all affected MCP tools:
- `get_funding_rate`
- `get_open_interest`
- `get_market_context`
- `run_system_diagnostic`
- `search_internet`
- `search_trading_news`
- `search_market_data`
- `store_core_belief`
- `recall_core_beliefs`
- `store_memory`
- `recall_memory`

Make each accept both `pair` and `symbol` aliases where applicable, or adjust to match what OpenClaw sends.

---

### **Step 5: Apply Change 4 (Error Handling)** — 20 min

Add try/except wrappers to all MCP tools to prevent crashes and return JSON error messages.

---

### **Step 6: Verify End-to-End** — 30 min

1. Restart MCP server (clean start, no debug flag)
2. From OpenClaw, call:
   - `aladdin__get_funding_rate(pair="BTCUSDT")` → should return JSON
   - `aladdin__get_open_interest(pair="BTCUSDT")` → should return JSON
   - `aladdin__get_market_context(pair="BTCUSDT", interval="1h")` → should return JSON
3. Check `main.log` — confirm no more `analyze_systemic_fragility` errors
4. Wait 5-10 minutes — confirm bot continues scanning and logging normally
5. Verify signals generated (check `open_signals` or Telegram channel)

---

## Rollback Plan

If any change causes new issues:

1. **Git revert** (if using git):
   ```bash
   git revert HEAD  # or specific commit
   ```
2. Or manually undo changes in the files
3. Restart affected services (main.py, mcp_server.py)
4. System should return to pre-fix state (with original bugs, but no new ones)

---

## Verification Checklist

After implementation:

- [ ] `main.log` shows NO `analyze_systemic_fragility` errors for 10 minutes
- [ ] MCP server logs show tool calls succeeding (no -32602 errors)
- [ ] `aladdin__get_funding_rate(pair="BTCUSDT")` returns valid JSON
- [ ] `aladdin__get_open_interest(pair="BTCUSDT")` returns valid JSON
- [ ] All other MCP tools (`search_internet`, `store_memory`, etc.) work
- [ ] Bot generates at least 1 signal within 1 hour
- [ ] System stable, no crash loops

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Stub method too naive, breaks later analysis | Low | Medium | Stub returns safe defaults; full implementation planned separately |
| Parameter alias approach confuses type hints | Medium | Medium | Test thoroughly; keep both options optional with clear precedence |
| MCP server restart causes brief downtime | Low | Low | Schedule during low activity; restart is quick |
| Error handling masks real bugs | Low | Medium | Log errors separately; monitor logs after deployment |

---

## Cost Estimate

- **Development**: 2-3 hours
- **Testing**: 1 hour
- **Monitoring**: 30 min post-deploy
- **Total**: ~3.5-4.5 hours

---

## Approval Required

This is a **critical bug fix**. Approval to proceed with:

1. ✅ Add `analyze_systemic_fragility` stub to `openrouter_intelligence.py`
2. ✅ Add `mcp_debug_echo` tool to `mcp_server.py`
3. ✅ Restart MCP with debug logging
4. ✅ Based on findings, adjust parameter names to be flexible
5. ✅ Add error handling wrappers

---

**Prepared by**: S.P.E.C.T.R.E.  
**Implementation Lead**: [Pending]  
**Test Approval**: [Pending]
