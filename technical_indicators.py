import pandas as pd
import numpy as np
import talib
from utils_logger import log_message

# Rust acceleration
try:
    from shared_state import RUST_CORE_AVAILABLE
    if RUST_CORE_AVAILABLE:
        import aladdin_core
except Exception:
    RUST_CORE_AVAILABLE = False

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
    """Calculate VWAP with daily reset at 00:00 UTC (institutional standard).
    Falls back to session-cumulative if index has no timezone info.
    """
    try:
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            day_group = df.index.normalize()
        elif hasattr(df.index, 'date'):
            day_group = pd.DatetimeIndex(df.index).normalize()
        else:
            # No datetime index — fall back to simple cumulative
            df['Cumulative Volume'] = df['volume'].cumsum()
            df['Cumulative Volume Price'] = (df['close'] * df['volume']).cumsum()
            df['VWAP'] = df['Cumulative Volume Price'] / df['Cumulative Volume']
            return df

        typical_price = (df['high'] + df['low'] + df['close']) / 3
        tp_vol = typical_price * df['volume']

        df['VWAP'] = (
            tp_vol.groupby(day_group).cumsum()
            / df['volume'].groupby(day_group).cumsum()
        )
    except Exception:
        # Safe fallback: cumulative (old behaviour)
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
            # Validate data before sending to Rust
            if len(df) < period:
                log_message(f"Insufficient data for ATR calculation: {len(df)} < {period}")
                df['ATR'] = np.zeros(len(df))
                return df
                
            # Clean and validate data
            high = df['high'].ffill().tolist()
            low = df['low'].ffill().tolist()
            close = df['close'].ffill().tolist()
            
            # Ensure no NaN or infinite values
            high = [float(x) if not (np.isnan(x) or np.isinf(x)) else 0.0 for x in high]
            low = [float(x) if not (np.isnan(x) or np.isinf(x)) else 0.0 for x in low]
            close = [float(x) if not (np.isnan(x) or np.isinf(x)) else 0.0 for x in close]
            
            atr_values = aladdin_core.calculate_atr_rust(high, low, close, period)
            if atr_values and len(atr_values) == len(df):
                df['ATR'] = atr_values
                return df
            else:
                log_message("Rust ATR returned invalid data, using talib fallback")
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
    """Calculate Ichimoku Cloud with Rust acceleration when available"""
    try:
        if RUST_CORE_AVAILABLE:
            high = df['high'].ffill().tolist()
            low  = df['low'].ffill().tolist()
            tenkan, kijun, span_a, span_b = aladdin_core.calculate_ichimoku_rust(high, low)
            df['tenkan_sen']   = tenkan
            df['kijun_sen']    = kijun
            df['senkou_span_a'] = span_a
            df['senkou_span_b'] = span_b
            return df
    except Exception as e:
        log_message(f"Rust Ichimoku unavailable, using pandas fallback: {e}")

    # Pandas fallback
    nine_period_high = df['high'].rolling(window=9).max()
    nine_period_low = df['low'].rolling(window=9).min()
    df['tenkan_sen'] = (nine_period_high + nine_period_low) / 2

    twenty_six_period_high = df['high'].rolling(window=26).max()
    twenty_six_period_low = df['low'].rolling(window=26).min()
    df['kijun_sen'] = (twenty_six_period_high + twenty_six_period_low) / 2

    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)

    fifty_two_period_high = df['high'].rolling(window=52).max()
    fifty_two_period_low = df['low'].rolling(window=52).min()
    df['senkou_span_b'] = ((fifty_two_period_high + fifty_two_period_low) / 2).shift(26)

    return df

