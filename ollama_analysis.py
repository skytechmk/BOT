import requests
import json
import os
import pandas as pd
import numpy as np
from datetime import datetime
import asyncio
import time
from typing import Dict, List, Optional, Any

class OllamaAnalyzer:
    def __init__(self, ollama_host="192.168.20.30", ollama_port=11434, model="gemma3:27b"):
        self.base_url = f"http://{ollama_host}:{ollama_port}"
        self.model = model
        self.session = requests.Session()
        self.session.timeout = 120  # 2 minute timeout for complex analysis
        
    def test_connection(self) -> bool:
        """Test connection to Ollama server"""
        try:
            response = self.session.get(f"{self.base_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [model['name'] for model in models]
                if self.model in model_names:
                    print(f"✅ Connected to Ollama server. Model {self.model} is available.")
                    return True
                else:
                    print(f"❌ Model {self.model} not found. Available models: {model_names}")
                    return False
            else:
                print(f"❌ Failed to connect to Ollama server: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def generate_analysis(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Generate analysis using Ollama model"""
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,  # Lower temperature for more focused analysis
                        "top_p": 0.9,
                        "num_predict": 2048,  # Limit response length
                        "stop": ["Human:", "Assistant:"]
                    }
                }
                
                response = self.session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get('response', '').strip()
                else:
                    print(f"Ollama API error (attempt {attempt + 1}): {response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        
            except Exception as e:
                print(f"Error generating analysis (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
        return None
    
    def create_technical_analysis_prompt(self, pair_data: Dict) -> str:
        """Create concise technical analysis prompt for Telegram - Analysis only, no position suggestions"""
        pair = pair_data['pair']
        latest = pair_data['latest_data']
        indicators = pair_data['indicators']
        patterns = pair_data['patterns']
        
        # Determine key signals
        rsi = indicators.get('rsi_14', 50)
        macd_hist = indicators.get('macd_histogram', 0)
        bb_pos = indicators.get('bb_position', 0.5)
        adx = indicators.get('adx', 25)
        
        prompt = f"""
You are a crypto analyst. Analyze {pair} and provide a CONCISE technical analysis report (max 800 characters). 

IMPORTANT: Do NOT provide any trading signals, position suggestions, or entry/exit recommendations. Only provide technical analysis and market observations.

DATA:
Price: ${latest['close']:.4f} | 24h: {latest.get('price_change_24h', 0):.1f}%
RSI: {rsi:.1f} | MACD: {'📈' if macd_hist > 0 else '📉'} | ADX: {adx:.1f}
BB Position: {bb_pos:.2f} | Pattern: {patterns.get('pattern_name', 'None')}

Provide ONLY:
📊 **TECHNICAL STATUS**: Current market condition analysis
📈 **MOMENTUM**: Trend strength and direction assessment  
⚖️ **KEY LEVELS**: Important support/resistance observations
🔍 **PATTERN**: Technical pattern analysis if present
📋 **SUMMARY**: Brief technical outlook

Keep it under 800 characters total. Use emojis. Focus on analysis, NOT trading advice.
"""
        return prompt
    
    def create_market_overview_prompt(self, top_pairs_data: List[Dict]) -> str:
        """Create concise market overview prompt for Telegram - Analysis only, no trading strategies"""
        # Count signals
        bullish_count = sum(1 for data in top_pairs_data if data.get('signal') == 'Long')
        bearish_count = sum(1 for data in top_pairs_data if data.get('signal') == 'Short')
        neutral_count = len(top_pairs_data) - bullish_count - bearish_count
        
        # Get key pairs summary
        key_pairs = []
        for data in top_pairs_data[:5]:  # Top 5 only
            pair = data['pair']
            signal = data.get('signal', 'Neutral')
            rsi = data['indicators'].get('rsi_14', 50)
            macd_trend = '📈' if data['indicators'].get('macd_histogram', 0) > 0 else '📉'
            key_pairs.append(f"{pair}: {signal} | RSI {rsi:.0f} {macd_trend}")
        
        prompt = f"""
You are a crypto market analyst. Provide a CONCISE market analysis overview (max 1200 characters).

IMPORTANT: Do NOT provide trading strategies, position recommendations, or investment advice. Only provide market analysis and observations.

MARKET DATA:
Technical Signals: {bullish_count} Bullish | {bearish_count} Bearish | {neutral_count} Neutral
Top 5: {' | '.join(key_pairs)}

Provide ONLY:
📊 **MARKET SENTIMENT**: Overall technical condition analysis
🎯 **KEY THEME**: Main market driver or trend observed
⚠️ **VOLATILITY**: Current market volatility assessment
📈 **TECHNICAL OUTLOOK**: General technical pattern observations
🔍 **NOTABLE PATTERNS**: Any significant technical developments

Keep under 1200 characters. Use emojis. Focus on analysis, NOT trading recommendations.
"""
        return prompt

    def save_analysis(self, analysis_type: str, result: str, data: Optional[Any] = None):
        """Save analysis results to a JSON file for ML system integration"""
        try:
            save_path = "performance_logs/ollama_sentiment.json"
            
            # Load existing or create new
            try:
                if not os.path.exists("performance_logs"):
                    os.makedirs("performance_logs")
                with open(save_path, 'r') as f:
                    history = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                history = {}
            
            # Update history
            history[analysis_type] = {
                'result': result,
                'data': data,
                'timestamp': datetime.now().isoformat(),
                'model': self.model
            }
            
            # Keep only last analysis for each type
            with open(save_path, 'w') as f:
                json.dump(history, f, indent=2)
                
            print(f"✅ Saved Ollama {analysis_type} analysis to {save_path}")
        except Exception as e:
            print(f"❌ Error saving analysis: {e}")

def extract_pair_data(pair: str, df: pd.DataFrame) -> Dict:
    """Extract comprehensive data for a trading pair"""
    try:
        latest = df.iloc[-1]
        
        # Basic price data
        pair_data = {
            'pair': pair,
            'latest_data': {
                'close': float(latest['close']),
                'open': float(latest['open']),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'volume': float(latest['volume']),
            },
            'indicators': {},
            'patterns': {},
            'signal': latest.get('Signal', 'Neutral')
        }
        
        # Add price change if we have enough data
        if len(df) > 1:
            try:
                price_change_24h = ((latest['close'] - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100
                pair_data['latest_data']['price_change_24h'] = float(price_change_24h)
            except Exception as e:
                print(f"Error calculating price change for {pair}: {e}")
                pair_data['latest_data']['price_change_24h'] = 0.0
        
        # Technical indicators
        indicator_mapping = {
            'rsi_14': 'RSI_14',
            'rsi_21': 'RSI_21',
            'macd': 'MACD Line',
            'macd_signal': 'Signal Line',
            'macd_histogram': 'MACD Histogram',
            'adx': 'ADX',
            'plus_di': 'PLUS_DI',
            'minus_di': 'MINUS_DI',
            'stoch_k': 'STOCH_K',
            'stoch_d': 'STOCH_D',
            'mfi': 'MFI',
            'willr': 'WILLR',
            'atr': 'ATR',
            'sma_20': 'SMA_20',
            'sma_50': 'SMA_50',
            'sma_200': 'SMA_200',
            'ema_20': 'EMA_20',
            'ema_50': 'EMA_50',
            'tenkan_sen': 'tenkan_sen',
            'kijun_sen': 'kijun_sen'
        }
        
        for key, col in indicator_mapping.items():
            if col in df.columns:
                try:
                    value = latest[col]
                    if not pd.isna(value) and np.isfinite(value):
                        pair_data['indicators'][key] = float(value)
                except (ValueError, TypeError, IndexError) as e:
                    print(f"Error processing indicator {key} for {pair}: {e}")
                    continue
        
        # Bollinger Bands position
        if all(col in df.columns for col in ['Upper Band', 'Lower Band']):
            bb_range = latest['Upper Band'] - latest['Lower Band']
            if bb_range > 0:
                bb_position = (latest['close'] - latest['Lower Band']) / bb_range
                pair_data['indicators']['bb_position'] = float(bb_position)
        
        # VWAP ratio
        if 'VWAP' in df.columns and not pd.isna(latest['VWAP']):
            pair_data['indicators']['price_vs_vwap'] = float(latest['close'] / latest['VWAP'])
        
        # Moving average ratios
        if 'SMA_20' in df.columns and not pd.isna(latest['SMA_20']):
            pair_data['indicators']['price_vs_sma20'] = float(latest['close'] / latest['SMA_20'])
        if 'SMA_50' in df.columns and not pd.isna(latest['SMA_50']):
            pair_data['indicators']['price_vs_sma50'] = float(latest['close'] / latest['SMA_50'])
        
        # Volume ratio
        if len(df) >= 20:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            if avg_volume > 0:
                pair_data['indicators']['volume_ratio'] = float(latest['volume'] / avg_volume)
        
        # Support/Resistance
        if len(df) >= 20:
            pair_data['indicators']['recent_high'] = float(df['high'].rolling(20).max().iloc[-1])
            pair_data['indicators']['recent_low'] = float(df['low'].rolling(20).min().iloc[-1])
        
        # Patterns
        if 'Pattern' in df.columns:
            pair_data['patterns'] = {
                'pattern_name': latest['Pattern'],
                'pattern_type': latest.get('Pattern_Type', 'Neutral'),
                'pattern_strength': latest.get('Pattern_Strength', 0)
            }
        
        # Ichimoku cloud position
        if all(col in df.columns for col in ['senkou_span_a', 'senkou_span_b']):
            if not pd.isna(latest['senkou_span_a']) and not pd.isna(latest['senkou_span_b']):
                cloud_top = max(latest['senkou_span_a'], latest['senkou_span_b'])
                cloud_bottom = min(latest['senkou_span_a'], latest['senkou_span_b'])
                if latest['close'] > cloud_top:
                    pair_data['indicators']['cloud_position'] = "Above Cloud (Bullish)"
                elif latest['close'] < cloud_bottom:
                    pair_data['indicators']['cloud_position'] = "Below Cloud (Bearish)"
                else:
                    pair_data['indicators']['cloud_position'] = "Inside Cloud (Neutral)"
        
        return pair_data
        
    except Exception as e:
        print(f"Error extracting data for {pair}: {e}")
        return None

async def analyze_top_pairs_with_ollama(pairs_data: List[Dict], send_telegram_func, send_closed_signals_func=None) -> None:

    """Analyze top pairs using Ollama and send results via Telegram to both channels"""
    try:
        analyzer = OllamaAnalyzer()
        
        # Test connection first
        if not analyzer.test_connection():
            error_msg = "❌ Failed to connect to Ollama server. Skipping AI analysis."
            print(error_msg)
            await send_telegram_func(error_msg)
            if send_closed_signals_func:
                await send_closed_signals_func(error_msg)
            return
        
        start_msg = "🤖 Starting AI-powered technical analysis of ETH and BTC..."
        await send_telegram_func(start_msg)
        if send_closed_signals_func:
            await send_closed_signals_func(start_msg)
        
        # Generate market overview first
        print("Generating market overview...")
        market_prompt = analyzer.create_market_overview_prompt(pairs_data)
        market_analysis = analyzer.generate_analysis(market_prompt)
        
        if market_analysis:
            market_msg = f"📊 **MARKET OVERVIEW - AI ANALYSIS**\n\n{market_analysis}"
            # Save for ML system
            analyzer.save_analysis("market_overview", market_analysis, {
                'bullish_count': sum(1 for data in pairs_data if data.get('signal') == 'Long'),
                'bearish_count': sum(1 for data in pairs_data if data.get('signal') == 'Short')
            })
            print("Market overview sent to both channels and saved to file")
        
        # Analyze only ETH and BTC individually for detailed analysis (no position suggestions)
        target_pairs = ['ETHUSDT', 'BTCUSDT']
        analyzed_pairs = []
        
        for pair_data in pairs_data:
            if pair_data['pair'] in target_pairs:
                analyzed_pairs.append(pair_data)
        
        for i, pair_data in enumerate(analyzed_pairs):
            try:
                pair = pair_data['pair']
                print(f"Analyzing {pair} ({i+1}/{len(analyzed_pairs)})...")
                
                # Generate concise analysis (no trading recommendations)
                prompt = analyzer.create_technical_analysis_prompt(pair_data)
                analysis = analyzer.generate_analysis(prompt)
                
                if analysis:
                    # Format concise message for Telegram
                    detailed_msg = f"📊 **{pair} TECHNICAL ANALYSIS**\n\n{analysis}"
                    
                    # Ensure message is under Telegram limit
                    if len(detailed_msg) > 1000:
                        detailed_msg = detailed_msg[:997] + "..."
                    
                    # Save for ML system
                    analyzer.save_analysis(f"pair_{pair}", analysis, pair_data)
                    
                    # Send to main channel
                    await send_telegram_func(detailed_msg)
                    # Send to closed signals channel as well
                    if send_closed_signals_func:
                        await send_closed_signals_func(detailed_msg)
                    print(f"Analysis for {pair} sent to both channels and saved to file")
                else:
                    error_msg = f"❌ Failed to generate analysis for {pair}"
                    print(error_msg)
                
                # Small delay between analyses
                await asyncio.sleep(1)
                
            except Exception as e:
                error_msg = f"❌ Error analyzing {pair_data['pair']}: {str(e)[:100]}"
                print(error_msg)
        
        completion_msg = "✅ AI technical analysis completed for ETH and BTC!"
        print(completion_msg)
        await send_telegram_func(completion_msg)
        if send_closed_signals_func:
            await send_closed_signals_func(completion_msg)
        
    except Exception as e:
        error_msg = f"❌ Error in Ollama analysis: {str(e)[:200]}"
        print(error_msg)
        await send_telegram_func(error_msg)
        if send_closed_signals_func:
            await send_closed_signals_func(error_msg)

if __name__ == "__main__":
    # Test the analyzer
    analyzer = OllamaAnalyzer()
    if analyzer.test_connection():
        print("Ollama analyzer is ready!")
    else:
        print("Failed to connect to Ollama server.")
