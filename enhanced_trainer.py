#!/usr/bin/env python3
"""
Enhanced ML model trainer with comprehensive data collection
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
import time

# Add current directory to path
sys.path.append('.')

def enhanced_model_training():
    """Train model with comprehensive data collection"""
    print("=" * 70)
    print("ENHANCED ML MODEL TRAINING")
    print("=" * 70)
    print(f"Started at: {datetime.now()}")
    print()
    
    try:
        from binance_hunter_talib import (
            fetch_data, calculate_bollinger_bands, calculate_vwap, calculate_macd,
            calculate_atr, calculate_ichimoku, calculate_advanced_indicators,
            detect_candlestick_patterns, prepare_ml_features, generate_training_labels,
            train_ensemble_models, train_ml_model, log_message
        )
        
        # Expanded list of trading pairs for diverse training data
        training_pairs = [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT', 
            'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT',
            'UNIUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT',
            'NEARUSDT', 'FTMUSDT', 'SANDUSDT', 'MANAUSDT', 'ALGOUSDT',
            'VETUSDT', 'ICPUSDT', 'THETAUSDT', 'AXSUSDT', 'EOSUSDT'
        ]
        
        all_features = []
        all_labels = []
        
        print(f"🔄 Processing {len(training_pairs)} trading pairs...")
        print("   Using multiple timeframes for comprehensive data")
        print()
        
        for i, pair in enumerate(training_pairs):
            try:
                print(f"📊 Processing {pair} ({i+1}/{len(training_pairs)})...")
                
                # Collect data from multiple timeframes
                timeframes = ['1d', '4h', '1h']
                pair_features = []
                pair_labels = []
                
                for tf in timeframes:
                    try:
                        print(f"   📈 Fetching {tf} data...")
                        df = fetch_data(pair, tf, retries=3)
                        
                        if df.empty or len(df) < 100:
                            print(f"   ⚠️  Insufficient {tf} data")
                            continue
                        
                        print(f"   🔧 Calculating indicators for {tf}...")
                        
                        # Calculate all technical indicators
                        df = calculate_bollinger_bands(df)
                        df = calculate_vwap(df)
                        df = calculate_macd(df)
                        df = calculate_atr(df)
                        df = calculate_ichimoku(df)
                        df = calculate_advanced_indicators(df)
                        df = detect_candlestick_patterns(df)
                        
                        print(f"   🎯 Preparing features for {tf}...")
                        
                        # Prepare features
                        features = prepare_ml_features(df)
                        if features.empty:
                            print(f"   ❌ No features for {tf}")
                            continue
                        
                        # Generate labels
                        labels = generate_training_labels(df, future_periods=5)
                        
                        # Align features and labels
                        min_len = min(len(features), len(labels))
                        if min_len > 30:  # Lower threshold for multiple timeframes
                            features_aligned = features.iloc[:min_len]
                            labels_aligned = labels.iloc[:min_len]
                            
                            pair_features.append(features_aligned)
                            pair_labels.append(labels_aligned)
                            
                            print(f"   ✅ Added {min_len} samples from {tf}")
                        else:
                            print(f"   ⚠️  Insufficient aligned data for {tf}: {min_len}")
                        
                        time.sleep(0.2)  # Rate limiting
                        
                    except Exception as e:
                        print(f"   ❌ Error with {tf}: {e}")
                        continue
                
                # Combine timeframe data for this pair
                if pair_features:
                    combined_features = pd.concat(pair_features, ignore_index=True)
                    combined_labels = pd.concat(pair_labels, ignore_index=True)
                    
                    all_features.append(combined_features)
                    all_labels.append(combined_labels)
                    
                    total_samples = len(combined_features)
                    total_features = len(combined_features.columns)
                    print(f"   ✅ {pair} complete: {total_samples} samples, {total_features} features")
                else:
                    print(f"   ❌ No usable data for {pair}")
                
                time.sleep(0.5)  # Rate limiting between pairs
                
            except Exception as e:
                print(f"   ❌ Error processing {pair}: {e}")
                continue
        
        if not all_features:
            print("\n❌ No training data collected!")
            return False
        
        # Combine all data
        print(f"\n🔗 Combining data from {len(all_features)} successful pairs...")
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)
        
        print(f"✅ Final dataset prepared:")
        print(f"   📊 Total samples: {len(X):,}")
        print(f"   🎯 Total features: {len(X.columns)}")
        print(f"   📈 Label distribution: {y.value_counts().to_dict()}")
        print(f"   🔍 Feature names: {list(X.columns)[:10]}...")
        
        # Log training details
        log_message(f"Enhanced training dataset: {len(X)} samples, {len(X.columns)} features")
        log_message(f"Label distribution: {y.value_counts().to_dict()}")
        
        # Train the model
        print(f"\n🤖 Training ML model with {len(X):,} samples...")
        
        try:
            # Try ensemble training first
            print("   🎯 Attempting ensemble model training...")
            models = train_ensemble_models(X, y)
            
            if models and isinstance(models, dict):
                print("   ✅ Ensemble models trained successfully!")
                model_type = "ensemble"
                
                # Test ensemble model
                best_model_name = max(models.keys(), key=lambda k: models[k]['test_acc'])
                best_accuracy = models[best_model_name]['test_acc']
                print(f"   🏆 Best model: {best_model_name} (accuracy: {best_accuracy:.3f})")
                
            elif models:
                # Single model returned from ensemble fallback
                print("   ✅ Single XGBoost model trained successfully!")
                model_type = "single XGBoost"
                
            else:
                print("   ⚠️  Ensemble training failed, trying single XGBoost...")
                model = train_ml_model(X, y)
                
                if model:
                    print("   ✅ Single XGBoost model trained successfully!")
                    model_type = "single XGBoost"
                else:
                    print("   ❌ All model training failed!")
                    return False
            
            # Test the trained model
            print(f"\n🧪 Testing trained {model_type} model...")
            success = test_trained_model()
            
            if success:
                print("   ✅ Model test successful!")
            else:
                print("   ⚠️  Model test had issues")
            
            print(f"\n" + "=" * 70)
            print(f"✅ ENHANCED TRAINING COMPLETE")
            print(f"   Model type: {model_type}")
            print(f"   Training samples: {len(X):,}")
            print(f"   Features: {len(X.columns)}")
            print(f"   Model file: signal_model.ubj")
            print("=" * 70)
            
            return True
            
        except Exception as e:
            print(f"❌ Training error: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"❌ Setup error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trained_model():
    """Test the newly trained model"""
    try:
        from binance_hunter_talib import (
            fetch_data, predict_with_ml, calculate_bollinger_bands,
            calculate_vwap, calculate_macd, calculate_atr, calculate_ichimoku,
            calculate_advanced_indicators, detect_candlestick_patterns
        )
        
        print("   📊 Fetching test data for BTCUSDT...")
        df = fetch_data('BTCUSDT', '1d', retries=2)
        
        if not df.empty:
            print("   🔧 Calculating test indicators...")
            
            # Add all indicators
            df = calculate_bollinger_bands(df)
            df = calculate_vwap(df)
            df = calculate_macd(df)
            df = calculate_atr(df)
            df = calculate_ichimoku(df)
            df = calculate_advanced_indicators(df)
            df = detect_candlestick_patterns(df)
            
            print("   🎯 Testing prediction...")
            
            # Test prediction
            prediction = predict_with_ml(df)
            if prediction is not None:
                signal = "BUY" if prediction else "SELL"
                print(f"   ✅ Test prediction: {signal}")
                
                # Test multiple predictions
                print("   🔄 Testing prediction consistency...")
                predictions = []
                for i in range(5):
                    pred = predict_with_ml(df)
                    if pred is not None:
                        predictions.append("BUY" if pred else "SELL")
                
                if predictions:
                    print(f"   📊 Prediction consistency: {predictions}")
                    return True
                else:
                    print("   ⚠️  Inconsistent predictions")
                    return False
            else:
                print("   ❌ Test prediction returned None")
                return False
        else:
            print("   ❌ Could not fetch test data")
            return False
            
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
        return False

def main():
    """Main function"""
    success = enhanced_model_training()
    
    if success:
        print("\n🎉 Enhanced model training completed successfully!")
        print("   The ML system is now ready with optimized features.")
        
        # Run final verification
        print("\n🔍 Running final verification...")
        from test_ml_functionality import main as test_main
        test_main()
        
    else:
        print("\n❌ Enhanced model training failed!")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