def calculate_chandelier_exit(df, atr_period=22, mult=3.0, lookback=None):
    """
    Chandelier Exit Hybrid (ATR-based trailing stop indicator)
    Adapted from CE Pro Hybrid PineScript logic.

    `lookback` controls the highest-high / lowest-low window; when None it
    defaults to `atr_period` (legacy behaviour). Pine CE Hybrid uses distinct
    values (Line: ATR=22, Look=14 ; Cloud: ATR=14, Look=28) — see reverse_hunt.py.
    """
    if lookback is None:
        lookback = atr_period
    try:
        if 'ATR' not in df.columns:
            high = df['high'].values
            low = df['low'].values
            close_prices = df['close'].values
            atr = talib.ATR(high, low, close_prices, timeperiod=atr_period)
        else:
            atr = df['ATR'].values

        # ── Rust fast path ──────────────────────────────────────────────────
        if RUST_CORE_AVAILABLE and not np.all(np.isnan(atr)):
            try:
                long_stop, short_stop, direction = aladdin_core.calculate_chandelier_exit_rust(
                    df['high'].tolist(),
                    df['low'].tolist(),
                    df['close'].tolist(),
                    atr.tolist(),
                    lookback,   # Rust `period` only drives rolling HH/LL; ATR is pre-computed
                    mult,
                )
                df['CE_Long_Stop']  = long_stop
                df['CE_Short_Stop'] = short_stop
                df['CE_Direction']  = direction
                return df
            except Exception as e:
                log_message(f"Rust Chandelier Exit fallback: {e}")

        # Calculate raw Highest High and Lowest Low
        highest_high = df['high'].rolling(window=lookback).max().values
        lowest_low = df['low'].rolling(window=lookback).min().values
        
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

