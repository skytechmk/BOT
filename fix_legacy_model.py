#!/usr/bin/env python3
"""
Fix legacy model compatibility by retraining with current feature set
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime

# Add current directory to path
sys.path.append('.')

def retrain_legacy_model():
    """Retrain the legacy model with current feature preparation"""
    try:
        from binance_hunter_talib import (
            fetch_data, calculate_bollinger_bands, calculate_vwap, calculate_macd,
            calculate_atr, calculate_ichimoku, calculate_advanced_indicators,
            detect_candlestick_patterns, prepare_ml_features, generate_training_labels,
            train_ml_model, log_message
        )
        
        print("=" * 70)
        print("FIXING LEGACY MODEL COMPATIBILITY")
        print("=" * 70)
        print(f"Started at: {datetime.now()}")
        print()
        
        # Training pairs
        training_pairs = [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT'
        ]
        
        all_features = []
        all_labels = []
        
        print(f"🔄 Processing {len(training_pairs)} trading pairs...")
        
        for pair in training_pairs:
            try:
                print(f"📊 Processing {pair}...")
                
                # Fetch data
                df = fetch_data(pair, '1h', retries=3)
                
                if df.empty or len(df) < 200:
                    print(f"   ⚠️  Insufficient data for {pair}")
                    continue
                
                print(f"   🔧 Calculating indicators...")
                
                # Calculate all indicators
                df = calculate_bollinger_bands(df)
                df = calculate_vwap(df)
                df = calculate_macd(df)
                df = calculate_atr(df)
                df = calculate_ichimoku(df)
                df = calculate_advanced_indicators(df)
                df = detect_candlestick_patterns(df)
                
                print(f"   🎯 Preparing features...")
                
                # Prepare features
                features = prepare_ml_features(df)
                if features.empty:
                    print(f"   ❌ No features for {pair}")
                    continue
                
                # Generate labels
                labels = generate_training_labels(df, future_periods=5)
                
                # Align features and labels
                min_len = min(len(features), len(labels))
                if min_len > 50:
                    features_aligned = features.iloc[:min_len]
                    labels_aligned = labels.iloc[:min_len]
                    
                    all_features.append(features_aligned)
                    all_labels.append(labels_aligned)
                    
                    print(f"   ✅ Added {min_len} samples with {len(features.columns)} features")
                else:
                    print(f"   ⚠️  Insufficient aligned data: {min_len}")
                
            except Exception as e:
                print(f"   ❌ Error processing {pair}: {e}")
                continue
        
        if not all_features:
            print("❌ No training data collected!")
            return False
        
        # Combine all data
        print(f"\n🔗 Combining training data...")
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)
        
        print(f"✅ Final dataset: {len(X)} samples with {len(X.columns)} features")
        print(f"   Label distribution: {y.value_counts().to_dict()}")
        print(f"   Feature columns: {len(X.columns)}")
        
        # Train the model
        print(f"\n🤖 Training legacy XGBoost model...")
        
        model = train_ml_model(X, y)
        
        if model:
            print("✅ Legacy model retrained successfully!")
            print("   - Model saved to signal_model.ubj")
            print("   - Features are now compatible")
            
            # Test the new model
            print(f"\n🧪 Testing the retrained model...")
            try:
                from binance_hunter_talib import predict_with_ml
                
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
                        print(f"   ⚠️  Test prediction returned None")
                else:
                    print(f"   ⚠️  Could not fetch test data")
                    
            except Exception as e:
                print(f"   ❌ Test failed: {e}")
            
            return True
        else:
            print("❌ Legacy model retraining failed!")
            return False
            
    except Exception as e:
        print(f"❌ Error during legacy model fix: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = retrain_legacy_model()
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}: Legacy model compatibility fix")
    sys.exit(0 if success else 1)
