#!/usr/bin/env python3
"""
AI Internet Search - Enable web search capabilities for AI
"""

import asyncio
import os
import sys
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from duckduckgo_search import DDGS

class AIInternetSearch:
    """AI Internet Search capabilities using DuckDuckGo"""
    
    def __init__(self):
        self.search_history = []
        
    async def search_web(self, query, engine="duckduckgo", max_results=5):
        """Search the web using DuckDuckGo"""
        try:
            results = await asyncio.to_thread(self._search_sync, query, max_results)
            
            self.search_history.append({
                "query": query,
                "results_count": len(results),
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "success": len(results) > 0,
                "query": query,
                "engine": "duckduckgo",
                "results": results,
                "count": len(results),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"success": False, "error": str(e), "query": query}
    
    def _search_sync(self, query, max_results=5):
        """Synchronous search via duckduckgo_search library"""
        results = []
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "position": i + 1
                })
        return results
    
    async def search_trading_news(self, query="trading signals"):
        """Search for trading-related news"""
        try:
            news = await asyncio.to_thread(self._news_sync, query)
            return {
                "success": len(news) > 0,
                "query": query,
                "news": news,
                "count": len(news),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            # Fallback to regular search
            result = await self.search_web(f"{query} cryptocurrency news", max_results=5)
            return {
                "success": result.get("success", False),
                "query": query,
                "news": result.get("results", []),
                "count": result.get("count", 0),
                "timestamp": datetime.now().isoformat()
            }
    
    def _news_sync(self, query, max_results=5):
        """Synchronous news search"""
        results = []
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.news(query, max_results=max_results)):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("body", ""),
                    "source": r.get("source", ""),
                    "date": r.get("date", ""),
                    "position": i + 1
                })
        return results
    
    async def search_market_data(self, symbol="BTC"):
        """Search for current market data"""
        result = await self.search_web(f"{symbol} price market analysis today", max_results=5)
        return {
            "success": result.get("success", False),
            "symbol": symbol,
            "results": result.get("results", []),
            "count": result.get("count", 0),
            "timestamp": datetime.now().isoformat()
        }
    
    def get_search_history(self):
        """Get search history"""
        return {
            "search_history": self.search_history[-10:],
            "total_searches": len(self.search_history),
            "engine": "duckduckgo"
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
            "news": result.get("news", []),
            "count": result.get("count", 0),
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
            "results": result.get("results", []),
            "count": result.get("count", 0),
            "timestamp": datetime.now().isoformat()
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

async def get_search_history():
    """MCP function to get search history"""
    try:
        history = AI_INTERNET_SEARCH.get_search_history()
        return json.dumps({"success": True, **history}, indent=2)
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
