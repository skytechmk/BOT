import pandas as pd
import numpy as np
import time
import asyncio
import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectTimeout
from urllib3.exceptions import MaxRetryError
from utils_logger import log_message
from constants import *
from shared_state import client

# Exchange Info Cache (P1 fix: avoid 50 API calls/cycle for precision)
_EXCHANGE_INFO_CACHE = {'data': None, 'timestamp': 0, 'precision_map': {}}
_EXCHANGE_INFO_TTL = 86400  # Refresh every 24h

# Funding Rate Cache (Fix 403 Forbidden WAF bans)
_FUNDING_CACHE = {'current': {}, 'history': {}}
_FUNDING_TTL = 300  # Cache for 5 minutes

def rate_limit():
    """Simple rate limiting to avoid API bans"""
    time.sleep(0.1)

def validate_api_response(response):
    """Validate Binance API response structure with detailed checks"""
    if response is None:
        log_message("API returned None response")
        return False
    if isinstance(response, str):
        log_message(f"API returned error string: {response}")
        return False
    if hasattr(response, 'message'):
        log_message(f"API returned error object: {response.message}")
        return False
    if not isinstance(response, (list, dict)):
        log_message(f"Unexpected API response type: {type(response)}")
        return False
        
    # Additional validation for dict responses
    if isinstance(response, dict):
        if 'error' in response:
            log_message(f"API returned error dict: {response['error']}")
            return False
        if 'data' not in response:
            log_message("API dict response missing 'data' key")
            return False
            
    return True

def fetch_data(pair, interval='1d', retries=5, timeout=20):
    """Fetch market data with comprehensive validation"""
    attempt = 0
    while attempt < retries:
        try:
            rate_limit()
            response = client.futures_klines(symbol=pair, interval=interval, limit=500)
            
            # Log response type for debugging
            log_message(f"API response type for {pair}: {type(response)}")
            
            # Ensure response is a list before processing
            if not isinstance(response, list):
                log_message(f"Invalid API response format for {pair}: {response}")
                return pd.DataFrame()
            
            # Validate response structure (comprehensive check)
            if not validate_api_response(response):
                return pd.DataFrame()
            
            # Convert to list if not already
            klines = []
            try:
                if isinstance(response, dict):
                    if 'data' in response:  # Some Binance responses wrap data
                        klines = list(response['data'])
                    else:
                        raise ValueError("Unexpected dict response format")
                else:
                    klines = list(response)
            except Exception as e:
                log_message(f"Response conversion error for {pair}: {e}")
                return pd.DataFrame()
                
            # Validate klines structure (single comprehensive check)
            if not isinstance(klines, list) or len(klines) == 0:
                log_message(f"Empty or invalid klines data for {pair}")
                return pd.DataFrame()
            if not all(isinstance(k, (list, tuple)) and len(k) >= 6 for k in klines):
                log_message(f"Invalid klines item format for {pair}")
                return pd.DataFrame()
                
            try:
                df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                                                   'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume',
                                                   'taker_buy_quote_asset_volume', 'ignore'])
            except Exception as e:
                log_message(f"DataFrame creation failed for {pair}: {e}")
                return pd.DataFrame()
            
            # Validate DataFrame structure
            if df.empty:
                log_message(f"Empty DataFrame for {pair}")
                return pd.DataFrame()
                
            # Convert and validate data types
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                numeric_cols = ['close', 'open', 'high', 'low', 'volume']
                df[numeric_cols] = df[numeric_cols].astype(float)
                return df
            except Exception as e:
                log_message(f"Data conversion error for {pair}: {e}")
                return pd.DataFrame()
                
        except (ConnectTimeout, MaxRetryError) as e:
            log_message(f"Attempt {attempt + 1}/{retries} failed to fetch data for {pair} at interval {interval}: {e}")
            attempt += 1
            backoff = min(2 ** attempt, 64)
            log_message(f"Retrying in {backoff} seconds...")
            time.sleep(backoff)
        except BinanceAPIException as e:
            log_message(f"API Error fetching data for {pair} at interval {interval}: {e}")
            return pd.DataFrame()
        except Exception as e:
            log_message(f"Unexpected error fetching data for {pair}: {e}")
            return pd.DataFrame()
            
    log_message(f"Max retries reached for {pair}")
    return pd.DataFrame()

