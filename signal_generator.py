import pandas as pd
import numpy as np
import time
from datetime import datetime
from constants import *
from shared_state import *
from technical_indicators import *
from trading_utilities import generate_market_summary
# CE Hybrid params — single source of truth so signal_generator's CE_Direction /
# CE_Cloud_Direction match the Rust batch + reverse_hunt gate + ML features.
from reverse_hunt import (
    CE_LINE_ATR_LEN, CE_LINE_LOOKBACK, CE_LINE_MULT,
    CE_CLOUD_ATR_LEN, CE_CLOUD_LOOKBACK, CE_CLOUD_MULT,
)

def calculate_detailed_confidence(df, signal, total_score):
    """Calculate ultra-precise confidence percentage with exact 0.1% increments from 10.0% to 100.0%"""
    try:
        latest = df.iloc[-1]
        confidence_factors = []
        
        # Enhanced base confidence from signal strength (0-28%)
        # Max weighted: bb(1)+vwap(1.2)+cloud(1)+rsi(1.3)+pattern(2)+ce(2.5)+adx(1.8)+bor(2)+channel(0.8)+tsi(1.5)+lr(1.2) = 16.3
        max_possible_score = 16.3
        base_score = min(abs(total_score) / max_possible_score, 1.0) if max_possible_score > 0 else 0
        
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
                if signal.upper() == 'LONG' and rsi_val < 50:  # More balanced range for long
                    rsi_factor = (50 - rsi_val) / 50
                    rsi_divergence = abs(rsi_val - 35) * 0.08  # Divergence from oversold
                    rsi_confidence = min(rsi_factor * 16 + rsi_divergence, 16)
                elif signal.upper() == 'SHORT' and rsi_val > 50:  # More balanced range for short
                    rsi_factor = (rsi_val - 50) / 50
                    rsi_divergence = abs(rsi_val - 65) * 0.08  # Divergence from overbought
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
                # Enhanced volume analysis with trend confirmation
                if volume_ratio > 1.05:
                    # Volume spike strength
                    volume_spike = min((volume_ratio - 1) * 6, 8)
                    # Volume consistency (prefer moderate spikes over extreme)
                    if volume_ratio < 2.0:
                        volume_consistency = min(volume_ratio * 2, 3)
                    else:
                        volume_consistency = max(3 - (volume_ratio - 2.0) * 0.5, 0)  # Penalize extreme spikes
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
        
        # Log confidence breakdown only for non-neutral signals
        if signal.upper() != 'NEUTRAL':
            log_message(f"Confidence breakdown for {signal} signal:")
            for factor_name, factor_value in confidence_factors:
                log_message(f"  {factor_name}: {factor_value:.2f}%")
            log_message(f"  Final Confidence: {final_confidence:.1f}%")
        
        return final_confidence / 100  # Return as decimal
        
    except Exception as e:
        log_message(f"Error calculating detailed confidence: {e}")
        return 0.5  # Default 50% confidence

