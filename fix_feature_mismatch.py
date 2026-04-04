#!/usr/bin/env python3
"""
Fix Feature Mismatch Error by Retraining Model with Consistent Features
"""

import os
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from joblib import dump
import time

def log_message(message):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}")

def retrain_model_with_consistent_features():
    """Retrain the model to fix feature mismatch"""
    try:
        log_message("Starting model retraining to fix feature mismatch...")
        
        # Import the main functions
        from binance_hunter_talib import (
            fetch_data, calculate_bollinger_bands, calculate_vwap, 
            calculate_macd, calculate_atr, calculate_ichimoku,
            calculate_advanced_indicators, detect_candlestick_patterns,
            prepare_ml_features, generate_training_labels
        )
        
        # Training pairs
        training_pairs = [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT'
        ]
        
        all_features = []
        all_labels = []
        
        for pair in training_pairs:
            try:
                log_message(f"Processing {pair}...")
                
                # Fetch data
                df = fetch_data(pair, '1h', retries=3)
                if df.empty or len(df) < 200:
                    log_message(f"Insufficient data for {pair}")
                    continue
                
                # Calculate all indicators in the same order as current system
                log_message(f"Calculating basic indicators for {pair}...")
                df = calculate_bollinger_bands(df)
                df = calculate_vwap(df)
                df = calculate_macd(df)
                df = calculate_atr(df)
                df = calculate_ichimoku(df)
                
                log_message(f"Calculating advanced indicators for {pair}...")
                df = calculate_advanced_indicators(df)
                
                log_message(f"Detecting patterns for {pair}...")
                df = detect_candlestick_patterns(df)
                
                log_message(f"Preparing features for {pair}...")
                # Prepare features using current system
                features = prepare_ml_features(df)
                log_message(f"Generated {len(features.columns) if not features.empty else 0} features for {pair}")
                if features.empty:
                    log_message(f"No features for {pair}")
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
                    
                    log_message(f"Added {min_len} samples from {pair} with {len(features.columns)} features")
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                log_message(f"Error processing {pair}: {e}")
                continue
        
        if not all_features:
            log_message("No training data collected")
            return False
        
        # Combine all data
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)
        
        log_message(f"Total samples: {len(X)}, Features: {len(X.columns)}")
        log_message(f"Feature columns: {list(X.columns)}")
        
        # Clean data
        X = X.replace([np.inf, -np.inf], np.nan)
        X = X.fillna(X.median())
        X = X.fillna(0)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Train XGBoost model
        log_message("Training XGBoost model...")
        params = {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'random_state': 42
        }
        
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)
        
        model = xgb.train(
            params, 
            dtrain, 
            num_boost_round=200,
            evals=[(dtrain, 'train'), (dtest, 'test')],
            early_stopping_rounds=20,
            verbose_eval=False
        )
        
        # Evaluate
        train_preds = model.predict(dtrain) > 0.5
        test_preds = model.predict(dtest) > 0.5
        
        train_acc = accuracy_score(y_train, train_preds)
        test_acc = accuracy_score(y_test, test_preds)
        
        log_message(f"Model performance - Train: {train_acc:.3f}, Test: {test_acc:.3f}")
        
        # Save model
        model.save_model('signal_model.ubj')
        log_message("Model saved to signal_model.ubj")
        
        # Also save ensemble format for compatibility
        models = {
            'xgboost': {
                'model': model,
                'train_acc': train_acc,
                'test_acc': test_acc,
                'type': 'xgboost'
            }
        }
        dump(models, 'ensemble_models.joblib')
        log_message("Ensemble models saved")
        
        return True
        
    except Exception as e:
        log_message(f"Error in model retraining: {e}")
        return False

if __name__ == "__main__":
    success = retrain_model_with_consistent_features()
    if success:
        print("✅ Model retraining completed successfully!")
        print("The feature mismatch error should now be resolved.")
    else:
        print("❌ Model retraining failed!")