def fetch_top_volume_pairs(limit=TOP_PAIRS_COUNT):
    """Fetch top trading pairs by 24h volume, filtered for Cornix compatibility"""
    try:
        rate_limit()
        ticker_24hr = client.futures_ticker()
        
        # Filter USDT pairs and sort by volume
        usdt_pairs = [
            ticker for ticker in ticker_24hr 
            if ticker['symbol'].endswith('USDT') and float(ticker['volume']) > 0
        ]
        
        # Sort by 24h volume (descending)
        usdt_pairs.sort(key=lambda x: float(x['volume']), reverse=True)
        
        # Fetch leverage brackets once to filter out low-leverage pairs
        try:
            rate_limit()
            leverage_brackets = client.futures_leverage_bracket()
            leverage_map = {}
            for item in leverage_brackets:
                sym = item['symbol']
                brackets = item.get('brackets', item.get('bracket', []))
                if isinstance(brackets, list) and len(brackets) > 0:
                    leverage_map[sym] = brackets[0].get('initialLeverage', 1)
                else:
                    leverage_map[sym] = 1
        except Exception as e:
            log_message(f"Error fetching leverage brackets: {e}")
            leverage_map = {}
        
        # Filter: only pairs with max leverage >= 5x (Cornix-compatible)
        MIN_LEVERAGE = 5
        filtered_pairs = []
        for pair_data in usdt_pairs:
            sym = pair_data['symbol']
            max_lev = leverage_map.get(sym, 20)
            if max_lev >= MIN_LEVERAGE:
                filtered_pairs.append(sym)
            else:
                log_message(f"⚠️ Excluded {sym} (max leverage: {max_lev}x < {MIN_LEVERAGE}x)")
            if len(filtered_pairs) >= limit:
                break
        
        log_message(f"Fetched top {len(filtered_pairs)} Cornix-compatible pairs by 24h volume")
        return filtered_pairs
        
    except Exception as e:
        log_message(f"Error fetching top volume pairs: {e}")
        # Fallback to default pairs
        return [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT',
            'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT',
            'UNIUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT'
        ][:limit]

def fetch_trading_pairs(retries=5, timeout=20):
    """Enhanced trading pairs fetching with volume-based selection"""
    attempt = 0
    while attempt < retries:
        try:
            # Use volume-based selection for better pairs
            return fetch_top_volume_pairs()
        except (ConnectTimeout, MaxRetryError) as e:
            log_message(f"Attempt {attempt + 1}/{retries} failed to fetch trading pairs: {e}")
            attempt += 1
            backoff = min(2 ** attempt, 64)
            log_message(f"Retrying in {backoff} seconds...")
            time.sleep(backoff)
        except BinanceAPIException as e:
            log_message(f"Error fetching trading pairs: {e}")
            return []
        except Exception as e:
            log_message(f"An unexpected error occurred while fetching trading pairs: {e}")
            return []
    return []

def _refresh_exchange_info_cache():
    """Refresh the exchange info cache if stale (called lazily)"""
    import time as _time
    now = _time.time()
    if _EXCHANGE_INFO_CACHE['data'] is None or (now - _EXCHANGE_INFO_CACHE['timestamp']) > _EXCHANGE_INFO_TTL:
        try:
            rate_limit()
            info = client.futures_exchange_info()
            _EXCHANGE_INFO_CACHE['data'] = info
            _EXCHANGE_INFO_CACHE['timestamp'] = now
            _EXCHANGE_INFO_CACHE['precision_map'] = {
                s['symbol']: s['quotePrecision'] for s in info.get('symbols', [])
            }
            log_message(f"Refreshed exchange_info cache: {len(_EXCHANGE_INFO_CACHE['precision_map'])} symbols")
        except Exception as e:
            log_message(f"Error refreshing exchange_info cache: {e}")

def get_precision(pair):
    """Get quote precision from cached exchange info (1 API call per 24h instead of per pair)"""
    _refresh_exchange_info_cache()
    return _EXCHANGE_INFO_CACHE['precision_map'].get(pair, 6)

