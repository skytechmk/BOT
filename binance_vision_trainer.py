#!/usr/bin/env python3
"""
Enhanced ML model trainer using Binance Vision historical data
"""

import sys
import os
import pandas as pd
import numpy as np
import requests
import zipfile
import io
from datetime import datetime, timedelta
import time
from pathlib import Path

# Add current directory to path
sys.path.append('.')

class BinanceVisionTrainer:
    def __init__(self):
        self.base_url = "https://data.binance.vision/data/spot/daily/klines"
        self.data_dir = Path("historical_data")
        self.data_dir.mkdir(exist_ok=True)
        
    def download_historical_data(self, symbol, interval="1d", days_back=365):
        """Download historical data from Binance Vision"""
        print(f"📥 Downloading {days_back} days of {interval} data for {symbol}...")
        
        all_data = []
        end_date = datetime.now()
        
        for i in range(days_back):
            date = end_date - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            
            # Binance Vision URL format
            url = f"{self.base_url}/{symbol}/{interval}/{symbol}-{interval}-{date_str}.zip"
            
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    # Extract CSV from ZIP
                    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                        csv_filename = f"{symbol}-{interval}-{date_str}.csv"
                        if csv_filename in zip_file.namelist():
                            csv_data = zip_file.read(csv_filename)
                            
                            # Parse CSV data
                            df = pd.read_csv(io.StringIO(csv_data.decode('utf-8')), header=None)
                            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                                        'close_time', 'quote_asset_volume', 'number_of_trades',
                                        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore']
                            
                            all_data.append(df)
                            
                            if i % 30 == 0:  # Progress update every 30 days
                                print(f"   Downloaded {i+1}/{days_back} days...")
                                
                elif response.status_code == 404:
                    # Data not available for this date (weekend/holiday)
                    continue
                else:
                    print(f"   Warning: Failed to download {date_str} (HTTP {response.status_code})")
                    
            except Exception as e:
                print(f"   Warning: Error downloading {date_str}: {e}")
                continue
                
            # Small delay to be respectful to the server
            time.sleep(0.1)
        
        if all_data:
            # Combine all data
            combined_df = pd.concat(all_data, ignore_index=True)
            combined_df['timestamp'] = pd.to_datetime(combined_df['timestamp'], unit='ms')
            combined_df.set_index('timestamp', inplace=True)
            combined_df = combined_df.sort_index()
            
            # Convert to numeric
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            combined_df[numeric_cols] = combined_df[numeric_cols].astype(float)
            
            print(f"   ✅ Downloaded {len(combined_df)} records for {symbol}")
            return combined_df
        else:
            print(f"   ❌ No data downloaded for {symbol}")
            return pd.DataFrame()
    
    def prepare_training_data(self, symbols, days_back=180):
        """Prepare comprehensive training data from multiple symbols"""
        print("🔄 Preparing comprehensive training dataset...")
        
        all_features = []
        all_labels = []
        
        for symbol in symbols:
            try:
                print(f"\n📊 Processing {symbol}...")
                
                # Download historical data
                df = self.download_historical_data(symbol, "1d", days_back)
                
                if df.empty or len(df) < 100:
                    print(f"   ⚠️  Insufficient data for {symbol}")
                    continue
                
                # Import required functions
                from binance_hunter_talib import (
                    calculate_bollinger_bands, calculate_vwap, calculate_macd,
                    calculate_atr, calculate_ichimoku, calculate_advanced_indicators,
                    detect_candlestick_patterns, prepare_ml_features, generate_training_labels
                )
                
                print(f"   🔧 Calculating technical indicators...")
                
                # Calculate all technical indicators
                df = calculate_bollinger_bands(df)
                df = calculate_vwap(df)
                df = calculate_macd(df)
                df = calculate_atr(df)
                df = calculate_ichimoku(df)
                df = calculate_advanced_indicators(df)
                df = detect_candlestick_patterns(df)
                
                print(f"   🎯 Preparing ML features...")
                
                # Prepare features
                features = prepare_ml_features(df)
                if features.empty:
                    print(f"   ❌ No features prepared for {symbol}")
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
                    print(f"   ⚠️  Insufficient aligned data: {min_len} samples")
                
            except Exception as e:
                print(f"   ❌ Error processing {symbol}: {e}")
                continue
        
        if not all_features:
            print("❌ No training data collected!")
            return None, None
        
        # Combine all data
        print("\n🔗 Combining all training data...")
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)
        
        print(f"✅ Final dataset: {len(X)} samples with {len(X.columns)} features")
        print(f"   Label distribution: {y.value_counts().to_dict()}")
        
        return X, y
    
    def train_enhanced_model(self):
        """Train model with enhanced historical data"""
        print("=" * 70)
        print("ENHANCED ML MODEL TRAINING WITH BINANCE VISION DATA")
        print("=" * 70)
        print(f"Started at: {datetime.now()}")
        print()
        
        # Define symbols for training (major pairs with good liquidity)
        training_symbols = [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT',
            'XRPUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT',
            'UNIUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'FILUSDT'
        ]
        
        # Prepare training data
        X, y = self.prepare_training_data(training_symbols, days_back=180)
        
        if X is None or y is None:
            print("❌ Failed to prepare training data")
            return False
        
        # Train the model
        print("\n🤖 Training ML model...")
        try:
            from binance_hunter_talib import train_ensemble_models, train_ml_model
            
            # Try ensemble training first
            models = train_ensemble_models(X, y)
            if models:
                print("✅ Ensemble models trained successfully!")
                model_type = "ensemble"
            else:
                print("⚠️  Ensemble training failed, trying single model...")
                model = train_ml_model(X, y)
                if model:
                    print("✅ Single XGBoost model trained successfully!")
                    model_type = "single"
                else:
                    print("❌ All model training failed!")
                    return False
            
            # Test the trained model
            print("\n🧪 Testing trained model...")
            self.test_trained_model()
            
            print("\n" + "=" * 70)
            print(f"✅ TRAINING COMPLETE - {model_type.upper()} MODEL READY")
            print("=" * 70)
            
            return True
            
        except Exception as e:
            print(f"❌ Training error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_trained_model(self):
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
                    return True
                else:
                    print("   ⚠️  Test prediction returned None")
                    return False
            else:
                print("   ⚠️  Could not fetch test data")
                return False
                
        except Exception as e:
            print(f"   ❌ Test failed: {e}")
            return False

def main():
    """Main training function"""
    trainer = BinanceVisionTrainer()
    success = trainer.train_enhanced_model()
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
