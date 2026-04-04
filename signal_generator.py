import pandas as pd
import numpy as np
import time
from datetime import datetime
from constants import *
from shared_state import *
from technical_indicators import *
from trading_utilities import generate_market_summary

def calculate_base_signal(df):
    """Calculate base trading signal without ML"""
    # Get the most recent values only
    latest = df.iloc[-1]
    
    # Volatility Spike Filter (ATR > 150% of recent trend)
    if 'ATR' in df.columns:
        avg_atr = df['ATR'].rolling(14).mean().iloc[-1]
        if pd.notna(avg_atr) and avg_atr > 0 and latest['ATR'] > (avg_atr * 1.5):
            return 'NEUTRAL'
    
    # Enhanced signal confirmation with multiple indicators
    bullish = (
        (latest['close'] < latest['Lower Band']) and
        (latest['MACD Histogram'] < 0) and
        (latest['close'] < latest['VWAP']) and
        (latest['close'] > latest['senkou_span_a']) and 
        (latest['close'] > latest['senkou_span_b'])
    )
    
    bearish = (
        (latest['close'] > latest['Upper Band']) and
        (latest['MACD Histogram'] > 0) and
        (latest['close'] > latest['VWAP']) and
        (latest['close'] < latest['senkou_span_a']) and
        (latest['close'] < latest['senkou_span_b'])
    )

    if bullish:
        return 'LONG'
    elif bearish:
        return 'SHORT'
    return 'NEUTRAL'

