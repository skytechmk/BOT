import pandas as pd
import numpy as np
import talib
from utils_logger import log_message

def calculate_rsi(data, period=14):
    close_prices = data['close'].values
    rsi = talib.RSI(close_prices, timeperiod=period)
    return pd.Series(rsi, index=data.index)

def calculate_bollinger_bands(df, period=20, std_dev=2):
    close_prices = df['close'].values
    upper, middle, lower = talib.BBANDS(close_prices, 
                                      timeperiod=period,
                                      nbdevup=std_dev,
                                      nbdevdn=std_dev,
                                      matype=0)  # 0 = SMA
    df['SMA'] = middle
    df['Upper Band'] = upper
    df['Lower Band'] = lower
    return df

def calculate_vwap(df):
    df['Cumulative Volume'] = df['volume'].cumsum()
    df['Cumulative Volume Price'] = (df['close'] * df['volume']).cumsum()
    df['VWAP'] = df['Cumulative Volume Price'] / df['Cumulative Volume']
    return df

def calculate_macd(df, short_window=12, long_window=26, signal_window=9):
    close_prices = df['close'].values
    macd, signal, hist = talib.MACD(close_prices,
                                   fastperiod=short_window,
                                   slowperiod=long_window,
                                   signalperiod=signal_window)
    df['MACD Line'] = macd
    df['Signal Line'] = signal
    df['MACD Histogram'] = hist
    return df

def calculate_atr(df, period=14):
    """Calculate ATR with Rust acceleration when available"""
    try:
        from shared_state import RUST_CORE_AVAILABLE
        if RUST_CORE_AVAILABLE:
            import aladdin_core
            # Use Rust implementation for better performance
            high = df['high'].tolist()
            low = df['low'].tolist()
            close = df['close'].tolist()
            
            atr_values = aladdin_core.calculate_atr_rust(high, low, close, period)
            df['ATR'] = atr_values
            return df
    except (ImportError, Exception) as e:
        log_message(f"Rust ATR unavailable, using talib fallback: {e}")
    
    # Fallback to talib implementation
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    atr = talib.ATR(high, low, close, timeperiod=period)
    df['ATR'] = atr
    return df

def calculate_ichimoku(df):
    # Tenkan-sen (Conversion Line)
    nine_period_high = df['high'].rolling(window=9).max()
    nine_period_low = df['low'].rolling(window=9).min()
    df['tenkan_sen'] = (nine_period_high + nine_period_low) / 2

    # Kijun-sen (Base Line)
    twenty_six_period_high = df['high'].rolling(window=26).max()
    twenty_six_period_low = df['low'].rolling(window=26).min()
    df['kijun_sen'] = (twenty_six_period_high + twenty_six_period_low) / 2

    # Senkou Span A (Leading Span A)
    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)

    # Senkou Span B (Leading Span B)
    fifty_two_period_high = df['high'].rolling(window=52).max()
    fifty_two_period_low = df['low'].rolling(window=52).min()
    df['senkou_span_b'] = ((fifty_two_period_high + fifty_two_period_low) / 2).shift(26)

    return df

