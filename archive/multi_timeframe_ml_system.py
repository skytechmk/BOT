#!/usr/bin/env python3
"""
Multi-Timeframe ML System with Self-Learning and Auto-Retraining
Implements ML across all timeframes with pattern correlation analysis
"""

import sys
import os
import pandas as pd
import numpy as np
import xgboost as xgb
import pickle
import json
import time
import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier
from joblib import dump, load
import warnings
warnings.filterwarnings('ignore')

# Add current directory to path
sys.path.append('.')

class MultiTimeframeMLSystem:
    def __init__(self):
        self.timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']
        self.models = {}
        self.scalers = {}
        self.feature_importance = {}
        self.performance_metrics = {}
        self.correlation_matrix = {}
        self.self_learning_data = {}
        
        # Directories
        self.model_dir = Path("ml_models")
        self.data_dir = Path("historical_data")
        self.performance_dir = Path("performance_logs")
        
        # Create directories
        for dir_path in [self.model_dir, self.data_dir, self.performance_dir]:
            dir_path.mkdir(exist_ok=True)
        
        # Configuration
        self.config = {
            'retrain_interval': 6 * 3600,  # 6 hours in seconds
            'min_accuracy_threshold': 0.55,
            'correlation_threshold': 0.7,
            'max_features': 200,
            'ensemble_models': ['xgboost', 'random_forest', 'gradient_boosting'],
            'prediction_confidence_threshold': 0.6
        }
        
        # Load existing models and data
        self.load_existing_models()
        self.load_self_learning_data()
        
        # Start background retraining thread
        self.last_retrain_time = time.time()
        self.retrain_thread = threading.Thread(target=self._background_retraining, daemon=True)
        self.retrain_thread.start()
        
        print("🤖 Multi-Timeframe ML System initialized")
        print(f"   Timeframes: {self.timeframes}")
        print(f"   Auto-retrain interval: {self.config['retrain_interval']/3600} hours")
    
    def load_existing_models(self):
        """Load existing models for all timeframes"""
        try:
            for tf in self.timeframes:
                model_file = self.model_dir / f"model_{tf}.joblib"
                scaler_file = self.model_dir / f"scaler_{tf}.joblib"
                
                if model_file.exists():
                    self.models[tf] = load(model_file)
                    print(f"   ✅ Loaded model for {tf}")
                
                if scaler_file.exists():
                    self.scalers[tf] = load(scaler_file)
                    print(f"   ✅ Loaded scaler for {tf}")
        except Exception as e:
            print(f"   ⚠️  Error loading existing models: {e}")
    
    def load_self_learning_data(self):
        """Load self-learning performance data"""
        try:
            learning_file = self.performance_dir / "self_learning_data.json"
            if learning_file.exists():
                with open(learning_file, 'r') as f:
                    self.self_learning_data = json.load(f)
                print(f"   ✅ Loaded self-learning data with {len(self.self_learning_data)} entries")
        except Exception as e:
            print(f"   ⚠️  Error loading self-learning data: {e}")
            
    def get_ai_sentiment(self, symbol="BTCUSDT"):
        """Load latest AI sentiment analysis from OpenRouter if available"""
        try:
            # Import here to avoid circular dependencies
            from shared_state import OPENROUTER_INTEL, OPENROUTER_AVAILABLE
            
            if OPENROUTER_AVAILABLE:
                # Use cached or new narrative analysis
                # Ideally, we'd have a market context here, but we can fallback to generic
                sentiment_data = OPENROUTER_INTEL.cache.get(f"market_narrative_{datetime.now().strftime('%Y-%m-%d_%H')}")
                if not sentiment_data:
                    # Fallback to general systemic risk cache
                    sentiment_data = OPENROUTER_INTEL.cache.get(f"systemic_risk_{datetime.now().strftime('%Y-%m-%d_%H')}")
                
                return sentiment_data if sentiment_data else {}
        except Exception as e:
            print(f"   ⚠️  Error getting AI sentiment: {e}")
        return {}
    
    def save_self_learning_data(self):
        """Save self-learning performance data"""
        try:
            learning_file = self.performance_dir / "self_learning_data.json"
            with open(learning_file, 'w') as f:
                json.dump(self.self_learning_data, f, indent=2)
        except Exception as e:
            print(f"   ⚠️  Error saving self-learning data: {e}")
    
    def fetch_multi_timeframe_data(self, symbol, limit=1000):
        """Fetch data for all timeframes"""
        try:
            from main import fetch_data
            
            timeframe_data = {}
            for tf in self.timeframes:
                try:
                    df = fetch_data(symbol, tf, retries=3)
                    if not df.empty and len(df) >= 50:
                        timeframe_data[tf] = df.tail(limit)  # Keep recent data
                        print(f"   📊 {tf}: {len(timeframe_data[tf])} records")
                    else:
                        print(f"   ⚠️  Insufficient data for {tf}")
                    time.sleep(0.2)  # Rate limiting
                except Exception as e:
                    print(f"   ❌ Error fetching {tf} data: {e}")
                    continue
            
            return timeframe_data
        except Exception as e:
            print(f"❌ Error in multi-timeframe data fetch: {e}")
            return {}
    
    def calculate_comprehensive_features(self, df, timeframe, symbol="BTCUSDT"):
        """Calculate comprehensive features for a specific timeframe"""
        try:
            from main import (
                calculate_bollinger_bands, calculate_vwap, calculate_macd,
                calculate_atr, calculate_ichimoku, calculate_advanced_indicators,
                detect_candlestick_patterns, prepare_ml_features, calculate_volume_profile
            )
            
            # Calculate all technical indicators
            df = calculate_bollinger_bands(df)
            df = calculate_vwap(df)
            df = calculate_macd(df)
            df = calculate_atr(df)
            df = calculate_ichimoku(df)
            df = calculate_advanced_indicators(df)
            df = detect_candlestick_patterns(df)
            
            # Prepare ML features
            features = prepare_ml_features(df)
            
            if not features.empty:
                # Timeframe encoding
                tf_encoding = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
                features['timeframe_minutes'] = tf_encoding.get(timeframe, 60)
                
                # Multi-timeframe momentum features
                if len(df) > 20:
                    for p in [5, 10, 20]:
                        momentum_p = df['close'].pct_change(p).iloc[-len(features):]
                        if len(momentum_p) == len(features):
                            features[f'momentum_{p}'] = momentum_p.values
                
                # Volatility regime
                if 'ATR' in df.columns and len(df) > 20:
                    atr_mean = df['ATR'].rolling(20).mean()
                    volatility_regime = (df['ATR'] / atr_mean).iloc[-len(features):]
                    if len(volatility_regime) == len(features):
                        features['volatility_regime'] = volatility_regime.values
                
                # Initialize all VRVP features with neutral defaults to ensure XGBoost feature consistency
                for feat in ['vrvp_poc_distance', 'vrvp_vah_distance', 'vrvp_val_distance', 
                            'vrvp_above_poc', 'vrvp_support_dist', 'vrvp_concentration', 
                            'vrvp_high_volume_nodes']:
                    features[feat] = 0.0

                # Enhanced VRVP features
                if len(df) >= 100:
                    try:
                        volume_profile = calculate_volume_profile(df)
                        if volume_profile:
                            current_price = df['close'].iloc[-1]
                            poc = volume_profile.get('poc', current_price)
                            vah = volume_profile.get('vah', current_price * 1.02)
                            val = volume_profile.get('val', current_price * 0.98)
                            
                            features['vrvp_poc_distance'] = (poc - current_price) / current_price
                            features['vrvp_vah_distance'] = (vah - current_price) / current_price
                            features['vrvp_val_distance'] = (val - current_price) / current_price
                            features['vrvp_above_poc'] = 1 if current_price > poc else 0
                            
                            support_levels = volume_profile.get('support_levels', [])
                            if support_levels:
                                nearest_s = max([s for s in support_levels if s < current_price], default=current_price * 0.95)
                                features['vrvp_support_dist'] = (current_price - nearest_s) / current_price
                            
                            volumes = volume_profile.get('volumes', [])
                            if volumes:
                                total_vol = sum(volumes)
                                if total_vol > 0:
                                    features['vrvp_concentration'] = max(volumes) / total_vol
                                    features['vrvp_high_volume_nodes'] = sum(1 for v in volumes if v >= max(volumes) * 0.3)
                    except Exception as e:
                        print(f"⚠️ Error adding VRVP features: {e}")

                # AI Sentiment Features (Replaced Ollama with OpenRouter)
                sentiment_data = self.get_ai_sentiment(symbol)
                if sentiment_data:
                    # Map OpenRouter fields to expected ML features
                    # OpenRouter uses 'institutional_score', 'systemic_risk_level', etc.
                    score = sentiment_data.get('institutional_score', 0.5)
                    features['sentiment_bullish_ratio'] = score
                    
                    risk_level = sentiment_data.get('systemic_risk_level', 'Medium').upper()
                    features['sentiment_is_bullish'] = 1 if score > 0.6 else (0 if score < 0.4 else 0.5)
                    features['sentiment_is_bearish'] = 1 if risk_level in ['HIGH', 'CRITICAL'] else 0
                else:
                    features['sentiment_bullish_ratio'] = 0.5
                    features['sentiment_is_bullish'] = 0.5
                    features['sentiment_is_bearish'] = 0.5
            
            return features
            
        except Exception as e:
            print(f"❌ Error calculating features for {timeframe}: {e}")
            return pd.DataFrame()
    
    def generate_multi_timeframe_labels(self, timeframe_data, future_periods=None):
        """Generate labels considering multiple timeframes"""
        try:
            if future_periods is None:
                # Adaptive future periods based on timeframe
                tf_periods = {
                    '1m': 15, '5m': 12, '15m': 8, '1h': 6, '4h': 4, '1d': 3
                }
            else:
                tf_periods = {tf: future_periods for tf in self.timeframes}
            
            all_labels = {}
            
            for tf, df in timeframe_data.items():
                if df.empty:
                    continue
                
                periods = tf_periods.get(tf, 5)
                labels = []
                
                for i in range(len(df) - periods):
                    current_price = df['close'].iloc[i]
                    future_price = df['close'].iloc[i + periods]
                    
                    # Multi-criteria labeling
                    price_change = (future_price - current_price) / current_price
                    
                    # Adaptive thresholds based on timeframe volatility
                    if 'ATR' in df.columns and not pd.isna(df['ATR'].iloc[i]):
                        atr_threshold = df['ATR'].iloc[i] / current_price
                        threshold = max(0.005, atr_threshold * 0.5)  # Minimum 0.5% or half ATR
                    else:
                        threshold = 0.01  # Default 1%
                    
                    # Label generation
                    if price_change > threshold:
                        label = 1  # Buy
                    elif price_change < -threshold:
                        label = 0  # Sell
                    else:
                        label = 0.5  # Neutral (converted to 0 for binary classification)
                    
                    labels.append(1 if label == 1 else 0)
                
                # Pad with neutral labels
                labels.extend([0] * periods)
                all_labels[tf] = pd.Series(labels, index=df.index)
            
            return all_labels
            
        except Exception as e:
            print(f"❌ Error generating multi-timeframe labels: {e}")
            return {}
    
    def calculate_timeframe_correlations(self, timeframe_data):
        """Calculate correlations between different timeframes"""
        try:
            correlations = {}
            
            # Get price data for correlation analysis
            price_data = {}
            for tf, df in timeframe_data.items():
                if not df.empty:
                    price_data[tf] = df['close'].pct_change().dropna()
            
            # Calculate pairwise correlations
            for tf1 in price_data:
                correlations[tf1] = {}
                for tf2 in price_data:
                    if tf1 != tf2:
                        # Align data for correlation
                        min_len = min(len(price_data[tf1]), len(price_data[tf2]))
                        if min_len > 10:
                            corr = np.corrcoef(
                                price_data[tf1].tail(min_len),
                                price_data[tf2].tail(min_len)
                            )[0, 1]
                            correlations[tf1][tf2] = corr if not np.isnan(corr) else 0
                        else:
                            correlations[tf1][tf2] = 0
            
            self.correlation_matrix = correlations
            return correlations
            
        except Exception as e:
            print(f"❌ Error calculating timeframe correlations: {e}")
            return {}
    
    def train_timeframe_model(self, features, labels, timeframe):
        """Train model for specific timeframe"""
        try:
            if features.empty or len(labels) == 0:
                print(f"   ❌ No data for {timeframe}")
                return None
            
            # Align features and labels
            min_len = min(len(features), len(labels))
            if min_len < 100:
                print(f"   ⚠️  Insufficient data for {timeframe}: {min_len} samples")
                return None
            
            X = features.iloc[:min_len]
            y = labels.iloc[:min_len]
            
            # Remove infinite values and handle NaN more robustly
            X = X.replace([np.inf, -np.inf], np.nan)
            
            # More aggressive NaN handling
            print(f"   🔍 NaN check before cleaning: {X.isnull().sum().sum()} NaN values")
            
            # Fill NaN values with multiple strategies
            for col in X.columns:
                if X[col].isnull().any():
                    if X[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                        # For numeric columns, try median first, then mean, then 0
                        median_val = X[col].median()
                        if pd.isna(median_val):
                            mean_val = X[col].mean()
                            if pd.isna(mean_val):
                                fill_val = 0.0
                            else:
                                fill_val = mean_val
                        else:
                            fill_val = median_val
                        X[col] = X[col].fillna(fill_val)
                    else:
                        # For other columns, use mode or 0
                        mode_val = X[col].mode()
                        if len(mode_val) > 0 and not pd.isna(mode_val[0]):
                            X[col] = X[col].fillna(mode_val[0])
                        else:
                            X[col] = X[col].fillna(0)
            
            # Aggressive final cleanup
            X = X.fillna(0)
            
            # Convert to numeric and handle any remaining issues
            for col in X.columns:
                X[col] = pd.to_numeric(X[col], errors='coerce')
            
            # Final NaN replacement after numeric conversion
            X = X.fillna(0)
            
            # Verify no NaN values remain
            nan_count = X.isnull().sum().sum()
            if nan_count > 0:
                print(f"   ❌ Still have {nan_count} NaN values after cleaning!")
                X = X.fillna(0)  # Force fill any remaining
                
            print(f"   ✅ NaN check after cleaning: {X.isnull().sum().sum()} NaN values")
            
            # Additional validation
            if not np.isfinite(X.values).all():
                print(f"   ⚠️  Non-finite values detected, replacing...")
                X = X.replace([np.inf, -np.inf], 0)
                X = X.fillna(0)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train ensemble models
            models = {}
            
            # XGBoost with proper base_score handling
            # Calculate base_score from training data
            positive_ratio = y_train.mean()
            base_score = max(0.001, min(0.999, positive_ratio))  # Ensure it's in (0,1)
            
            xgb_params = {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'max_depth': 6,
                'learning_rate': 0.1,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42,
                'base_score': base_score,
                'reg_alpha': 0.1,
                'reg_lambda': 0.1
            }
            
            dtrain = xgb.DMatrix(X_train, label=y_train)
            dtest = xgb.DMatrix(X_test, label=y_test)
            
            # Additional validation for labels
            if len(np.unique(y_train)) < 2:
                print(f"   ⚠️  Warning: Only one class in training data for {timeframe}")
                # Create balanced dummy data to avoid single-class issues
                if y_train.iloc[0] == 0:
                    y_train.iloc[-1] = 1
                else:
                    y_train.iloc[-1] = 0
                dtrain = xgb.DMatrix(X_train, label=y_train)
            
            xgb_model = xgb.train(
                xgb_params, dtrain, num_boost_round=200,
                evals=[(dtest, 'test')], early_stopping_rounds=20,
                verbose_eval=False
            )
            
            xgb_pred = xgb_model.predict(dtest) > 0.5
            xgb_acc = accuracy_score(y_test, xgb_pred)
            models['xgboost'] = {'model': xgb_model, 'accuracy': xgb_acc, 'type': 'xgboost'}
            
            # Random Forest
            rf_model = RandomForestClassifier(
                n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
            )
            rf_model.fit(X_train_scaled, y_train)
            rf_acc = rf_model.score(X_test_scaled, y_test)
            models['random_forest'] = {'model': rf_model, 'accuracy': rf_acc, 'type': 'sklearn'}
            
            # Histogram-based Gradient Boosting (handles NaN natively)
            try:
                gb_model = HistGradientBoostingClassifier(
                    max_iter=100, learning_rate=0.1, max_depth=6, random_state=42
                )
                gb_model.fit(X_train, y_train)  # Use unscaled data since it handles NaN
                gb_acc = gb_model.score(X_test, y_test)
                models['gradient_boosting'] = {'model': gb_model, 'accuracy': gb_acc, 'type': 'sklearn'}
            except Exception as e:
                print(f"   ⚠️  Error with gradient_boosting for {timeframe}: {e}")
                # Skip gradient boosting if it fails
                pass
            
            # Select best model
            best_model_name = max(models.keys(), key=lambda k: models[k]['accuracy'])
            best_model = models[best_model_name]
            
            print(f"   ✅ {timeframe} - Best: {best_model_name} (acc: {best_model['accuracy']:.3f})")
            
            # Save model and scaler
            model_file = self.model_dir / f"model_{timeframe}.joblib"
            scaler_file = self.model_dir / f"scaler_{timeframe}.joblib"
            
            dump(models, model_file)
            dump(scaler, scaler_file)
            
            # Store in memory
            self.models[timeframe] = models
            self.scalers[timeframe] = scaler
            
            # Store performance metrics
            self.performance_metrics[timeframe] = {
                'accuracy': best_model['accuracy'],
                'best_model': best_model_name,
                'training_samples': len(X_train),
                'test_samples': len(X_test),
                'timestamp': datetime.now().isoformat()
            }
            
            return models
            
        except Exception as e:
            print(f"   ❌ Error training {timeframe} model: {e}")
            return None
    
    def train_all_timeframes(self, symbol_list=None):
        """Train models for all timeframes"""
        try:
            if symbol_list is None:
                symbol_list = [
                    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT',
                    'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT'
                ]
            
            print(f"🔄 Training models for all timeframes using {len(symbol_list)} symbols...")
            
            # Collect data from all symbols and timeframes
            all_timeframe_features = {tf: [] for tf in self.timeframes}
            all_timeframe_labels = {tf: [] for tf in self.timeframes}
            
            for symbol in symbol_list:
                try:
                    print(f"\n📊 Processing {symbol}...")
                    
                    # Fetch multi-timeframe data
                    timeframe_data = self.fetch_multi_timeframe_data(symbol)
                    
                    if not timeframe_data:
                        print(f"   ❌ No data for {symbol}")
                        continue
                    
                    # Calculate correlations
                    correlations = self.calculate_timeframe_correlations(timeframe_data)
                    
                    # Generate labels
                    labels = self.generate_multi_timeframe_labels(timeframe_data)
                    
                    # Process each timeframe
                    for tf in self.timeframes:
                        if tf in timeframe_data and tf in labels:
                            features = self.calculate_comprehensive_features(timeframe_data[tf], tf)
                            
                            if not features.empty:
                                all_timeframe_features[tf].append(features)
                                all_timeframe_labels[tf].append(labels[tf])
                                print(f"   ✅ {tf}: {len(features)} samples")
                    
                    time.sleep(1)  # Rate limiting
                    
                except Exception as e:
                    print(f"   ❌ Error processing {symbol}: {e}")
                    continue
            
            # Train models for each timeframe
            print(f"\n🤖 Training models for each timeframe...")
            
            for tf in self.timeframes:
                if all_timeframe_features[tf]:
                    print(f"\n🎯 Training {tf} model...")
                    
                    # Combine data
                    combined_features = pd.concat(all_timeframe_features[tf], ignore_index=True)
                    combined_labels = pd.concat(all_timeframe_labels[tf], ignore_index=True)
                    
                    print(f"   📊 Dataset: {len(combined_features)} samples, {len(combined_features.columns)} features")
                    
                    # Train model
                    models = self.train_timeframe_model(combined_features, combined_labels, tf)
                    
                    if models:
                        print(f"   ✅ {tf} model trained successfully")
                    else:
                        print(f"   ❌ {tf} model training failed")
                else:
                    print(f"   ⚠️  No data for {tf}")
            
            # Save performance summary
            self.save_performance_summary()
            
            print(f"\n✅ Multi-timeframe training complete!")
            return True
            
        except Exception as e:
            print(f"❌ Error in multi-timeframe training: {e}")
            return False
    
    def predict_multi_timeframe(self, symbol, confidence_threshold=None):
        """Generate predictions across all timeframes"""
        try:
            if confidence_threshold is None:
                confidence_threshold = self.config['prediction_confidence_threshold']
            
            # Fetch current data
            timeframe_data = self.fetch_multi_timeframe_data(symbol, limit=200)
            
            if not timeframe_data:
                return None
            
            predictions = {}
            confidences = {}
            
            for tf in self.timeframes:
                if tf not in timeframe_data or tf not in self.models:
                    continue
                
                try:
                    # Calculate features
                    features = self.calculate_comprehensive_features(timeframe_data[tf], tf, symbol)

                    
                    if features.empty:
                        continue
                    
                    # Get latest features
                    latest_features = features.iloc[-1:].copy()
                    
                    # Handle missing values
                    latest_features = latest_features.fillna(latest_features.median())
                    latest_features = latest_features.replace([np.inf, -np.inf], 0)
                    
                    # Scale features
                    if tf in self.scalers:
                        latest_features_scaled = self.scalers[tf].transform(latest_features)
                    else:
                        latest_features_scaled = latest_features.values
                    
                    # Get ensemble predictions
                    tf_predictions = []
                    tf_confidences = []
                    
                    for model_name, model_info in self.models[tf].items():
                        try:
                            if model_info['type'] == 'xgboost':
                                dmatrix = xgb.DMatrix(latest_features)
                                pred_prob = model_info['model'].predict(dmatrix)[0]
                            else:  # sklearn models
                                pred_prob = model_info['model'].predict_proba(latest_features_scaled)[0][1]
                            
                            tf_predictions.append(pred_prob)
                            tf_confidences.append(abs(pred_prob - 0.5) * 2)
                            
                        except Exception as e:
                            print(f"   ⚠️  Error with {model_name} for {tf}: {e}")
                            continue
                    
                    if tf_predictions:
                        # Ensemble prediction (weighted by accuracy)
                        weights = [self.models[tf][name]['accuracy'] for name in self.models[tf].keys()]
                        
                        # Ensure weights and predictions have same length
                        if len(weights) == len(tf_predictions):
                            weighted_pred = np.average(tf_predictions, weights=weights)
                        else:
                            # Fallback to simple average if lengths don't match
                            weighted_pred = np.mean(tf_predictions)
                        
                        avg_confidence = np.mean(tf_confidences)
                        
                        predictions[tf] = {
                            'probability': weighted_pred,
                            'signal': 'BUY' if weighted_pred > 0.5 else 'SELL',
                            'confidence': avg_confidence
                        }
                        confidences[tf] = avg_confidence
                
                except Exception as e:
                    print(f"   ❌ Error predicting {tf}: {e}")
                    continue
            
            # Multi-timeframe consensus
            if predictions:
                consensus = self.calculate_consensus(predictions, confidences)
                return {
                    'symbol': symbol,
                    'timeframe_predictions': predictions,
                    'consensus': consensus,
                    'timestamp': datetime.now().isoformat()
                }
            
            return None
            
        except Exception as e:
            print(f"❌ Error in multi-timeframe prediction: {e}")
            return None
    
    def calculate_consensus(self, predictions, confidences):
        """Calculate consensus across timeframes"""
        try:
            # Weight predictions by timeframe importance and confidence
            tf_weights = {
                '1m': 0.1, '5m': 0.15, '15m': 0.2, 
                '1h': 0.25, '4h': 0.2, '1d': 0.1
            }
            
            weighted_signals = []
            total_weight = 0
            
            for tf, pred in predictions.items():
                if tf in tf_weights:
                    weight = tf_weights[tf] * confidences[tf]
                    signal_value = 1 if pred['signal'] == 'BUY' else 0
                    weighted_signals.append(signal_value * weight)
                    total_weight += weight
            
            if total_weight > 0:
                consensus_score = sum(weighted_signals) / total_weight
                consensus_signal = 'BUY' if consensus_score > 0.5 else 'SELL'
                consensus_confidence = abs(consensus_score - 0.5) * 2
                
                return {
                    'signal': consensus_signal,
                    'confidence': consensus_confidence,
                    'score': consensus_score,
                    'participating_timeframes': len(predictions)
                }
            
            return None
            
        except Exception as e:
            print(f"❌ Error calculating consensus: {e}")
            return None
    
    def update_self_learning(self, symbol, prediction, actual_outcome, timeframe):
        """Update self-learning system with prediction outcomes"""
        try:
            timestamp = datetime.now().isoformat()
            
            # Validate inputs
            if not isinstance(timeframe, str):
                print(f"⚠️  Invalid timeframe type for {symbol}: {type(timeframe)} - {timeframe}")
                return
            
            # Ensure prediction and actual_outcome are comparable
            if isinstance(prediction, str):
                prediction_normalized = prediction.upper()
            else:
                prediction_normalized = 'LONG' if prediction else 'SHORT'
            
            if isinstance(actual_outcome, str):
                outcome_normalized = actual_outcome.upper()
            else:
                outcome_normalized = 'SUCCESS' if actual_outcome else 'FAILURE'
            
            # Calculate accuracy based on prediction success
            # Success keywords: SUCCESS, GOOD, EXCELLENT, PARTIAL
            success_keywords = ['SUCCESS', 'GOOD', 'EXCELLENT', 'PARTIAL']
            
            is_prediction_correct = False
            if prediction_normalized in ['LONG', 'BUY']:
                if outcome_normalized in success_keywords:
                    is_prediction_correct = True
            elif prediction_normalized in ['SHORT', 'SELL']:
                if outcome_normalized in success_keywords:
                    is_prediction_correct = True
            
            accuracy = 1 if is_prediction_correct else 0

            
            # Create enhanced learning entry
            learning_entry = {
                'symbol': symbol,
                'timeframe': timeframe,  # Now properly validated as string
                'prediction': prediction_normalized,
                'actual_outcome': outcome_normalized,
                'timestamp': timestamp,
                'accuracy': accuracy,
                'prediction_confidence': getattr(self, 'last_prediction_confidence', 0.5),
                'market_conditions': self._get_market_conditions(symbol, timeframe)
            }
            
            # Store in self-learning data
            if symbol not in self.self_learning_data:
                self.self_learning_data[symbol] = []
            
            self.self_learning_data[symbol].append(learning_entry)
            
            # Keep only recent entries (last 1000 per symbol)
            if len(self.self_learning_data[symbol]) > 1000:
                self.self_learning_data[symbol] = self.self_learning_data[symbol][-1000:]
            
            # Save updated data
            self.save_self_learning_data()
            
            # Log learning update
            print(f"📚 Learning updated for {symbol} {timeframe}: {prediction_normalized} -> {outcome_normalized} (accuracy: {accuracy})")
            
            # Analyze performance and trigger retraining if needed
            self.analyze_performance_and_adapt(symbol, timeframe)
            
        except Exception as e:
            print(f"❌ Error updating self-learning: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_market_conditions(self, symbol, timeframe):
        """Get current market conditions for enhanced learning context"""
        try:
            # Fetch recent data for market condition analysis
            timeframe_data = self.fetch_multi_timeframe_data(symbol, limit=50)
            
            if not timeframe_data or timeframe not in timeframe_data:
                return {'volatility': 'unknown', 'trend': 'unknown', 'volume': 'unknown'}
            
            df = timeframe_data[timeframe]
            
            # Calculate market conditions
            conditions = {}
            
            # Volatility analysis
            if 'ATR' in df.columns and len(df) > 14:
                atr_current = df['ATR'].iloc[-1]
                atr_avg = df['ATR'].rolling(14).mean().iloc[-1]
                if pd.notna(atr_current) and pd.notna(atr_avg) and atr_avg > 0:
                    volatility_ratio = atr_current / atr_avg
                    if volatility_ratio > 1.5:
                        conditions['volatility'] = 'high'
                    elif volatility_ratio < 0.7:
                        conditions['volatility'] = 'low'
                    else:
                        conditions['volatility'] = 'normal'
                else:
                    conditions['volatility'] = 'unknown'
            else:
                conditions['volatility'] = 'unknown'
            
            # Trend analysis
            if len(df) > 20:
                sma_20 = df['close'].rolling(20).mean().iloc[-1]
                current_price = df['close'].iloc[-1]
                if pd.notna(sma_20) and pd.notna(current_price):
                    if current_price > sma_20 * 1.02:
                        conditions['trend'] = 'bullish'
                    elif current_price < sma_20 * 0.98:
                        conditions['trend'] = 'bearish'
                    else:
                        conditions['trend'] = 'sideways'
                else:
                    conditions['trend'] = 'unknown'
            else:
                conditions['trend'] = 'unknown'
            
            # Volume analysis
            if len(df) > 10:
                vol_avg = df['volume'].rolling(10).mean().iloc[-1]
                vol_current = df['volume'].iloc[-1]
                if pd.notna(vol_avg) and pd.notna(vol_current) and vol_avg > 0:
                    volume_ratio = vol_current / vol_avg
                    if volume_ratio > 1.5:
                        conditions['volume'] = 'high'
                    elif volume_ratio < 0.5:
                        conditions['volume'] = 'low'
                    else:
                        conditions['volume'] = 'normal'
                else:
                    conditions['volume'] = 'unknown'
            else:
                conditions['volume'] = 'unknown'
            
            return conditions
            
        except Exception as e:
            print(f"❌ Error getting market conditions: {e}")
            return {'volatility': 'unknown', 'trend': 'unknown', 'volume': 'unknown'}
    
    def analyze_performance_and_adapt(self, symbol, timeframe):
        """Analyze performance and adapt models if needed"""
        try:
            if symbol not in self.self_learning_data:
                return
            
            # Get recent performance for this symbol and timeframe
            recent_entries = [
                entry for entry in self.self_learning_data[symbol][-100:]
                if entry['timeframe'] == timeframe
            ]
            
            if len(recent_entries) < 20:
                return
            
            # Calculate recent accuracy
            recent_accuracy = sum(entry['accuracy'] for entry in recent_entries) / len(recent_entries)
            
            # Check if performance is below threshold
            if recent_accuracy < self.config['min_accuracy_threshold']:
                print(f"⚠️  Performance degradation detected for {symbol} {timeframe}: {recent_accuracy:.3f}")
                
                # Trigger adaptive retraining for this specific timeframe
                self.adaptive_retrain_timeframe(timeframe, [symbol])
            
        except Exception as e:
            print(f"❌ Error analyzing performance: {e}")
    
    def adaptive_retrain_timeframe(self, timeframe, symbol_list):
        """Adaptively retrain a specific timeframe model"""
        try:
            print(f"🔄 Adaptive retraining for {timeframe}...")
            
            # Collect fresh data
            all_features = []
            all_labels = []
            
            for symbol in symbol_list:
                timeframe_data = self.fetch_multi_timeframe_data(symbol, limit=500)
                
                if timeframe in timeframe_data:
                    features = self.calculate_comprehensive_features(timeframe_data[timeframe], timeframe)
                    labels = self.generate_multi_timeframe_labels({timeframe: timeframe_data[timeframe]})
                    
                    if not features.empty and timeframe in labels:
                        all_features.append(features)
                        all_labels.append(labels[timeframe])
            
            if all_features:
                combined_features = pd.concat(all_features, ignore_index=True)
                combined_labels = pd.concat(all_labels, ignore_index=True)
                
                # Retrain model
                models = self.train_timeframe_model(combined_features, combined_labels, timeframe)
                
                if models:
                    print(f"✅ Adaptive retraining complete for {timeframe}")
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error in adaptive retraining: {e}")
            return False
    
    def save_performance_summary(self):
        """Save performance summary to file"""
        try:
            summary_file = self.performance_dir / "performance_summary.json"
            
            summary = {
                'timestamp': datetime.now().isoformat(),
                'timeframe_performance': self.performance_metrics,
                'correlation_matrix': self.correlation_matrix,
                'config': self.config
            }
            
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
                
        except Exception as e:
            print(f"❌ Error saving performance summary: {e}")
    
    def _background_retraining(self):
        """Background thread for automatic retraining"""
        while True:
            try:
                current_time = time.time()
                
                # Check if it's time to retrain
                if current_time - self.last_retrain_time >= self.config['retrain_interval']:
                    print(f"🔄 Starting scheduled retraining...")
                    
                    # Retrain all models
                    success = self.train_all_timeframes()
                    
                    if success:
                        self.last_retrain_time = current_time
                        print(f"✅ Scheduled retraining complete")
                    else:
                        print(f"❌ Scheduled retraining failed")
                
                # Sleep for 30 minutes before checking again
                time.sleep(1800)
                
            except Exception as e:
                print(f"❌ Error in background retraining: {e}")
                time.sleep(3600)  # Sleep for 1 hour on error

# Global instance
ml_system = None

def initialize_ml_system():
    """Initialize the global ML system"""
    global ml_system
    if ml_system is None:
        ml_system = MultiTimeframeMLSystem()
    return ml_system

def get_multi_timeframe_prediction(symbol):
    """Get multi-timeframe prediction for a symbol"""
    global ml_system
    if ml_system is None:
        ml_system = initialize_ml_system()
    
    return ml_system.predict_multi_timeframe(symbol)

def train_all_models():
    """Train all timeframe models"""
    global ml_system
    if ml_system is None:
        ml_system = initialize_ml_system()
    
    return ml_system.train_all_timeframes()

def update_prediction_outcome(symbol, prediction, actual_outcome, timeframe):
    """Update self-learning system with prediction outcome"""
    global ml_system
    if ml_system is None:
        ml_system = initialize_ml_system()
    
    ml_system.update_self_learning(symbol, prediction, actual_outcome, timeframe)

if __name__ == "__main__":
    # Initialize and train the system
    system = MultiTimeframeMLSystem()
    success = system.train_all_timeframes()
    
    if success:
        print("🎉 Multi-timeframe ML system training completed successfully!")
        
        # Test the system with a sample prediction
        print("\n🧪 Testing multi-timeframe prediction...")
        test_prediction = system.predict_multi_timeframe('BTCUSDT')
        
        if test_prediction:
            print("✅ Multi-timeframe prediction test successful!")
            print(f"   Consensus: {test_prediction['consensus']}")
        else:
            print("⚠️  Multi-timeframe prediction test failed")
    else:
        print("❌ Multi-timeframe ML system training failed!")