def calculate_detailed_confidence(df, signal, total_score):
    """Calculate ultra-precise confidence percentage with exact 0.1% increments from 10.0% to 100.0%"""
    try:
        latest = df.iloc[-1]
        confidence_factors = []
        
        # Enhanced base confidence from signal strength (0-28%)
        max_possible_score = 6  # BB, MACD, VWAP, Cloud, RSI, Pattern
        base_score = abs(total_score) / max_possible_score if max_possible_score > 0 else 0
        
        # Price momentum micro-adjustment
        price_momentum = (latest['close'] - df['close'].iloc[-5]) / df['close'].iloc[-5] * 100 if len(df) > 5 else 0
        momentum_boost = min(abs(price_momentum) * 0.7, 4)  # Up to 4% boost from momentum
        
        # Base confidence with enhanced granularity
        base_confidence = min(base_score * 28 + momentum_boost + (base_score * 1.8), 28)
        confidence_factors.append(('Signal Strength', base_confidence))
        
        # Enhanced RSI confirmation (0-16%)
        rsi_confidence = 0
        if 'RSI_14' in df.columns and not pd.isna(latest['RSI_14']):
            try:
                rsi_val = float(latest['RSI_14'])  # Convert to scalar
                if signal.upper() == 'LONG' and rsi_val < 55:  # Expanded range for long
                    rsi_factor = (55 - rsi_val) / 55
                    rsi_divergence = abs(rsi_val - 30) * 0.08  # Divergence from oversold
                    rsi_confidence = min(rsi_factor * 16 + rsi_divergence, 16)
                elif signal.upper() == 'SHORT' and rsi_val > 45:  # Expanded range for short
                    rsi_factor = (rsi_val - 45) / 55
                    rsi_divergence = abs(rsi_val - 70) * 0.08  # Divergence from overbought
                    rsi_confidence = min(rsi_factor * 16 + rsi_divergence, 16)
            except (TypeError, ValueError) as e:
                log_message(f"Error processing RSI value: {e}")
                rsi_confidence = 0
        confidence_factors.append(('RSI Confirmation', rsi_confidence))
        
        # Enhanced volume confirmation (0-12%)
        volume_confidence = 0
        if len(df) > 20:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            if pd.notna(avg_volume) and avg_volume > 0:
                volume_ratio = latest['volume'] / avg_volume
                # Ultra-sophisticated volume analysis
                if volume_ratio > 1.05:
                    volume_spike = min((volume_ratio - 1) * 7, 8)
                    volume_consistency = min(abs(volume_ratio - 1.4) * 1.8, 3)  # Optimal around 1.4x
                    volume_confidence = min(volume_spike + volume_consistency, 12)
        confidence_factors.append(('Volume Confirmation', volume_confidence))
        
        # Enhanced volatility factor (0-11%)
        volatility_confidence = 0
        if 'ATR' in df.columns and not pd.isna(latest['ATR']):
            atr_avg = df['ATR'].rolling(14).mean().iloc[-1]
            if pd.notna(atr_avg) and atr_avg > 0:
                volatility_ratio = float(latest['ATR']) / float(atr_avg)  # Convert to scalars
                # Ultra-nuanced volatility scoring
                if 0.6 <= volatility_ratio <= 2.0:
                    optimal_distance = abs(volatility_ratio - 1.15)  # Optimal around 1.15
                    volatility_base = 11 - (optimal_distance * 7)
                    volatility_confidence = max(0, min(volatility_base, 11))
        confidence_factors.append(('Volatility Factor', volatility_confidence))
        
        # Enhanced trend alignment (0-15%)
        trend_confidence = 0
        if 'SMA_20' in df.columns and 'SMA_50' in df.columns and 'EMA_10' in df.columns:
            sma20 = float(latest['SMA_20'])  # Convert to scalar
            sma50 = float(latest['SMA_50'])  # Convert to scalar
            ema10 = float(latest['EMA_10'])  # Convert to scalar
            price = float(latest['close'])  # Convert to scalar
            
            # Ultra-detailed trend analysis
            if signal.upper() == 'LONG':
                trend_score = 0
                if price > sma20: trend_score += 5.5
                if sma20 > sma50: trend_score += 4.5
                if price > ema10: trend_score += 3.5
                if ema10 > sma20: trend_score += 1.5
                trend_confidence = min(trend_score, 15)
            elif signal.upper() == 'SHORT':
                trend_score = 0
                if price < sma20: trend_score += 5.5
                if sma20 < sma50: trend_score += 4.5
                if price < ema10: trend_score += 3.5
                if ema10 < sma20: trend_score += 1.5
                trend_confidence = min(trend_score, 15)
        confidence_factors.append(('Trend Alignment', trend_confidence))
        
        # Enhanced pattern strength (0-10%)
        pattern_confidence = 0
        if 'Pattern_Strength' in df.columns and not pd.isna(latest['Pattern_Strength']):
            pattern_strength = float(latest['Pattern_Strength'])  # Convert to scalar
            pattern_type = str(latest.get('Pattern_Type', 'Neutral'))  # Convert to string
            
            if ((signal.upper() == 'LONG' and pattern_type == 'Bullish') or 
                (signal.upper() == 'SHORT' and pattern_type == 'Bearish')):
                pattern_base = min(abs(pattern_strength) * 5, 8)
                pattern_confidence = min(pattern_base, 10)
        confidence_factors.append(('Pattern Strength', pattern_confidence))
        
        # Additional momentum indicators (0-7%)
        momentum_confidence = 0
        if 'MACD Histogram' in df.columns and not pd.isna(latest['MACD Histogram']):
            macd_hist = float(latest['MACD Histogram'])  # Convert to scalar
            if ((signal.upper() == 'LONG' and macd_hist > 0) or (signal.upper() == 'SHORT' and macd_hist < 0)):
                momentum_base = min(abs(macd_hist) * 800 + 1.5, 6)  # Scale MACD appropriately
                momentum_confidence = min(momentum_base, 7)
        confidence_factors.append(('Momentum Indicators', momentum_confidence))
        
        # Market structure bonus (0-5%)
        structure_confidence = 0
        if len(df) > 10:
            recent_highs = float(df['high'].rolling(10).max().iloc[-1])  # Convert to scalar
            recent_lows = float(df['low'].rolling(10).min().iloc[-1])   # Convert to scalar
            current_close = float(latest['close'])  # Convert to scalar
            price_position = (current_close - recent_lows) / (recent_highs - recent_lows) if recent_highs != recent_lows else 0.5
            
            if signal.upper() == 'LONG' and price_position < 0.35:  # Near lows for long
                structure_base = (0.35 - price_position) * 14
                structure_confidence = min(structure_base, 5)
            elif signal.upper() == 'SHORT' and price_position > 0.65:  # Near highs for short
                structure_base = (price_position - 0.65) * 14
                structure_confidence = min(structure_base, 5)
        confidence_factors.append(('Market Structure', structure_confidence))
        
        # Calculate total confidence from validated factors (no artificial noise)
        total_confidence = sum(factor[1] for factor in confidence_factors)
        
        # Ensure confidence is between 10.0% and 100.0%
        final_confidence = max(10.0, min(100.0, total_confidence))
        
        # Round to 1 decimal place for clean display
        final_confidence = round(final_confidence, 1)
        
        # Log confidence breakdown for debugging
        log_message(f"Confidence breakdown for {signal} signal:")
        for factor_name, factor_value in confidence_factors:
            log_message(f"  {factor_name}: {factor_value:.2f}%")
        log_message(f"  Final Confidence: {final_confidence:.1f}%")
        
        return final_confidence / 100  # Return as decimal
        
    except Exception as e:
        log_message(f"Error calculating detailed confidence: {e}")
        return 0.5  # Default 50% confidence