def get_order_book_depth(pair, depth=100):
    """Calculate bid/ask imbalance and identify key supply/demand walls"""
    try:
        rate_limit()
        order_book = client.futures_order_book(symbol=pair, limit=depth)
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return {'imbalance': 1.0, 'buy_walls': [], 'sell_walls': []}
            
        # Calculate volume at different depths (1%, 5%)
        current_price = float(bids[0][0])
        depth_1pct = current_price * 0.01
        depth_5pct = current_price * 0.05
        
        vol_bid_1pct = sum(float(b[1]) for b in bids if float(b[0]) > current_price - depth_1pct)
        vol_ask_1pct = sum(float(a[1]) for a in asks if float(a[0]) < current_price + depth_1pct)
        
        # Identify "Walls" (Price levels with > 3x average volume)
        avg_bid_vol = sum(float(b[1]) for b in bids) / len(bids)
        avg_ask_vol = sum(float(a[1]) for a in asks) / len(asks)
        
        buy_walls = [float(b[0]) for b in bids if float(b[1]) > avg_bid_vol * 3]
        sell_walls = [float(a[0]) for a in asks if float(a[1]) > avg_ask_vol * 3]
        
        imbalance = vol_bid_1pct / vol_ask_1pct if vol_ask_1pct > 0 else 2.0
        
        return {
            'imbalance': imbalance,
            'buy_walls': sorted(buy_walls, reverse=True)[:3],
            'sell_walls': sorted(sell_walls)[:3],
            'vol_ratio': vol_bid_1pct / (vol_bid_1pct + vol_ask_1pct) if (vol_bid_1pct + vol_ask_1pct) > 0 else 0.5
        }
    except Exception as e:
        log_message(f"Error fetching order book for {pair}: {e}")
        return {'imbalance': 1.0, 'buy_walls': [], 'sell_walls': []}

def get_funding_rate(pair):
    """Get current funding rate for the pair with caching"""
    import time as _time
    now = _time.time()
    
    # Check cache
    if pair in _FUNDING_CACHE['current']:
        cached_data, cached_time = _FUNDING_CACHE['current'][pair]
        if now - cached_time < _FUNDING_TTL:
            return cached_data
            
    try:
        rate_limit()
        funding_rate_info = client.futures_funding_rate(symbol=pair, limit=1)
        if funding_rate_info and len(funding_rate_info) > 0:
            funding_rate = float(funding_rate_info[0]['fundingRate'])
            funding_time = int(funding_rate_info[0]['fundingTime'])
            # Save to cache
            _FUNDING_CACHE['current'][pair] = ((funding_rate, funding_time), now)
            log_message(f"Funding rate for {pair}: {funding_rate:.6f} ({funding_rate*100:.4f}%)")
            return funding_rate, funding_time
        return 0.0, 0
    except BinanceAPIException as e:
        log_message(f"API Error fetching funding rate for {pair}: {e}")
        return 0.0, 0
    except Exception as e:
        log_message(f"Error fetching funding rate for {pair}: {e}")
        return 0.0, 0

def get_funding_rate_history(pair, limit=10):
    """Get historical funding rates for trend analysis with caching"""
    import time as _time
    now = _time.time()
    
    # Check cache
    cache_key = f"{pair}_{limit}"
    if cache_key in _FUNDING_CACHE['history']:
        cached_data, cached_time = _FUNDING_CACHE['history'][cache_key]
        if now - cached_time < _FUNDING_TTL:
            return cached_data
            
    try:
        rate_limit()
        funding_history = client.futures_funding_rate(symbol=pair, limit=limit)
        if funding_history and len(funding_history) > 0:
            rates = [float(item['fundingRate']) for item in funding_history]
            times = [int(item['fundingTime']) for item in funding_history]
            # Save to cache
            _FUNDING_CACHE['history'][cache_key] = ((rates, times), now)
            log_message(f"Retrieved {len(rates)} historical funding rates for {pair}")
            return rates, times
        return [], []
    except BinanceAPIException as e:
        log_message(f"API Error fetching funding rate history for {pair}: {e}")
        return [], []
    except Exception as e:
        log_message(f"Error fetching funding rate history for {pair}: {e}")
        return [], []