def calculate_chandelier_exit(df, atr_period=22, mult=3.0):
    """
    Chandelier Exit Hybrid (ATR-based trailing stop indicator)
    Adapted from CE Pro Hybrid PineScript logic.
    """
    try:
        if 'ATR' not in df.columns:
            high = df['high'].values
            low = df['low'].values
            close_prices = df['close'].values
            atr = talib.ATR(high, low, close_prices, timeperiod=atr_period)
        else:
            atr = df['ATR'].values
            
        # Calculate raw Highest High and Lowest Low
        highest_high = df['high'].rolling(window=atr_period).max().values
        lowest_low = df['low'].rolling(window=atr_period).min().values
        
        # Base Stops
        long_raw = lowest_low - (atr * mult)
        short_raw = highest_high + (atr * mult)
        
        # State Arrays
        long_stop = np.full(len(df), np.nan)
        short_stop = np.full(len(df), np.nan)
        direction = np.zeros(len(df))
        
        cl = df['close'].values
        
        # Seed initial values safely skipping NaNs
        l_stop = 0.0
        s_stop = 0.0
        d = 1
        
        for i in range(1, len(df)):
            if np.isnan(long_raw[i]) or np.isnan(short_raw[i]):
                long_stop[i] = l_stop
                short_stop[i] = s_stop
                direction[i] = d
                continue
                
            prev_close = cl[i-1]
            prev_l_stop = l_stop if not np.isnan(l_stop) else long_raw[i]
            prev_s_stop = s_stop if not np.isnan(s_stop) else short_raw[i]
            
            # Update Long Stop
            if prev_close > prev_l_stop:
                l_stop = max(long_raw[i], prev_l_stop)
            else:
                l_stop = long_raw[i]
                
            # Update Short Stop
            if prev_close < prev_s_stop:
                s_stop = min(short_raw[i], prev_s_stop)
            else:
                s_stop = short_raw[i]
                
            # Update Direction - Institutional Stabilizer
            # Use prev_close (i-1) to lock the signal and prevent intra-candle flipping/repainting
            if cl[i-1] > prev_s_stop:
                d = 1
            elif cl[i-1] < prev_l_stop:
                d = -1
                
            long_stop[i] = l_stop
            short_stop[i] = s_stop
            direction[i] = d

        df['CE_Long_Stop'] = long_stop
        df['CE_Short_Stop'] = short_stop
        df['CE_Direction'] = direction  # 1 for LONG, -1 for SHORT
        
        return df
    except Exception as e:
        log_message(f"Error calculating Chandelier Exit: {e}")
        df['CE_Long_Stop'] = df['low']
        df['CE_Short_Stop'] = df['high']
        df['CE_Direction'] = 0
        return df

