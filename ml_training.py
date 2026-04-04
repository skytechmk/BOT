import pandas as pd
import numpy as np
import xgboost as xgb
import torch
import os
import time
from joblib import dump, load
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from utils_logger import log_message
from constants import *
from shared_state import *
from technical_indicators import *
from data_fetcher import fetch_data, analyze_funding_rate_sentiment, get_funding_rate_history
from trading_utilities import generate_market_summary
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Lazy-loaded transformer components for sentiment analysis
_TOKENIZER = None
_TRANSFORMER_MODEL = None

def prepare_ml_features(df):
    """Prepare comprehensive features for machine learning models with optimized NaN handling"""
    try:
        # Use dictionary to collect all features first, then create DataFrame once
        feature_dict = {}
        
        # Basic OHLCV features
        feature_dict['open'] = df['open']
        feature_dict['high'] = df['high']
        feature_dict['low'] = df['low']
        feature_dict['close'] = df['close']
        feature_dict['volume'] = df['volume']
        
        # Price action features
        feature_dict['returns'] = df['close'].pct_change()
        feature_dict['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        feature_dict['volatility_5'] = df['close'].rolling(5).std()
        feature_dict['volatility_10'] = df['close'].rolling(10).std()
        feature_dict['volatility_20'] = df['close'].rolling(20).std()
        feature_dict['price_change_1'] = df['close'].pct_change(1)
        feature_dict['price_change_3'] = df['close'].pct_change(3)
        feature_dict['price_change_5'] = df['close'].pct_change(5)
        feature_dict['price_change_10'] = df['close'].pct_change(10)
        feature_dict['volume_ratio_5'] = df['volume'] / df['volume'].rolling(5).mean()
        feature_dict['volume_ratio_10'] = df['volume'] / df['volume'].rolling(10).mean()
        feature_dict['volume_ratio_20'] = df['volume'] / df['volume'].rolling(20).mean()
        
        # High-Low features
        feature_dict['hl_ratio'] = df['high'] / df['low']
        feature_dict['oc_ratio'] = df['open'] / df['close']
        feature_dict['body_size'] = abs(df['close'] - df['open']) / df['close']
        feature_dict['upper_shadow'] = (df['high'] - np.maximum(df['open'], df['close'])) / df['close']
        feature_dict['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / df['close']
        
        # Always ensure we have all advanced indicators calculated first
        if 'RSI_14' not in df.columns:
            # If advanced indicators are missing, calculate them
            df = calculate_advanced_indicators(df)
        
        # Technical indicators from advanced calculation (ensure all features are included)
        # Momentum indicators - always include with fallback values
        feature_dict['rsi_14'] = df.get('RSI_14', pd.Series(50.0, index=df.index))
        feature_dict['rsi_21'] = df.get('RSI_21', pd.Series(50.0, index=df.index))
        feature_dict['stoch_k'] = df.get('STOCH_K', pd.Series(50.0, index=df.index))
        feature_dict['stoch_d'] = df.get('STOCH_D', pd.Series(50.0, index=df.index))
        feature_dict['stochf_k'] = df.get('STOCHF_K', pd.Series(50.0, index=df.index))
        feature_dict['stochf_d'] = df.get('STOCHF_D', pd.Series(50.0, index=df.index))
        feature_dict['stochrsi_k'] = df.get('STOCHRSI_K', pd.Series(50.0, index=df.index))
        feature_dict['stochrsi_d'] = df.get('STOCHRSI_D', pd.Series(50.0, index=df.index))
        feature_dict['willr'] = df.get('WILLR', pd.Series(-50.0, index=df.index))
        feature_dict['roc_10'] = df.get('ROC_10', pd.Series(0.0, index=df.index))
        feature_dict['roc_20'] = df.get('ROC_20', pd.Series(0.0, index=df.index))
        feature_dict['mom_10'] = df.get('MOM_10', pd.Series(0.0, index=df.index))
        feature_dict['mom_20'] = df.get('MOM_20', pd.Series(0.0, index=df.index))
        feature_dict['cci_14'] = df.get('CCI_14', pd.Series(0.0, index=df.index))
        feature_dict['cci_20'] = df.get('CCI_20', pd.Series(0.0, index=df.index))
        feature_dict['cmo'] = df.get('CMO', pd.Series(0.0, index=df.index))
        feature_dict['adx'] = df.get('ADX', pd.Series(25.0, index=df.index))
        feature_dict['adxr'] = df.get('ADXR', pd.Series(25.0, index=df.index))
        feature_dict['plus_di'] = df.get('PLUS_DI', pd.Series(25.0, index=df.index))
        feature_dict['minus_di'] = df.get('MINUS_DI', pd.Series(25.0, index=df.index))
        feature_dict['dx'] = df.get('DX', pd.Series(25.0, index=df.index))
        feature_dict['aroon_up'] = df.get('AROON_UP', pd.Series(50.0, index=df.index))
        feature_dict['aroon_down'] = df.get('AROON_DOWN', pd.Series(50.0, index=df.index))
        feature_dict['aroonosc'] = df.get('AROONOSC', pd.Series(0.0, index=df.index))
        feature_dict['bop'] = df.get('BOP', pd.Series(0.0, index=df.index))
        feature_dict['mfi'] = df.get('MFI', pd.Series(50.0, index=df.index))
        feature_dict['ppo'] = df.get('PPO', pd.Series(0.0, index=df.index))
        feature_dict['trix'] = df.get('TRIX', pd.Series(0.0, index=df.index))
        feature_dict['ultosc'] = df.get('ULTOSC', pd.Series(50.0, index=df.index))
        
        # Moving averages - always include all periods including EMA 80
        for period in [5, 10, 20, 50, 80, 100, 200]:
            sma_col = f'SMA_{period}'
            ema_col = f'EMA_{period}'
            if period != 80:  # SMA 80 is not calculated, only EMA 80
                feature_dict[f'sma_{period}'] = df.get(sma_col, df['close'])
            feature_dict[f'ema_{period}'] = df.get(ema_col, df['close'])
        
        # Other moving averages - always include with fallbacks
        feature_dict['wma_20'] = df.get('WMA_20', df['close'])
        feature_dict['dema'] = df.get('DEMA', df['close'])
        feature_dict['tema'] = df.get('TEMA', df['close'])
        feature_dict['trima'] = df.get('TRIMA', df['close'])
        feature_dict['kama'] = df.get('KAMA', df['close'])
        feature_dict['mama'] = df.get('MAMA', df['close'])
        feature_dict['fama'] = df.get('FAMA', df['close'])
        feature_dict['t3'] = df.get('T3', df['close'])
        feature_dict['ht_trendline'] = df.get('HT_TRENDLINE', df['close'])
        
        # Volatility indicators - always include
        if 'ATR' in df.columns:
            feature_dict['atr'] = df['ATR']
        else:
            feature_dict['atr'] = pd.Series(df['high'] - df['low'], index=df.index)
        feature_dict['natr'] = df.get('NATR', pd.Series(1.0, index=df.index))
        feature_dict['trange'] = df.get('TRANGE', df['high'] - df['low'])
        
        # Volume indicators - always include
        feature_dict['ad'] = df.get('AD', df['volume'].cumsum())
        feature_dict['adosc'] = df.get('ADOSC', pd.Series(0.0, index=df.index))
        
        # OBV with enhanced error handling
        try:
            obv_values = talib.OBV(df['close'].values, df['volume'].values)
            # Handle multi-dimensional arrays more robustly
            if hasattr(obv_values, 'shape'):
                if len(obv_values.shape) > 1:
                    # Multi-dimensional - take first column and flatten
                    if obv_values.shape[1] > 0:
                        obv_values = obv_values[:, 0]
                    obv_values = np.asarray(obv_values).flatten()
                else:
                    # Already 1D but ensure it's flattened
                    obv_values = np.asarray(obv_values).flatten()
            else:
                # Convert to numpy array and flatten
                obv_values = np.asarray(obv_values).flatten()
            
            # Ensure we have the right length
            if len(obv_values) == len(df):
                feature_dict['obv'] = pd.Series(obv_values, index=df.index)
            elif len(obv_values) > len(df):
                # Truncate to match DataFrame length
                feature_dict['obv'] = pd.Series(obv_values[:len(df)], index=df.index)
            else:
                # Pad with last value to match DataFrame length
                padded_obv = np.concatenate([
                    obv_values, 
                    np.full(len(df) - len(obv_values), obv_values[-1] if len(obv_values) > 0 else 0)
                ])
                feature_dict['obv'] = pd.Series(padded_obv, index=df.index)
        except Exception as e:
            log_message(f"OBV calculation error: {e}")
            feature_dict['obv'] = df['volume'].cumsum()
        
        # Cycle indicators - always include with proper handling of multi-dimensional arrays
        def safe_get_series(col_name, default_val):
            if col_name in df.columns:
                col_data = df[col_name]
                try:
                    # Convert to numpy array first for consistent handling
                    if hasattr(col_data, 'values'):
                        array_data = col_data.values
                    else:
                        array_data = np.array(col_data)
                    
                    # Handle different array shapes
                    if array_data.ndim > 1:
                        # Multi-dimensional array - take first column and flatten
                        if array_data.shape[1] > 0:
                            flat_data = array_data[:, 0].flatten()
                        else:
                            flat_data = array_data.flatten()
                    elif array_data.ndim == 1:
                        # 1D array - use as is
                        flat_data = array_data.flatten()
                    else:
                        # 0D array (scalar) - broadcast to all rows
                        flat_data = np.full(len(df.index), array_data.item())
                    
                    # Ensure we have the right length
                    if len(flat_data) >= len(df.index):
                        return pd.Series(flat_data[:len(df.index)], index=df.index)
                    else:
                        # Pad with default values if too short
                        padded_data = np.concatenate([
                            flat_data, 
                            np.full(len(df.index) - len(flat_data), default_val)
                        ])
                        return pd.Series(padded_data, index=df.index)
                    
                except Exception as e:
                    log_message(f"Error processing {col_name}: {e}, using default")
                    return pd.Series(default_val, index=df.index)
            return pd.Series(default_val, index=df.index)
        
        feature_dict['ht_dcperiod'] = safe_get_series('HT_DCPERIOD', 20.0)
        feature_dict['ht_dcphase'] = safe_get_series('HT_DCPHASE', 0.0)
        feature_dict['ht_phasor_inphase'] = safe_get_series('HT_PHASOR_INPHASE', 0.0)
        feature_dict['ht_phasor_quad'] = safe_get_series('HT_PHASOR_QUAD', 0.0)
        feature_dict['ht_sine_sine'] = safe_get_series('HT_SINE_SINE', 0.0)
        feature_dict['ht_sine_lead'] = safe_get_series('HT_SINE_LEAD', 0.0)
        feature_dict['ht_trendmode'] = safe_get_series('HT_TRENDMODE', 1.0)
        
        # Price transform - always include
        feature_dict['avgprice'] = df.get('AVGPRICE', (df['open'] + df['high'] + df['low'] + df['close']) / 4)
        feature_dict['medprice'] = df.get('MEDPRICE', (df['high'] + df['low']) / 2)
        feature_dict['typprice'] = df.get('TYPPRICE', (df['high'] + df['low'] + df['close']) / 3)
        feature_dict['wclprice'] = df.get('WCLPRICE', (df['high'] + df['low'] + 2 * df['close']) / 4)
        
        # Statistical functions - always include
        feature_dict['beta'] = df.get('BETA', pd.Series(1.0, index=df.index))
        feature_dict['correl'] = df.get('CORREL', pd.Series(0.0, index=df.index))
        feature_dict['linearreg'] = df.get('LINEARREG', df['close'])
        feature_dict['linearreg_angle'] = df.get('LINEARREG_ANGLE', pd.Series(0.0, index=df.index))
        feature_dict['linearreg_intercept'] = df.get('LINEARREG_INTERCEPT', df['close'])
        feature_dict['linearreg_slope'] = df.get('LINEARREG_SLOPE', pd.Series(0.0, index=df.index))
        feature_dict['stddev'] = df.get('STDDEV', df['close'].rolling(20).std())
        feature_dict['tsf'] = df.get('TSF', df['close'])
        feature_dict['var'] = df.get('VAR', df['close'].rolling(20).var())
        
        # MACD features
        if 'MACD Line' in df.columns:
            feature_dict['macd'] = df['MACD Line']
            feature_dict['macd_signal'] = df['Signal Line']
            feature_dict['macd_histogram'] = df['MACD Histogram']
            feature_dict['macd_cross'] = (df['MACD Line'] > df['Signal Line']).astype(int)
        
        # Bollinger Bands features
        if 'Upper Band' in df.columns and 'Lower Band' in df.columns:
            bb_range = df['Upper Band'] - df['Lower Band']
            # Avoid division by zero
            bb_range_safe = bb_range.replace(0, np.nan)
            feature_dict['bb_position'] = (df['close'] - df['Lower Band']) / bb_range_safe
            if 'SMA' in df.columns:
                sma_safe = df['SMA'].replace(0, np.nan)
                feature_dict['bb_width'] = bb_range / sma_safe
            feature_dict['bb_upper_breach'] = (df['close'] > df['Upper Band']).astype(int)
            feature_dict['bb_lower_breach'] = (df['close'] < df['Lower Band']).astype(int)
        
        # VWAP features
        if 'VWAP' in df.columns:
            feature_dict['vwap'] = df['VWAP']
            vwap_safe = df['VWAP'].replace(0, np.nan)
            feature_dict['price_vs_vwap'] = df['close'] / vwap_safe
            feature_dict['above_vwap'] = (df['close'] > df['VWAP']).astype(int)
        
        # Ichimoku features - always include with fallbacks
        feature_dict['tenkan_sen'] = df.get('tenkan_sen', df['close'])
        feature_dict['kijun_sen'] = df.get('kijun_sen', df['close'])
        feature_dict['senkou_span_a'] = df.get('senkou_span_a', df['close'])
        feature_dict['senkou_span_b'] = df.get('senkou_span_b', df['close'])
        
        # Calculate tk_cross and price_vs_cloud with fallbacks
        tenkan = feature_dict['tenkan_sen']
        kijun = feature_dict['kijun_sen']
        span_a = feature_dict['senkou_span_a']
        span_b = feature_dict['senkou_span_b']
        
        feature_dict['tk_cross'] = (tenkan > kijun).astype(int)
        feature_dict['price_vs_cloud'] = np.where(
            df['close'] > np.maximum(span_a, span_b), 1,
            np.where(df['close'] < np.minimum(span_a, span_b), -1, 0)
        )
        
        # Pattern features - always include with fallbacks
        feature_dict['pattern_strength'] = df.get('Pattern_Strength', pd.Series(0, index=df.index))
        feature_dict['pattern_bullish'] = (df.get('Pattern_Type', 'Neutral') == 'Bullish').astype(int)
        feature_dict['pattern_bearish'] = (df.get('Pattern_Type', 'Neutral') == 'Bearish').astype(int)
        
        # Chandelier Exit features
        feature_dict['ce_direction'] = df.get('CE_Direction', pd.Series(0, index=df.index))
        ce_long_stop = df.get('CE_Long_Stop', df['low'])
        ce_short_stop = df.get('CE_Short_Stop', df['high'])
        feature_dict['ce_long_dist'] = (df['close'] - ce_long_stop) / df['close']
        feature_dict['ce_short_dist'] = (ce_short_stop - df['close']) / df['close']
        feature_dict['ce_long_breach'] = (df['close'] < ce_long_stop).astype(int)
        feature_dict['ce_short_breach'] = (df['close'] > ce_short_stop).astype(int)
        
        # Moving average crossovers - always include
        sma_20 = feature_dict['sma_20']
        sma_50 = feature_dict['sma_50']
        sma_200 = feature_dict['sma_200']
        ema_20 = feature_dict['ema_20']
        ema_50 = feature_dict['ema_50']
        
        feature_dict['sma_20_50_cross'] = (sma_20 > sma_50).astype(int)
        feature_dict['sma_50_200_cross'] = (sma_50 > sma_200).astype(int)
        feature_dict['ema_20_50_cross'] = (ema_20 > ema_50).astype(int)
        
        # EMA 10 and EMA 80 crossing - key feature for signal generation
        ema_10 = feature_dict['ema_10']
        ema_80 = feature_dict['ema_80']
        feature_dict['ema_10_80_cross'] = (ema_10 > ema_80).astype(int)
        
        # Price position relative to moving averages - always include
        sma_20_safe = sma_20.replace(0, np.nan).fillna(df['close'])
        sma_50_safe = sma_50.replace(0, np.nan).fillna(df['close'])
        sma_200_safe = sma_200.replace(0, np.nan).fillna(df['close'])
        ema_20_safe = ema_20.replace(0, np.nan).fillna(df['close'])
        ema_50_safe = ema_50.replace(0, np.nan).fillna(df['close'])
        
        feature_dict['price_vs_sma20'] = df['close'] / sma_20_safe
        feature_dict['price_vs_sma50'] = df['close'] / sma_50_safe
        feature_dict['price_vs_sma200'] = df['close'] / sma_200_safe
        feature_dict['price_vs_ema20'] = df['close'] / ema_20_safe
        feature_dict['price_vs_ema50'] = df['close'] / ema_50_safe
        
        # Funding Rate Analysis Features - Enhanced ML Integration
        try:
            # Extract pair symbol from DataFrame index or use a default for feature preparation
            pair_symbol = 'BTCUSDT'  # Default fallback
            if hasattr(df, 'pair_symbol'):
                pair_symbol = df.pair_symbol
            elif len(df) > 0:
                # Try to extract from any available context or use the most common pair
                pair_symbol = 'BTCUSDT'
            
            # Get funding rate analysis
            funding_analysis = analyze_funding_rate_sentiment(pair_symbol)
            
            # Core funding rate features
            feature_dict['funding_rate'] = pd.Series(funding_analysis['current_rate'], index=df.index)
            feature_dict['funding_rate_pct'] = pd.Series(funding_analysis['current_rate_pct'], index=df.index)
            feature_dict['funding_strength'] = pd.Series(funding_analysis['strength'], index=df.index)
            feature_dict['funding_confidence_adj'] = pd.Series(funding_analysis['confidence_adjustment'], index=df.index)
            
            # Funding sentiment encoding (categorical to numerical)
            sentiment_mapping = {
                'EXTREMELY_BULLISH': 1.0, 'VERY_BULLISH': 0.8, 'BULLISH': 0.6, 'SLIGHTLY_BULLISH': 0.3,
                'NEUTRAL': 0.0, 'SLIGHTLY_BEARISH': -0.3, 'BEARISH': -0.6, 'VERY_BEARISH': -0.8, 'EXTREMELY_BEARISH': -1.0
            }
            feature_dict['funding_sentiment_score'] = pd.Series(
                sentiment_mapping.get(funding_analysis['sentiment'], 0.0), index=df.index
            )
            
            # Signal bias encoding
            bias_mapping = {
                'LONG': 1.0, 'SLIGHT_LONG': 0.5, 'NONE': 0.0, 'SLIGHT_SHORT': -0.5, 'SHORT': -1.0
            }
            feature_dict['funding_signal_bias'] = pd.Series(
                bias_mapping.get(funding_analysis['signal_bias'], 0.0), index=df.index
            )
            
            # Funding trend encoding
            trend_mapping = {'INCREASING': 1.0, 'STABLE': 0.0, 'DECREASING': -1.0, 'UNKNOWN': 0.0}
            feature_dict['funding_trend'] = pd.Series(
                trend_mapping.get(funding_analysis['funding_trend'], 0.0), index=df.index
            )
            
            # Extreme funding flag
            feature_dict['funding_extreme'] = pd.Series(
                1.0 if funding_analysis['extreme_funding'] else 0.0, index=df.index
            )
            
            # Funding rate thresholds (binary features)
            current_rate = funding_analysis['current_rate']
            feature_dict['funding_very_positive'] = pd.Series(1.0 if current_rate > 0.005 else 0.0, index=df.index)
            feature_dict['funding_positive'] = pd.Series(1.0 if current_rate > 0.001 else 0.0, index=df.index)
            feature_dict['funding_slightly_positive'] = pd.Series(1.0 if current_rate > 0.0001 else 0.0, index=df.index)
            feature_dict['funding_slightly_negative'] = pd.Series(1.0 if current_rate < -0.0001 else 0.0, index=df.index)
            feature_dict['funding_negative'] = pd.Series(1.0 if current_rate < -0.001 else 0.0, index=df.index)
            feature_dict['funding_very_negative'] = pd.Series(1.0 if current_rate < -0.005 else 0.0, index=df.index)
            
            # Funding cost analysis
            funding_cost_8h = abs(current_rate) * 3  # 3 funding periods per day
            funding_cost_daily = funding_cost_8h * 100  # Convert to percentage
            feature_dict['funding_cost_daily'] = pd.Series(funding_cost_daily, index=df.index)
            feature_dict['funding_high_cost'] = pd.Series(1.0 if funding_cost_daily > 0.5 else 0.0, index=df.index)
            feature_dict['funding_extreme_cost'] = pd.Series(1.0 if funding_cost_daily > 2.0 else 0.0, index=df.index)
            
            # Funding rate interaction with price action - ALWAYS ensure both features exist
            if len(df) > 1:
                price_change_1h = df['close'].pct_change(1).iloc[-1]
                # Funding vs price momentum alignment
                if current_rate > 0 and price_change_1h > 0:
                    feature_dict['funding_price_alignment'] = pd.Series(1.0, index=df.index)  # Both bullish
                    feature_dict['funding_price_divergence'] = pd.Series(0.0, index=df.index)  # No divergence
                elif current_rate < 0 and price_change_1h < 0:
                    feature_dict['funding_price_alignment'] = pd.Series(-1.0, index=df.index)  # Both bearish
                    feature_dict['funding_price_divergence'] = pd.Series(0.0, index=df.index)  # No divergence
                elif abs(current_rate) > 0.001 and price_change_1h * current_rate < 0:
                    feature_dict['funding_price_alignment'] = pd.Series(0.0, index=df.index)  # No alignment
                    feature_dict['funding_price_divergence'] = pd.Series(1.0, index=df.index)  # Divergence signal
                else:
                    feature_dict['funding_price_alignment'] = pd.Series(0.0, index=df.index)
                    feature_dict['funding_price_divergence'] = pd.Series(0.0, index=df.index)
            else:
                feature_dict['funding_price_alignment'] = pd.Series(0.0, index=df.index)
                feature_dict['funding_price_divergence'] = pd.Series(0.0, index=df.index)
            
            # Funding rate volatility (if historical data available)
            try:
                historical_rates, _ = get_funding_rate_history(pair_symbol, limit=10)
                if len(historical_rates) >= 5:
                    import statistics
                    funding_volatility = statistics.stdev(historical_rates[:5])
                    feature_dict['funding_volatility'] = pd.Series(funding_volatility, index=df.index)
                    feature_dict['funding_high_volatility'] = pd.Series(1.0 if funding_volatility > 0.002 else 0.0, index=df.index)
                    
                    # Funding rate momentum (recent vs older average)
                    if len(historical_rates) >= 6:
                        recent_avg = sum(historical_rates[:3]) / 3
                        older_avg = sum(historical_rates[3:6]) / 3
                        funding_momentum = recent_avg - older_avg
                        feature_dict['funding_momentum'] = pd.Series(funding_momentum, index=df.index)
                        feature_dict['funding_momentum_positive'] = pd.Series(1.0 if funding_momentum > 0.001 else 0.0, index=df.index)
                        feature_dict['funding_momentum_negative'] = pd.Series(1.0 if funding_momentum < -0.001 else 0.0, index=df.index)
                    else:
                        feature_dict['funding_momentum'] = pd.Series(0.0, index=df.index)
                        feature_dict['funding_momentum_positive'] = pd.Series(0.0, index=df.index)
                        feature_dict['funding_momentum_negative'] = pd.Series(0.0, index=df.index)
                else:
                    feature_dict['funding_volatility'] = pd.Series(0.0, index=df.index)
                    feature_dict['funding_high_volatility'] = pd.Series(0.0, index=df.index)
                    feature_dict['funding_momentum'] = pd.Series(0.0, index=df.index)
                    feature_dict['funding_momentum_positive'] = pd.Series(0.0, index=df.index)
                    feature_dict['funding_momentum_negative'] = pd.Series(0.0, index=df.index)
            except Exception as e:
                log_message(f"Funding rate history error: {e}")
                feature_dict['funding_volatility'] = pd.Series(0.0, index=df.index)
                feature_dict['funding_high_volatility'] = pd.Series(0.0, index=df.index)
                feature_dict['funding_momentum'] = pd.Series(0.0, index=df.index)
                feature_dict['funding_momentum_positive'] = pd.Series(0.0, index=df.index)
                feature_dict['funding_momentum_negative'] = pd.Series(0.0, index=df.index)
            
            # Funding rate contrarian signals
            feature_dict['funding_contrarian_long'] = pd.Series(
                1.0 if current_rate > 0.005 else 0.0, index=df.index  # High positive funding favors shorts, contrarian long
            )
            feature_dict['funding_contrarian_short'] = pd.Series(
                1.0 if current_rate < -0.005 else 0.0, index=df.index  # High negative funding favors longs, contrarian short
            )
            
            log_message(f"Added {len([k for k in feature_dict.keys() if k.startswith('funding')])} funding rate features to ML model")
            
        except Exception as e:
            log_message(f"Funding rate feature extraction error: {e}")
            # Add default funding features if extraction fails
            default_funding_features = [
                'funding_rate', 'funding_rate_pct', 'funding_strength', 'funding_confidence_adj',
                'funding_sentiment_score', 'funding_signal_bias', 'funding_trend', 'funding_extreme',
                'funding_very_positive', 'funding_positive', 'funding_slightly_positive',
                'funding_slightly_negative', 'funding_negative', 'funding_very_negative',
                'funding_cost_daily', 'funding_high_cost', 'funding_extreme_cost',
                'funding_price_alignment', 'funding_price_divergence', 'funding_volatility',
                'funding_high_volatility', 'funding_momentum', 'funding_momentum_positive',
                'funding_momentum_negative', 'funding_contrarian_long', 'funding_contrarian_short'
            ]
            for feature_name in default_funding_features:
                feature_dict[feature_name] = pd.Series(0.0, index=df.index)
        
        # Transformer sentiment (with error handling and proper device management)
        try:
            global _TOKENIZER, _TRANSFORMER_MODEL
            
            if _TOKENIZER is None or _TRANSFORMER_MODEL is None:
                model_name = "ProsusAI/finbert"
                _TOKENIZER = AutoTokenizer.from_pretrained(model_name)
                _TRANSFORMER_MODEL = AutoModelForSequenceClassification.from_pretrained(model_name)
                if GPU_INFO['available']:
                    _TRANSFORMER_MODEL = _TRANSFORMER_MODEL.to(device)
            
            news_text = generate_market_summary(df)
            inputs = _TOKENIZER(news_text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            
            # Move inputs to the same device as the model
            if GPU_INFO['available']:
                inputs = {k: v.to(device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = _TRANSFORMER_MODEL(**inputs)
                logits = outputs.logits
                if logits.shape[0] > 0 and logits.shape[1] >= 2:
                    sentiment_probs = logits.softmax(dim=1)
                    feature_dict['sentiment_score'] = sentiment_probs[0][1].item()
                    feature_dict['sentiment_confidence'] = sentiment_probs.max(dim=1)[0].item()
                else:
                    feature_dict['sentiment_score'] = 0.5  # Neutral default
                    feature_dict['sentiment_confidence'] = 0.5
        except Exception as e:
            # log_message(f"Transformer sentiment error: {e}") # Suppressed to avoid log spam, use neutral default
            feature_dict['sentiment_score'] = 0.5 
            feature_dict['sentiment_confidence'] = 0.5
        
        # Enhanced Volume Profile (VRVP) features for ML consistency - ALWAYS include all features
        # This ensures feature consistency between training and prediction phases
        try:
            # Initialize all VRVP features with defaults first
            vrvp_defaults = {
                'vrvp_poc_distance': 0, 'vrvp_vah_distance': 0, 'vrvp_val_distance': 0,
                'vrvp_above_poc': 0, 'vrvp_above_vah': 0, 'vrvp_below_val': 0, 'vrvp_in_value_area': 0,
                'vrvp_nearest_support_distance': 0.05, 'vrvp_support_count': 0,
                'vrvp_nearest_resistance_distance': 0.05, 'vrvp_resistance_count': 0,
                'vrvp_volume_concentration': 0, 'vrvp_volume_skew': 0, 'vrvp_high_volume_nodes': 0,
                'vrvp_poc_migration': 0, 'vrvp_value_area_change': 0
            }
            
            # Add all default VRVP features first
            for key, value in vrvp_defaults.items():
                feature_dict[key] = pd.Series(value, index=df.index)
            
            # Now try to calculate actual VRVP features if we have sufficient data
            if len(df) >= 100:  # Need sufficient data for VRVP
                try:
                    # Calculate VRVP for the entire dataset
                    volume_profile = calculate_volume_profile(df)
                    
                    if volume_profile:
                        current_price = df['close'].iloc[-1]
                        
                        # VRVP Core Features
                        poc = volume_profile.get('poc', current_price)
                        vah = volume_profile.get('vah', current_price * 1.02)
                        val = volume_profile.get('val', current_price * 0.98)
                        
                        # Distance features (normalized by current price)
                        feature_dict['vrvp_poc_distance'] = pd.Series((poc - current_price) / current_price, index=df.index)
                        feature_dict['vrvp_vah_distance'] = pd.Series((vah - current_price) / current_price, index=df.index)
                        feature_dict['vrvp_val_distance'] = pd.Series((val - current_price) / current_price, index=df.index)
                        
                        # Position features (where price is relative to VRVP levels)
                        feature_dict['vrvp_above_poc'] = pd.Series(1 if current_price > poc else 0, index=df.index)
                        feature_dict['vrvp_above_vah'] = pd.Series(1 if current_price > vah else 0, index=df.index)
                        feature_dict['vrvp_below_val'] = pd.Series(1 if current_price < val else 0, index=df.index)
                        feature_dict['vrvp_in_value_area'] = pd.Series(1 if val <= current_price <= vah else 0, index=df.index)
                        
                        # Support/Resistance level features
                        support_levels = volume_profile.get('support_levels', [])
                        resistance_levels = volume_profile.get('resistance_levels', [])
                        
                        # Nearest support/resistance distances
                        if support_levels:
                            nearest_support = max([s for s in support_levels if s < current_price], default=current_price * 0.95)
                            feature_dict['vrvp_nearest_support_distance'] = pd.Series((current_price - nearest_support) / current_price, index=df.index)
                            feature_dict['vrvp_support_count'] = pd.Series(len(support_levels), index=df.index)
                        
                        if resistance_levels:
                            nearest_resistance = min([r for r in resistance_levels if r > current_price], default=current_price * 1.05)
                            feature_dict['vrvp_nearest_resistance_distance'] = pd.Series((nearest_resistance - current_price) / current_price, index=df.index)
                            feature_dict['vrvp_resistance_count'] = pd.Series(len(resistance_levels), index=df.index)
                        
                        # Volume distribution features
                        price_levels = volume_profile.get('price_levels', [])
                        volumes = volume_profile.get('volumes', [])
                        
                        if price_levels and volumes:
                            total_volume = sum(volumes)
                            if total_volume > 0:
                                # Volume concentration metrics
                                max_volume = max(volumes)
                                feature_dict['vrvp_volume_concentration'] = pd.Series(max_volume / total_volume, index=df.index)
                                
                                # Volume distribution skewness (where is most volume concentrated)
                                weighted_price = sum(p * v for p, v in zip(price_levels, volumes)) / total_volume
                                feature_dict['vrvp_volume_skew'] = pd.Series((weighted_price - current_price) / current_price, index=df.index)
                                
                                # High volume node count (significant levels)
                                high_volume_threshold = max_volume * 0.3
                                high_volume_nodes = sum(1 for v in volumes if v >= high_volume_threshold)
                                feature_dict['vrvp_high_volume_nodes'] = pd.Series(high_volume_nodes, index=df.index)
                        
                        # VRVP trend features (comparing recent vs older VRVP)
                        if len(df) >= 200:
                            try:
                                # Calculate VRVP for first half vs second half
                                mid_point = len(df) // 2
                                older_vp = calculate_volume_profile(df.iloc[:mid_point])
                                recent_vp = calculate_volume_profile(df.iloc[mid_point:])
                                
                                if older_vp and recent_vp:
                                    older_poc = older_vp.get('poc', current_price)
                                    recent_poc = recent_vp.get('poc', current_price)
                                    
                                    # POC migration (is the Point of Control moving up or down?)
                                    feature_dict['vrvp_poc_migration'] = pd.Series((recent_poc - older_poc) / older_poc if older_poc != 0 else 0, index=df.index)
                                    
                                    # Value area expansion/contraction
                                    older_va_range = older_vp.get('vah', current_price) - older_vp.get('val', current_price)
                                    recent_va_range = recent_vp.get('vah', current_price) - recent_vp.get('val', current_price)
                                    
                                    if older_va_range > 0:
                                        feature_dict['vrvp_value_area_change'] = pd.Series((recent_va_range - older_va_range) / older_va_range, index=df.index)
                            except Exception as e:
                                log_message(f"Error calculating VRVP trend features: {e}")
                                # Keep default values already set
                        
                        log_message(f"VRVP features calculated: POC={poc:.6f}, VAH={vah:.6f}, VAL={val:.6f}")
                    
                except Exception as e:
                    log_message(f"Error calculating detailed VRVP features: {e}")
                    # Keep default values already set
            
            # Ensure all VRVP features are present (double-check)
            for key in vrvp_defaults.keys():
                if key not in feature_dict:
                    feature_dict[key] = pd.Series(vrvp_defaults[key], index=df.index)
                    log_message(f"Added missing VRVP feature: {key}")
            
            log_message(f"All {len(vrvp_defaults)} VRVP features ensured in feature set")
            
        except Exception as e:
            log_message(f"Critical error in VRVP feature calculation: {e}")
            # Ensure all VRVP features exist with defaults
            vrvp_defaults = {
                'vrvp_poc_distance': 0, 'vrvp_vah_distance': 0, 'vrvp_val_distance': 0,
                'vrvp_above_poc': 0, 'vrvp_above_vah': 0, 'vrvp_below_val': 0, 'vrvp_in_value_area': 0,
                'vrvp_nearest_support_distance': 0.05, 'vrvp_support_count': 0,
                'vrvp_nearest_resistance_distance': 0.05, 'vrvp_resistance_count': 0,
                'vrvp_volume_concentration': 0, 'vrvp_volume_skew': 0, 'vrvp_high_volume_nodes': 0,
                'vrvp_poc_migration': 0, 'vrvp_value_area_change': 0
            }
            for key, value in vrvp_defaults.items():
                feature_dict[key] = pd.Series(value, index=df.index)
        
        # Ensure all features are 1D before creating DataFrame
        final_feature_dict = {}
        target_len = len(df.index)
        for k, v in feature_dict.items():
            try:
                # Handle numpy arrays, pandas Series, and lists
                if hasattr(v, 'values'): v_data = v.values
                else: v_data = np.array(v)
                
                # Flatten multi-dimensional data
                if v_data.ndim > 1:
                    v_data = v_data.reshape(v_data.shape[0], -1)[:, 0]
                elif v_data.ndim == 0:
                    # Scalar value - broadcast to full length
                    v_data = np.full(target_len, v_data.item())
                
                # Ensure correct length
                if len(v_data) > target_len:
                    v_data = v_data[:target_len]
                elif len(v_data) < target_len:
                    # Pad with last value or default
                    pad_val = v_data[-1] if len(v_data) > 0 else 0
                    v_data = np.pad(v_data, (0, target_len - len(v_data)), constant_values=pad_val)
                    
                final_feature_dict[k] = pd.Series(v_data, index=df.index)
            except Exception as e:
                log_message(f"⚠️ Error flattening feature {k}: {e}")
                final_feature_dict[k] = pd.Series(0.0, index=df.index)
        
        feature_dict = final_feature_dict
        for k, v in feature_dict.items():
            if hasattr(v, 'shape') and len(v.shape) > 1:
                log_message(f"⚠️ Feature {k} has shape {v.shape}")
            elif isinstance(v, (list, tuple)):
                log_message(f"⚠️ Feature {k} is a {type(v)}")

        features = pd.DataFrame(feature_dict, index=df.index)
        
        # Clean missing values with more lenient approach
        features = features.replace([np.inf, -np.inf], np.nan)
        
        # Instead of dropping all NaN rows, use forward fill and backward fill
        features = features.ffill().bfill()
        
        # Only drop rows where ALL values are NaN
        features = features.dropna(how='all')
        
        # More lenient minimum data requirement
        min_required = min(20, len(df) // 2)  # At least 20 rows or half the dataset
        if len(features) < min_required:
            log_message(f"Insufficient feature data: {len(features)} rows (minimum: {min_required})")
            return pd.DataFrame()
        
        log_message(f"Prepared {len(features.columns)} features for ML model with {len(features)} rows")
        return features
        
    except Exception as e:
        log_message(f"Feature preparation error: {e}")
        return pd.DataFrame()

def generate_training_labels(df, future_periods=5):
    """Generate training labels based on future price movements"""
    try:
        labels = []
        
        for i in range(len(df) - future_periods):
            current_price = df['close'].iloc[i]
            future_price = df['close'].iloc[i + future_periods]
            
            # Calculate percentage change
            price_change = (future_price - current_price) / current_price
            
            # Label as 1 (buy) if price increases by more than 1%, 0 (sell) otherwise
            label = 1 if price_change > 0.01 else 0
            labels.append(label)
        
        # Pad with neutral labels for the last few periods
        labels.extend([0] * future_periods)
        
        return pd.Series(labels, index=df.index)
        
    except Exception as e:
        log_message(f"Error generating training labels: {e}")
        return pd.Series([0] * len(df), index=df.index)

def train_ensemble_models(X, y):
    """Train ensemble of ML models for robust predictions"""
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.svm import SVC
        from sklearn.metrics import classification_report, confusion_matrix
        from sklearn.preprocessing import StandardScaler
        
        if len(X) < 100:
            log_message(f"Insufficient training data: {len(X)} samples")
            return None
            
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)
        
        # Scale features for some models
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        models = {}
        
        # 1. XGBoost (primary model)
        log_message("Training XGBoost model...")
        # PROPOSAL 1 FIX: Compute class balance to prevent SHORT bias
        n_pos = int(y_train.sum())
        n_neg = len(y_train) - n_pos
        spw = n_neg / n_pos if n_pos > 0 else 1.0
        log_message(f"XGBoost class balance: {n_pos} positive / {n_neg} negative, scale_pos_weight={spw:.2f}")
        
        xgb_params = {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'random_state': 42,
            'reg_alpha': 0.1,
            'reg_lambda': 0.1,
            'scale_pos_weight': spw
        }
        
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)
        
        xgb_model = xgb.train(
            xgb_params, 
            dtrain, 
            num_boost_round=300,
            evals=[(dtrain, 'train'), (dtest, 'test')],
            early_stopping_rounds=30,
            verbose_eval=False
        )
        
        xgb_train_preds = xgb_model.predict(dtrain) > 0.5
        xgb_test_preds = xgb_model.predict(dtest) > 0.5
        xgb_train_acc = accuracy_score(y_train, xgb_train_preds)
        xgb_test_acc = accuracy_score(y_test, xgb_test_preds)
        
        models['xgboost'] = {
            'model': xgb_model,
            'train_acc': xgb_train_acc,
            'test_acc': xgb_test_acc,
            'type': 'xgboost'
        }
        
        log_message(f"XGBoost - Train: {xgb_train_acc:.3f}, Test: {xgb_test_acc:.3f}")
        
        # 2. Random Forest
        log_message("Training Random Forest model...")
        rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train, y_train)
        
        rf_train_acc = rf_model.score(X_train, y_train)
        rf_test_acc = rf_model.score(X_test, y_test)
        
        models['random_forest'] = {
            'model': rf_model,
            'train_acc': rf_train_acc,
            'test_acc': rf_test_acc,
            'type': 'sklearn'
        }
        
        log_message(f"Random Forest - Train: {rf_train_acc:.3f}, Test: {rf_test_acc:.3f}")
        
        # 3. Gradient Boosting
        log_message("Training Gradient Boosting model...")
        gb_model = GradientBoostingClassifier(
            n_estimators=200,
            learning_rate=0.1,
            max_depth=6,
            random_state=42
        )
        gb_model.fit(X_train, y_train)
        
        gb_train_acc = gb_model.score(X_train, y_train)
        gb_test_acc = gb_model.score(X_test, y_test)
        
        models['gradient_boosting'] = {
            'model': gb_model,
            'train_acc': gb_train_acc,
            'test_acc': gb_test_acc,
            'type': 'sklearn'
        }
        
        log_message(f"Gradient Boosting - Train: {gb_train_acc:.3f}, Test: {gb_test_acc:.3f}")
        
        # 4. Logistic Regression (for linear patterns)
        log_message("Training Logistic Regression model...")
        lr_model = LogisticRegression(
            random_state=42,
            max_iter=1000,
            C=1.0
        )
        lr_model.fit(X_train_scaled, y_train)
        
        lr_train_acc = lr_model.score(X_train_scaled, y_train)
        lr_test_acc = lr_model.score(X_test_scaled, y_test)
        
        models['logistic_regression'] = {
            'model': lr_model,
            'scaler': scaler,
            'train_acc': lr_train_acc,
            'test_acc': lr_test_acc,
            'type': 'sklearn_scaled'
        }
        
        log_message(f"Logistic Regression - Train: {lr_train_acc:.3f}, Test: {lr_test_acc:.3f}")
        
        # Save all models
        dump(models, 'ensemble_models.joblib')
        
        # Also save primary XGBoost model separately for compatibility
        xgb_model.save_model('signal_model.ubj')
        
        log_message("Ensemble models saved successfully")
        log_message(f"Best performing model: {max(models.keys(), key=lambda k: models[k]['test_acc'])}")
        
        return models
        
    except Exception as e:
        log_message(f"Ensemble training error: {e}")
        # Fallback to single XGBoost model
        single_model = train_ml_model(X, y)
        if single_model:
            # Return as dictionary for consistency
            return {
                'xgboost_fallback': {
                    'model': single_model,
                    'train_acc': 0.0,  # Not calculated in fallback
                    'test_acc': 0.0,   # Not calculated in fallback
                    'type': 'xgboost'
                }
            }
        return None

def train_ml_model(X, y):
    """Train XGBoost classifier (fallback method)"""
    try:
        if len(X) < 100:
            log_message(f"Insufficient training data: {len(X)} samples")
            return None
            
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)
        
        # PROPOSAL 1 FIX: Compute class balance to prevent SHORT bias
        n_pos = int(y_train.sum())
        n_neg = len(y_train) - n_pos
        spw = n_neg / n_pos if n_pos > 0 else 1.0
        log_message(f"XGBoost retrain class balance: {n_pos} pos / {n_neg} neg, scale_pos_weight={spw:.2f}")
        
        params = {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'random_state': 42,
            'reg_alpha': 0.1,
            'reg_lambda': 0.1,
            'min_child_weight': 1,
            'gamma': 0.1,
            'scale_pos_weight': spw
        }
        
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)
        
        # Train with early stopping
        evals_result = {}
        model = xgb.train(
            params, 
            dtrain, 
            num_boost_round=300,
            evals=[(dtrain, 'train'), (dtest, 'test')],
            early_stopping_rounds=30,
            evals_result=evals_result,
            verbose_eval=False
        )
        
        # Evaluate
        train_preds = model.predict(dtrain) > 0.5
        test_preds = model.predict(dtest) > 0.5
        
        train_accuracy = accuracy_score(y_train, train_preds)
        test_accuracy = accuracy_score(y_test, test_preds)
        
        log_message(f"XGBoost Model trained - Train accuracy: {train_accuracy:.3f}, Test accuracy: {test_accuracy:.3f}")
        log_message(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
        
        # Feature importance analysis
        try:
            importance = model.get_score(importance_type='weight')
            top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
            log_message(f"Top 10 important features: {top_features}")
        except Exception as e:
            log_message(f"Feature importance analysis failed: {e}")
        
        # Save model
        model.save_model('signal_model.ubj')
        log_message("Model saved to signal_model.ubj")
        
        return model
        
    except Exception as e:
        log_message(f"Model training error: {e}")
        return None

def should_retrain_model():
    """Check if model should be retrained"""
    model_file = 'signal_model.ubj'
    
    if not os.path.exists(model_file):
        return True
        
    # Check if model is older than 24 hours
    model_age = time.time() - os.path.getmtime(model_file)
    return model_age > 86400  # 24 hours in seconds

def train_model_with_historical_data():
    """Train ensemble models using historical data from multiple pairs"""
    try:
        log_message("Starting comprehensive model training with historical data...")
        
        # Expanded set of trading pairs for more diverse training data
        training_pairs = [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT', 
            'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT',
            'UNIUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT'
        ]
        all_features = []
        all_labels = []
        
        for pair in training_pairs:
            try:
                log_message(f"Fetching training data for {pair}")
                df = fetch_data(pair, '1h', retries=3)  # Use hourly data for training
                
                if df.empty or len(df) < 200:
                    log_message(f"Insufficient data for {pair}")
                    continue
                
                # Calculate all technical indicators
                df = calculate_bollinger_bands(df)
                df = calculate_vwap(df)
                df = calculate_macd(df)
                df = calculate_atr(df)
                df = calculate_ichimoku(df)
                df = calculate_advanced_indicators(df)
                df = calculate_chandelier_exit(df)
                df = detect_candlestick_patterns(df)
                
                # Prepare comprehensive features
                features = prepare_ml_features(df)
                if features.empty:
                    log_message(f"No features prepared for {pair}")
                    continue
                
                # Generate labels with multiple strategies
                labels = generate_training_labels(df, future_periods=5)
                
                # Align features and labels
                min_len = min(len(features), len(labels))
                if min_len > 100:  # Increased minimum threshold
                    features_aligned = features.iloc[:min_len]
                    labels_aligned = labels.iloc[:min_len]
                    
                    all_features.append(features_aligned)
                    all_labels.append(labels_aligned)
                    
                    log_message(f"Added {min_len} samples from {pair} with {len(features.columns)} features")
                else:
                    log_message(f"Insufficient aligned data for {pair}: {min_len} samples")
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                log_message(f"Error processing {pair} for training: {e}")
                continue
        
        if not all_features:
            log_message("No training data collected")
            return None
        
        # Combine all features and labels
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)
        
        log_message(f"Total training samples: {len(X)}")
        log_message(f"Total features: {len(X.columns)}")
        log_message(f"Label distribution: {y.value_counts().to_dict()}")
        log_message(f"Feature names: {list(X.columns)[:20]}...")  # Log first 20 features
        
        # Train ensemble models
        try:
            models = train_ensemble_models(X, y)
            if models:
                log_message("Ensemble models trained successfully")
                return models
            else:
                log_message("Ensemble training failed, falling back to single model")
                return train_ml_model(X, y)
        except Exception as e:
            log_message(f"Ensemble training failed: {e}, falling back to single model")
            return train_ml_model(X, y)
        
    except Exception as e:
        log_message(f"Training workflow error: {e}")
        return None

def predict_with_ml(df, model=None):
    """Generate ML predictions with confidence score"""
    if model is None and os.path.exists('signal_model.ubj'):
        model = xgb.Booster()
        model.load_model('signal_model.ubj')
    
    if model:
        try:
            features = prepare_ml_features(df)
            if not features.empty:
                dmatrix = xgb.DMatrix(features)
                prob = model.predict(dmatrix)[-1]
                # Confidence is the distance from the 0.5 decision boundary
                confidence = abs(prob - 0.5) * 2
                return (prob > 0.5), confidence
        except Exception as e:
            from utils_logger import log_message
            log_message(f"ML Prediction Error: {e}")
    return None, 0.0

