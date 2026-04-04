#!/usr/bin/env python3
"""
Test script to verify machine learning functionality in binance_hunter_talib.py
"""

import sys
import os
import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime

def test_model_loading():
    """Test if the XGBoost model can be loaded"""
    try:
        if os.path.exists('signal_model.ubj'):
            model = xgb.Booster()
            model.load_model('signal_model.ubj')
            print("✅ XGBoost model loaded successfully")
            return model
        else:
            print("❌ Model file not found")
            return None
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return None

def test_feature_preparation():
    """Test feature preparation with sample data"""
    try:
        # Import the feature preparation function
        sys.path.append('.')
        from binance_hunter_talib import prepare_ml_features
        
        # Create sample data
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
        sample_data = pd.DataFrame({
            'open': np.random.uniform(40000, 50000, 100),
            'high': np.random.uniform(50000, 55000, 100),
            'low': np.random.uniform(35000, 40000, 100),
            'close': np.random.uniform(40000, 50000, 100),
            'volume': np.random.uniform(1000, 10000, 100)
        }, index=dates)
        
        # Add some technical indicators that the function expects
        sample_data['RSI_14'] = np.random.uniform(20, 80, 100)
        sample_data['MACD Line'] = np.random.uniform(-100, 100, 100)
        sample_data['Signal Line'] = np.random.uniform(-100, 100, 100)
        sample_data['MACD Histogram'] = sample_data['MACD Line'] - sample_data['Signal Line']
        sample_data['Upper Band'] = sample_data['close'] * 1.02
        sample_data['Lower Band'] = sample_data['close'] * 0.98
        sample_data['SMA'] = sample_data['close']
        sample_data['VWAP'] = sample_data['close']
        sample_data['ATR'] = np.random.uniform(100, 1000, 100)
        
        features = prepare_ml_features(sample_data)
        
        if not features.empty:
            print(f"✅ Feature preparation working - Generated {len(features.columns)} features")
            print(f"   Sample features: {list(features.columns)[:10]}")
            return features
        else:
            print("❌ Feature preparation returned empty DataFrame")
            return None
            
    except Exception as e:
        print(f"❌ Error in feature preparation: {e}")
        return None

def test_ml_prediction():
    """Test ML prediction with sample features"""
    try:
        model = test_model_loading()
        features = test_feature_preparation()
        
        if model and features is not None and not features.empty:
            # Create DMatrix for prediction
            dmatrix = xgb.DMatrix(features.iloc[-1:])  # Use last row
            prediction = model.predict(dmatrix)
            
            print(f"✅ ML prediction working - Prediction: {prediction[0]:.4f}")
            print(f"   Signal: {'BUY' if prediction[0] > 0.5 else 'SELL'}")
            return True
        else:
            print("❌ Cannot test prediction - model or features unavailable")
            return False
            
    except Exception as e:
        print(f"❌ Error in ML prediction: {e}")
        return False

def test_transformer_components():
    """Test transformer model components"""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        
        # Test if transformer components can be loaded
        TRANSFORMER_MODEL = "distilbert-base-uncased"
        tokenizer = AutoTokenizer.from_pretrained(TRANSFORMER_MODEL)
        transformer_model = AutoModelForSequenceClassification.from_pretrained(TRANSFORMER_MODEL, num_labels=2)
        
        # Test tokenization and prediction
        test_text = "The market is showing bullish momentum with strong volume"
        inputs = tokenizer(test_text, return_tensors="pt", padding=True, truncation=True, max_length=512)
        
        with torch.no_grad():
            outputs = transformer_model(**inputs)
            logits = outputs.logits
            sentiment_probs = logits.softmax(dim=1)
            
        print("✅ Transformer model working")
        print(f"   Sentiment probabilities: {sentiment_probs[0].tolist()}")
        return True
        
    except Exception as e:
        print(f"❌ Error in transformer components: {e}")
        return False

def test_ensemble_models():
    """Test if ensemble models exist"""
    try:
        if os.path.exists('ensemble_models.joblib'):
            from joblib import load
            models = load('ensemble_models.joblib')
            print(f"✅ Ensemble models found - {len(models)} models available")
            for name, model_info in models.items():
                print(f"   - {name}: Test accuracy {model_info['test_acc']:.3f}")
            return True
        else:
            print("ℹ️  Ensemble models not found (using single XGBoost model)")
            return False
    except Exception as e:
        print(f"❌ Error checking ensemble models: {e}")
        return False

def main():
    """Run all ML functionality tests"""
    print("=" * 60)
    print("MACHINE LEARNING FUNCTIONALITY TEST")
    print("=" * 60)
    print(f"Test started at: {datetime.now()}")
    print()
    
    tests_passed = 0
    total_tests = 5
    
    print("1. Testing XGBoost model loading...")
    if test_model_loading():
        tests_passed += 1
    print()
    
    print("2. Testing feature preparation...")
    if test_feature_preparation() is not None:
        tests_passed += 1
    print()
    
    print("3. Testing ML prediction...")
    if test_ml_prediction():
        tests_passed += 1
    print()
    
    print("4. Testing transformer components...")
    if test_transformer_components():
        tests_passed += 1
    print()
    
    print("5. Testing ensemble models...")
    if test_ensemble_models():
        tests_passed += 1
    print()
    
    print("=" * 60)
    print(f"RESULTS: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed >= 3:
        print("✅ MACHINE LEARNING IS WORKING!")
        print("   Core ML functionality is operational.")
    elif tests_passed >= 1:
        print("⚠️  MACHINE LEARNING PARTIALLY WORKING")
        print("   Some components are working, others may need attention.")
    else:
        print("❌ MACHINE LEARNING NOT WORKING")
        print("   Major issues detected with ML components.")
    
    print("=" * 60)
    
    return tests_passed >= 3

if __name__ == "__main__":
    main()