def detect_candlestick_patterns(df):
    """Comprehensive candlestick pattern detection using TA-Lib"""
    try:
        open_prices = df['open'].values
        high_prices = df['high'].values
        low_prices = df['low'].values
        close_prices = df['close'].values
        
        # Initialize pattern data
        pattern_data = {
            'Pattern': 'None',
            'Pattern_Strength': 0,
            'Pattern_Type': 'Neutral'
        }
        
        # Bullish patterns
        patterns = {
            # Single candlestick patterns
            'CDLHAMMER': ('Hammer', 'Bullish'),
            'CDLINVERTEDHAMMER': ('Inverted Hammer', 'Bullish'),
            'CDLDRAGONFLYDOJI': ('Dragonfly Doji', 'Bullish'),
            'CDLENGULFING': ('Bullish Engulfing', 'Bullish'),
            'CDLMORNINGSTAR': ('Morning Star', 'Bullish'),
            'CDLPIERCING': ('Piercing Pattern', 'Bullish'),
            'CDL3WHITESOLDIERS': ('Three White Soldiers', 'Bullish'),
            'CDLMORNINGDOJISTAR': ('Morning Doji Star', 'Bullish'),
            'CDLBELTHOLD': ('Belt Hold', 'Mixed'),
            
            # Bearish patterns
            'CDLSHOOTINGSTAR': ('Shooting Star', 'Bearish'),
            'CDLHANGINGMAN': ('Hanging Man', 'Bearish'),
            'CDLGRAVESTONEDOJI': ('Gravestone Doji', 'Bearish'),
            'CDLEVENINGSTAR': ('Evening Star', 'Bearish'),
            'CDLDARKCLOUDCOVER': ('Dark Cloud Cover', 'Bearish'),
            'CDL3BLACKCROWS': ('Three Black Crows', 'Bearish'),
            'CDLEVENINGDOJISTAR': ('Evening Doji Star', 'Bearish'),
            
            # Reversal patterns
            'CDLHARAMI': ('Harami', 'Mixed'),
            'CDLHARAMICROSS': ('Harami Cross', 'Mixed'),
            'CDLDOJI': ('Doji', 'Neutral'),
            'CDLSPINNINGTOP': ('Spinning Top', 'Neutral'),
            'CDLMARUBOZU': ('Marubozu', 'Mixed'),
            
            # Advanced patterns
            'CDLTHRUSTING': ('Thrusting Pattern', 'Bearish'),
            'CDLINNECK': ('In Neck Pattern', 'Bearish'),
            'CDLONNECK': ('On Neck Pattern', 'Bearish'),
            'CDLKICKING': ('Kicking Pattern', 'Mixed'),
            'CDLGAPSIDESIDEWHITE': ('Up/Down Gap Side by Side White', 'Mixed'),
            'CDLHIGHWAVE': ('High Wave Candle', 'Neutral'),
            'CDLRICKSHAWMAN': ('Rickshaw Man', 'Neutral'),
            'CDLSEPARATINGLINES': ('Separating Lines', 'Mixed'),
            'CDLADVANCEBLOCK': ('Advance Block', 'Bearish'),
            'CDLBREAKAWAY': ('Breakaway', 'Mixed'),
            'CDLCLOSINGMARUBOZU': ('Closing Marubozu', 'Mixed'),
            'CDLCONCEALBABYSWALL': ('Concealing Baby Swallow', 'Bullish'),
            'CDLCOUNTERATTACK': ('Counterattack', 'Mixed'),
            'CDLHOMINGPIGEON': ('Homing Pigeon', 'Bullish'),
            'CDLIDENTICAL3CROWS': ('Identical Three Crows', 'Bearish'),
            'CDLLADDERBOTTOM': ('Ladder Bottom', 'Bullish'),
            'CDLLONGLEGGEDDOJI': ('Long Legged Doji', 'Neutral'),
            'CDLMATCHINGLOW': ('Matching Low', 'Bullish'),
            'CDLMATHOLD': ('Mat Hold', 'Bullish'),
            'CDLRISEFALL3METHODS': ('Rising/Falling Three Methods', 'Mixed'),
            'CDLSTALLEDPATTERN': ('Stalled Pattern', 'Bearish'),
            'CDLSTICKSANDWICH': ('Stick Sandwich', 'Bullish'),
            'CDLTAKURI': ('Takuri', 'Bullish'),
            'CDLTASUKIGAP': ('Tasuki Gap', 'Mixed'),
            'CDLUNIQUE3RIVER': ('Unique 3 River', 'Bullish'),
            'CDLUPSIDEGAP2CROWS': ('Upside Gap Two Crows', 'Bearish'),
            'CDLXSIDEGAP3METHODS': ('Upside/Downside Gap Three Methods', 'Mixed')
        }
        
        detected_patterns = []
        
        # Detect all patterns
        for pattern_func, (pattern_name, pattern_type) in patterns.items():
            try:
                pattern_result = getattr(talib, pattern_func)(open_prices, high_prices, low_prices, close_prices)
                latest_signal = pattern_result[-1]
                
                if latest_signal != 0:
                    strength = abs(latest_signal)
                    direction = 'Bullish' if latest_signal > 0 else 'Bearish'
                    
                    # Override direction based on pattern type for mixed patterns
                    if pattern_type == 'Mixed':
                        direction = 'Bullish' if latest_signal > 0 else 'Bearish'
                    elif pattern_type != 'Neutral':
                        direction = pattern_type
                    
                    detected_patterns.append({
                        'name': pattern_name,
                        'strength': strength,
                        'direction': direction,
                        'type': pattern_type
                    })
                    
                    log_message(f"Pattern detected: {pattern_name} ({direction}) - Strength: {strength}")
                    
            except Exception as e:
                log_message(f"Error detecting pattern {pattern_func}: {e}")
                continue
        
        # Select the strongest pattern and update pattern_data
        if detected_patterns:
            strongest_pattern = max(detected_patterns, key=lambda x: x['strength'])
            pattern_data['Pattern'] = strongest_pattern['name']
            pattern_data['Pattern_Strength'] = strongest_pattern['strength']
            pattern_data['Pattern_Type'] = strongest_pattern['direction']
            
            log_message(f"Strongest pattern: {strongest_pattern['name']} ({strongest_pattern['direction']}) - Strength: {strongest_pattern['strength']}")
        
        # Add pattern columns efficiently using pd.concat
        pattern_df = pd.DataFrame(pattern_data, index=df.index)
        df = pd.concat([df, pattern_df], axis=1)
        
        return df
        
    except Exception as e:
        log_message(f"Error in candlestick pattern detection: {e}")
        # Add default pattern columns efficiently
        pattern_df = pd.DataFrame(pattern_data, index=df.index)
        df = pd.concat([df, pattern_df], axis=1)
        return df

