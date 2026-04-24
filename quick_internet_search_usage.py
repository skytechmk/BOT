#!/usr/bin/env python3
"""
Quick Internet Search Usage - Direct examples
"""

import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def quick_internet_search_examples():
    """Quick examples of internet search usage"""
    
    print("🌐 БРЗИ ПРИМЕРИ ЗА ИНТЕРНЕТ ПРЕБАРУВАЊЕ")
    print("=" * 50)
    
    # Import the search functions
    from ai_internet_search import (
        search_internet, 
        search_trading_news, 
        search_market_data
    )
    
    print("\n📋 ДОСТАПНИ ФУНКЦИИ:")
    print("1. search_internet(query, engine, max_results)")
    print("2. search_trading_news(query)")
    print("3. search_market_data(symbol)")
    
    print("\n🎯 ПРИМЕРИ ЗА КОРИСТЕЊЕ:")
    
    # Example 1: Basic search
    print("\n1️⃣ ОПШТО ПРЕБАРУВАЊЕ:")
    print("   Код: await search_internet('crypto trading', 'duckduckgo', 5)")
    print("   Опис: Пребарува 'crypto trading' на DuckDuckGo")
    
    try:
        result = await search_internet("crypto trading", "duckduckgo", 3)
        data = json.loads(result) if isinstance(result, str) else result
        if data.get("success"):
            print(f"   ✅ Резултат: {data.get('count', 0)} резултати пронајдени")
        else:
            print(f"   ❌ Грешка: {data.get('error')}")
    except Exception as e:
        print(f"   ❌ Грешка: {e}")
    
    # Example 2: Trading news
    print("\n2️⃣ ТРГОВСКИ ВЕСТИ:")
    print("   Код: await search_trading_news('bitcoin analysis')")
    print("   Опис: Пребарува трговски вести за bitcoin")
    
    try:
        result2 = await search_trading_news("bitcoin analysis")
        data2 = json.loads(result2) if isinstance(result2, str) else result2
        if data2.get("success"):
            print(f"   ✅ Резултат: {data2.get('total_queries', 0)} пребарувања извршени")
        else:
            print(f"   ❌ Грешка: {data2.get('error')}")
    except Exception as e:
        print(f"   ❌ Грешка: {e}")
    
    # Example 3: Market data
    print("\n3️⃣ МАРКЕТ ПОДАТОЦИ:")
    print("   Код: await search_market_data('BTC')")
    print("   Опис: Пребарува маркет податоци за BTC")
    
    try:
        result3 = await search_market_data("BTC")
        data3 = json.loads(result3) if isinstance(result3, str) else result3
        if data3.get("success"):
            print(f"   ✅ Резултат: Податоци за {data3.get('symbol', 'BTC')} пронајдени")
        else:
            print(f"   ❌ Грешка: {data3.get('error')}")
    except Exception as e:
        print(f"   ❌ Грешка: {e}")
    
    print("\n🎮 КАКО ДА КОРИСТИТЕ ВО РАЗГОВОР:")
    print("📱 Во Ops чатот, напишете:")
    print("   👤 '@ai_assistant Пребарај информации за Ethereum'")
    print("   👤 '@ai_assistant Дади ги најновите crypto вести'")
    print("   👤 '@ai_assistant Анализа на BTC пазарот'")
    
    print("\n🤖 AI автоматски ќе:")
    print("   🔍 Пребара на интернет")
    print("   📊 Проанализира резултати")
    print("   💬 Одговори со информации")
    print("   🔄 Може да пребарува дополнително")
    
    print("\n✅ ИНТЕРНЕТ ПРЕБАРУВАЊЕТО Е ВЕЌЕ АКТИВНО!")
    print("📋 Нема потреба од активација - веќе е интегрирано!")

if __name__ == "__main__":
    asyncio.run(quick_internet_search_examples())
