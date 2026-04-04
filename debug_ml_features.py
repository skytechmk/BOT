#!/usr/bin/env python3
"""
Debug script to identify issues with ML feature preparation
"""

import sys
import os
import pandas as pd
import numpy as np
import talib
from datetime import datetime

def create_comprehensive_sample_data():
    """Create sample data with all required technical indicators"""
    try:
        # Create sample OHLCV data
        dates = pd.date_range(start='2024-01-01', periods=200, freq='D')  # More data points
        np.random.seed(42)  # For reproducible results
        
        # Generate realistic price data
        base_price = 45000
        price_changes = np.random.normal(0, 0.02, 200)  # 2% daily volatility
        prices = [base_price]
        
        for change in price_changes[1:]:
            new_price = prices[-1] * (1 + change)
            prices.append(new_price)
        
        # Create OHLCV data
        sample_data = pd.DataFrame(index=dates)
        sample_data['close'] = prices
        sample_data['open'] = sample_data['close'].shift(1) * (1 + np.random.normal(0, 0.005, 200))
        sample_data['high'] = np.maximum(sample_data['open'], sample_data['close']) * (1 + np.random.uniform(0, 0.01, 200))
        sample_data['low'] = np.minimum(sample_data['open'], sample_data['close']) * (1 - np.random.uniform(0, 0.01, 200))
        sample_data['volume'] = np.random.uniform(1000, 10000, 200)
        
        # Fill NaN values
        sample_data = sample_data.fillna(method='bfill')
        
        print(f"✅ Created sample OHLCV data with {len(sample_data)} rows")
        return sample_data
        
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
        return None

def add_technical_indicators(df):
    """Add all technical indicators that the ML feature preparation expects"""
    try:
        # Import functions from the main script
        sys.path.append('.')
        from main import (
            calculate_bollinger_bands, calculate_vwap, calculate_macd, 
            calculate_atr, calculate_ichimoku, calculate_advanced_indicators,
            detect_candlestick_patterns
        )
        
        print("Adding technical indicators...")
        
        # Add basic indicators
        df = calculate_bollinger_bands(df)
        print("  ✅ Bollinger Bands added")
        
        df = calculate_vwap(df)
        print("  ✅ VWAP added")
        
        df = calculate_macd(df)
        print("  ✅ MACD added")
        
        df = calculate_atr(df)
        print("  ✅ ATR added")
        
        df = calculate_ichimoku(df)
        print("  ✅ Ichimoku added")
        
        df = calculate_advanced_indicators(df)
        print("  ✅ Advanced indicators added")
        
        df = detect_candlestick_patterns(df)
        print("  ✅ Candlestick patterns added")
        
        print(f"✅ All technical indicators added. DataFrame shape: {df.shape}")
        print(f"   Columns: {list(df.columns)}")
        
        return df
        
    except Exception as e:
        print(f"❌ Error adding technical indicators: {e}")
        import traceback
        traceback.print_exc()
        return df

def test_feature_preparation_detailed():
    """Test feature preparation with detailed debugging"""
    try:
        # Import the feature preparation function
        sys.path.append('.')
        from main import prepare_ml_features
        
        # Create comprehensive sample data
        sample_data = create_comprehensive_sample_data()
        if sample_data is None:
            return None
            
        # Add all technical indicators
        sample_data = add_technical_indicators(sample_data)
        
        print("\nTesting feature preparation...")
        print(f"Input DataFrame shape: {sample_data.shape}")
        print(f"Input columns: {len(sample_data.columns)}")
        
        # Check for NaN values
        nan_count = sample_data.isnull().sum().sum()
        print(f"NaN values in input: {nan_count}")
        
        if nan_count > 0:
            print("NaN values by column:")
            for col in sample_data.columns:
                nan_col = sample_data[col].isnull().sum()
                if nan_col > 0:
                    print(f"  {col}: {nan_col}")
        
        # Prepare features
        features = prepare_ml_features(sample_data)
        
        if features is not None and not features.empty:
            print(f"✅ Feature preparation successful!")
            print(f"   Output shape: {features.shape}")
            print(f"   Features: {len(features.columns)}")
            print(f"   Sample features: {list(features.columns)[:15]}")
            
            # Check for NaN values in features
            feature_nan_count = features.isnull().sum().sum()
            print(f"   NaN values in features: {feature_nan_count}")
            
            return features
        else:
            print("❌ Feature preparation returned empty DataFrame")
            return None
            
    except Exception as e:
        print(f"❌ Error in detailed feature preparation test: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_ml_prediction_with_real_features():
    """Test ML prediction with properly prepared features"""
    try:
        import xgboost as xgb
        
        # Load model
        if not os.path.exists('signal_model.ubj'):
            print("❌ Model file not found")
            return False
            
        model = xgb.Booster()
        model.load_model('signal_model.ubj')
        print("✅ Model loaded successfully")
        
        # Get features
        features = test_feature_preparation_detailed()
        if features is None or features.empty:
            print("❌ Cannot test prediction - no features available")
            return False
        
        # Make prediction
        print("\nTesting ML prediction...")
        dmatrix = xgb.DMatrix(features.iloc[-1:])  # Use last row
        prediction = model.predict(dmatrix)
        
        print(f"✅ ML prediction successful!")
        print(f"   Raw prediction: {prediction[0]:.6f}")
        print(f"   Signal: {'BUY' if prediction[0] > 0.5 else 'SELL'}")
        print(f"   Confidence: {abs(prediction[0] - 0.5) * 2:.2%}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in ML prediction test: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run detailed ML debugging"""
    print("=" * 70)
    print("DETAILED MACHINE LEARNING DEBUG TEST")
    print("=" * 70)
    print(f"Test started at: {datetime.now()}")
    print()
    
    # Test feature preparation in detail
    print("1. Testing detailed feature preparation...")
    features = test_feature_preparation_detailed()
    print()
    
    # Test ML prediction with real features
    print("2. Testing ML prediction with real features...")
    prediction_success = test_ml_prediction_with_real_features()
    print()
    
    print("=" * 70)
    if features is not None and not features.empty and prediction_success:
        print("✅ MACHINE LEARNING IS FULLY WORKING!")
        print("   All components are operational.")
    elif features is not None and not features.empty:
        print("⚠️  MACHINE LEARNING PARTIALLY WORKING")
        print("   Feature preparation works, but prediction has issues.")
    else:
        print("❌ MACHINE LEARNING HAS ISSUES")
        print("   Feature preparation is failing.")
    
    print("=" * 70)

if __name__ == "__main__":
    main()