def calculate_fair_value_gaps(df, lookback=50):
    """Calculate Fair Value Gaps (FVG) for enhanced target identification"""
    try:
        if len(df) < 3:
            return {'bullish_fvgs': [], 'bearish_fvgs': [], 'unfilled_fvgs': []}
        
        bullish_fvgs = []
        bearish_fvgs = []
        unfilled_fvgs = []
        
        # Look for FVGs in recent data
        start_idx = max(0, len(df) - lookback)
        
        for i in range(start_idx + 2, len(df)):
            # Get three consecutive candles
            candle1 = df.iloc[i-2]  # First candle
            candle2 = df.iloc[i-1]  # Middle candle (gap candle)
            candle3 = df.iloc[i]    # Third candle
            
            # Bullish FVG: Gap between candle1 high and candle3 low
            # Condition: candle1 high < candle3 low (with candle2 in between)
            if candle1['high'] < candle3['low']:
                # Verify it's a true gap (candle2 doesn't fill it)
                if candle2['low'] > candle1['high'] and candle2['high'] < candle3['low']:
                    fvg = {
                        'type': 'bullish',
                        'top': candle3['low'],
                        'bottom': candle1['high'],
                        'index': i-2,
                        'timestamp': candle1.name,
                        'filled': False,
                        'strength': abs(candle3['low'] - candle1['high']) / candle1['high']
                    }
                    bullish_fvgs.append(fvg)
            
            # Bearish FVG: Gap between candle1 low and candle3 high
            # Condition: candle1 low > candle3 high (with candle2 in between)
            elif candle1['low'] > candle3['high']:
                # Verify it's a true gap (candle2 doesn't fill it)
                if candle2['high'] < candle1['low'] and candle2['low'] > candle3['high']:
                    fvg = {
                        'type': 'bearish',
                        'top': candle1['low'],
                        'bottom': candle3['high'],
                        'index': i-2,
                        'timestamp': candle1.name,
                        'filled': False,
                        'strength': abs(candle1['low'] - candle3['high']) / candle3['high']
                    }
                    bearish_fvgs.append(fvg)
        
        # Check which FVGs are still unfilled
        current_price = df['close'].iloc[-1]
        
        for fvg in bullish_fvgs + bearish_fvgs:
            # Check if FVG has been filled by subsequent price action
            fvg_start_idx = fvg['index'] + 3
            filled = False
            
            for j in range(fvg_start_idx, len(df)):
                candle = df.iloc[j]
                
                if fvg['type'] == 'bullish':
                    # Bullish FVG is filled if price trades back into the gap
                    if candle['low'] <= fvg['top'] and candle['high'] >= fvg['bottom']:
                        filled = True
                        break
                else:  # bearish
                    # Bearish FVG is filled if price trades back into the gap
                    if candle['high'] >= fvg['bottom'] and candle['low'] <= fvg['top']:
                        filled = True
                        break
            
            fvg['filled'] = filled
            
            # Add to unfilled list if still valid
            if not filled:
                # Check if FVG is still relevant (within reasonable distance from current price)
                fvg_mid = (fvg['top'] + fvg['bottom']) / 2
                distance_pct = abs(fvg_mid - current_price) / current_price
                
                if distance_pct <= 0.1:  # Within 10% of current price
                    unfilled_fvgs.append(fvg)
        
        # Sort unfilled FVGs by proximity to current price
        unfilled_fvgs.sort(key=lambda x: abs(((x['top'] + x['bottom']) / 2) - current_price))
        
        log_message(f"Fair Value Gaps identified: {len(bullish_fvgs)} bullish, {len(bearish_fvgs)} bearish, {len(unfilled_fvgs)} unfilled")
        
        return {
            'bullish_fvgs': bullish_fvgs,
            'bearish_fvgs': bearish_fvgs,
            'unfilled_fvgs': unfilled_fvgs
        }
        
    except Exception as e:
        log_message(f"Error calculating Fair Value Gaps: {e}")
        return {'bullish_fvgs': [], 'bearish_fvgs': [], 'unfilled_fvgs': []}