def calculate_kicko_indicator(df, pair=None, use_ml=True, regime=None, pair_tier=None):
    if not isinstance(df, pd.DataFrame) or df.empty:
        log_message("Invalid DataFrame input to calculate_kicko_indicator")
        return df  # Return the DataFrame as is

    # Phase 3: inject batch-pre-computed Rust indicators when available,
    # skipping ATR, Chandelier Exit, and Ichimoku recomputation entirely.
    if pair is not None:
        try:
            from rust_batch_processor import BATCH_PROCESSOR
            # Detect timeframe from df length heuristic (HTF dfs are shorter)
            tf_hint = '4h' if len(df) < 200 else '15m'
            df = BATCH_PROCESSOR.apply(df, pair, tf_hint)
        except Exception:
            pass
    
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
            df = calculate_chandelier_exit(
                df,
                atr_period=CE_LINE_ATR_LEN,
                mult=CE_LINE_MULT,
                lookback=CE_LINE_LOOKBACK,
            )
        if 'CE_Cloud_Direction' not in df.columns:
            df = calculate_chandelier_exit_cloud(
                df,
                cloud_atr_period=CE_CLOUD_ATR_LEN,
                cloud_mult=CE_CLOUD_MULT,
                cloud_lookback=CE_CLOUD_LOOKBACK,
            )
        if 'Pattern_Type' not in df.columns:
            df = detect_candlestick_patterns(df)
        if 'TSI' not in df.columns:
            df = calculate_tsi(df)
        if 'LR_Osc' not in df.columns:
            df = calculate_lr_oscillator(df)
        if 'ADX' not in df.columns:
            df = calculate_advanced_indicators(df)
    except Exception as e:
        log_message(f"Technical indicator calculation failed: {e}")
        return df
    
    # P0 ADX mandatory gate: neutralize all rows where ADX < 20 (weak trend / chop)
    # Winners avg ADX>25, losers avg ADX<18 — this prevents scoring weak setups entirely
    if 'ADX' in df.columns:
        df['_adx_ok'] = df['ADX'].fillna(0) >= 20
    else:
        df['_adx_ok'] = True  # ADX unavailable — allow scoring (non-blocking fallback)

    # More lenient signal logic with lower thresholds for more signals
    # Calculate individual signal scores
    bb_score = np.where(df['close'] < df['Lower Band'], 1,  # Oversold - bullish
                       np.where(df['close'] > df['Upper Band'], -1, 0))  # Overbought - bearish
    
    macd_score = np.where(df['MACD Histogram'] > 0, 1,  # MACD bullish (histogram positive)
                         np.where(df['MACD Histogram'] < 0, -1, 0))  # MACD bearish (histogram negative)
    
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
    
    # More balanced RSI thresholds (35/65 for better signal frequency)
    rsi_score = 0
    if 'RSI_14' in df.columns:
        rsi_score = np.where(df['RSI_14'] < 35, 1,  # Oversold
                            np.where(df['RSI_14'] > 65, -1, 0))  # Overbought
    
    # Pattern score
    pattern_score = np.zeros(len(df))
    if 'Pattern_Type' in df.columns:
        pattern_score = np.where(df['Pattern_Type'] == 'Bullish', 1,
                               np.where(df['Pattern_Type'] == 'Bearish', -1, 0))

    # ADX trend-strength score: rewards strong-trend setups, penalizes weak-trend noise
    # ADX>25 + DI direction aligned → +1.2 (strong confirmed trend)
    # ADX 20-25 → 0 (neutral)
    # ADX<20 → -0.5 (penalise — stops will be hit by chop)
    adx_score = np.zeros(len(df))
    if 'ADX' in df.columns and 'PLUS_DI' in df.columns and 'MINUS_DI' in df.columns:
        adx_strong = df['ADX'] > 25
        adx_weak = df['ADX'] < 20
        di_bullish = df['PLUS_DI'] > df['MINUS_DI']
        di_bearish = df['MINUS_DI'] > df['PLUS_DI']
        adx_score = np.where(adx_strong & di_bullish, 1.2,
                    np.where(adx_strong & di_bearish, -1.2,
                    np.where(adx_weak, -0.5, 0.0)))
                               
    # Chandelier Exit score — Hybrid Mode (line filtered by cloud)
    # Cloud layer (ATR 50, mult 5.0) acts as macro trend gate:
    #   line + cloud AGREE    → full score (±1.0)
    #   line + cloud DISAGREE → halved score (±0.5)  counter-trend caution
    #   line NEUTRAL          → 0
    ce_score = np.zeros(len(df))
    if 'CE_Direction' in df.columns:
        line_dir  = np.where(df['CE_Direction'] == 1, 1.0,
                    np.where(df['CE_Direction'] == -1, -1.0, 0.0))
        if 'CE_Cloud_Direction' in df.columns:
            cloud_dir = np.where(df['CE_Cloud_Direction'] == 1, 1.0,
                        np.where(df['CE_Cloud_Direction'] == -1, -1.0, 0.0))
            same_dir  = (line_dir == cloud_dir) & (line_dir != 0)
            diff_dir  = (line_dir != cloud_dir) & (line_dir != 0)
            ce_score  = np.where(same_dir, line_dir, np.where(diff_dir, line_dir * 0.5, 0.0))
        else:
            ce_score  = line_dir
    
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

    # Handle ADX score
    if hasattr(adx_score, '__len__'):
        adx_score = np.asarray(adx_score).flatten()[:df_len]
        if len(adx_score) != df_len:
            adx_score = np.resize(adx_score, df_len)
    else:
        adx_score = np.full(df_len, adx_score)
    
    # ── TSI Score (True Strength Index) ──────────────────────────────
    # TSI > 0 = bullish momentum, TSI < 0 = bearish
    # TSI_Hist (TSI - Signal) gives crossover direction
    if 'TSI_Hist' in df.columns:
        tsi_score = np.where(df['TSI_Hist'] > 0, 1,
                    np.where(df['TSI_Hist'] < 0, -1, 0)).astype(float)
    else:
        tsi_score = np.zeros(df_len)

    # ── LR Oscillator Score (Normalized Linear Regression Slope) ─────
    # LR_Osc > 0.5  = strong upslope  → bullish
    # LR_Osc < -0.5 = strong downslope → bearish
    # LR_Osc near 0 = choppy / neutral
    if 'LR_Osc' in df.columns:
        lr_arr = df['LR_Osc'].fillna(0).values
        lr_score = np.where(lr_arr > 1.0, 1,
                   np.where(lr_arr < -1.0, -1, 0)).astype(float)
    else:
        lr_score = np.zeros(df_len)

    # ── Breakout + Retest pattern score ──────────────────────────────
    # detect_breakout_retest returns scalar for last candle only
    # Apply it as a constant array (same value across all rows — last row is what matters)
    bor_score_val = 0.0
    channel_score_val = 0.0
    try:
        from technical_indicators import detect_breakout_retest
        bor_result = detect_breakout_retest(df)
        bor_score_val     = float(bor_result.get('breakout_score', 0.0))
        channel_slope     = float(bor_result.get('channel_slope', 0.0))
        channel_position  = float(bor_result.get('channel_position', 0.0))
        # Channel score: descending channel near lower bound = bullish setup
        #                ascending channel near upper bound  = bearish setup
        if channel_slope < -0.0001 and channel_position < -0.5:   # descending, near bottom
            channel_score_val = 1.0
        elif channel_slope > 0.0001 and channel_position > 0.5:   # ascending, near top
            channel_score_val = -1.0
        if bor_result['breakout_type'] != 'NONE':
            log_message(f"📐 Breakout/Retest: {bor_result['breakout_type']} at {bor_result['level']} (score={bor_score_val:+.1f})")
    except Exception:
        pass
    bor_score     = np.full(df_len, bor_score_val)
    channel_score = np.full(df_len, channel_score_val)

    # ── Adaptive weights per regime ──────────────────────────────────
    # Base weights (conservative defaults)
    weights = {
        'bb': 1.0,
        'macd': 0.0,     # disabled — TSI covers momentum (double-counting)
        'vwap': 1.2,
        'cloud': 1.0,
        'rsi': 1.3,
        'pattern': 2.0,
        'ce': 2.5,
        'adx': 1.8,
        'bor': 2.0,      # breakout+retest — high weight, rare but high accuracy
        'channel': 0.8,  # channel position — supplementary
        'tsi': 1.5,      # TSI: cleaner momentum than MACD
        'lr': 1.2,       # LR Oscillator: slope direction confirmation
    }
    # Regime-specific weight overrides
    _regime_name = (regime or {}).get('regime', 'NORMAL') if isinstance(regime, dict) else str(regime or '')
    if 'TREND' in _regime_name.upper():
        # Strong trend: CE and ADX are most reliable
        weights['ce']   = 3.2
        weights['adx']  = 2.5
        weights['cloud']= 1.5
        weights['bb']   = 0.6   # BB fires late in trends
        weights['rsi']  = 0.8   # RSI stays extended in trends
    elif 'RANG' in _regime_name.upper() or 'CHOP' in _regime_name.upper():
        # Ranging: mean-reversion indicators shine
        weights['bb']   = 2.0
        weights['rsi']  = 2.0
        weights['vwap'] = 1.8
        weights['ce']   = 1.5   # CE less reliable in chop
        weights['adx']  = 0.8
    elif 'VOLAT' in _regime_name.upper() or 'PANIC' in _regime_name.upper():
        # High volatility: breakouts + TSI most reliable
        weights['bor']  = 3.0
        weights['tsi']  = 2.2
        weights['lr']   = 1.8
        weights['rsi']  = 0.7   # RSI extremes misleading in panic
    
    # Calculate total score with weights
    # max: bb(1)+vwap(1.2)+cloud(1)+rsi(1.3)+pattern(2)+ce(2.5)+adx(1.8)+bor(2)+channel(0.8)+tsi(1.5)+lr(1.2) = 16.3
    total_score = (bb_score * weights['bb'] +
                   vwap_score * weights['vwap'] +
                   cloud_score * weights['cloud'] +
                   rsi_score * weights['rsi'] +
                   pattern_score * weights['pattern'] +
                   ce_score * weights['ce'] +
                   adx_score * weights['adx'] +
                   bor_score * weights['bor'] +
                   channel_score * weights['channel'] +
                   tsi_score * weights['tsi'] +
                   lr_score * weights['lr'])
    
    # P0: Apply ADX gate — zero out score where trend is too weak to trade
    adx_ok_mask = df['_adx_ok'].values if '_adx_ok' in df.columns else np.ones(df_len, dtype=bool)
    total_score = np.where(adx_ok_mask, total_score, 0.0)

    # ── Dynamic signal threshold ──────────────────────────────────────
    # Base: 3.5 (raised from 1.8 — filters ~60% of weak setups)
    # small_cap / high_risk require 6.0 (higher bar for volatile micro-caps)
    _base_threshold = 3.5
    if pair_tier in ('small_cap', 'high_risk'):
        # Extra ATR% check: if price moves >12% per candle, demand stronger consensus
        try:
            _atr_pct = float(df['ATR'].iloc[-1]) / float(df['close'].iloc[-1]) * 100
            if _atr_pct > 8.0:
                _base_threshold = 6.0
            elif _atr_pct > 5.0:
                _base_threshold = 4.5
        except Exception:
            _base_threshold = 5.0   # can't compute ATR% — be conservative

    signal_conditions = np.where(total_score >= _base_threshold, 'LONG',
                               np.where(total_score <= -_base_threshold, 'SHORT', 'NEUTRAL'))
    
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
    
    # Log signal generation details only for non-neutral signals
    latest_idx = df.index[-1]
    if signal_conditions[-1] != 'NEUTRAL':
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
            
            if base_signal.upper() != 'NEUTRAL':
                log_message(f"Running Smart Money analysis for signal: {base_signal}")
                
                # Perform smart money analysis
                smart_money_result = SMART_MONEY_ANALYZER.analyze_market_structure(df)
                
                if smart_money_result and 'signal' in smart_money_result:
                    smart_money_signal = smart_money_result['signal']
                    smart_money_confidence = smart_money_result.get('confidence', 0.0)
                    
                    log_message(f"Smart Money analysis: {smart_money_signal} (confidence: {smart_money_confidence:.2f})")
                    
                    # Check if smart money analysis agrees with base signal
                    sm_norm = smart_money_signal.upper() if smart_money_signal else ''
                    base_norm = base_signal.upper()
                    if sm_norm == base_norm:
                        # Smart money confirms the signal - boost confidence
                        log_message(f"Smart Money CONFIRMS {base_signal} signal")
                        # Add smart money confirmation to the dataframe
                        df.loc[df.index[-1], 'Smart_Money_Confirmation'] = True
                        df.loc[df.index[-1], 'Smart_Money_Confidence'] = smart_money_confidence
                    elif sm_norm in ['LONG', 'SHORT'] and smart_money_confidence > 0.7:
                        # Strong smart money signal that disagrees - override
                        log_message(f"Smart Money OVERRIDE: {base_signal} -> {sm_norm} (confidence: {smart_money_confidence:.2f})")
                        df.loc[df.index[-1], 'Signal'] = sm_norm
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

    return df


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
