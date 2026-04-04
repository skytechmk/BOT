#!/usr/bin/env python3
"""
Send REAL trading signals analysis - no mock data
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def send_real_signals():
    from telegram_chat_interface import CHAT_INTERFACE
    from data_fetcher import fetch_data
    from shared_state import OPEN_SIGNALS_TRACKER, SIGNAL_REGISTRY
    import pandas as pd
    from datetime import datetime
    
    print('📊 Sending REAL trading signals analysis...')
    
    try:
        # Get real BTC data for signal analysis
        btc_df = fetch_data('BTCUSDT', '4h')
        if btc_df.empty:
            print('❌ No BTC data available for signals')
            return
        
        # Calculate real signal indicators
        current_price = btc_df.iloc[-1]['close']
        sma_20 = btc_df['close'].rolling(window=20).mean().iloc[-1]
        sma_50 = btc_df['close'].rolling(window=50).mean().iloc[-1]
        
        # RSI
        delta = btc_df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        # Volume analysis
        avg_volume = btc_df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = btc_df.iloc[-1]['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        # Signal logic
        price_above_sma20 = current_price > sma_20
        price_above_sma50 = current_price > sma_50
        sma_bullish = sma_20 > sma_50
        rsi_oversold = current_rsi < 30
        rsi_overbought = current_rsi > 70
        volume_high = volume_ratio > 1.2
        
        # Generate signal
        signal_strength = 0
        signal_reasons = []
        
        if price_above_sma20:
            signal_strength += 1
            signal_reasons.append("Price above SMA20")
        if price_above_sma50:
            signal_strength += 1
            signal_reasons.append("Price above SMA50")
        if sma_bullish:
            signal_strength += 1
            signal_reasons.append("SMA20 > SMA50 (Bullish)")
        if rsi_oversold:
            signal_strength += 2
            signal_reasons.append(f"RSI oversold ({current_rsi:.1f})")
        elif not rsi_overbought and current_rsi < 50:
            signal_strength += 1
            signal_reasons.append(f"RSI neutral ({current_rsi:.1f})")
        if volume_high:
            signal_strength += 1
            signal_reasons.append(f"High volume ({volume_ratio:.1f}x)")
        
        # Determine signal type
        if signal_strength >= 4:
            signal_type = "🟢 STRONG BUY"
            signal_emoji = "🚀"
        elif signal_strength >= 2:
            signal_type = "🟡 BUY"
            signal_emoji = "📈"
        elif signal_strength >= 0:
            signal_type = "🔵 HOLD"
            signal_emoji = "⚖️"
        else:
            signal_type = "🔴 SELL"
            signal_emoji = "📉"
        
        # Get real active signals count
        active_signals = len(OPEN_SIGNALS_TRACKER)
        total_signals = len(SIGNAL_REGISTRY)
        
        # Create real signal analysis
        signals_analysis = f"""{signal_emoji} **LIVE SIGNAL ANALYSIS** - Real Data

📊 **Current Signal:**
• Type: {signal_type}
• Strength: {signal_strength}/6
• Price: ${current_price:,.2f}
• RSI: {current_rsi:.1f}
• Volume: {volume_ratio:.1f}x average

📈 **Technical Reasons:**
{chr(10).join([f'• {reason}' for reason in signal_reasons]) if signal_reasons else '• No clear signal'}

📋 **Signal Statistics:**
• Active Positions: {active_signals}
• Total Signals: {total_signals}
• Success Rate: Calculating...
• Avg Return: Processing...

💡 **AI Signal Insight:**
{'Strong bullish momentum detected' if signal_strength >= 4 else 'Moderate buy signal' if signal_strength >= 2 else 'Market neutral - wait for confirmation'} with {'high' if volume_high else 'normal'} volume confirmation.

⚠️ **Risk Warning:**
Always use proper risk management. Signals are based on technical analysis only.

🤖 *Real-time signal using live Binance data*
⏰ Updated: {datetime.now().strftime('%H:%M:%S UTC')}"""
        
        result = await CHAT_INTERFACE.send_message(
            chat_id='-1002209928687',
            text=signals_analysis,
            parse_mode='Markdown'
        )
        print(f'✅ Real signals analysis sent: {result.get("success", False)}')
        
        # Send to ops channel with more technical details
        ops_signals = f"""🔧 **TECHNICAL SIGNALS** - Ops Analysis

📊 **Market Conditions:**
• BTC: ${current_price:,.2f}
• SMA20: ${sma_20:,.2f}
• SMA50: ${sma_50:,.2f}
• RSI: {current_rsi:.1f}
• Volume Ratio: {volume_ratio:.1f}x

🎯 **Signal Logic:**
• Price > SMA20: {price_above_sma20}
• Price > SMA50: {price_above_sma50}
• SMA20 > SMA50: {sma_bullish}
• RSI Oversold: {rsi_oversold}
• Volume High: {volume_high}

📈 **System Status:**
• Active Signals: {active_signals}
• Signal Registry: {total_signals}
• Last Update: {datetime.now().strftime('%H:%M:%S')}

💡 **Ops Recommendation:**
{'Monitor for entry points' if signal_strength >= 2 else 'Maintain current positions'}"""

        ops_result = await CHAT_INTERFACE.send_message(
            chat_id='-1003706659588',
            text=ops_signals,
            parse_mode='Markdown'
        )
        print(f'✅ Ops signals analysis sent: {ops_result.get("success", False)}')
        
    except Exception as e:
        print(f'❌ Real signals error: {e}')
    
    print('\n🎯 Real signals analysis completed!')

if __name__ == "__main__":
    asyncio.run(send_real_signals())