def analyze_funding_rate_sentiment(pair):
    """Analyze funding rate to determine market sentiment and signal strength"""
    try:
        # Get current funding rate
        current_rate, funding_time = get_funding_rate(pair)
        
        # Get historical rates for trend analysis
        historical_rates, historical_times = get_funding_rate_history(pair, limit=10)
        
        analysis = {
            'current_rate': current_rate,
            'current_rate_pct': current_rate * 100,
            'sentiment': 'NEUTRAL',
            'strength': 0.0,
            'signal_bias': 'NONE',
            'confidence_adjustment': 0.0,
            'funding_trend': 'STABLE',
            'extreme_funding': False
        }
        
        # Analyze current funding rate
        if current_rate > 0.01:  # 1% funding rate (very high)
            analysis['sentiment'] = 'EXTREMELY_BULLISH'
            analysis['strength'] = 1.0
            analysis['signal_bias'] = 'SHORT'  # High funding favors shorts
            analysis['confidence_adjustment'] = 15.0  # Boost short confidence
            analysis['extreme_funding'] = True
        elif current_rate > 0.005:  # 0.5% funding rate (high)
            analysis['sentiment'] = 'VERY_BULLISH'
            analysis['strength'] = 0.8
            analysis['signal_bias'] = 'SHORT'
            analysis['confidence_adjustment'] = 10.0
        elif current_rate > 0.001:  # 0.1% funding rate (moderately high)
            analysis['sentiment'] = 'BULLISH'
            analysis['strength'] = 0.6
            analysis['signal_bias'] = 'SHORT'
            analysis['confidence_adjustment'] = 5.0
        elif current_rate > 0.0001:  # 0.01% funding rate (slightly positive)
            analysis['sentiment'] = 'SLIGHTLY_BULLISH'
            analysis['strength'] = 0.3
            analysis['signal_bias'] = 'SLIGHT_SHORT'
            analysis['confidence_adjustment'] = 2.0
        elif current_rate < -0.01:  # -1% funding rate (very negative)
            analysis['sentiment'] = 'EXTREMELY_BEARISH'
            analysis['strength'] = 1.0
            analysis['signal_bias'] = 'LONG'  # Negative funding favors longs
            analysis['confidence_adjustment'] = 15.0  # Boost long confidence
            analysis['extreme_funding'] = True
        elif current_rate < -0.005:  # -0.5% funding rate (negative)
            analysis['sentiment'] = 'VERY_BEARISH'
            analysis['strength'] = 0.8
            analysis['signal_bias'] = 'LONG'
            analysis['confidence_adjustment'] = 10.0
        elif current_rate < -0.001:  # -0.1% funding rate (moderately negative)
            analysis['sentiment'] = 'BEARISH'
            analysis['strength'] = 0.6
            analysis['signal_bias'] = 'LONG'
            analysis['confidence_adjustment'] = 5.0
        elif current_rate < -0.0001:  # -0.01% funding rate (slightly negative)
            analysis['sentiment'] = 'SLIGHTLY_BEARISH'
            analysis['strength'] = 0.3
            analysis['signal_bias'] = 'SLIGHT_LONG'
            analysis['confidence_adjustment'] = 2.0
        else:
            analysis['sentiment'] = 'NEUTRAL'
            analysis['strength'] = 0.0
            analysis['signal_bias'] = 'NONE'
            analysis['confidence_adjustment'] = 0.0
        
        # Analyze funding rate trend if we have historical data
        if len(historical_rates) >= 3:
            recent_avg = sum(historical_rates[:3]) / 3  # Last 3 periods
            older_avg = sum(historical_rates[3:6]) / 3 if len(historical_rates) >= 6 else recent_avg
            
            trend_change = recent_avg - older_avg
            
            if trend_change > 0.001:  # Increasing funding rate
                analysis['funding_trend'] = 'INCREASING'
                if analysis['signal_bias'] == 'SHORT':
                    analysis['confidence_adjustment'] += 3.0  # Strengthen short bias
            elif trend_change < -0.001:  # Decreasing funding rate
                analysis['funding_trend'] = 'DECREASING'
                if analysis['signal_bias'] == 'LONG':
                    analysis['confidence_adjustment'] += 3.0  # Strengthen long bias
            else:
                analysis['funding_trend'] = 'STABLE'
        
        # Calculate funding rate volatility
        if len(historical_rates) >= 5:
            import statistics
            funding_volatility = statistics.stdev(historical_rates[:5])
            if funding_volatility > 0.002:  # High volatility in funding
                analysis['high_volatility'] = True
                analysis['confidence_adjustment'] *= 0.8  # Reduce confidence in volatile funding
            else:
                analysis['high_volatility'] = False
        
        log_message(f"Funding analysis for {pair}: {analysis['sentiment']} "
                   f"({analysis['current_rate_pct']:.4f}%), bias: {analysis['signal_bias']}, "
                   f"confidence adj: {analysis['confidence_adjustment']:.1f}%")
        
        return analysis
        
    except Exception as e:
        log_message(f"Error analyzing funding rate for {pair}: {e}")
        return {
            'current_rate': 0.0,
            'current_rate_pct': 0.0,
            'sentiment': 'NEUTRAL',
            'strength': 0.0,
            'signal_bias': 'NONE',
            'confidence_adjustment': 0.0,
            'funding_trend': 'UNKNOWN',
            'extreme_funding': False
        }