def calculate_volume_profile(df, num_bins=20):
    """Calculate Visible Range Volume Profile (VRVP) for target identification"""
    try:
        # Get price range for the visible period (last 100 candles or available data)
        visible_period = min(100, len(df))
        df_visible = df.tail(visible_period).copy()
        
        # Calculate price range
        price_min = df_visible['low'].min()
        price_max = df_visible['high'].max()
        price_range = price_max - price_min
        
        if price_range == 0:
            log_message("Zero price range in volume profile calculation")
            return {}
        
        # Create price bins
        bin_size = price_range / num_bins
        bins = [price_min + i * bin_size for i in range(num_bins + 1)]
        
        # Initialize volume profile data
        volume_profile = {
            'price_levels': [],
            'volumes': [],
            'poc': 0,  # Point of Control (highest volume)
            'vah': 0,  # Value Area High
            'val': 0,  # Value Area Low
            'support_levels': [],
            'resistance_levels': []
        }
        
        # Calculate volume for each price bin
        bin_volumes = []
        bin_prices = []
        
        for i in range(num_bins):
            bin_low = bins[i]
            bin_high = bins[i + 1]
            bin_mid = (bin_low + bin_high) / 2
            bin_prices.append(bin_mid)
            
            # Vectorized overlap calculation
            overlap_low = np.maximum(bin_low, df_visible['low'].values)
            overlap_high = np.minimum(bin_high, df_visible['high'].values)
            valid_overlap = overlap_high > overlap_low
            
            candle_range = (df_visible['high'] - df_visible['low']).values
            candle_range = np.where(candle_range > 0, candle_range, 1.0)
            
            overlap_ratio = np.where(valid_overlap, (overlap_high - overlap_low) / candle_range, 0.0)
            
            # Handle single price candles (high == low)
            single_price_mask = (df_visible['high'] == df_visible['low']).values
            in_bin_mask = (df_visible['low'].values >= bin_low) & (df_visible['low'].values <= bin_high)
            overlap_ratio = np.where(single_price_mask & in_bin_mask, 1.0, overlap_ratio)
            
            bin_volume = np.sum(df_visible['volume'].values * overlap_ratio)
            bin_volumes.append(float(bin_volume))
        
        volume_profile['price_levels'] = bin_prices
        volume_profile['volumes'] = bin_volumes
        
        # Find Point of Control (POC) - price level with highest volume
        if bin_volumes:
            max_volume_idx = bin_volumes.index(max(bin_volumes))
            volume_profile['poc'] = bin_prices[max_volume_idx]
            
            # Calculate Value Area (70% of total volume)
            total_volume = sum(bin_volumes)
            target_volume = total_volume * 0.7
            
            # Find Value Area High and Low
            sorted_bins = sorted(zip(bin_volumes, bin_prices), reverse=True)
            cumulative_volume = 0
            value_area_prices = []
            
            for volume, price in sorted_bins:
                cumulative_volume += volume
                value_area_prices.append(price)
                if cumulative_volume >= target_volume:
                    break
            
            if value_area_prices:
                volume_profile['vah'] = max(value_area_prices)
                volume_profile['val'] = min(value_area_prices)
            
            # Identify support and resistance levels from volume profile
            # Look for local volume maxima (high volume nodes)
            volume_threshold = max(bin_volumes) * 0.3  # 30% of max volume
            
            for i, (price, volume) in enumerate(zip(bin_prices, bin_volumes)):
                if volume >= volume_threshold:
                    # Check if it's a local maximum
                    is_local_max = True
                    for j in range(max(0, i-2), min(len(bin_volumes), i+3)):
                        if j != i and bin_volumes[j] > volume:
                            is_local_max = False
                            break
                    
                    if is_local_max:
                        current_price = df['close'].iloc[-1]
                        if price > current_price:
                            volume_profile['resistance_levels'].append(price)
                        else:
                            volume_profile['support_levels'].append(price)
            
            # Sort levels
            volume_profile['resistance_levels'].sort()
            volume_profile['support_levels'].sort(reverse=True)
        
        log_message(f"Volume Profile calculated: POC={volume_profile['poc']:.6f}, "
                   f"VAH={volume_profile['vah']:.6f}, VAL={volume_profile['val']:.6f}, "
                   f"Resistance levels: {len(volume_profile['resistance_levels'])}, "
                   f"Support levels: {len(volume_profile['support_levels'])}")
        
        return volume_profile
        
    except Exception as e:
        log_message(f"Error calculating volume profile: {e}")
        return {}