def calculate_kicko_indicator(df, pair=None, use_ml=True):
    if not isinstance(df, pd.DataFrame) or df.empty:
        log_message("Invalid DataFrame input to calculate_kicko_indicator")
        return df  # Return the DataFrame as is
    
    try:
        if 'Upper Band' not in df.columns:
            df = calculate_bollinger_bands(df)
        if 'VWAP' not in df.columns:
            df = calculate_vwap(df)
        if 'MACD Line' not in df.columns:
            df = calculate_macd(df)
        if 'ATR' not in df.columns:
            df = calculate_atr(df)
        if 'tenkan_sen' not in df.columns:
            df = calculate_ichimoku(df)
        if 'CE_Direction' not in df.columns:
            df = calculate_chandelier_exit(df)
        if 'Pattern_Type' not in df.columns:
            df = detect_candlestick_patterns(df)
    except Exception as e:
        log_message(f"Technical indicator calculation failed: {e}")
        return df
    
    # More lenient signal logic with lower thresholds for more signals
    # Calculate individual signal scores
    bb_score = np.where(df['close'] < df['Lower Band'], 1,  # Oversold - bullish
                       np.where(df['close'] > df['Upper Band'], -1, 0))  # Overbought - bearish
    
    macd_score = np.where(df['MACD Histogram'] > 0, 1,  # MACD bullish
                         np.where(df['MACD Histogram'] < 0, -1, 0))  # MACD bearish
    
    vwap_score = np.where(df['close'] > df['VWAP'], 1,  # Above VWAP - bullish
                         np.where(df['close'] < df['VWAP'], -1, 0))  # Below VWAP - bearish
    
    # Ichimoku cloud score
    cloud_score = np.where(
        (df['close'] > df['senkou_span_a']) & (df['close'] > df['senkou_span_b']), 1,  # Above cloud - bullish
        np.where(
            (df['close'] < df['senkou_span_a']) & (df['close'] < df['senkou_span_b']), -1,  # Below cloud - bearish
            0  # In cloud - neutral
        )
    )
    
    # Tighten RSI thresholds (standard 30/70)
    rsi_score = 0
    if 'RSI_14' in df.columns:
        rsi_score = np.where(df['RSI_14'] < 30, 1,
                            np.where(df['RSI_14'] > 70, -1, 0))
    
    # Pattern score
    pattern_score = np.zeros(len(df))
    if 'Pattern_Type' in df.columns:
        pattern_score = np.where(df['Pattern_Type'] == 'Bullish', 1,
                               np.where(df['Pattern_Type'] == 'Bearish', -1, 0))
                               
    # Chandelier Exit score
    ce_score = np.zeros(len(df))
    if 'CE_Direction' in df.columns:
        ce_score = np.where(df['CE_Direction'] == 1, 1,
                           np.where(df['CE_Direction'] == -1, -1, 0))
    
    # Ensure all scores have the same shape and are 1D arrays
    df_len = len(df)
    
    # Convert all scores to 1D numpy arrays of the same length
    bb_score = np.asarray(bb_score).flatten()[:df_len] if hasattr(bb_score, '__len__') else np.full(df_len, bb_score)
    macd_score = np.asarray(macd_score).flatten()[:df_len] if hasattr(macd_score, '__len__') else np.full(df_len, macd_score)
    vwap_score = np.asarray(vwap_score).flatten()[:df_len] if hasattr(vwap_score, '__len__') else np.full(df_len, vwap_score)
    cloud_score = np.asarray(cloud_score).flatten()[:df_len] if hasattr(cloud_score, '__len__') else np.full(df_len, cloud_score)
    
    # Ensure all arrays are exactly the right length
    if len(bb_score) != df_len:
        bb_score = np.resize(bb_score, df_len)
    if len(macd_score) != df_len:
        macd_score = np.resize(macd_score, df_len)
    if len(vwap_score) != df_len:
        vwap_score = np.resize(vwap_score, df_len)
    if len(cloud_score) != df_len:
        cloud_score = np.resize(cloud_score, df_len)
    
    # Handle RSI score
    if hasattr(rsi_score, '__len__'):
        rsi_score = np.asarray(rsi_score).flatten()[:df_len]
        if len(rsi_score) != df_len:
            rsi_score = np.resize(rsi_score, df_len)
    else:
        rsi_score = np.full(df_len, rsi_score)
    
    # Handle pattern score
    if hasattr(pattern_score, '__len__'):
        pattern_score = np.asarray(pattern_score).flatten()[:df_len]
        if len(pattern_score) != df_len:
            pattern_score = np.resize(pattern_score, df_len)
    else:
        pattern_score = np.full(df_len, pattern_score)
        
    # Handle Chandelier Exit score
    if hasattr(ce_score, '__len__'):
        ce_score = np.asarray(ce_score).flatten()[:df_len]
        if len(ce_score) != df_len:
            ce_score = np.resize(ce_score, df_len)
    else:
        ce_score = np.full(df_len, ce_score)
    
    # Dynamic weights based on historical reliability
    weights = {
        'bb': 1.0,
        'macd': 1.5,
        'vwap': 1.2,
        'cloud': 1.0,
        'rsi': 1.3,
        'pattern': 2.0,
        'ce': 2.5
    }
    
    # Calculate total score with weights
    total_score = (bb_score * weights['bb'] + 
                   macd_score * weights['macd'] + 
                   vwap_score * weights['vwap'] + 
                   cloud_score * weights['cloud'] + 
                   rsi_score * weights['rsi'] + 
                   pattern_score * weights['pattern'] +
                   ce_score * weights['ce'])
    
    # Stricter signal thresholds to reduce noise and "fakeouts"
    # Require a higher cumulative score for entry (was 1, now 3.5)
    signal_conditions = np.where(total_score >= 3.5, 'LONG',
                               np.where(total_score <= -3.5, 'SHORT', 'NEUTRAL'))
    
    # Create signal and position size data efficiently
    signal_data = {
        'Position_Size': np.where(
            df['ATR'] > df['ATR'].rolling(14).mean(),
            0.5,  # Reduce size in high volatility
            1.0    # Normal size
        ),
        'Signal': signal_conditions,
        'Signal_Score': total_score
    }
    
    # Add signal columns efficiently using pd.concat
    signal_df = pd.DataFrame(signal_data, index=df.index)
    df = pd.concat([df, signal_df], axis=1)
    
    # Log signal generation details for latest row
    latest_idx = df.index[-1]
    log_message(f"Signal generation details:")
    log_message(f"  BB Score: {bb_score[-1]}, MACD Score: {macd_score[-1]}, VWAP Score: {vwap_score[-1]}")
    log_message(f"  Cloud Score: {cloud_score[-1]}, RSI Score: {rsi_score[-1] if hasattr(rsi_score, '__getitem__') else rsi_score}")
    log_message(f"  Pattern Score: {pattern_score[-1] if hasattr(pattern_score, '__getitem__') else pattern_score}, CE Score: {ce_score[-1] if hasattr(ce_score, '__getitem__') else ce_score}")
    log_message(f"  Total Score: {total_score[-1]}, Signal: {signal_conditions[-1]}")
    
    # Apply Smart Money Analysis if available
    smart_money_signal = None
    smart_money_confidence = 0.0
    
    if SMART_MONEY_AVAILABLE:
        try:
            # Get base signal for smart money analysis
            base_signal = df['Signal'].iloc[-1]
            
            if base_signal != 'Neutral':
                log_message(f"Running Smart Money analysis for signal: {base_signal}")
                
                # Perform smart money analysis
                smart_money_result = SMART_MONEY_ANALYZER.analyze_market_structure(df)
                
                if smart_money_result and 'signal' in smart_money_result:
                    smart_money_signal = smart_money_result['signal']
                    smart_money_confidence = smart_money_result.get('confidence', 0.0)
                    
                    log_message(f"Smart Money analysis: {smart_money_signal} (confidence: {smart_money_confidence:.2f})")
                    
                    # Check if smart money analysis agrees with base signal
                    if smart_money_signal == base_signal:
                        # Smart money confirms the signal - boost confidence
                        log_message(f"Smart Money CONFIRMS {base_signal} signal")
                        # Add smart money confirmation to the dataframe
                        df.loc[df.index[-1], 'Smart_Money_Confirmation'] = True
                        df.loc[df.index[-1], 'Smart_Money_Confidence'] = smart_money_confidence
                    elif smart_money_signal in ['Long', 'Short'] and smart_money_confidence > 0.7:
                        # Strong smart money signal that disagrees - override
                        log_message(f"Smart Money OVERRIDE: {base_signal} -> {smart_money_signal} (confidence: {smart_money_confidence:.2f})")
                        df.loc[df.index[-1], 'Signal'] = smart_money_signal.upper()
                        df.loc[df.index[-1], 'Smart_Money_Override'] = True
                        df.loc[df.index[-1], 'Smart_Money_Confidence'] = smart_money_confidence
                    else:
                        # Weak smart money signal or neutral - keep base signal but note the analysis
                        log_message(f"Smart Money analysis weak or neutral: {smart_money_signal} (confidence: {smart_money_confidence:.2f})")
                        df.loc[df.index[-1], 'Smart_Money_Confirmation'] = False
                        df.loc[df.index[-1], 'Smart_Money_Confidence'] = smart_money_confidence
                        
        except Exception as e:
            log_message(f"Smart Money analysis error: {e}")
            # Add default values if analysis fails
            df.loc[df.index[-1], 'Smart_Money_Confirmation'] = False
            df.loc[df.index[-1], 'Smart_Money_Confidence'] = 0.0

    # Apply Institutional ML Analysis if available
    institutional_ml_signal = None
    institutional_ml_confidence = 0.0
    
    if INSTITUTIONAL_ML_AVAILABLE:
        try:
            # Use the pair parameter if available, otherwise use a default
            pair_symbol = pair if pair else 'BTCUSDT'
            
            # Get base signal for institutional ML analysis
            base_signal = df['Signal'].iloc[-1]
            
            if base_signal != 'Neutral':
                log_message(f"Running Institutional ML analysis for signal: {base_signal}")
                
                # Initialize ML system if not already done
                initialize_institutional_ml()
                
                # Get ML prediction for the current pair
                institutional_prediction = get_institutional_prediction(pair_symbol, timeframe='1h')
                
                if institutional_prediction and 'signal' in institutional_prediction:
                    institutional_ml_signal = institutional_prediction['signal']
                    institutional_ml_confidence = institutional_prediction.get('confidence', 0.0)
                    
                    log_message(f"Institutional ML analysis: {institutional_ml_signal} (confidence: {institutional_ml_confidence:.2f})")
                    
                    # ML signal logic
                    if institutional_ml_signal == base_signal and institutional_ml_confidence > 0.6:
                        # Strong ML confirmation - boost confidence
                        log_message(f"Institutional ML CONFIRMS {base_signal} signal")
                        df.loc[df.index[-1], 'ML_Confirmation'] = True
                        df.loc[df.index[-1], 'ML_Confidence'] = institutional_ml_confidence
                        
                        # Boost signal strength if both Smart Money and ML agree
                        if smart_money_signal == base_signal:
                            log_message(f"TRIPLE CONFIRMATION: Base + Smart Money + ML all agree on {base_signal}")
                            df.loc[df.index[-1], 'Triple_Confirmation'] = True
                        
                    elif institutional_ml_signal != base_signal and institutional_ml_confidence > 0.8:
                        # Very strong ML disagreement - consider override
                        log_message(f"Institutional ML STRONG OVERRIDE: {base_signal} -> {institutional_ml_signal} (confidence: {institutional_ml_confidence:.2f})")
                        df.loc[df.index[-1], 'Signal'] = institutional_ml_signal.upper()
                        df.loc[df.index[-1], 'ML_Override'] = True
                        df.loc[df.index[-1], 'ML_Confidence'] = institutional_ml_confidence
                        
                    else:
                        # Weak ML signal or moderate disagreement - note but don't override
                        log_message(f"Institutional ML analysis noted: {institutional_ml_signal} (confidence: {institutional_ml_confidence:.2f})")
                        df.loc[df.index[-1], 'ML_Confirmation'] = False
                        df.loc[df.index[-1], 'ML_Confidence'] = institutional_ml_confidence
                
                else:
                    log_message("Institutional ML analysis returned no prediction")
                    df.loc[df.index[-1], 'ML_Confirmation'] = False
                    df.loc[df.index[-1], 'ML_Confidence'] = 0.0
                    
        except Exception as e:
            log_message(f"Institutional ML analysis error: {e}")
            # Add default values if analysis fails
            df.loc[df.index[-1], 'ML_Confirmation'] = False
            df.loc[df.index[-1], 'ML_Confidence'] = 0.0
    else:
        # Add default values if ML not available
        df.loc[df.index[-1], 'ML_Confirmation'] = False
        df.loc[df.index[-1], 'ML_Confidence'] = 0.0

    # Apply ML enhancement if enabled
    if use_ml:
        try:
            # Get current signal (may have been modified by smart money analysis)
            current_signal = df['Signal'].iloc[-1]
            
            if current_signal != 'Neutral':
                # Try XGBoost first
                from ml_training import predict_with_ml
                xgb_signal, xgb_conf = predict_with_ml(df)
                if xgb_signal is not None:
                    ml_signal = 'LONG' if xgb_signal else 'SHORT'
                    log_message(f"XGBoost prediction: {ml_signal} (Confidence: {xgb_conf:.2f})")
                    
                    # Override signal if ML disagrees and smart money didn't already override
                    if ml_signal != current_signal and not df.get('Smart_Money_Override', pd.Series([False])).iloc[-1]:
                        # NEW CONSENSUS LOGIC: Only overrule if confidence is extreme
                        if xgb_conf >= 0.85:
                            log_message(f"🔥 Aladdin Institutional Overrule: {current_signal} -> {ml_signal} ({xgb_conf:.2f} confidence)")
                            df.loc[df.index[-1], 'Signal'] = ml_signal
                            df.loc[df.index[-1], 'ML_Override'] = True
                            # P0 Fix: Update Signal_Score so main.py doesn't evaluate this as 0 precision!
                            df.loc[df.index[-1], 'Signal_Score'] = 8.0 * xgb_conf if ml_signal == 'LONG' else -8.0 * xgb_conf
                        else:
                            # Conflicting signal: Technicals and ML disagree and ML is not extreme
                            log_message(f"✋ Conflicting Signal Neutralized: Technicals {current_signal} vs ML {ml_signal} (Low {xgb_conf:.2f} confidence conflict)")
                            df.loc[df.index[-1], 'Signal'] = 'Neutral'
                            df.loc[df.index[-1], 'Conflict_Neutralized'] = True
                            df.loc[df.index[-1], 'Signal_Score'] = 0.0
                        
                elif current_signal != 'Neutral':
                    trans_signal, trans_conf = predict_with_transformer(df)
                    if trans_signal is not None:
                        ml_signal = 'LONG' if trans_signal else 'SHORT'
                        log_message(f"Transformer prediction: {ml_signal} (Confidence: {trans_conf:.2f})")
                        
                        if ml_signal != current_signal and not df.get('Smart_Money_Override', pd.Series([False])).iloc[-1]:
                            if trans_conf >= 0.85:
                                log_message(f"🔥 Aladdin Transformer Overrule: {current_signal} -> {ml_signal} ({trans_conf:.2f} confidence)")
                                df.loc[df.index[-1], 'Signal'] = ml_signal
                                df.loc[df.index[-1], 'ML_Override'] = True
                                df.loc[df.index[-1], 'Signal_Score'] = 8.0 * trans_conf if ml_signal == 'LONG' else -8.0 * trans_conf
                            else:
                                log_message(f"✋ Conflicting Signal Neutralized (Transformer): {current_signal} vs ML {ml_signal} (Low {trans_conf:.2f} confidence conflict)")
                                df.loc[df.index[-1], 'Signal'] = 'Neutral'
                                df.loc[df.index[-1], 'Conflict_Neutralized'] = True
                                df.loc[df.index[-1], 'Signal_Score'] = 0.0
                            
        except Exception as e:
            log_message(f"ML prediction error: {e}")
    
    return df

