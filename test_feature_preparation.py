#!/usr/bin/env python3
"""
Test Feature Preparation to Debug Empty DataFrame Issue
"""

import pandas as pd
import numpy as np
import time

def log_message(message):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def test_feature_preparation():
    """Test feature preparation with sample data"""
    try:
        log_message("Testing feature preparation...")
        
        # Import the main functions
        from main import (
            calculate_bollinger_bands, calculate_vwap, 
            calculate_macd, calculate_atr, calculate_ichimoku,
            calculate_advanced_indicators, detect_candlestick_patterns,
            prepare_ml_features
        )
        
        # Create sample data
        dates = pd.date_range(start='2024-01-01', periods=500, freq='1H')
        np.random.seed(42)
        
        # Generate realistic price data
        base_price = 50000
        price_changes = np.random.normal(0, 0.02, 500)
        prices = [base_price]
        
        for change in price_changes[1:]:
            new_price = prices[-1] * (1 + change)
            prices.append(new_price)
        
        # Create OHLCV data
        df = pd.DataFrame({
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
            'close': prices,
            'volume': np.random.uniform(100, 1000, 500)
        }, index=dates)
        
        log_message(f"Created sample data with {len(df)} rows")
        log_message(f"Sample data columns: {list(df.columns)}")
        log_message(f"Sample data shape: {df.shape}")
        
        # Calculate indicators step by step
        log_message("Calculating Bollinger Bands...")
        df = calculate_bollinger_bands(df)
        
        log_message("Calculating VWAP...")
        df = calculate_vwap(df)
        
        log_message("Calculating MACD...")
        df = calculate_macd(df)
        
        log_message("Calculating ATR...")
        df = calculate_atr(df)
        
        log_message("Calculating Ichimoku...")
        df = calculate_ichimoku(df)
        
        log_message("Calculating advanced indicators...")
        df = calculate_advanced_indicators(df)
        
        log_message("Detecting patterns...")
        df = detect_candlestick_patterns(df)
        
        log_message(f"After indicators, DataFrame shape: {df.shape}")
        log_message(f"Columns after indicators: {len(df.columns)}")
        
        # Test feature preparation
        log_message("Testing feature preparation...")
        features = prepare_ml_features(df)
        
        if features.empty:
            log_message("❌ Feature preparation returned empty DataFrame")
            log_message("Debugging feature preparation...")
            
            # Check what's in the DataFrame
            log_message(f"Input DataFrame shape: {df.shape}")
            log_message(f"Input DataFrame columns: {list(df.columns)[:10]}...")
            log_message(f"Any NaN values: {df.isnull().sum().sum()}")
            log_message(f"Any inf values: {np.isinf(df.select_dtypes(include=[np.number])).sum().sum()}")
            
            return False
        else:
            log_message(f"✅ Feature preparation successful!")
            log_message(f"Generated {len(features.columns)} features")
            log_message(f"Feature DataFrame shape: {features.shape}")
            log_message(f"Sample features: {list(features.columns)[:10]}")
            
            # Check for issues
            nan_count = features.isnull().sum().sum()
            inf_count = np.isinf(features.select_dtypes(include=[np.number])).sum().sum()
            
            log_message(f"NaN values in features: {nan_count}")
            log_message(f"Inf values in features: {inf_count}")
            
            return True
            
    except Exception as e:
        log_message(f"Error in feature preparation test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_feature_preparation()
    if success:
        print("✅ Feature preparation test passed!")
    else:
        print("❌ Feature preparation test failed!")