def calculate_advanced_indicators(df):
    """Calculate comprehensive technical indicators"""
    try:
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        volume = df['volume'].values
        
        # Momentum Indicators
        df['RSI_14'] = talib.RSI(close, timeperiod=14)
        df['RSI_21'] = talib.RSI(close, timeperiod=21)
        df['STOCH_K'], df['STOCH_D'] = talib.STOCH(high, low, close)
        df['STOCHF_K'], df['STOCHF_D'] = talib.STOCHF(high, low, close)
        df['STOCHRSI_K'], df['STOCHRSI_D'] = talib.STOCHRSI(close)
        df['WILLR'] = talib.WILLR(high, low, close)
        df['ROC_10'] = talib.ROC(close, timeperiod=10)
        df['ROC_20'] = talib.ROC(close, timeperiod=20)
        df['MOM_10'] = talib.MOM(close, timeperiod=10)
        df['MOM_20'] = talib.MOM(close, timeperiod=20)
        df['CCI_14'] = talib.CCI(high, low, close, timeperiod=14)
        df['CCI_20'] = talib.CCI(high, low, close, timeperiod=20)
        df['CMO'] = talib.CMO(close)
        df['DX'] = talib.DX(high, low, close)
        df['MINUS_DI'] = talib.MINUS_DI(high, low, close)
        df['PLUS_DI'] = talib.PLUS_DI(high, low, close)
        df['ADX'] = talib.ADX(high, low, close)
        df['ADXR'] = talib.ADXR(high, low, close)
        df['APO'] = talib.APO(close)
        df['AROON_UP'], df['AROON_DOWN'] = talib.AROON(high, low)
        df['AROONOSC'] = talib.AROONOSC(high, low)
        df['BOP'] = talib.BOP(df['open'].values, high, low, close)
        df['MFI'] = talib.MFI(high, low, close, volume)
        df['PPO'] = talib.PPO(close)
        df['TRIX'] = talib.TRIX(close)
        df['ULTOSC'] = talib.ULTOSC(high, low, close)
        
        # Overlap Studies (Moving Averages)
        df['SMA_5'] = talib.SMA(close, timeperiod=5)
        df['SMA_10'] = talib.SMA(close, timeperiod=10)
        df['SMA_20'] = talib.SMA(close, timeperiod=20)
        df['SMA_50'] = talib.SMA(close, timeperiod=50)
        df['SMA_100'] = talib.SMA(close, timeperiod=100)
        df['SMA_200'] = talib.SMA(close, timeperiod=200)
        df['EMA_5'] = talib.EMA(close, timeperiod=5)
        df['EMA_10'] = talib.EMA(close, timeperiod=10)
        df['EMA_20'] = talib.EMA(close, timeperiod=20)
        df['EMA_50'] = talib.EMA(close, timeperiod=50)
        df['EMA_80'] = talib.EMA(close, timeperiod=80)
        df['EMA_100'] = talib.EMA(close, timeperiod=100)
        df['EMA_200'] = talib.EMA(close, timeperiod=200)
        df['WMA_20'] = talib.WMA(close, timeperiod=20)
        df['DEMA'] = talib.DEMA(close)
        df['TEMA'] = talib.TEMA(close)
        df['TRIMA'] = talib.TRIMA(close)
        df['KAMA'] = talib.KAMA(close)
        df['MAMA'], df['FAMA'] = talib.MAMA(close)
        df['T3'] = talib.T3(close)
        df['HT_TRENDLINE'] = talib.HT_TRENDLINE(close)
        
        # Volatility Indicators
        df['NATR'] = talib.NATR(high, low, close)
        df['TRANGE'] = talib.TRANGE(high, low, close)
        
        # Volume Indicators
        df['AD'] = talib.AD(high, low, close, volume)
        df['ADOSC'] = talib.ADOSC(high, low, close, volume)
        
        # Cycle Indicators - handle multi-dimensional returns
        try:
            ht_dcperiod = talib.HT_DCPERIOD(close)
            df['HT_DCPERIOD'] = ht_dcperiod if hasattr(ht_dcperiod, '__len__') and len(ht_dcperiod.shape) == 1 else ht_dcperiod
        except Exception as e:
            log_message(f"HT_DCPERIOD calculation failed: {e}", level="DEBUG")
            df['HT_DCPERIOD'] = pd.Series(20.0, index=df.index)
            
        try:
            ht_dcphase = talib.HT_DCPHASE(close)
            df['HT_DCPHASE'] = ht_dcphase if hasattr(ht_dcphase, '__len__') and len(ht_dcphase.shape) == 1 else ht_dcphase
        except Exception as e:
            log_message(f"HT_DCPHASE calculation failed: {e}", level="DEBUG")
            df['HT_DCPHASE'] = pd.Series(0.0, index=df.index)
            
        try:
            ht_phasor = talib.HT_PHASOR(close)
            if isinstance(ht_phasor, tuple) and len(ht_phasor) == 2:
                inphase, quad = ht_phasor
                df['HT_PHASOR_INPHASE'] = inphase if hasattr(inphase, '__len__') and len(inphase.shape) == 1 else inphase
                df['HT_PHASOR_QUAD'] = quad if hasattr(quad, '__len__') and len(quad.shape) == 1 else quad
            else:
                df['HT_PHASOR_INPHASE'] = pd.Series(0.0, index=df.index)
                df['HT_PHASOR_QUAD'] = pd.Series(0.0, index=df.index)
        except Exception as e:
            log_message(f"HT_PHASOR calculation failed: {e}", level="DEBUG")
            df['HT_PHASOR_INPHASE'] = pd.Series(0.0, index=df.index)
            df['HT_PHASOR_QUAD'] = pd.Series(0.0, index=df.index)
            
        try:
            ht_sine = talib.HT_SINE(close)
            if isinstance(ht_sine, tuple) and len(ht_sine) == 2:
                sine, lead = ht_sine
                df['HT_SINE_SINE'] = sine if hasattr(sine, '__len__') and len(sine.shape) == 1 else sine
                df['HT_SINE_LEAD'] = lead if hasattr(lead, '__len__') and len(lead.shape) == 1 else lead
            else:
                df['HT_SINE_SINE'] = pd.Series(0.0, index=df.index)
                df['HT_SINE_LEAD'] = pd.Series(0.0, index=df.index)
        except Exception as e:
            log_message(f"HT_SINE calculation failed: {e}", level="DEBUG")
            df['HT_SINE_SINE'] = pd.Series(0.0, index=df.index)
            df['HT_SINE_LEAD'] = pd.Series(0.0, index=df.index)
            
        try:
            ht_trendmode = talib.HT_TRENDMODE(close)
            df['HT_TRENDMODE'] = ht_trendmode if hasattr(ht_trendmode, '__len__') and len(ht_trendmode.shape) == 1 else ht_trendmode
        except Exception as e:
            log_message(f"HT_TRENDMODE calculation failed: {e}", level="DEBUG")
            df['HT_TRENDMODE'] = pd.Series(1.0, index=df.index)
        
        # Price Transform
        df['AVGPRICE'] = talib.AVGPRICE(df['open'].values, high, low, close)
        df['MEDPRICE'] = talib.MEDPRICE(high, low)
        df['TYPPRICE'] = talib.TYPPRICE(high, low, close)
        df['WCLPRICE'] = talib.WCLPRICE(high, low, close)
        
        # Statistical Functions
        df['BETA'] = talib.BETA(high, low)
        df['CORREL'] = talib.CORREL(high, low)
        df['LINEARREG'] = talib.LINEARREG(close)
        df['LINEARREG_ANGLE'] = talib.LINEARREG_ANGLE(close)
        df['LINEARREG_INTERCEPT'] = talib.LINEARREG_INTERCEPT(close)
        df['LINEARREG_SLOPE'] = talib.LINEARREG_SLOPE(close)
        df['STDDEV'] = talib.STDDEV(close)
        df['TSF'] = talib.TSF(close)
        df['VAR'] = talib.VAR(close)
        
        log_message("Advanced technical indicators calculated successfully")
        return df
        
    except Exception as e:
        log_message(f"Error calculating advanced indicators: {e}")
        return df

