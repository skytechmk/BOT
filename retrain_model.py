#!/usr/bin/env python3
"""
Script to retrain the ML model with the optimized feature preparation
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime

# Add current directory to path
sys.path.append('.')

def retrain_model():
    """Retrain the ML model with current feature preparation"""
    try:
        from binance_hunter_talib import train_model_with_historical_data, log_message
        
        print("=" * 60)
        print("RETRAINING ML MODEL WITH OPTIMIZED FEATURES")
        print("=" * 60)
        print(f"Started at: {datetime.now()}")
        print()
        
        # Clear any existing logs for this session
        log_message("=" * 50)
        log_message("STARTING MODEL RETRAINING SESSION")
        log_message("=" * 50)
        
        print("🤖 Starting comprehensive model training...")
        print("   This will fetch data from multiple trading pairs")
        print("   and train the model with the optimized feature set.")
        print()
        
        # Train the model
        model = train_model_with_historical_data()
        
        if model:
            print("✅ MODEL TRAINING SUCCESSFUL!")
            print("   - New model saved to signal_model.ubj")
            print("   - Features are now compatible with optimized preparation")
            print("   - ML predictions should work correctly")
            
            # Test the new model
            print("\n🧪 Testing the new model...")
            try:
                from binance_hunter_talib import fetch_data, prepare_ml_features, predict_with_ml
                from binance_hunter_talib import (calculate_bollinger_bands, calculate_vwap, 
                                                calculate_macd, calculate_atr, calculate_ichimoku,
                                                calculate_advanced_indicators, detect_candlestick_patterns)
                
                # Test with BTCUSDT data
                print("   Fetching test data for BTCUSDT...")
                df = fetch_data('BTCUSDT', '1d', retries=2)
                
                if not df.empty:
                    # Add all indicators
                    df = calculate_bollinger_bands(df)
                    df = calculate_vwap(df)
                    df = calculate_macd(df)
                    df = calculate_atr(df)
                    df = calculate_ichimoku(df)
                    df = calculate_advanced_indicators(df)
                    df = detect_candlestick_patterns(df)
                    
                    # Test prediction
                    prediction = predict_with_ml(df)
                    if prediction is not None:
                        signal = "BUY" if prediction else "SELL"
                        print(f"   ✅ Test prediction successful: {signal}")
                    else:
                        print("   ⚠️  Test prediction returned None")
                else:
                    print("   ⚠️  Could not fetch test data")
                    
            except Exception as e:
                print(f"   ❌ Test failed: {e}")
            
        else:
            print("❌ MODEL TRAINING FAILED!")
            print("   Check the debug log for details")
            return False
            
        print("\n" + "=" * 60)
        print("RETRAINING COMPLETE")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"❌ Error during retraining: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = retrain_model()
    sys.exit(0 if success else 1)
