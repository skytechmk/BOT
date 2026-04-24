# Proposal: Improve Real-Time Market Data Access

**Date**: 2026-04-06  
**Priority**: HIGH  
**Files affected**: Data fetching layer, MCP tools, potentially new integrations

---

## Problem

The Aladdin Trading Bot currently lacks access to critical real-time market metrics needed for high-conviction trading decisions:

1. **Funding Rates** — Cannot retrieve live or recent funding rates from Binance/Bybit/OKX
2. **Order Book Depth** — No bid/ask imbalance or wall detection
3. **Open Interest** — Cannot track OI trends across exchanges
4. **Liquidation Levels** — Missing cluster detection for stops/ squeezes
5. **Real-time Skew** — No put/call ratios or options flow data

These metrics are essential for:
- Confirming breakout sustainability (funding rates indicate leverage)
- Identifying support/resistance (order book walls)
- Detecting trend strength (OI divergence)
- Risk management (liquidation clusters)

---

## Current Limitations

- `search_internet()` returns static pages, not dynamic data
- `web_fetch()` cannot execute JavaScript → funding rate charts (Coinglass, Binance) are unreadable
- No direct API integration with:
  - Binance Futures API (funding rate endpoint)
  - Bybit API (funding, OI, liquidations)
  - CryptoQuant/Glassnode/Santiment (on-chain metrics)
  - Skew.com (options flow)

---

## Proposed Solutions

### **Option A: Direct Exchange APIs** (Recommended)

Integrate native REST API calls to major exchanges:

#### 1. Binance Futures API
- Endpoint: `/fapi/v1/fundingRate` (historical funding)
- Endpoint: `/fapi/v1/openInterest` (global OI)
- Endpoint: `/fapi/v1/globalLongShortAccountRatio` (account ratio)
- Rate limits: 1200 weight/min — acceptable for periodic polling (1-5 min)

#### 2. Bybit API
- Endpoint: `/v5/market/funding/history`
- Endpoint: `/v5/market/open-interest`
- Endpoint: `/v5/market/liquidation-list`
- Higher rate limits: 600 req/min

#### 3. OKX API
- Endpoint: `/api/v5/public/funding-rate`
- Endpoint: `/api/v5/public/oi-taker`
- Similar rate limits

**Implementation**:
- Create new module: `exchange_apis.py`
- Add async functions with rate limiting (asyncio.Semaphore)
- Cache responses to avoid redundant calls
- Expose via MCP tools: `get_funding_rate(pair)`, `get_open_interest(pair)`, `get_liquidations(pair)`

---

### **Option B: Web Scraping with Headless Browser**

If APIs are restricted or require signed requests:

- Use `browser` tool (Playwright) to render JS-heavy pages:
  - Coinglass funding rate pages
  - Skew.com charts
  - Binance funding history UI

**Pros**: No API keys needed  
**Cons**: Fragile (UI changes break), slower, more resource-intensive

---

### **Option C: Third-Party Aggregator APIs**

(suboptimal, but quick)

- CryptoQuant API (paid)
- Glassnode API (paid)
- Messari API (free tier limited)

---

## Recommended Implementation Plan

### **Phase 1: Binance Futures API Integration** (Week 1)

1. Add `httpx` or `aiohttp` for async HTTP requests (if not already present)
2. Create `binance_client.py`:
   ```python
   async def get_funding_rate(symbol: str, limit: int = 100) -> List[Dict]:
       # Fetch recent funding rates
       pass

   async def get_open_interest(symbol: str) -> Dict:
       # Global OI in USD and contracts
       pass
   ```
3. Add configuration: `BINANCE_FUTURES_API_KEY` (public endpoints don't need key, but rate limits tighter)
4. Implement caching: 30-second TTL for funding, 60-second for OI
5. Wrap as MCP tools: `aladdin__get_funding_rate`, `aladdin__get_open_interest`

### **Phase 2: Additional Exchanges** (Week 2)

- Extend to Bybit (better liquidation data)
- Add OKX for redundancy

### **Phase 3: On-Chain Metrics** (Week 3)

- Integrate CryptoQuant free tier (exchange flows, SOPR, MVRV)
- Glassnode if budget allows

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| API rate limit exceeded | Medium | Service disruption | Implement aggressive caching, respect `X-MBX-USED-WEIGHT` header |
| API key compromise | Low | Security breach | Store in `.env`, never commit; use read-only keys |
| Exchange downtime | Low | Data unavailable | Fallback to other exchanges, graceful degradation |
| Code complexity | Medium | Maintenance burden | Modular design, separate client per exchange |

**Rollback**: Remove new tools, revert to current state. No database changes → fully reversible.

---

## Verification

1. **Manual check**: Call `get_funding_rate("BTCUSDT")` → returns 0-0.1% values
2. **Market analysis**: Use funding rate in signal confidence scoring
3. **Backtest**: Compare signals with/without funding confirmation
4. **Monitoring**: Log API latency, error rates, cache hit rate

---

## Success Criteria

- ✅ Fetch funding rates for BTC, ETH, SOL within 5 seconds
- ✅ Fetch open interest with <10% error rate
- ✅ Cache prevents >3 calls/minute to same endpoint
- ✅ MCP tools stable and documented
- ✅ No increase in error logs or crash loops

---

## Cost Estimate

- **Time**: 2-3 days development + 1 day testing
- **Infrastructure**: None (uses existing server)
- **External costs**: Zero (public APIs)
- **Maintenance**: Low (monitor rate limits, occasional endpoint updates)

---

## Request

Approve implementation of **Option A, Phase 1** (Binance Futures API integration) to gain immediate access to funding rates and open interest data. This will significantly improve signal quality and risk management.

Proceed with:
1. Create `exchange_apis/binance_client.py`
2. Add MCP tools for `get_funding_rate` and `get_open_interest`
3. Update `ai_mcp_bridge.py` to expose new tools
4. Test with BTCUSDT, ETHUSDT, SOLUSDT

---

**Author**: S.P.E.C.T.R.E.  
**Reviewed by**: [Pending]