def calculate_technical_targets(df, current_price, signal_direction, precision, vp=None, fvg_data=None):
    """
    Institutional target identification using Market Structure and Liquidity.
    Prioritizes Volume Profile (POC/VAH/VAL) and Unfilled FVGs over simple ATR.
    """
    try:
        atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else current_price * 0.02
        adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 20
        
        # Base targets (ATR-based)
        tp_scale_mult = 1.3 if adx > 30 else 0.8 if adx < 20 else 1.0
        
        # Primary exit logic: Look for Liquidity Clusters
        liquidity_targets = []
        
        if vp:
            # Add POC (Point of Control) and VAH/VAL as potential magnetic targets
            poc = vp.get('poc', 0)
            vah = vp.get('vah', 0)
            val = vp.get('val', 0)
            
            for lvl in [poc, vah, val]:
                if lvl == 0: continue
                # Is this level in the right direction?
                if signal_direction.upper() in ['LONG', 'BUY'] and lvl > current_price:
                    liquidity_targets.append(lvl)
                elif signal_direction.upper() not in ['LONG', 'BUY'] and lvl < current_price:
                    liquidity_targets.append(lvl)
        
        if fvg_data:
            # Add unfilled FVGs as magnetic targets (liquidity voids)
            for fvg in fvg_data.get('unfilled_fvgs', []):
                mid = (fvg['top'] + fvg['bottom']) / 2
                if signal_direction.upper() in ['LONG', 'BUY'] and mid > current_price:
                    liquidity_targets.append(mid)
                elif signal_direction.upper() not in ['LONG', 'BUY'] and mid < current_price:
                    liquidity_targets.append(mid)
        
        # Sort and deduplicate
        liquidity_targets = sorted(list(set(liquidity_targets)), reverse=(signal_direction.upper() not in ['LONG', 'BUY']))
        
        # Final TP extraction
        final_tps = []
        # Take the top 2 liquidity zones if they exist
        for lt in liquidity_targets[:2]:
            if abs(lt - current_price) / current_price > 0.005: # At least 0.5% move
                final_tps.append(lt)
        
        # Fill remaining with ATR-based targets
        if signal_direction.upper() in ['LONG', 'BUY']:
            while len(final_tps) < 5:
                # Add incremental ATR steps starting from the last TP
                last_tp = final_tps[-1] if final_tps else current_price
                final_tps.append(last_tp + (atr * 1.5 * tp_scale_mult))
            sl = current_price - (atr * (2.0 if adx > 20 else 1.5))
        else:
            while len(final_tps) < 5:
                last_tp = final_tps[-1] if final_tps else current_price
                final_tps.append(last_tp - (atr * 1.5 * tp_scale_mult))
            sl = current_price + (atr * (2.0 if adx > 20 else 1.5))
            
        targets = [round(t, precision) for t in sorted(final_tps, reverse=(signal_direction.upper() not in ['LONG', 'BUY']))]
        stop_loss = round(sl, precision)
        
        return targets, stop_loss
    except Exception as e:
        log_message(f"Error calculating liquidity targets: {e}")
        # Full fallback to simple ATR
        if signal_direction.upper() in ['LONG', 'BUY']:
            return [round(current_price * (1 + 0.02*i), precision) for i in range(1, 6)], round(current_price * 0.98, precision)
        else:
            return [round(current_price * (1 - 0.02*i), precision) for i in range(1, 6)], round(current_price * 1.02, precision)