def get_max_leverage(pair):
    try:
        rate_limit()
        max_leverage_info = client.futures_leverage_bracket()
        for item in max_leverage_info:
            if item['symbol'] == pair:
                # Handle different API response structures
                if isinstance(item['brackets'], list) and len(item['brackets']) > 0:
                    return min(item['brackets'][0]['initialLeverage'], 50)
                elif isinstance(item['bracket'], list) and len(item['bracket']) > 0:
                    return min(item['bracket'][0]['initialLeverage'], 50)
        return 20
    except BinanceAPIException as e:
        log_message(f"API Error fetching max leverage for {pair}: {e}")
        return 20
    except Exception as e:
        log_message(f"Error fetching max leverage for {pair}: {e}")
        return 20

def set_cross_leverage(pair):
    try:
        max_leverage = get_max_leverage(pair)
        rate_limit()
        
        # Directly check permissions for this specific pair
        try:
            # First check if we can trade this pair at all
            exchange_info = client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == pair), None)
            if not symbol_info or not symbol_info.get('status') == 'TRADING':
                log_message(f"Pair {pair} not available for trading")
                return max_leverage
                
            # Initialize all permission variables first
            can_trade = False
            can_change_margin = False
            can_change_leverage = False
            
            # Then check account permissions
            account_info = client.futures_account()
            can_trade = account_info.get('canTrade', False)
            can_change_margin = account_info.get('canChangeMarginType', False)
            can_change_leverage = account_info.get('canTrade', False)  # Using canTrade as proxy
            
            # Log all permission states
            log_message(f"Permissions for {pair}: Trade={can_trade}, Margin={can_change_margin}, Leverage={can_change_leverage}")
            
            if not can_trade:
                log_message(f"Cannot trade {pair} - skipping")
                log_message(f"API key lacks specific permissions for {pair}: "
                          f"can_change_margin={can_change_margin}, "
                          f"can_change_leverage={can_change_leverage}")
                return max_leverage
        except BinanceAPIException as e:
            log_message(f"Detailed API key verification failed for {pair}: {e}")
            return max_leverage
            
        # Try to set margin type with better error handling
        try:
            client.futures_change_margin_type(symbol=pair, marginType='CROSSED')
        except BinanceAPIException as e:
            if 'No need to change margin type' not in str(e):
                if 'permissions' in str(e).lower():
                    log_message(f"Skipping margin type change for {pair} (permission denied)")
                else:
                    log_message(f"Margin type change failed for {pair}: {e}")
            return max_leverage  # Still return max leverage even if change failed
            
        # Try to set leverage (skip if permission denied)
        try:
            client.futures_change_leverage(symbol=pair, leverage=max_leverage)
            log_message(f"Set cross leverage x{max_leverage} for {pair}")
        except BinanceAPIException as e:
            if 'permissions' in str(e).lower():
                log_message(f"Skipping leverage change for {pair} (permission denied)")
            else:
                log_message(f"Leverage change failed for {pair}: {e}")
                
        return max_leverage
            
    except Exception as e:
        log_message(f"Unexpected error setting leverage for {pair}: {e}")
        return 20  # Fallback to default leverage

# Global variable to track API permissions
API_PERMISSIONS = {
    'can_change_margin': None,
    'can_change_leverage': None,
    'last_checked': 0
}

# PROPOSAL 4: Open Interest Flow Analysis
_OI_CACHE = {}
_OI_CACHE_TTL = 300  # 5 minutes

def get_open_interest_change(symbol):
    """Get Open Interest change to detect crowded positioning or weak rallies."""
    try:
        now = time.time()
        if symbol in _OI_CACHE and now - _OI_CACHE[symbol]['ts'] < _OI_CACHE_TTL:
            return _OI_CACHE[symbol]['data']
        
        oi_data = client.futures_open_interest_hist(symbol=symbol, period='5m', limit=3)
        if oi_data and len(oi_data) >= 2:
            oi_current = float(oi_data[-1]['sumOpenInterest'])
            oi_prev = float(oi_data[-2]['sumOpenInterest'])
            oi_change = (oi_current - oi_prev) / oi_prev if oi_prev > 0 else 0.0
            result = {'oi_change': oi_change, 'oi_current': oi_current}
            _OI_CACHE[symbol] = {'data': result, 'ts': now}
            log_message(f"📈 OI for {symbol}: {oi_change:+.2%} change ({oi_current:.0f})")
            return result
        return {'oi_change': 0.0, 'oi_current': 0.0}
    except Exception:
        return {'oi_change': 0.0, 'oi_current': 0.0}