def predict_with_transformer(df):
    """Generate predictions using transformer model with GPU support and confidence score"""
    try:
        news_text = generate_market_summary(df)
        inputs = tokenizer(news_text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        
        # Move inputs to GPU if available
        if GPU_INFO['available']:
            inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = transformer_model(**inputs)
            logits = outputs.logits
            if logits.shape[0] > 0 and logits.shape[1] >= 2:
                probs = torch.softmax(logits, dim=1)
                best_prob = probs.max().item()
                # Confidence is the softmax probability of the winning class
                return (logits.argmax().item() == 1), best_prob
            else:
                log_message("Invalid transformer output shape")
                return None, 0.0
    except Exception as e:
        log_message(f"Transformer prediction error: {e}")
        return None, 0.0

def log_detailed_analysis(pair, df):
    """Log comprehensive analysis details for each trading pair"""
    try:
        latest = df.iloc[-1]
        
        # Basic price information
        log_message(f"=== DETAILED ANALYSIS FOR {pair} ===")
        log_message(f"Price Data - Open: {latest['open']:.6f}, High: {latest['high']:.6f}, Low: {latest['low']:.6f}, Close: {latest['close']:.6f}")
        log_message(f"Volume: {latest['volume']:.2f}")
        
        # Technical indicators analysis
        if 'RSI_14' in df.columns:
            log_message(f"RSI Analysis - RSI(14): {latest['RSI_14']:.2f}, RSI(21): {latest['RSI_21']:.2f}")
            rsi_signal = "Oversold" if latest['RSI_14'] < 30 else "Overbought" if latest['RSI_14'] > 70 else "Neutral"
            log_message(f"RSI Signal: {rsi_signal}")
        
        # MACD analysis
        if 'MACD Line' in df.columns:
            log_message(f"MACD Analysis - Line: {latest['MACD Line']:.6f}, Signal: {latest['Signal Line']:.6f}, Histogram: {latest['MACD Histogram']:.6f}")
            macd_trend = "Bullish" if latest['MACD Histogram'] > 0 else "Bearish"
            log_message(f"MACD Trend: {macd_trend}")
        
        # Bollinger Bands analysis
        if 'Upper Band' in df.columns:
            bb_range = latest['Upper Band'] - latest['Lower Band']
            if bb_range > 0:
                bb_position = (latest['close'] - latest['Lower Band']) / bb_range
                log_message(f"Bollinger Bands - Upper: {latest['Upper Band']:.6f}, Middle: {latest['SMA']:.6f}, Lower: {latest['Lower Band']:.6f}")
                log_message(f"BB Position: {bb_position:.3f} (0=Lower, 0.5=Middle, 1=Upper)")
            else:
                log_message(f"Bollinger Bands - Upper: {latest['Upper Band']:.6f}, Middle: {latest['SMA']:.6f}, Lower: {latest['Lower Band']:.6f}")
                log_message("BB Position: Invalid (zero range)")
            
            if latest['close'] > latest['Upper Band']:
                bb_signal = "Above Upper Band (Potential Sell)"
            elif latest['close'] < latest['Lower Band']:
                bb_signal = "Below Lower Band (Potential Buy)"
            else:
                bb_signal = "Within Bands (Neutral)"
            log_message(f"BB Signal: {bb_signal}")
        
        # VWAP analysis
        if 'VWAP' in df.columns:
            vwap_position = "Above" if latest['close'] > latest['VWAP'] else "Below"
            log_message(f"VWAP Analysis - VWAP: {latest['VWAP']:.6f}, Price vs VWAP: {vwap_position}")
        
        # Ichimoku analysis
        if 'tenkan_sen' in df.columns:
            log_message(f"Ichimoku - Tenkan: {latest['tenkan_sen']:.6f}, Kijun: {latest['kijun_sen']:.6f}")
            if not pd.isna(latest['senkou_span_a']) and not pd.isna(latest['senkou_span_b']):
                cloud_top = max(latest['senkou_span_a'], latest['senkou_span_b'])
                cloud_bottom = min(latest['senkou_span_a'], latest['senkou_span_b'])
                if latest['close'] > cloud_top:
                    cloud_position = "Above Cloud (Bullish)"
                elif latest['close'] < cloud_bottom:
                    cloud_position = "Below Cloud (Bearish)"
                else:
                    cloud_position = "Inside Cloud (Neutral)"
                log_message(f"Ichimoku Cloud Position: {cloud_position}")
        
        # Advanced momentum indicators
        if 'STOCH_K' in df.columns:
            log_message(f"Stochastic - K: {latest['STOCH_K']:.2f}, D: {latest['STOCH_D']:.2f}")
            stoch_signal = "Oversold" if latest['STOCH_K'] < 20 else "Overbought" if latest['STOCH_K'] > 80 else "Neutral"
            log_message(f"Stochastic Signal: {stoch_signal}")
        
        if 'ADX' in df.columns:
            log_message(f"ADX Analysis - ADX: {latest['ADX']:.2f}, +DI: {latest['PLUS_DI']:.2f}, -DI: {latest['MINUS_DI']:.2f}")
            trend_strength = "Strong" if latest['ADX'] > 25 else "Weak"
            trend_direction = "Bullish" if latest['PLUS_DI'] > latest['MINUS_DI'] else "Bearish"
            log_message(f"Trend: {trend_strength} {trend_direction}")
        
        if 'MFI' in df.columns:
            log_message(f"Money Flow Index: {latest['MFI']:.2f}")
            mfi_signal = "Oversold" if latest['MFI'] < 20 else "Overbought" if latest['MFI'] > 80 else "Neutral"
            log_message(f"MFI Signal: {mfi_signal}")
        
        # Volume analysis
        if 'AD' in df.columns:
            log_message(f"Volume Indicators - A/D Line: {latest['AD']:.2f}, OBV: {talib.OBV(df['close'].values, df['volume'].values)[-1]:.2f}")
        
        # Volatility analysis
        if 'ATR' in df.columns:
            log_message(f"Volatility - ATR: {latest['ATR']:.6f}, NATR: {latest['NATR']:.4f}")
            volatility_level = "High" if latest['ATR'] > df['ATR'].rolling(20).mean().iloc[-1] * 1.5 else "Normal"
            log_message(f"Volatility Level: {volatility_level}")
        
        # Pattern analysis
        if 'Pattern' in df.columns and latest['Pattern'] != 'None':
            log_message(f"Candlestick Pattern: {latest['Pattern']} ({latest['Pattern_Type']}) - Strength: {latest['Pattern_Strength']}")
        
        # Moving averages analysis
        if 'SMA_20' in df.columns:
            ma_analysis = []
            if latest['close'] > latest['SMA_20']:
                ma_analysis.append("Above SMA20")
            if latest['close'] > latest['SMA_50']:
                ma_analysis.append("Above SMA50")
            if 'SMA_200' in df.columns and latest['close'] > latest['SMA_200']:
                ma_analysis.append("Above SMA200")
            
            log_message(f"Moving Average Position: {', '.join(ma_analysis) if ma_analysis else 'Below major MAs'}")
            
            # Golden/Death cross analysis
            if 'SMA_50' in df.columns and 'SMA_200' in df.columns:
                if latest['SMA_50'] > latest['SMA_200']:
                    cross_status = "Golden Cross (Bullish)"
                else:
                    cross_status = "Death Cross (Bearish)"
                log_message(f"MA Cross Status: {cross_status}")
        
        # Support/Resistance levels
        recent_high = df['high'].rolling(20).max().iloc[-1]
        recent_low = df['low'].rolling(20).min().iloc[-1]
        log_message(f"Support/Resistance - 20-period High: {recent_high:.6f}, Low: {recent_low:.6f}")
        
        # Price action analysis
        price_change_1d = ((latest['close'] - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100 if len(df) > 1 else 0
        price_change_5d = ((latest['close'] - df['close'].iloc[-6]) / df['close'].iloc[-6]) * 100 if len(df) > 5 else 0
        log_message(f"Price Changes - 1D: {price_change_1d:.2f}%, 5D: {price_change_5d:.2f}%")
        
        # Volume analysis with comprehensive safety checks
        try:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            if pd.notna(avg_volume) and avg_volume > 0 and pd.notna(latest['volume']) and latest['volume'] > 0:
                volume_ratio = latest['volume'] / avg_volume
                volume_status = "High" if volume_ratio > 1.5 else "Low" if volume_ratio < 0.5 else "Normal"
                log_message(f"Volume Analysis - Current: {latest['volume']:.2f}, 20-day Avg: {avg_volume:.2f}, Status: {volume_status}")
            else:
                avg_volume_safe = avg_volume if pd.notna(avg_volume) else 0
                current_volume_safe = latest['volume'] if pd.notna(latest['volume']) else 0
                log_message(f"Volume Analysis - Current: {current_volume_safe:.2f}, 20-day Avg: {avg_volume_safe:.2f}, Status: Unknown")
        except Exception as e:
            log_message(f"Volume analysis error: {e}")
        
        log_message(f"=== END ANALYSIS FOR {pair} ===")
        
    except Exception as e:
        log_message(f"Error in detailed analysis logging for {pair}: {e}")
