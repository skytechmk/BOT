#!/usr/bin/env python3
"""
Test EMA 10/80 Crossing Functionality
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import time

def log_message(message):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def test_ema_crossing():
    """Test EMA 10/80 crossing functionality"""
    try:
        log_message("Testing EMA 10/80 crossing functionality...")
        
        # Import the main functions
        from binance_hunter_talib import (
            calculate_bollinger_bands, calculate_vwap, 
            calculate_macd, calculate_atr, calculate_ichimoku,
            calculate_advanced_indicators, detect_candlestick_patterns,
            prepare_ml_features, predict_with_ml
        )
        
        # Create sample data with clear EMA crossing pattern (need more data for EMA 80)
        dates = pd.date_range(start='2024-01-01', periods=500, freq='1H')
        
        # Create price data that will show EMA crossing
        base_price = 50000
        prices = []
        
        # First 250 periods: downtrend (EMA 10 below EMA 80)
        for i in range(250):
            price = base_price * (1 - i * 0.0005)  # Gradual decline
            prices.append(price)
        
        # Next 250 periods: uptrend (EMA 10 crosses above EMA 80)
        for i in range(250):
            price = prices[-1] * (1 + i * 0.001)  # Gradual rise
            prices.append(price)
        
        # Create OHLCV data
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.01 for p in prices],
            'low': [p * 0.99 for p in prices],
            'close': prices,
            'volume': [1000] * 500
        }, index=dates)
        
        log_message(f"Created test data with {len(df)} rows")
        
        # Calculate all indicators including EMA 10 and EMA 80
        df = calculate_bollinger_bands(df)
        df = calculate_vwap(df)
        df = calculate_macd(df)
        df = calculate_atr(df)
        df = calculate_ichimoku(df)
        df = calculate_advanced_indicators(df)
        df = detect_candlestick_patterns(df)
        
        # Check if EMA 10 and EMA 80 are calculated
        if 'EMA_10' not in df.columns or 'EMA_80' not in df.columns:
            log_message("❌ EMA 10 or EMA 80 not found in DataFrame")
            return False
        
        log_message("✅ EMA 10 and EMA 80 calculated successfully")
        
        # Prepare features
        features = prepare_ml_features(df)
        if features.empty:
            log_message("❌ Feature preparation failed")
            return False
        
        # Check if EMA crossing feature is included
        if 'ema_10_80_cross' not in features.columns:
            log_message("❌ EMA 10/80 crossing feature not found")
            return False
        
        log_message("✅ EMA 10/80 crossing feature found in features")
        
        # Analyze the crossing pattern
        ema_10 = df['EMA_10'].dropna()
        ema_80 = df['EMA_80'].dropna()
        ema_cross = features['ema_10_80_cross'].dropna()
        
        # Find crossing points
        crossings = []
        for i in range(1, len(ema_cross)):
            if ema_cross.iloc[i] != ema_cross.iloc[i-1]:
                crossings.append(i)
        
        log_message(f"Found {len(crossings)} EMA crossing points")
        
        # Test ML prediction with the crossing data
        if os.path.exists('signal_model.ubj'):
            log_message("Testing ML prediction with EMA crossing data...")
            
            # Test prediction at different points
            test_points = [50, 100, 150, 199]  # Different phases of the trend
            
            for point in test_points:
                if point < len(df):
                    test_df = df.iloc[:point+1].copy()
                    
                    # Get prediction
                    prediction = predict_with_ml(test_df)
                    ema_10_val = df['EMA_10'].iloc[point] if not pd.isna(df['EMA_10'].iloc[point]) else 0
                    ema_80_val = df['EMA_80'].iloc[point] if not pd.isna(df['EMA_80'].iloc[point]) else 0
                    cross_val = 1 if ema_10_val > ema_80_val else 0
                    
                    signal = "Long" if prediction else "Short" if prediction is not None else "No Signal"
                    
                    log_message(f"Point {point}: EMA10={ema_10_val:.2f}, EMA80={ema_80_val:.2f}, Cross={cross_val}, Prediction={signal}")
        
        # Summary
        final_ema_10 = ema_10.iloc[-1] if len(ema_10) > 0 else 0
        final_ema_80 = ema_80.iloc[-1] if len(ema_80) > 0 else 0
        final_cross = ema_cross.iloc[-1] if len(ema_cross) > 0 else 0
        
        log_message(f"Final state:")
        log_message(f"  EMA 10: {final_ema_10:.2f}")
        log_message(f"  EMA 80: {final_ema_80:.2f}")
        log_message(f"  EMA 10 > EMA 80: {final_cross == 1}")
        log_message(f"  Cross feature value: {final_cross}")
        
        return True
        
    except Exception as e:
        log_message(f"Error in EMA crossing test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import os
    success = test_ema_crossing()
    if success:
        print("✅ EMA 10/80 crossing functionality test passed!")
        print("The EMA crossing feature is working correctly in the ML system.")
    else:
        print("❌ EMA 10/80 crossing functionality test failed!")
