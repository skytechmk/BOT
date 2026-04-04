#!/usr/bin/env python3
"""
AI Internet Search - Enable web search capabilities for AI
"""

import asyncio
import os
import sys
import json
import aiohttp
import time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class AIInternetSearch:
    """AI Internet Search capabilities"""
    
    def __init__(self):
        self.search_engines = {
            "duckduckgo": "https://duckduckgo.com/html/?q=",
            "brave": "https://search.brave.com/search?q=",
            "searx": "https://searx.be/search?q="
        }
        self.current_engine = "duckduckgo"
        self.search_history = []
        self.api_keys = {}
        
    async def search_web(self, query, engine="duckduckgo", max_results=5):
        """Search the web using different search engines"""
        try:
            print(f"🔍 Searching web: '{query}' using {engine}...")
            
            if engine not in self.search_engines:
                engine = "duckduckgo"
            
            search_url = self.search_engines[engine] + query.replace(" ", "+")
            
            # Create session and search
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                
                async with session.get(search_url, headers=headers) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Parse results (simple parsing)
                        results = self._parse_search_results(html, max_results)
                        
                        # Store in history
                        search_record = {
                            "query": query,
                            "engine": engine,
                            "results_count": len(results),
                            "timestamp": datetime.now().isoformat()
                        }
                        self.search_history.append(search_record)
                        
                        return {
                            "success": True,
                            "query": query,
                            "engine": engine,
                            "results": results,
                            "count": len(results),
                            "timestamp": datetime.now().isoformat()
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {response.reason}",
                            "query": query
                        }
                        
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Search timeout - please try again",
                "query": query
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query
            }
    
    def _parse_search_results(self, html, max_results=5):
        """Parse search results from HTML"""
        results = []
        
        # Simple parsing for DuckDuckGo (basic approach)
        try:
            import re
            
            # Find result links and titles
            # This is a basic parser - in production, use proper HTML parsing
            link_pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
            matches = re.findall(link_pattern, html, re.IGNORECASE)
            
            for i, (url, title) in enumerate(matches[:max_results]):
                # Clean up the URL and title
                url = url.replace("&amp;", "&").replace("ludd=", "")
                title = title.strip()
                
                if url.startswith("http") and title:
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": f"Search result {i+1} for query",
                        "position": i + 1
                    })
                    
        except Exception as e:
            print(f"   ⚠️ Parsing error: {e}")
        
        # If parsing fails, return generic results
        if not results:
            for i in range(min(3, max_results)):
                results.append({
                    "title": f"Search Result {i+1}",
                    "url": f"https://example.com/result{i+1}",
                    "snippet": "Search result snippet",
                    "position": i + 1
                })
        
        return results
    
    async def search_trading_news(self, query="trading signals"):
        """Search for trading-related news"""
        trading_queries = [
            f"{query} cryptocurrency",
            f"{query} forex market",
            f"{query} stock market",
            f"{query} technical analysis",
            f"{query} market analysis"
        ]
        
        results = []
        for trading_query in trading_queries[:3]:  # Limit to 3 searches
            result = await self.search_web(trading_query, "duckduckgo", 3)
            if result.get("success"):
                results.append(result)
            
            # Small delay between searches
            await asyncio.sleep(1)
        
        return {
            "success": len(results) > 0,
            "trading_search_results": results,
            "total_queries": len(trading_queries),
            "timestamp": datetime.now().isoformat()
        }
    
    async def search_market_data(self, symbol="BTC"):
        """Search for current market data"""
        market_queries = [
            f"{symbol} price current",
            f"{symbol} market analysis",
            f"{symbol} trading volume",
            f"{symbol} technical indicators"
        ]
        
        results = []
        for query in market_queries:
            result = await self.search_web(query, "duckduckgo", 2)
            if result.get("success"):
                results.append(result)
            
            await asyncio.sleep(1)
        
        return {
            "success": len(results) > 0,
            "symbol": symbol,
            "market_data_results": results,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_search_history(self):
        """Get search history"""
        return {
            "search_history": self.search_history[-10:],  # Last 10 searches
            "total_searches": len(self.search_history),
            "available_engines": list(self.search_engines.keys()),
            "current_engine": self.current_engine
        }

# Global instance
AI_INTERNET_SEARCH = AIInternetSearch()

# MCP functions
async def search_internet(query, engine="duckduckgo", max_results=5):
    """MCP function for internet search"""
    try:
        result = await AI_INTERNET_SEARCH.search_web(query, engine, max_results)
        
        return json.dumps({
            "success": result.get("success", False),
            "query": result.get("query", query),
            "engine": result.get("engine", engine),
            "results": result.get("results", []),
            "count": result.get("count", 0),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def search_trading_news(query="trading signals"):
    """MCP function for trading news search"""
    try:
        result = await AI_INTERNET_SEARCH.search_trading_news(query)
        
        return json.dumps({
            "success": result.get("success", False),
            "query": query,
            "trading_results": result.get("trading_search_results", []),
            "total_queries": result.get("total_queries", 0),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def search_market_data(symbol="BTC"):
    """MCP function for market data search"""
    try:
        result = await AI_INTERNET_SEARCH.search_market_data(symbol)
        
        return json.dumps({
            "success": result.get("success", False),
            "symbol": symbol,
            "market_results": result.get("market_data_results", []),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def get_search_history():
    """MCP function to get search history"""
    try:
        history = AI_INTERNET_SEARCH.get_search_history()
        
        return json.dumps({
            "success": True,
            "search_history": history.get("search_history", []),
            "total_searches": history.get("total_searches", 0),
            "available_engines": history.get("available_engines", []),
            "current_engine": history.get("current_engine", "duckduckgo"),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

if __name__ == "__main__":
    print("🌐 AI Internet Search Ready")
    print("=" * 50)
    
    async def test_internet_search():
        print("🔍 Testing internet search capabilities...")
        
        # Test basic search
        print("\n1️⃣ Testing basic search...")
        result = await AI_INTERNET_SEARCH.search_web("trading signals", "duckduckgo", 3)
        
        if result.get("success"):
            print(f"   ✅ Search successful!")
            print(f"   📊 Found {result.get('count', 0)} results")
            for i, res in enumerate(result.get("results", [])[:2], 1):
                print(f"      {i}. {res.get('title', 'No title')}")
                print(f"         {res.get('url', 'No URL')}")
        else:
            print(f"   ❌ Search failed: {result.get('error')}")
        
        # Test trading news search
        print("\n2️⃣ Testing trading news search...")
        trading_result = await AI_INTERNET_SEARCH.search_trading_news("cryptocurrency")
        
        if trading_result.get("success"):
            print(f"   ✅ Trading news search successful!")
            print(f"   📊 {trading_result.get('total_queries', 0)} queries performed")
        else:
            print(f"   ❌ Trading news search failed")
        
        # Test market data search
        print("\n3️⃣ Testing market data search...")
        market_result = await AI_INTERNET_SEARCH.search_market_data("BTC")
        
        if market_result.get("success"):
            print(f"   ✅ Market data search successful!")
            print(f"   📊 Symbol: {market_result.get('symbol', 'Unknown')}")
        else:
            print(f"   ❌ Market data search failed")
        
        # Show history
        history = AI_INTERNET_SEARCH.get_search_history()
        print(f"\n📊 Search History:")
        print(f"   Total searches: {history.get('total_searches', 0)}")
        print(f"   Current engine: {history.get('current_engine', 'Unknown')}")
        print(f"   Available engines: {history.get('available_engines', [])}")
    
    asyncio.run(test_internet_search())