def calculate_chandelier_exit_cloud(df, cloud_atr_period=50, cloud_mult=5.0, cloud_lookback=None):
    """
    Chandelier Exit — Cloud (Trend) Layer.
    Ported from 'CE Pro Hybrid' PineScript by ChartArchitect_Gemini.

    Runs a second, slower CE calculation on top of the existing Line layer so the
    bot has a macro trend filter:
      - CE_Cloud_Direction  : +1 (bull) / -1 (bear)  — macro trend
      - CE_Cloud_Long_Stop  : slow long trailing stop
      - CE_Cloud_Short_Stop : slow short trailing stop
      - CE_Break_Sup        : True when line-layer was bull but close breaks below lStop
      - CE_Break_Res        : True when line-layer was bear but close breaks above sStop

    Must be called AFTER calculate_chandelier_exit() so CE_Direction / CE_Long_Stop /
    CE_Short_Stop are already present.
    """
    if cloud_lookback is None:
        cloud_lookback = cloud_atr_period
    try:
        n = len(df)
        high   = df['high'].values
        low    = df['low'].values
        close  = df['close'].values

        # ── ATR for cloud layer (independent of Line ATR) ─────────────────────
        try:
            cloud_atr = talib.ATR(high, low, close, timeperiod=cloud_atr_period)
        except Exception:
            cloud_atr = df['ATR'].values if 'ATR' in df.columns else np.full(n, np.nan)

        # ── Rust fast path ─────────────────────────────────────────────────────
        if RUST_CORE_AVAILABLE and not np.all(np.isnan(cloud_atr)):
            try:
                cl_long, cl_short, cl_dir = aladdin_core.calculate_chandelier_exit_rust(
                    high.tolist(), low.tolist(), close.tolist(),
                    cloud_atr.tolist(), cloud_lookback, cloud_mult,
                )
                df['CE_Cloud_Direction']  = [int(d) for d in cl_dir]
                df['CE_Cloud_Long_Stop']  = cl_long
                df['CE_Cloud_Short_Stop'] = cl_short
            except Exception as e:
                log_message(f"Rust CE cloud fallback: {e}")
                df['CE_Cloud_Direction']  = 0
                df['CE_Cloud_Long_Stop']  = low
                df['CE_Cloud_Short_Stop'] = high
        else:
            # Pure-Python fallback ── same ratchet logic as calculate_chandelier_exit
            hh       = np.array([np.nanmax(high[max(0, i - cloud_lookback):i + 1])  for i in range(n)])
            ll       = np.array([np.nanmin(low[max(0,  i - cloud_lookback):i + 1])  for i in range(n)])
            long_raw  = ll  - cloud_atr * cloud_mult
            short_raw = hh  + cloud_atr * cloud_mult

            cl_long_arr  = np.full(n, np.nan)
            cl_short_arr = np.full(n, np.nan)
            cl_dir_arr   = np.zeros(n, dtype=int)
            l_s, s_s, d = 0.0, 0.0, 1

            for i in range(1, n):
                if np.isnan(long_raw[i]) or np.isnan(short_raw[i]):
                    cl_long_arr[i] = l_s; cl_short_arr[i] = s_s; cl_dir_arr[i] = d
                    continue
                pl = l_s if not np.isnan(l_s) else long_raw[i]
                ps = s_s if not np.isnan(s_s) else short_raw[i]
                l_s = max(long_raw[i], pl)  if close[i-1] > pl else long_raw[i]
                s_s = min(short_raw[i], ps) if close[i-1] < ps else short_raw[i]
                if   close[i-1] > ps: d = 1
                elif close[i-1] < pl: d = -1
                cl_long_arr[i] = l_s; cl_short_arr[i] = s_s; cl_dir_arr[i] = d

            df['CE_Cloud_Direction']  = cl_dir_arr
            df['CE_Cloud_Long_Stop']  = cl_long_arr
            df['CE_Cloud_Short_Stop'] = cl_short_arr

        # ── breakSup / breakRes marks (ported from Pine Script Hybrid) ─────────
        # Uses the LINE layer stops already present in the DataFrame.
        if 'CE_Direction' in df.columns and 'CE_Long_Stop' in df.columns:
            line_dir   = df['CE_Direction'].values
            line_lStop = df['CE_Long_Stop'].values
            line_sStop = df['CE_Short_Stop'].values

            prev_dir   = np.roll(line_dir,   1);  prev_dir[0]   = line_dir[0]
            prev_lStop = np.roll(line_lStop, 1);  prev_lStop[0] = line_lStop[0]
            prev_sStop = np.roll(line_sStop, 1);  prev_sStop[0] = line_sStop[0]

            df['CE_Break_Sup'] = (prev_dir == 1)  & (close < prev_lStop)
            df['CE_Break_Res'] = (prev_dir == -1) & (close > prev_sStop)
        else:
            df['CE_Break_Sup'] = False
            df['CE_Break_Res'] = False

        return df

    except Exception as e:
        log_message(f"Error in calculate_chandelier_exit_cloud: {e}")
        df['CE_Cloud_Direction']  = 0
        df['CE_Cloud_Long_Stop']  = df['low']
        df['CE_Cloud_Short_Stop'] = df['high']
        df['CE_Break_Sup']        = False
        df['CE_Break_Res']        = False
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
                    
                    # Removed per-pattern logging to reduce noise
                    
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

        current_price = float(df['close'].iloc[-1])

        # ── Rust fast path ──────────────────────────────────────────────────
        if RUST_CORE_AVAILABLE:
            try:
                gaps = aladdin_core.detect_fair_value_gaps_rust(
                    df['high'].tolist(),
                    df['low'].tolist(),
                    lookback,
                    current_price,
                    0.10,  # max 10% distance from current price
                )
                bullish  = [{'type':'bullish',  'top':g[0], 'bottom':g[1], 'strength':g[3], 'filled':False} for g in gaps if     g[2]]
                bearish  = [{'type':'bearish',  'top':g[0], 'bottom':g[1], 'strength':g[3], 'filled':False} for g in gaps if not g[2]]
                unfilled = [{'type': 'bullish' if g[2] else 'bearish', 'top':g[0], 'bottom':g[1], 'strength':g[3], 'filled':False} for g in gaps]
                log_message(f"FVGs (Rust): {len(bullish)} bullish, {len(bearish)} bearish, {len(unfilled)} unfilled")
                return {'bullish_fvgs': bullish, 'bearish_fvgs': bearish, 'unfilled_fvgs': unfilled}
            except Exception as e:
                log_message(f"Rust FVG fallback: {e}")

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

        # ── Rust fast path (Rayon-parallelized bins) ────────────────────────
        if RUST_CORE_AVAILABLE:
            try:
                bin_prices, bin_volumes, poc, vah, val = aladdin_core.calculate_volume_profile_rust(
                    df_visible['high'].tolist(),
                    df_visible['low'].tolist(),
                    df_visible['close'].tolist(),
                    df_visible['volume'].tolist(),
                    num_bins,
                )
                current_price = float(df['close'].iloc[-1])
                threshold = max(bin_volumes) * 0.3 if bin_volumes else 0
                support    = sorted([p for p, v in zip(bin_prices, bin_volumes) if v >= threshold and p < current_price], reverse=True)
                resistance = sorted([p for p, v in zip(bin_prices, bin_volumes) if v >= threshold and p > current_price])
                log_message(f"Volume Profile (Rust): POC={poc:.6f}, VAH={vah:.6f}, VAL={val:.6f}")
                return {
                    'price_levels': bin_prices, 'volumes': bin_volumes,
                    'poc': poc, 'vah': vah, 'val': val,
                    'support_levels': support, 'resistance_levels': resistance,
                }
            except Exception as e:
                log_message(f"Rust Volume Profile fallback: {e}")
        
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
        
        # Momentum Indicators — skip if already injected by Rust batch processor
        if 'RSI_14' not in df.columns:
            df['RSI_14'] = talib.RSI(close, timeperiod=14)
        if 'RSI_21' not in df.columns:
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

    Target spacing (ATR-based): TP1 ≈ 1.5×ATR, TP2 ≈ 3×ATR, TP3 ≈ 5×ATR
    Liquidity levels (VP/FVG) replace ATR targets when they fall within range.
    Max distance cap: 10% from entry for any single target.
    """
    try:
        atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else current_price * 0.02

        # ADX for trend strength — compute inline if not present
        if 'ADX' in df.columns:
            adx = float(df['ADX'].iloc[-1])
        else:
            try:
                adx = float(talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)[-1])
            except Exception:
                adx = 20.0
        if np.isnan(adx):
            adx = 20.0

        # Trending markets → stretch targets; ranging → tighter targets
        tp_scale_mult = 1.3 if adx > 30 else 0.8 if adx < 20 else 1.0

        is_long = signal_direction.upper() in ['LONG', 'BUY']
        max_dist = current_price * 0.10  # 10% max distance cap

        # ── Collect liquidity magnets (VP + FVG) ────────────────────────────
        liquidity_targets = []

        if vp:
            for lvl in [vp.get('poc', 0), vp.get('vah', 0), vp.get('val', 0)]:
                if lvl == 0:
                    continue
                if is_long and lvl > current_price:
                    liquidity_targets.append(lvl)
                elif not is_long and lvl < current_price:
                    liquidity_targets.append(lvl)

        if fvg_data:
            for fvg in fvg_data.get('unfilled_fvgs', []):
                mid = (fvg['top'] + fvg['bottom']) / 2
                if is_long and mid > current_price:
                    liquidity_targets.append(mid)
                elif not is_long and mid < current_price:
                    liquidity_targets.append(mid)

        # Filter: min 0.5% away, max 10% away, then sort by distance
        liquidity_targets = [
            t for t in liquidity_targets
            if 0.005 < abs(t - current_price) / current_price <= 0.10
        ]
        liquidity_targets.sort(key=lambda t: abs(t - current_price))

        # ── Build 3 ATR-based default targets (evenly spaced from entry) ────
        # TP1 ≈ 1×ATR, TP2 ≈ 1.8×ATR, TP3 ≈ 3×ATR (tighter for faster turnover)
        atr_steps = [1.0, 1.8, 3.0]
        sign = 1 if is_long else -1
        atr_targets = []
        for step in atr_steps:
            offset = sign * atr * step * tp_scale_mult
            # Enforce max distance cap
            if abs(offset) > max_dist:
                offset = sign * max_dist
            atr_targets.append(current_price + offset)

        # ── Merge: liquidity replaces nearest ATR target ────────────────────
        final_tps = list(atr_targets)  # Start with ATR defaults

        for lt in liquidity_targets[:3]:
            # Find the ATR target closest in distance to this liquidity level
            best_idx = min(range(len(final_tps)), key=lambda i: abs(final_tps[i] - lt))
            # Replace only if the liquidity level is on the correct side
            if is_long and lt > current_price:
                final_tps[best_idx] = lt
            elif not is_long and lt < current_price:
                final_tps[best_idx] = lt

        # Deduplicate and ensure correct ordering
        final_tps = sorted(set(final_tps), reverse=(not is_long))

        # Pad back to 3 if dedup removed any (rare edge case)
        while len(final_tps) < 3:
            last = final_tps[-1] if final_tps else current_price
            final_tps.append(last + sign * atr * 1.5 * tp_scale_mult)

        # Stop loss (CE stop overrides this in main.py, but provide a sensible default)
        sl = current_price - sign * atr * (2.0 if adx > 20 else 1.5)

        targets = [round(t, precision) for t in final_tps[:5]]
        stop_loss = round(sl, precision)

        return targets, stop_loss
    except Exception as e:
        log_message(f"Error calculating liquidity targets: {e}")
        # Full fallback to simple ATR
        if signal_direction.upper() in ['LONG', 'BUY']:
            return [round(current_price * (1 + 0.02*i), precision) for i in range(1, 4)], round(current_price * 0.98, precision)
        else:
            return [round(current_price * (1 - 0.02*i), precision) for i in range(1, 4)], round(current_price * 1.02, precision)


def calculate_tsi(df, long_period=25, short_period=13, signal_period=7):
    """
    True Strength Index (TSI) — ported from REVERSE HUNT [MTF] Pine Script.
    Double-smoothed momentum: cleaner than MACD, fewer false crossovers.

    Formula:
        pc  = close.diff()
        TSI = 100 × EMA(EMA(pc, long), short) / EMA(EMA(|pc|, long), short)

    Adds columns: TSI, TSI_Signal, TSI_Hist
    """
    try:
        close = df['close']
        pc    = close.diff()

        double_smooth     = pc.ewm(span=long_period,  adjust=False).mean() \
                              .ewm(span=short_period, adjust=False).mean()
        double_smooth_abs = pc.abs().ewm(span=long_period,  adjust=False).mean() \
                                    .ewm(span=short_period, adjust=False).mean()

        tsi = 100 * double_smooth / double_smooth_abs.replace(0, np.nan)
        tsi_signal = tsi.ewm(span=signal_period, adjust=False).mean()

        df['TSI']       = tsi
        df['TSI_Signal']= tsi_signal
        df['TSI_Hist']  = tsi - tsi_signal
    except Exception as e:
        log_message(f"calculate_tsi error: {e}")
        df['TSI']        = 0.0
        df['TSI_Signal'] = 0.0
        df['TSI_Hist']   = 0.0
    return df


def calculate_lr_oscillator(df, reg_len=20, norm_len=100, smooth=1, invert=True):
    """
    Normalized Linear Regression Oscillator — ported from REVERSE HUNT [MTF].
    Measures slope direction normalized as Z-score → range approx [-3, +3].

    Adds columns: LR_Osc  (normalized, optionally inverted)
                  LR_Raw  (raw slope value)
    """
    try:
        closes = df['close'].values
        n      = len(closes)
        reg_n  = reg_len
        slopes = np.full(n, np.nan)

        # Rolling linear regression slope
        x = np.arange(reg_n, dtype=float)
        x_mean = x.mean()
        x_var  = ((x - x_mean) ** 2).sum()
        for i in range(reg_n - 1, n):
            y       = closes[i - reg_n + 1: i + 1]
            y_mean  = y.mean()
            slopes[i] = ((x - x_mean) * (y - y_mean)).sum() / x_var

        slope_series = pd.Series(slopes, index=df.index)
        if invert:
            slope_series = -slope_series

        # Z-score normalization over norm_len window
        sma_   = slope_series.rolling(norm_len, min_periods=1).mean()
        std_   = slope_series.rolling(norm_len, min_periods=1).std().replace(0, np.nan)
        norm   = (slope_series - sma_) / std_

        if smooth > 1:
            norm = norm.ewm(span=smooth, adjust=False).mean()

        df['LR_Osc'] = norm
        df['LR_Raw'] = slope_series
    except Exception as e:
        log_message(f"calculate_lr_oscillator error: {e}")
        df['LR_Osc'] = 0.0
        df['LR_Raw'] = 0.0
    return df


def detect_breakout_retest(df, lookback=50, tolerance_pct=0.015):
    """
    Detect breakout + retest patterns on OHLCV data.

    Logic:
    1. Find swing highs/lows over `lookback` candles (key S/R levels)
    2. Detect if price broke above a resistance (bullish breakout) or
       below a support (bearish breakout) in the last 10 candles
    3. Check if current price is retesting that broken level (within tolerance%)

    Returns dict with:
      breakout_score : +1.0 (bullish retest = long entry)
                       -1.0 (bearish retest = short entry)
                        0.0 (no pattern detected)
      level         : price level being retested (or None)
      breakout_type : 'BULLISH_RETEST' | 'BEARISH_RETEST' | 'NONE'
      channel_slope : linear regression slope of price (positive=uptrend channel,
                      negative=downtrend channel)
    """
    result = {
        'breakout_score': 0.0,
        'level': None,
        'breakout_type': 'NONE',
        'channel_slope': 0.0,
        'channel_position': 0.0,  # +1=near upper, -1=near lower, 0=middle
    }
    try:
        if df is None or len(df) < max(lookback, 20):
            return result

        highs  = df['high'].values
        lows   = df['low'].values
        closes = df['close'].values
        n      = len(closes)

        # ── Channel detection via linear regression on highs and lows ────
        x = np.arange(lookback)
        h_slice = highs[-lookback:]
        l_slice = lows[-lookback:]
        c_slice = closes[-lookback:]

        h_slope, h_intercept = np.polyfit(x, h_slice, 1)
        l_slope, l_intercept = np.polyfit(x, l_slice, 1)
        avg_slope = (h_slope + l_slope) / 2.0
        # Normalize slope relative to average price
        avg_price = np.mean(c_slice)
        result['channel_slope'] = float(avg_slope / avg_price) if avg_price > 0 else 0.0

        # Channel position: where is current price relative to channel
        upper_now = h_slope * (lookback - 1) + h_intercept
        lower_now = l_slope * (lookback - 1) + l_intercept
        cur_price = float(closes[-1])
        channel_range = upper_now - lower_now
        if channel_range > 0:
            pos = (cur_price - lower_now) / channel_range  # 0=lower, 1=upper
            result['channel_position'] = float(np.clip(pos * 2 - 1, -1, 1))  # scale to [-1,+1]

        # ── Swing high/low identification ─────────────────────────────────
        # A swing high: local max over 5-candle window
        # A swing low:  local min over 5-candle window
        swing_window = 5
        swing_highs, swing_lows = [], []
        for i in range(swing_window, n - swing_window):
            if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                swing_highs.append((i, highs[i]))
            if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                swing_lows.append((i, lows[i]))

        if not swing_highs and not swing_lows:
            return result

        # ── Breakout detection window: last 3-15 candles ─────────────────
        breakout_window = 15
        recent_start    = n - breakout_window

        # BULLISH BREAKOUT: price closed above a recent swing high
        # then came back to retest it from above
        for idx, level in reversed(swing_highs):
            if idx >= recent_start:
                continue   # level must be established BEFORE breakout window
            if idx < n - lookback:
                continue   # too old
            # Check if any candle in breakout window closed above this level
            broke_above = any(closes[j] > level * 1.002 for j in range(recent_start, n - 1))
            if not broke_above:
                continue
            # Check if current price is retesting the level (within tolerance)
            dist_pct = abs(cur_price - level) / level
            if dist_pct <= tolerance_pct:
                # Confirm: price approached from above (retest, not breakdown)
                if cur_price >= level * (1 - tolerance_pct * 0.5):
                    result['breakout_score'] = 1.0
                    result['level']          = float(level)
                    result['breakout_type']  = 'BULLISH_RETEST'
                    return result

        # BEARISH BREAKOUT: price closed below a recent swing low
        # then came back to retest it from below
        for idx, level in reversed(swing_lows):
            if idx >= recent_start:
                continue
            if idx < n - lookback:
                continue
            broke_below = any(closes[j] < level * 0.998 for j in range(recent_start, n - 1))
            if not broke_below:
                continue
            dist_pct = abs(cur_price - level) / level
            if dist_pct <= tolerance_pct:
                if cur_price <= level * (1 + tolerance_pct * 0.5):
                    result['breakout_score'] = -1.0
                    result['level']          = float(level)
                    result['breakout_type']  = 'BEARISH_RETEST'
                    return result

    except Exception as e:
        log_message(f"detect_breakout_retest error: {e}")

    return result

