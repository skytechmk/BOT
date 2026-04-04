#!/usr/bin/env python3
"""
Test script for the Multi-Timeframe ML System
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
import time

# Add current directory to path
sys.path.append('.')

def test_system_initialization():
    """Test Multi-Timeframe ML System initialization"""
    print("=" * 70)
    print("TESTING MULTI-TIMEFRAME ML SYSTEM INITIALIZATION")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        print("🔄 Initializing Multi-Timeframe ML System...")
        ml_system = initialize_ml_system()
        
        if ml_system:
            print("✅ Multi-Timeframe ML System initialized successfully!")
            print(f"   Timeframes: {ml_system.timeframes}")
            print(f"   Auto-retrain interval: {ml_system.config['retrain_interval']/3600} hours")
            print(f"   Model directory: {ml_system.model_dir}")
            print(f"   Performance directory: {ml_system.performance_dir}")
            return True
        else:
            print("❌ Multi-Timeframe ML System initialization failed!")
            return False
            
    except Exception as e:
        print(f"❌ Error during initialization: {e}")
        return False

def test_data_fetching():
    """Test multi-timeframe data fetching"""
    print("\n" + "=" * 70)
    print("TESTING MULTI-TIMEFRAME DATA FETCHING")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        ml_system = initialize_ml_system()
        
        print("🔄 Testing data fetching for BTCUSDT...")
        timeframe_data = ml_system.fetch_multi_timeframe_data('BTCUSDT', limit=100)
        
        if timeframe_data:
            print("✅ Multi-timeframe data fetched successfully!")
            for tf, df in timeframe_data.items():
                print(f"   {tf}: {len(df)} records")
            return True
        else:
            print("❌ No data fetched!")
            return False
            
    except Exception as e:
        print(f"❌ Error during data fetching: {e}")
        return False

def test_feature_calculation():
    """Test comprehensive feature calculation"""
    print("\n" + "=" * 70)
    print("TESTING COMPREHENSIVE FEATURE CALCULATION")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        ml_system = initialize_ml_system()
        
        print("🔄 Testing feature calculation for BTCUSDT 1h...")
        timeframe_data = ml_system.fetch_multi_timeframe_data('BTCUSDT', limit=200)
        
        if '1h' in timeframe_data:
            features = ml_system.calculate_comprehensive_features(timeframe_data['1h'], '1h')
            
            if not features.empty:
                print("✅ Features calculated successfully!")
                print(f"   Features shape: {features.shape}")
                print(f"   Feature columns: {len(features.columns)}")
                print(f"   Sample features: {list(features.columns)[:10]}")
                return True
            else:
                print("❌ No features calculated!")
                return False
        else:
            print("❌ No 1h data available!")
            return False
            
    except Exception as e:
        print(f"❌ Error during feature calculation: {e}")
        return False

def test_label_generation():
    """Test multi-timeframe label generation"""
    print("\n" + "=" * 70)
    print("TESTING MULTI-TIMEFRAME LABEL GENERATION")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        ml_system = initialize_ml_system()
        
        print("🔄 Testing label generation for BTCUSDT...")
        timeframe_data = ml_system.fetch_multi_timeframe_data('BTCUSDT', limit=200)
        
        if timeframe_data:
            labels = ml_system.generate_multi_timeframe_labels(timeframe_data)
            
            if labels:
                print("✅ Labels generated successfully!")
                for tf, label_series in labels.items():
                    unique_labels = label_series.value_counts()
                    print(f"   {tf}: {len(label_series)} labels, distribution: {unique_labels.to_dict()}")
                return True
            else:
                print("❌ No labels generated!")
                return False
        else:
            print("❌ No timeframe data available!")
            return False
            
    except Exception as e:
        print(f"❌ Error during label generation: {e}")
        return False

def test_correlation_analysis():
    """Test timeframe correlation analysis"""
    print("\n" + "=" * 70)
    print("TESTING TIMEFRAME CORRELATION ANALYSIS")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        ml_system = initialize_ml_system()
        
        print("🔄 Testing correlation analysis for BTCUSDT...")
        timeframe_data = ml_system.fetch_multi_timeframe_data('BTCUSDT', limit=200)
        
        if timeframe_data:
            correlations = ml_system.calculate_timeframe_correlations(timeframe_data)
            
            if correlations:
                print("✅ Correlations calculated successfully!")
                for tf1, corr_dict in correlations.items():
                    for tf2, corr_value in corr_dict.items():
                        print(f"   {tf1} vs {tf2}: {corr_value:.3f}")
                return True
            else:
                print("❌ No correlations calculated!")
                return False
        else:
            print("❌ No timeframe data available!")
            return False
            
    except Exception as e:
        print(f"❌ Error during correlation analysis: {e}")
        return False

def test_model_training():
    """Test model training for a single timeframe"""
    print("\n" + "=" * 70)
    print("TESTING MODEL TRAINING (SINGLE TIMEFRAME)")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import initialize_ml_system
        
        ml_system = initialize_ml_system()
        
        print("🔄 Testing model training for 1h timeframe...")
        
        # Get data for training
        timeframe_data = ml_system.fetch_multi_timeframe_data('BTCUSDT', limit=500)
        
        if '1h' in timeframe_data:
            # Calculate features
            features = ml_system.calculate_comprehensive_features(timeframe_data['1h'], '1h')
            
            # Generate labels
            labels = ml_system.generate_multi_timeframe_labels({'1h': timeframe_data['1h']})
            
            if not features.empty and '1h' in labels:
                print(f"   Training data: {len(features)} samples, {len(features.columns)} features")
                
                # Train model
                models = ml_system.train_timeframe_model(features, labels['1h'], '1h')
                
                if models:
                    print("✅ Model training successful!")
                    for model_name, model_info in models.items():
                        print(f"   {model_name}: accuracy {model_info['accuracy']:.3f}")
                    return True
                else:
                    print("❌ Model training failed!")
                    return False
            else:
                print("❌ Insufficient training data!")
                return False
        else:
            print("❌ No 1h data available!")
            return False
            
    except Exception as e:
        print(f"❌ Error during model training: {e}")
        return False

def test_prediction():
    """Test multi-timeframe prediction"""
    print("\n" + "=" * 70)
    print("TESTING MULTI-TIMEFRAME PREDICTION")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import get_multi_timeframe_prediction
        
        print("🔄 Testing multi-timeframe prediction for BTCUSDT...")
        
        prediction = get_multi_timeframe_prediction('BTCUSDT')
        
        if prediction:
            print("✅ Multi-timeframe prediction successful!")
            print(f"   Symbol: {prediction['symbol']}")
            print(f"   Timestamp: {prediction['timestamp']}")
            
            if 'consensus' in prediction and prediction['consensus']:
                consensus = prediction['consensus']
                print(f"   Consensus Signal: {consensus['signal']}")
                print(f"   Consensus Confidence: {consensus['confidence']:.1%}")
                print(f"   Participating Timeframes: {consensus['participating_timeframes']}")
            
            if 'timeframe_predictions' in prediction:
                print("   Individual Timeframe Predictions:")
                for tf, pred in prediction['timeframe_predictions'].items():
                    print(f"     {tf}: {pred['signal']} (confidence: {pred['confidence']:.1%})")
            
            return True
        else:
            print("❌ Multi-timeframe prediction failed!")
            return False
            
    except Exception as e:
        print(f"❌ Error during prediction: {e}")
        return False

def test_self_learning():
    """Test self-learning system"""
    print("\n" + "=" * 70)
    print("TESTING SELF-LEARNING SYSTEM")
    print("=" * 70)
    
    try:
        from multi_timeframe_ml_system import update_prediction_outcome
        
        print("🔄 Testing self-learning update...")
        
        # Simulate prediction outcome
        update_prediction_outcome('BTCUSDT', 'BUY', 'BUY', '1h')
        update_prediction_outcome('BTCUSDT', 'SELL', 'BUY', '1h')  # Wrong prediction
        update_prediction_outcome('BTCUSDT', 'BUY', 'BUY', '4h')
        
        print("✅ Self-learning updates completed!")
        print("   Added 3 prediction outcomes to learning system")
        return True
            
    except Exception as e:
        print(f"❌ Error during self-learning test: {e}")
        return False

def test_integration_with_main_bot():
    """Test integration with main trading bot"""
    print("\n" + "=" * 70)
    print("TESTING INTEGRATION WITH MAIN TRADING BOT")
    print("=" * 70)
    
    try:
        # Test if main bot can import and use the system
        from binance_hunter_talib import MULTI_TF_ML_AVAILABLE
        
        if MULTI_TF_ML_AVAILABLE:
            print("✅ Multi-Timeframe ML System is available in main bot!")
            
            # Test importing functions
            from binance_hunter_talib import (
                initialize_ml_system, get_multi_timeframe_prediction,
                train_all_models, update_prediction_outcome
            )
            print("✅ All ML functions imported successfully!")
            return True
        else:
            print("❌ Multi-Timeframe ML System not available in main bot!")
            return False
            
    except Exception as e:
        print(f"❌ Error during integration test: {e}")
        return False

def run_comprehensive_test():
    """Run all tests"""
    print("🚀 STARTING COMPREHENSIVE MULTI-TIMEFRAME ML SYSTEM TEST")
    print("=" * 70)
    print(f"Test started at: {datetime.now()}")
    print()
    
    tests = [
        ("System Initialization", test_system_initialization),
        ("Data Fetching", test_data_fetching),
        ("Feature Calculation", test_feature_calculation),
        ("Label Generation", test_label_generation),
        ("Correlation Analysis", test_correlation_analysis),
        ("Model Training", test_model_training),
        ("Prediction", test_prediction),
        ("Self-Learning", test_self_learning),
        ("Integration", test_integration_with_main_bot)
    ]
    
    passed_tests = 0
    total_tests = len(tests)
    
    for test_name, test_func in tests:
        try:
            print(f"\n🧪 Running {test_name} test...")
            if test_func():
                passed_tests += 1
                print(f"✅ {test_name} test PASSED")
            else:
                print(f"❌ {test_name} test FAILED")
        except Exception as e:
            print(f"❌ {test_name} test ERROR: {e}")
    
    print("\n" + "=" * 70)
    print("COMPREHENSIVE TEST RESULTS")
    print("=" * 70)
    print(f"Tests passed: {passed_tests}/{total_tests}")
    print(f"Success rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED! Multi-Timeframe ML System is fully operational!")
    elif passed_tests >= total_tests * 0.8:
        print("✅ Most tests passed! System is mostly operational with minor issues.")
    elif passed_tests >= total_tests * 0.5:
        print("⚠️  Some tests passed! System has significant issues that need attention.")
    else:
        print("❌ Most tests failed! System requires major fixes before use.")
    
    print("=" * 70)
    return passed_tests == total_tests

if __name__ == "__main__":
    success = run_comprehensive_test()
    sys.exit(0 if success else 1)
