# Proposal: Fix MCP Parameter Schema & Missing Systemic Fragility Method

**Date**: 2026-04-06  
**Priority**: HIGH  
**Status**: Urgent  
**Related**: MCP server, OpenRouter Intelligence, main trading loop

---

## Problem Summary

Two critical issues are preventing the Aladdin Trading Bot from operating correctly:

### 1. MCP Tool Calls Failing ❌

**Symptom**: All MCP tool calls via OpenClaw return:
```
MCP error -32602: Invalid request parameters
```

**Impact**:
- AI agent cannot access funding rates, open interest, market context, or any MCP-exposed tools
- Trading signal generation is blind to real-time metrics
- System diagnostics and internet search are broken

**Root Cause Analysis**:
- MCP server (`mcp_server.py`) is running on port 8819
- Tools are registered with FastMCP using parameter names like `pair`, `command_key`, etc.
- The OpenClaw MCP client likely sends parameters with different naming (e.g., `symbol` instead of `pair`)
- JSON Schema mismatch causes validation rejection before tool execution
- Alternatively: FastMCP version incompatibility or parameter type coercion issues

**Evidence**:
```bash
$ ps aux | grep mcp
root 3614771 python3 mcp_server.py --transport sse --port 8819

$ curl -s http://localhost:8819/ → 404 (SSE endpoint, not HTTP)
$ Tool calls via aladdin__* → all -32602 errors
```

---

### 2. Main Loop Crashing 🔴

**Symptom**: `main.log` shows repeated errors every minute:
```
'OpenRouterIntelligence' object has no attribute 'analyze_systemic_fragility'
```

**Impact**:
- Main trading loop cannot complete systemic fragility & stress tests
- Signal generation may be incomplete or skipped
- System may enter error recovery loops

**Root Cause**:
- `main.py` calls `openrouter_intelligence.analyze_systemic_fragility(market_data)`
- The method is either missing, renamed, or has a signature mismatch in `openrouter_intelligence.py`
- No fallback or stub implementation

**Evidence**:
```
2026-04-06 20:07:17 - Critical error in main loop: 'OpenRouterIntelligence' object has no attribute 'analyze_systemic_fragility'
[Repeats every minute at :07]
```

---

## Proposed Solutions

---

### **Fix 1: MCP Parameter Schema Alignment**

#### Option A: Add Explicit JSON Schema (Recommended)

FastMCP infers schema from type hints. Ensure all tool parameters have clear, consistent names and types.

**Changes in `mcp_server.py`**:

1. Verify parameter names match between MCP tool definition and bridge implementation:
   - `get_funding_rate(pair: str)` ✅
   - `get_open_interest(pair: str)` ✅
   - `get_market_context(pair: str, interval: str)` ✅
   - `run_system_diagnostic(command_key: str)` ✅

2. Add explicit `Field` definitions if needed (using Pydantic):
```python
from pydantic import Field

@mcp.tool()
async def get_funding_rate(pair: str = Field(..., description="Trading pair symbol, e.g. BTCUSDT")) -> str:
    ...
```

3. Ensure no optional parameters without defaults are sent as `null` incorrectly.

#### Option B: Add Debug Echo Tool

Temporarily add a tool to capture exactly what the client sends:

```python
@mcp.tool()
async def mcp_debug_echo(**kwargs) -> str:
    """Debug: echo back received parameters"""
    return json.dumps({"received": kwargs, "keys": list(kwargs.keys())})
```

Call this from OpenClaw to see the actual payload structure.

#### Option C: Restart MCP with Debug Logging

```bash
# Set environment variable for debug
FASTMCP_DEBUG=1 python3 mcp_server.py --transport sse --port 8819
```

Check stderr for schema validation errors.

---

### **Fix 2: Implement Missing `analyze_systemic_fragility` Method**

#### Location: `openrouter_intelligence.py`

Add the missing method stub or full implementation:

```python
class OpenRouterIntelligence:
    # ... existing code ...

    def analyze_systemic_fragility(self, market_data: Dict) -> Dict:
        """
        Analyze systemic fragility across multiple assets and timeframes.
        Returns fragility score and risk level.
        """
        try:
            # Placeholder implementation — to be enhanced with real logic
            fragility_score = 0.5  # neutral
            risk_level = "moderate"
            signals = []

            # Basic checks:
            # - Correlations between assets
            # - Funding rate extremes
            # - Open interest spikes
            # - Liquidity cluster detection

            return {
                "fragility_score": fragility_score,
                "risk_level": risk_level,
                "signals": signals,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            log_message(f"Error in analyze_systemic_fragility: {e}")
            return {
                "fragility_score": 0.5,
                "risk_level": "unknown",
                "error": str(e)
            }
```

**Then** update `main.py` to handle potential exceptions gracefully:

```python
try:
    fragility = self.openrouter.analyze_systemic_fragility(market_data)
except Exception as e:
    log_message(f"Systemic fragility check failed: {e}")
    fragility = {"fragility_score": 0.5, "risk_level": "moderate"}
```

---

## Implementation Plan

### **Phase 1: Immediate Hotfix** (30 minutes)

1. **Add stub method** to `openrouter_intelligence.py`:
   - Create `analyze_systemic_fragility(self, market_data)` returning safe defaults
   - Wrap in try/except to prevent crashes
2. **Restart main bot** to confirm loop stabilizes.

**Expected**: Main loop stops crashing; trading resumes.

---

### **Phase 2: MCP Investigation** (1 hour)

1. **Add debug echo tool** to `mcp_server.py`
2. **Call from OpenClaw**:
   ```python
   aladdin__mcp_debug_echo(pair="BTCUSDT", test="value")
   ```
   (or whatever the agreed parameter format)
3. **Inspect returned JSON** to see what the client actually sends.
4. **Compare with tool schema** — identify mismatches.
5. **Fix parameter names** or add schema validation overrides.

**Expected**: Identify exact cause of -32602 errors.

---

### **Phase 3: MCP Schema Fix** (1 hour)

Based on findings:

- If parameter name mismatch: Rename all MCP tool params to `pair` consistently; ensure bridge methods accept `pair`.
- If type coercion: Add explicit `str` type hints and default values.
- If FastMCP version issue: Pin to known working version or adjust decorator syntax.

**Expected**: MCP tool calls succeed and return data.

---

### **Phase 4: Verify End-to-End** (30 minutes)

1. Test `get_funding_rate("BTCUSDT")` via OpenClaw → should return JSON with funding rate and sentiment.
2. Test `get_open_interest("BTCUSDT")` → should return OI snapshot.
3. Test `get_market_context("BTCUSDT", "1h")` → should return OHLCV data.
4. Confirm main bot log shows no `analyze_systemic_fragility` errors.
5. Verify signal generation includes funding/OI data.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Hotfix stub too simplistic | Low | Medium | Stub returns safe defaults; can enhance later |
| MCP schema fix breaks other tools | Medium | High | Test all tools after changes; have rollback plan |
| Restarting bot disrupts trading | Low | Medium | Schedule during low volatility; monitor closely |
| Parameter name changes ripple effects | Medium | Medium | Update bridge methods and `_SYNC_TOOLS` accordingly |

**Rollback**:
- Git stash or revert changes if MCP fix causes broader issues
- Stub method can be safely removed after real implementation

---

## Testing & Verification

**Phase 1 Pass Criteria**:
- ✅ `main.log` shows no `analyze_systemic_fragility` errors for 10 minutes
- ✅ Bot continues scanning pairs and logging normally

**Phase 3 Pass Criteria**:
- ✅ `aladdin__get_funding_rate(pair="BTCUSDT")` returns valid JSON with `current_rate_pct`
- ✅ `aladdin__get_open_interest(pair="BTCUSDT")` returns valid JSON with `open_interest`
- ✅ No MCP -32602 errors in OpenClaw logs

**Phase 4 Pass Criteria**:
- ✅ All MCP tools accessible to AI
- ✅ Funding/OI data appears in signal generator logs
- ✅ Signals generated with enhanced confidence scoring

---

## Cost Estimate

- **Time**: ~2-3 hours total (split across phases)
- **Infrastructure**: None
- **External Dependencies**: None

---

## Request

Approve immediate implementation of **Phase 1** (stub method) to stop main loop crashes. Then proceed with **Phase 2-3** to restore MCP functionality.

---

**Prepared by**: S.P.E.C.T.R.E.  
**Reviewed by**: [Pending]
