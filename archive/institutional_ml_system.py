#!/usr/bin/env python3
"""
Institutional-Grade ML System with Per-Pair Models and Advanced Self-Learning
Optimized for NVIDIA RTX 3090 with CUDA acceleration
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
import sqlite3
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from sklearn.model_selection import train_test_split, TimeSeriesSplit, GridSearchCV
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.preprocessing import StandardScaler, RobustScaler, MinMaxScaler
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, VotingClassifier
from sklearn.neural_network import MLPClassifier
from joblib import dump, load, Parallel, delayed
import warnings
warnings.filterwarnings('ignore')

# Enhanced ML imports with fallback
try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
    print("🚀 LightGBM available")
except ImportError:
    LIGHTGBM_AVAILABLE = False
    print("⚠️  LightGBM not available, using sklearn fallback")

try:
    import catboost as cb
    CATBOOST_AVAILABLE = True
    print("🚀 CatBoost available")
except ImportError:
    CATBOOST_AVAILABLE = False
    print("⚠️  CatBoost not available, using sklearn fallback")

ADVANCED_ML_AVAILABLE = LIGHTGBM_AVAILABLE or CATBOOST_AVAILABLE

# CUDA/GPU optimization imports
try:
    import cudf
    import cuml
    from cuml.ensemble import RandomForestClassifier as cuRF
    from cuml.linear_model import LogisticRegression as cuLR
    from cuml.svm import SVC as cuSVC
    CUDA_AVAILABLE = True
    print("🚀 CUDA/Rapids acceleration available")
except ImportError:
    CUDA_AVAILABLE = False
    print("⚠️  CUDA/Rapids not available, using CPU fallback")

# Deep Learning imports for RTX 3090
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    import torch.nn.functional as F
    
    # Check for CUDA availability
    if torch.cuda.is_available():
        TORCH_DEVICE = torch.device("cuda:0")
        print(f"🔥 PyTorch CUDA available: {torch.cuda.get_device_name(0)}")
        print(f"   CUDA Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    else:
        TORCH_DEVICE = torch.device("cpu")
        print("⚠️  PyTorch CUDA not available, using CPU")
    
    PYTORCH_AVAILABLE = True
except ImportError:
    PYTORCH_AVAILABLE = False
    TORCH_DEVICE = None
    print("⚠️  PyTorch not available")

# Add current directory to path
sys.path.append('.')

class InstitutionalMLSystem:
    def __init__(self):
        self.pairs = []  # Will be populated with trading pairs
        self.timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']
        
        # Per-pair models storage
        self.pair_models = {}  # {pair: {timeframe: {model_type: model}}}
        self.pair_scalers = {}  # {pair: {timeframe: scaler}}
        self.pair_performance = {}  # {pair: performance_metrics}
        
        # Historical database
        self.db_path = Path("institutional_data") / "trading_database.db"
        self.feature_cache = {}
        
        # Self-learning system
        self.trade_outcomes = {}  # {pair: [trade_results]}
        self.mistake_patterns = {}  # {pair: [mistake_analysis]}
        self.success_patterns = {}  # {pair: [success_analysis]}
        
        # Directories
        self.model_dir = Path("institutional_models")
        self.data_dir = Path("institutional_data")
        self.performance_dir = Path("institutional_performance")
        self.cache_dir = Path("institutional_cache")
        
        # Create directories
        for dir_path in [self.model_dir, self.data_dir, self.performance_dir, self.cache_dir]:
            dir_path.mkdir(exist_ok=True)
        
        # Enhanced configuration for institutional trading
        self.config = {
            'models_per_pair': ['xgboost', 'lightgbm', 'catboost', 'neural_network', 'ensemble'],
            'retrain_interval': 2 * 3600,  # 2 hours for institutional-grade responsiveness
            'min_accuracy_threshold': 0.65,  # Higher threshold for institutional grade
            'min_samples_per_pair': 500,  # Minimum samples for reliable training
            'feature_selection_threshold': 0.01,  # Feature importance threshold
            'ensemble_voting': 'soft',  # Soft voting for probability-based decisions
            'cross_validation_folds': 5,
            'hyperparameter_optimization': True,
            'cuda_batch_size': 10000,  # Optimized for RTX 3090
            'neural_network_layers': [512, 256, 128, 64],  # Deep network for complex patterns
            'learning_rate_schedule': True,
            'early_stopping_patience': 50,
            'trade_outcome_memory': 10000,  # Remember last 10k trades per pair
            'mistake_analysis_depth': 100,  # Analyze last 100 mistakes
            'success_pattern_tracking': 200,  # Track last 200 successful trades
        }
        
        # Initialize database
        self.init_database()
        
        # Load existing data
        self.load_existing_models()
        self.load_trade_outcomes()
        
        # Start background processes
        self.start_background_processes()
        
        print("🏛️  Institutional-Grade ML System initialized")
        print(f"   GPU Acceleration: {'✅ CUDA' if CUDA_AVAILABLE else '❌ CPU only'}")
        print(f"   PyTorch Device: {TORCH_DEVICE}")
        print(f"   Models per pair: {len(self.config['models_per_pair'])}")
        print(f"   Retrain interval: {self.config['retrain_interval']/3600} hours")
    
    def init_database(self):
        """Initialize SQLite database for historical data storage"""
        try:
            self.db_path.parent.mkdir(exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Historical price data table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS price_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL,
                        data_hash TEXT UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Features table for ML training
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS features (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        features_json TEXT NOT NULL,
                        label INTEGER,
                        feature_hash TEXT UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Trade outcomes table for self-learning
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trade_outcomes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair TEXT NOT NULL,
                        signal_id TEXT,
                        prediction TEXT NOT NULL,
                        confidence REAL,
                        entry_price REAL NOT NULL,
                        exit_price REAL,
                        pnl_percentage REAL,
                        success INTEGER,
                        trade_duration INTEGER,
                        market_conditions TEXT,
                        mistake_category TEXT,
                        timestamp INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Model performance tracking
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS model_performance (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        model_type TEXT NOT NULL,
                        accuracy REAL NOT NULL,
                        precision_score REAL,
                        recall_score REAL,
                        f1_score REAL,
                        auc_score REAL,
                        training_samples INTEGER,
                        validation_samples INTEGER,
                        feature_count INTEGER,
                        training_time REAL,
                        timestamp INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create indexes for performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_pair_tf ON price_data(pair, timeframe)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_features_pair_tf ON features(pair, timeframe)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_pair ON trade_outcomes(pair)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_performance_pair ON model_performance(pair, timeframe)')
                
                conn.commit()
                print("✅ Database initialized successfully")
                
        except Exception as e:
            print(f"❌ Error initializing database: {e}")
    
    def store_historical_data(self, pair, timeframe, df):
        """Store historical price data in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                for _, row in df.iterrows():
                    # Create unique hash for deduplication
                    data_string = f"{pair}_{timeframe}_{row.name}_{row['open']}_{row['high']}_{row['low']}_{row['close']}_{row['volume']}"
                    data_hash = hashlib.md5(data_string.encode()).hexdigest()
                    
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR IGNORE INTO price_data 
                        (pair, timeframe, timestamp, open, high, low, close, volume, data_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        pair, timeframe, int(row.name.timestamp()),
                        float(row['open']), float(row['high']), float(row['low']),
                        float(row['close']), float(row['volume']), data_hash
                    ))
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error storing historical data for {pair}: {e}")
    
    def store_features(self, pair, timeframe, features, labels=None):
        """Store calculated features in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                for i, (timestamp, feature_row) in enumerate(features.iterrows()):
                    # Convert features to JSON
                    features_dict = feature_row.to_dict()
                    features_json = json.dumps(features_dict, default=str)
                    
                    # Create unique hash
                    feature_string = f"{pair}_{timeframe}_{timestamp}_{features_json}"
                    feature_hash = hashlib.md5(feature_string.encode()).hexdigest()
                    
                    # Get label if available
                    label = None
                    if labels is not None and i < len(labels):
                        label = int(labels.iloc[i])
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO features 
                        (pair, timeframe, timestamp, features_json, label, feature_hash)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        pair, timeframe, int(timestamp.timestamp()),
                        features_json, label, feature_hash
                    ))
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error storing features for {pair}: {e}")
    
    def load_historical_features(self, pair, timeframe, limit=None):
        """Load historical features from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT timestamp, features_json, label 
                    FROM features 
                    WHERE pair = ? AND timeframe = ? 
                    ORDER BY timestamp DESC
                '''
                
                if limit:
                    query += f' LIMIT {limit}'
                
                cursor = conn.cursor()
                cursor.execute(query, (pair, timeframe))
                rows = cursor.fetchall()
                
                if not rows:
                    return None, None
                
                # Reconstruct features DataFrame
                features_list = []
                labels_list = []
                timestamps = []
                
                for timestamp, features_json, label in rows:
                    features_dict = json.loads(features_json)
                    features_list.append(features_dict)
                    labels_list.append(label if label is not None else 0)
                    timestamps.append(pd.Timestamp.fromtimestamp(timestamp))
                
                features_df = pd.DataFrame(features_list, index=timestamps)
                labels_series = pd.Series(labels_list, index=timestamps)
                
                return features_df, labels_series
                
        except Exception as e:
            print(f"❌ Error loading historical features for {pair}: {e}")
            return None, None
    
    def store_trade_outcome(self, pair, signal_id, prediction, confidence, entry_price, 
                          exit_price=None, pnl_percentage=None, success=None, 
                          trade_duration=None, market_conditions=None):
        """Store trade outcome for self-learning"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Analyze mistake category if trade was unsuccessful
                mistake_category = None
                if success is False and pnl_percentage is not None:
                    mistake_category = self.analyze_mistake_category(
                        pair, prediction, pnl_percentage, market_conditions
                    )
                
                cursor.execute('''
                    INSERT INTO trade_outcomes 
                    (pair, signal_id, prediction, confidence, entry_price, exit_price, 
                     pnl_percentage, success, trade_duration, market_conditions, 
                     mistake_category, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    pair, signal_id, prediction, confidence, entry_price, exit_price,
                    pnl_percentage, success, trade_duration, 
                    json.dumps(market_conditions) if market_conditions else None,
                    mistake_category, int(time.time())
                ))
                
                conn.commit()
                
                # Update in-memory cache
                if pair not in self.trade_outcomes:
                    self.trade_outcomes[pair] = []
                
                self.trade_outcomes[pair].append({
                    'signal_id': signal_id,
                    'prediction': prediction,
                    'confidence': confidence,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_percentage': pnl_percentage,
                    'success': success,
                    'trade_duration': trade_duration,
                    'market_conditions': market_conditions,
                    'mistake_category': mistake_category,
                    'timestamp': time.time()
                })
                
                # Keep only recent trades in memory
                if len(self.trade_outcomes[pair]) > self.config['trade_outcome_memory']:
                    self.trade_outcomes[pair] = self.trade_outcomes[pair][-self.config['trade_outcome_memory']:]
                
                # Trigger self-learning analysis
                self.analyze_trade_patterns(pair)
                
        except Exception as e:
            print(f"❌ Error storing trade outcome for {pair}: {e}")
    
    def analyze_mistake_category(self, pair, prediction, pnl_percentage, market_conditions):
        """Analyze and categorize trading mistakes for learning"""
        try:
            if pnl_percentage >= 0:
                return None  # Not a mistake
            
            loss_magnitude = abs(pnl_percentage)
            
            # Categorize mistakes based on loss magnitude and conditions
            if loss_magnitude > 5.0:
                category = "MAJOR_LOSS"
            elif loss_magnitude > 2.0:
                category = "SIGNIFICANT_LOSS"
            elif loss_magnitude > 1.0:
                category = "MODERATE_LOSS"
            else:
                category = "MINOR_LOSS"
            
            # Add market condition context
            if market_conditions:
                if market_conditions.get('volatility') == 'high':
                    category += "_HIGH_VOLATILITY"
                elif market_conditions.get('trend') == 'sideways':
                    category += "_SIDEWAYS_MARKET"
                elif market_conditions.get('volume') == 'low':
                    category += "_LOW_VOLUME"
            
            return category
            
        except Exception as e:
            print(f"❌ Error analyzing mistake category: {e}")
            return "UNKNOWN_MISTAKE"
    
    def analyze_trade_patterns(self, pair):
        """Analyze trading patterns for self-learning improvements"""
        try:
            if pair not in self.trade_outcomes or len(self.trade_outcomes[pair]) < 20:
                return
            
            recent_trades = self.trade_outcomes[pair][-100:]  # Last 100 trades
            
            # Analyze mistakes
            mistakes = [t for t in recent_trades if t['success'] is False]
            successes = [t for t in recent_trades if t['success'] is True]
            
            # Update mistake patterns
            if mistakes:
                mistake_analysis = self.analyze_mistake_patterns(mistakes)
                self.mistake_patterns[pair] = mistake_analysis
            
            # Update success patterns
            if successes:
                success_analysis = self.analyze_success_patterns(successes)
                self.success_patterns[pair] = success_analysis
            
            # Calculate recent performance metrics
            if len(recent_trades) >= 20:
                success_rate = len(successes) / len(recent_trades)
                avg_pnl = np.mean([t['pnl_percentage'] for t in recent_trades if t['pnl_percentage'] is not None])
                
                # Store performance metrics
                self.pair_performance[pair] = {
                    'success_rate': success_rate,
                    'avg_pnl': avg_pnl,
                    'total_trades': len(recent_trades),
                    'mistake_count': len(mistakes),
                    'last_updated': time.time()
                }
                
                # Trigger retraining if performance is poor
                if success_rate < self.config['min_accuracy_threshold']:
                    print(f"⚠️  Poor performance detected for {pair}: {success_rate:.3f}")
                    self.schedule_pair_retraining(pair)
            
        except Exception as e:
            print(f"❌ Error analyzing trade patterns for {pair}: {e}")
    
    def analyze_mistake_patterns(self, mistakes):
        """Analyze patterns in trading mistakes"""
        try:
            patterns = {
                'common_categories': {},
                'market_conditions': {},
                'confidence_correlation': [],
                'timing_patterns': {},
                'recommendations': []
            }
            
            # Analyze mistake categories
            for mistake in mistakes:
                category = mistake.get('mistake_category', 'UNKNOWN')
                patterns['common_categories'][category] = patterns['common_categories'].get(category, 0) + 1
            
            # Analyze market conditions during mistakes
            for mistake in mistakes:
                conditions = mistake.get('market_conditions')
                if conditions:
                    for condition, value in conditions.items():
                        if condition not in patterns['market_conditions']:
                            patterns['market_conditions'][condition] = {}
                        patterns['market_conditions'][condition][value] = patterns['market_conditions'][condition].get(value, 0) + 1
            
            # Analyze confidence vs outcome correlation
            for mistake in mistakes:
                if mistake.get('confidence') is not None and mistake.get('pnl_percentage') is not None:
                    patterns['confidence_correlation'].append({
                        'confidence': mistake['confidence'],
                        'loss': abs(mistake['pnl_percentage'])
                    })
            
            # Generate recommendations
            if patterns['common_categories']:
                most_common_mistake = max(patterns['common_categories'], key=patterns['common_categories'].get)
                patterns['recommendations'].append(f"Focus on reducing {most_common_mistake} mistakes")
            
            if patterns['confidence_correlation']:
                avg_confidence = np.mean([c['confidence'] for c in patterns['confidence_correlation']])
                if avg_confidence > 0.7:
                    patterns['recommendations'].append("High confidence mistakes detected - review feature selection")
            
            return patterns
            
        except Exception as e:
            print(f"❌ Error analyzing mistake patterns: {e}")
            return {}
    
    def analyze_success_patterns(self, successes):
        """Analyze patterns in successful trades"""
        try:
            patterns = {
                'optimal_conditions': {},
                'confidence_ranges': [],
                'timing_patterns': {},
                'market_conditions': {},
                'recommendations': []
            }
            
            # Analyze market conditions during successes
            for success in successes:
                conditions = success.get('market_conditions')
                if conditions:
                    for condition, value in conditions.items():
                        if condition not in patterns['market_conditions']:
                            patterns['market_conditions'][condition] = {}
                        patterns['market_conditions'][condition][value] = patterns['market_conditions'][condition].get(value, 0) + 1
            
            # Analyze confidence ranges for successful trades
            for success in successes:
                if success.get('confidence') is not None and success.get('pnl_percentage') is not None:
                    patterns['confidence_ranges'].append({
                        'confidence': success['confidence'],
                        'profit': success['pnl_percentage']
                    })
            
            # Generate recommendations
            if patterns['confidence_ranges']:
                high_profit_trades = [c for c in patterns['confidence_ranges'] if c['profit'] > 2.0]
                if high_profit_trades:
                    avg_confidence = np.mean([c['confidence'] for c in high_profit_trades])
                    patterns['recommendations'].append(f"High-profit trades average confidence: {avg_confidence:.3f}")
            
            return patterns
            
        except Exception as e:
            print(f"❌ Error analyzing success patterns: {e}")
            return {}
    
    def create_neural_network(self, input_size, pair):
        """Create optimized neural network for RTX 3090"""
        try:
            if not PYTORCH_AVAILABLE:
                return None
            
            class InstitutionalNN(nn.Module):
                def __init__(self, input_size, hidden_layers, dropout_rate=0.3):
                    super(InstitutionalNN, self).__init__()
                    
                    layers = []
                    prev_size = input_size
                    
                    # Build hidden layers
                    for hidden_size in hidden_layers:
                        layers.extend([
                            nn.Linear(prev_size, hidden_size),
                            nn.BatchNorm1d(hidden_size),
                            nn.ReLU(),
                            nn.Dropout(dropout_rate)
                        ])
                        prev_size = hidden_size
                    
                    # Output layer
                    layers.append(nn.Linear(prev_size, 2))  # Binary classification
                    
                    self.network = nn.Sequential(*layers)
                    
                    # Initialize weights
                    self.apply(self._init_weights)
                
                def _init_weights(self, module):
                    if isinstance(module, nn.Linear):
                        torch.nn.init.xavier_uniform_(module.weight)
                        module.bias.data.fill_(0.01)
                
                def forward(self, x):
                    return self.network(x)
            
            # Create model optimized for the pair's characteristics
            hidden_layers = self.config['neural_network_layers'].copy()
            
            # Adjust network size based on pair's historical performance
            if pair in self.pair_performance:
                success_rate = self.pair_performance[pair].get('success_rate', 0.5)
                if success_rate < 0.6:
                    # Increase network complexity for difficult pairs
                    hidden_layers = [int(x * 1.5) for x in hidden_layers]
            
            model = InstitutionalNN(input_size, hidden_layers)
            
            # Move to GPU if available
            if TORCH_DEVICE.type == 'cuda':
                model = model.to(TORCH_DEVICE)
            
            return model
            
        except Exception as e:
            print(f"❌ Error creating neural network for {pair}: {e}")
            return None
    
    def train_neural_network(self, X_train, y_train, X_val, y_val, pair):
        """Train neural network with RTX 3090 optimization"""
        try:
            if not PYTORCH_AVAILABLE:
                return None
            
            # Create model
            model = self.create_neural_network(X_train.shape[1], pair)
            if model is None:
                return None
            
            # Convert data to tensors
            X_train_tensor = torch.FloatTensor(X_train.values).to(TORCH_DEVICE)
            y_train_tensor = torch.LongTensor(y_train.values).to(TORCH_DEVICE)
            X_val_tensor = torch.FloatTensor(X_val.values).to(TORCH_DEVICE)
            y_val_tensor = torch.LongTensor(y_val.values).to(TORCH_DEVICE)
            
            # Create data loaders
            train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
            val_dataset = TensorDataset(X_val_tensor, y_val_tensor)
            
            batch_size = min(self.config['cuda_batch_size'], len(train_dataset))
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
            
            # Optimizer and loss function
            optimizer = optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
            criterion = nn.CrossEntropyLoss()
            
            # Learning rate scheduler
            if self.config['learning_rate_schedule']:
                scheduler = optim.lr_scheduler.ReduceLROnPlateau(
                    optimizer, mode='min', factor=0.5, patience=10, verbose=False
                )
            
            # Training loop
            best_val_loss = float('inf')
            patience_counter = 0
            
            for epoch in range(200):  # Max epochs
                # Training phase
                model.train()
                train_loss = 0.0
                
                for batch_X, batch_y in train_loader:
                    optimizer.zero_grad()
                    outputs = model(batch_X)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    
                    # Gradient clipping
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    
                    optimizer.step()
                    train_loss += loss.item()
                
                # Validation phase
                model.eval()
                val_loss = 0.0
                correct = 0
                total = 0
                
                with torch.no_grad():
                    for batch_X, batch_y in val_loader:
                        outputs = model(batch_X)
                        loss = criterion(outputs, batch_y)
                        val_loss += loss.item()
                        
                        _, predicted = torch.max(outputs.data, 1)
                        total += batch_y.size(0)
                        correct += (predicted == batch_y).sum().item()
                
                val_accuracy = correct / total
                avg_val_loss = val_loss / len(val_loader)
                
                # Learning rate scheduling
                if self.config['learning_rate_schedule']:
                    scheduler.step(avg_val_loss)
                
                # Early stopping
                if avg_val_loss < best_val_loss:
                    best_val_loss = avg_val_loss
                    patience_counter = 0
                    # Save best model state
                    best_model_state = model.state_dict().copy()
                else:
                    patience_counter += 1
                
                if patience_counter >= self.config['early_stopping_patience']:
                    print(f"   Early stopping at epoch {epoch}")
                    break
            
            # Restore best model
            model.load_state_dict(best_model_state)
            
            # Final evaluation
            model.eval()
            with torch.no_grad():
                val_outputs = model(X_val_tensor)
                val_probs = F.softmax(val_outputs, dim=1)[:, 1].cpu().numpy()
                val_preds = (val_probs > 0.5).astype(int)
                final_accuracy = accuracy_score(y_val, val_preds)
            
            print(f"   Neural Network trained: {final_accuracy:.3f} accuracy")
            
            return {
                'model': model,
                'accuracy': final_accuracy,
                'type': 'pytorch'
            }
            
        except Exception as e:
            print(f"❌ Error training neural network for {pair}: {e}")
            return None
    
    def train_pair_models(self, pair, timeframe, features, labels):
        """Train all models for a specific pair and timeframe"""
        try:
            if features.empty or len(labels) == 0:
                return None
            
            print(f"🎯 Training models for {pair} {timeframe}...")
            
            # Align features and labels
            min_len = min(len(features), len(labels))
            if min_len < self.config['min_samples_per_pair']:
                print(f"   ⚠️  Insufficient data: {min_len} samples")
                return None
            
            X = features.iloc[:min_len].copy()
            y = labels.iloc[:min_len].copy()
            
            # Advanced data cleaning
            X = self.advanced_data_cleaning(X)
            
            # Feature selection based on importance
            X = self.feature_selection(X, y, pair)
            
            # Split data with time series consideration
            if self.config['cross_validation_folds'] > 1:
                tscv = TimeSeriesSplit(n_splits=self.config['cross_validation_folds'])
                train_idx, val_idx = next(tscv.split(X))
                X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
                y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
            else:
                X_train, X_val, y_train, y_val = train_test_split(
                    X, y, test_size=0.2, random_state=42, stratify=y
                )
            
            # Scale features
            scaler = RobustScaler()  # More robust to outliers
            X_train_scaled = pd.DataFrame(
                scaler.fit_transform(X_train), 
                columns=X_train.columns, 
                index=X_train.index
            )
            X_val_scaled = pd.DataFrame(
                scaler.transform(X_val), 
                columns=X_val.columns, 
                index=X_val.index
            )
            
            # Store scaler
            if pair not in self.pair_scalers:
                self.pair_scalers[pair] = {}
            self.pair_scalers[pair][timeframe] = scaler
            
            # Train models
            models = {}
            training_start = time.time()
            
            # 1. XGBoost with hyperparameter optimization
            print(f"   🚀 Training XGBoost...")
            if self.config['hyperparameter_optimization']:
                xgb_params = self.optimize_xgboost_params(X_train, y_train)
            else:
                xgb_params = {
                    'objective': 'binary:logistic',
                    'eval_metric': 'logloss',
                    'max_depth': 6,
                    'learning_rate': 0.1,
                    'subsample': 0.8,
                    'colsample_bytree': 0.8,
                    'random_state': 42
                }
            
            dtrain = xgb.DMatrix(X_train, label=y_train)
            dval = xgb.DMatrix(X_val, label=y_val)
            
            xgb_model = xgb.train(
                xgb_params, dtrain, num_boost_round=300,
                evals=[(dval, 'val')], early_stopping_rounds=30,
                verbose_eval=False
            )
            
            xgb_pred = xgb_model.predict(dval) > 0.5
            xgb_acc = accuracy_score(y_val, xgb_pred)
            models['xgboost'] = {'model': xgb_model, 'accuracy': xgb_acc, 'type': 'xgboost'}
            
            # 2. LightGBM or Random Forest fallback
            if LIGHTGBM_AVAILABLE:
                print(f"   💡 Training LightGBM...")
                lgb_train = lgb.Dataset(X_train, label=y_train)
                lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_train)
                
                lgb_params = {
                    'objective': 'binary',
                    'metric': 'binary_logloss',
                    'boosting_type': 'gbdt',
                    'num_leaves': 31,
                    'learning_rate': 0.1,
                    'feature_fraction': 0.8,
                    'bagging_fraction': 0.8,
                    'bagging_freq': 5,
                    'verbose': -1,
                    'random_state': 42
                }
                
                lgb_model = lgb.train(
                    lgb_params, lgb_train, valid_sets=[lgb_val],
                    num_boost_round=300, callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)]
                )
                
                lgb_pred = lgb_model.predict(X_val) > 0.5
                lgb_acc = accuracy_score(y_val, lgb_pred)
                models['lightgbm'] = {'model': lgb_model, 'accuracy': lgb_acc, 'type': 'lightgbm'}
            else:
                print(f"   🌲 Training Random Forest (LightGBM fallback)...")
                rf_model = RandomForestClassifier(
                    n_estimators=300,
                    max_depth=10,
                    min_samples_split=5,
                    min_samples_leaf=2,
                    random_state=42,
                    n_jobs=-1
                )
                rf_model.fit(X_train, y_train)
                rf_pred = rf_model.predict(X_val)
                rf_acc = accuracy_score(y_val, rf_pred)
                models['lightgbm'] = {'model': rf_model, 'accuracy': rf_acc, 'type': 'sklearn'}
            
            # 3. CatBoost or Extra Trees fallback
            if CATBOOST_AVAILABLE:
                print(f"   🐱 Training CatBoost...")
                cb_model = cb.CatBoostClassifier(
                    iterations=300,
                    learning_rate=0.1,
                    depth=6,
                    loss_function='Logloss',
                    eval_metric='Accuracy',
                    random_seed=42,
                    verbose=False,
                    early_stopping_rounds=30
                )
                
                cb_model.fit(X_train, y_train, eval_set=(X_val, y_val))
                cb_pred = cb_model.predict(X_val)
                cb_acc = accuracy_score(y_val, cb_pred)
                models['catboost'] = {'model': cb_model, 'accuracy': cb_acc, 'type': 'catboost'}
            else:
                print(f"   🌳 Training Extra Trees (CatBoost fallback)...")
                et_model = ExtraTreesClassifier(
                    n_estimators=300,
                    max_depth=12,
                    min_samples_split=3,
                    min_samples_leaf=1,
                    random_state=42,
                    n_jobs=-1
                )
                et_model.fit(X_train, y_train)
                et_pred = et_model.predict(X_val)
                et_acc = accuracy_score(y_val, et_pred)
                models['catboost'] = {'model': et_model, 'accuracy': et_acc, 'type': 'sklearn'}
            
            # 4. Neural Network (if PyTorch available)
            if PYTORCH_AVAILABLE:
                print(f"   🧠 Training Neural Network...")
                nn_result = self.train_neural_network(X_train_scaled, y_train, X_val_scaled, y_val, pair)
                if nn_result:
                    models['neural_network'] = nn_result
            
            # 5. CUDA-accelerated models (if available)
            if CUDA_AVAILABLE:
                print(f"   🚀 Training CUDA models...")
                try:
                    # Convert to cuDF for GPU acceleration
                    X_train_gpu = cudf.DataFrame(X_train_scaled)
                    y_train_gpu = cudf.Series(y_train.values)
                    X_val_gpu = cudf.DataFrame(X_val_scaled)
                    y_val_gpu = cudf.Series(y_val.values)
                    
                    # CUDA Random Forest
                    cu_rf = cuRF(n_estimators=100, max_depth=10, random_state=42)
                    cu_rf.fit(X_train_gpu, y_train_gpu)
                    cu_rf_pred = cu_rf.predict(X_val_gpu).to_pandas()
                    cu_rf_acc = accuracy_score(y_val, cu_rf_pred)
                    models['cuda_rf'] = {'model': cu_rf, 'accuracy': cu_rf_acc, 'type': 'cuml'}
                    
                except Exception as e:
                    print(f"   ⚠️  CUDA models failed: {e}")
            
            # 6. Ensemble model
            print(f"   🎭 Creating ensemble...")
            ensemble_models = []
            ensemble_names = []
            
            for name, model_info in models.items():
                if model_info['type'] in ['xgboost', 'lightgbm', 'catboost']:
                    ensemble_models.append((name, model_info['model']))
                    ensemble_names.append(name)
            
            if len(ensemble_models) >= 2:
                # Create voting classifier wrapper for non-sklearn models
                class ModelWrapper:
                    def __init__(self, model, model_type):
                        self.model = model
                        self.model_type = model_type
                    
                    def predict_proba(self, X):
                        if self.model_type == 'xgboost':
                            pred = self.model.predict(xgb.DMatrix(X))
                            return np.column_stack([1-pred, pred])
                        elif self.model_type == 'lightgbm':
                            pred = self.model.predict(X)
                            return np.column_stack([1-pred, pred])
                        elif self.model_type == 'catboost':
                            return self.model.predict_proba(X)
                        else:
                            return X  # Fallback
                    
                    def predict(self, X):
                        proba = self.predict_proba(X)
                        return (proba[:, 1] > 0.5).astype(int)
                
                wrapped_models = [
                    (name, ModelWrapper(model_info['model'], model_info['type']))
                    for name, model_info in models.items()
                    if model_info['type'] in ['xgboost', 'lightgbm', 'catboost']
                ]
                
                if wrapped_models:
                    ensemble = VotingClassifier(
                        estimators=wrapped_models,
                        voting=self.config['ensemble_voting']
                    )
                    
                    # Fit ensemble (this is a dummy fit since models are already trained)
                    ensemble.estimators_ = [model for _, model in wrapped_models]
                    ensemble.named_estimators_ = dict(wrapped_models)
                    
                    # Evaluate ensemble
                    ensemble_pred = ensemble.predict(X_val)
                    ensemble_acc = accuracy_score(y_val, ensemble_pred)
                    models['ensemble'] = {'model': ensemble, 'accuracy': ensemble_acc, 'type': 'ensemble'}
            
            training_time = time.time() - training_start
            
            # Select best model
            best_model_name = max(models.keys(), key=lambda k: models[k]['accuracy'])
            best_accuracy = models[best_model_name]['accuracy']
            
            print(f"   ✅ Best model: {best_model_name} ({best_accuracy:.3f} accuracy)")
            print(f"   ⏱️  Training time: {training_time:.1f}s")
            
            # Store models
            if pair not in self.pair_models:
                self.pair_models[pair] = {}
            self.pair_models[pair][timeframe] = models
            
            # Save models to disk
            self.save_pair_models(pair, timeframe, models, scaler)
            
            # Store performance metrics in database
            self.store_model_performance(pair, timeframe, models, len(X_train), len(X_val), 
                                       len(X.columns), training_time)
            
            return models
            
        except Exception as e:
            print(f"❌ Error training models for {pair} {timeframe}: {e}")
            return None
    
    def advanced_data_cleaning(self, X):
        """Advanced data cleaning optimized for financial data"""
        try:
            # Remove infinite values
            X = X.replace([np.inf, -np.inf], np.nan)
            
            # Handle NaN values with sophisticated approach
            for col in X.columns:
                if X[col].isnull().any():
                    if X[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                        # For numeric columns, use forward fill then backward fill
                        X[col] = X[col].fillna(method='ffill').fillna(method='bfill')
                        # If still NaN, use median
                        if X[col].isnull().any():
                            X[col] = X[col].fillna(X[col].median())
                        # If still NaN, use 0
                        if X[col].isnull().any():
                            X[col] = X[col].fillna(0)
            
            # Remove columns with too many missing values (>50%)
            missing_threshold = 0.5
            cols_to_drop = []
            for col in X.columns:
                if X[col].isnull().sum() / len(X) > missing_threshold:
                    cols_to_drop.append(col)
            
            if cols_to_drop:
                X = X.drop(columns=cols_to_drop)
                print(f"   🧹 Dropped {len(cols_to_drop)} columns with >50% missing values")
            
            # Remove constant columns
            constant_cols = []
            for col in X.columns:
                if X[col].nunique() <= 1:
                    constant_cols.append(col)
            
            if constant_cols:
                X = X.drop(columns=constant_cols)
                print(f"   🧹 Dropped {len(constant_cols)} constant columns")
            
            # Remove highly correlated features (>0.95 correlation)
            corr_matrix = X.corr().abs()
            upper_triangle = corr_matrix.where(
                np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            )
            
            high_corr_cols = [
                column for column in upper_triangle.columns 
                if any(upper_triangle[column] > 0.95)
            ]
            
            if high_corr_cols:
                X = X.drop(columns=high_corr_cols)
                print(f"   🧹 Dropped {len(high_corr_cols)} highly correlated columns")
            
            return X
            
        except Exception as e:
            print(f"❌ Error in advanced data cleaning: {e}")
            return X
    
    def feature_selection(self, X, y, pair):
        """Intelligent feature selection based on importance and pair-specific patterns"""
        try:
            if len(X.columns) <= 50:  # Skip if already small feature set
                return X
            
            # Use XGBoost for feature importance
            dtrain = xgb.DMatrix(X, label=y)
            
            xgb_params = {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'max_depth': 3,
                'learning_rate': 0.1,
                'random_state': 42
            }
            
            model = xgb.train(xgb_params, dtrain, num_boost_round=50, verbose_eval=False)
            
            # Get feature importance
            importance = model.get_score(importance_type='weight')
            
            # Select features above threshold
            important_features = [
                feature for feature, score in importance.items()
                if score >= self.config['feature_selection_threshold']
            ]
            
            # Ensure we keep at least 20 features
            if len(important_features) < 20:
                # Sort by importance and take top 20
                sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
                important_features = [f[0] for f in sorted_features[:20]]
            
            # Apply pair-specific feature selection if we have historical data
            if pair in self.mistake_patterns:
                # Add features that help avoid common mistakes
                mistake_patterns = self.mistake_patterns[pair]
                if 'recommendations' in mistake_patterns:
                    # This is a simplified approach - in practice, you'd analyze which features
                    # correlate with mistake patterns and ensure they're included
                    pass
            
            selected_X = X[important_features]
            print(f"   🎯 Selected {len(important_features)} features from {len(X.columns)}")
            
            return selected_X
            
        except Exception as e:
            print(f"❌ Error in feature selection: {e}")
            return X
    
    def optimize_xgboost_params(self, X_train, y_train):
        """Optimize XGBoost hyperparameters using GridSearch"""
        try:
            param_grid = {
                'max_depth': [3, 6, 9],
                'learning_rate': [0.05, 0.1, 0.2],
                'subsample': [0.8, 0.9, 1.0],
                'colsample_bytree': [0.8, 0.9, 1.0]
            }
            
            # Use a subset for faster optimization
            sample_size = min(1000, len(X_train))
            X_sample = X_train.sample(n=sample_size, random_state=42)
            y_sample = y_train.loc[X_sample.index]
            
            best_score = 0
            best_params = {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'random_state': 42
            }
            
            # Simple grid search (limited for performance)
            for max_depth in param_grid['max_depth']:
                for learning_rate in param_grid['learning_rate']:
                    params = best_params.copy()
                    params.update({
                        'max_depth': max_depth,
                        'learning_rate': learning_rate,
                        'subsample': 0.8,
                        'colsample_bytree': 0.8
                    })
                    
                    dtrain = xgb.DMatrix(X_sample, label=y_sample)
                    cv_results = xgb.cv(
                        params, dtrain, num_boost_round=50, nfold=3,
                        metrics='logloss', seed=42, verbose_eval=False
                    )
                    
                    score = 1 - cv_results['test-logloss-mean'].iloc[-1]  # Convert to accuracy-like metric
                    
                    if score > best_score:
                        best_score = score
                        best_params.update({
                            'max_depth': max_depth,
                            'learning_rate': learning_rate,
                            'subsample': 0.8,
                            'colsample_bytree': 0.8
                        })
            
            print(f"   🎯 Optimized XGBoost params: depth={best_params['max_depth']}, lr={best_params['learning_rate']}")
            return best_params
            
        except Exception as e:
            print(f"❌ Error optimizing XGBoost params: {e}")
            return {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'max_depth': 6,
                'learning_rate': 0.1,
                'random_state': 42
            }
    
    def save_pair_models(self, pair, timeframe, models, scaler):
        """Save trained models to disk"""
        try:
            pair_dir = self.model_dir / pair
            pair_dir.mkdir(exist_ok=True)
            
            # Save each model
            for model_name, model_info in models.items():
                model_file = pair_dir / f"{model_name}_{timeframe}.joblib"
                
                if model_info['type'] == 'pytorch':
                    # Save PyTorch model separately
                    torch_file = pair_dir / f"{model_name}_{timeframe}.pth"
                    torch.save(model_info['model'].state_dict(), torch_file)
                    # Save model info without the actual model
                    model_info_copy = model_info.copy()
                    model_info_copy['model'] = None  # Remove model for joblib
                    model_info_copy['model_file'] = str(torch_file)
                    dump(model_info_copy, model_file)
                else:
                    dump(model_info, model_file)
            
            # Save scaler
            scaler_file = pair_dir / f"scaler_{timeframe}.joblib"
            dump(scaler, scaler_file)
            
        except Exception as e:
            print(f"❌ Error saving models for {pair}: {e}")
    
    def load_existing_models(self):
        """Load existing trained models"""
        try:
            if not self.model_dir.exists():
                return
            
            for pair_dir in self.model_dir.iterdir():
                if pair_dir.is_dir():
                    pair = pair_dir.name
                    self.pair_models[pair] = {}
                    self.pair_scalers[pair] = {}
                    
                    for timeframe in self.timeframes:
                        # Load scaler
                        scaler_file = pair_dir / f"scaler_{timeframe}.joblib"
                        if scaler_file.exists():
                            self.pair_scalers[pair][timeframe] = load(scaler_file)
                        
                        # Load models
                        models = {}
                        for model_type in self.config['models_per_pair']:
                            model_file = pair_dir / f"{model_type}_{timeframe}.joblib"
                            if model_file.exists():
                                model_info = load(model_file)
                                
                                # Handle PyTorch models
                                if model_info.get('type') == 'pytorch' and 'model_file' in model_info:
                                    torch_file = Path(model_info['model_file'])
                                    if torch_file.exists():
                                        # Recreate model architecture and load weights
                                        # This would need the input size - simplified for now
                                        pass
                                
                                models[model_type] = model_info
                        
                        if models:
                            self.pair_models[pair][timeframe] = models
                    
                    if self.pair_models[pair]:
                        print(f"   ✅ Loaded models for {pair}")
            
        except Exception as e:
            print(f"❌ Error loading existing models: {e}")
    
    def load_trade_outcomes(self):
        """Load trade outcomes from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT pair, signal_id, prediction, confidence, entry_price, exit_price,
                           pnl_percentage, success, trade_duration, market_conditions,
                           mistake_category, timestamp
                    FROM trade_outcomes
                    ORDER BY timestamp DESC
                    LIMIT 50000
                ''')
                
                rows = cursor.fetchall()
                
                for row in rows:
                    pair = row[0]
                    if pair not in self.trade_outcomes:
                        self.trade_outcomes[pair] = []
                    
                    trade_data = {
                        'signal_id': row[1],
                        'prediction': row[2],
                        'confidence': row[3],
                        'entry_price': row[4],
                        'exit_price': row[5],
                        'pnl_percentage': row[6],
                        'success': bool(row[7]) if row[7] is not None else None,
                        'trade_duration': row[8],
                        'market_conditions': json.loads(row[9]) if row[9] else None,
                        'mistake_category': row[10],
                        'timestamp': row[11]
                    }
                    
                    self.trade_outcomes[pair].append(trade_data)
                
                print(f"   ✅ Loaded trade outcomes for {len(self.trade_outcomes)} pairs")
                
        except Exception as e:
            print(f"❌ Error loading trade outcomes: {e}")
    
    def store_model_performance(self, pair, timeframe, models, train_samples, val_samples, 
                              feature_count, training_time):
        """Store model performance metrics in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                for model_name, model_info in models.items():
                    cursor.execute('''
                        INSERT INTO model_performance
                        (pair, timeframe, model_type, accuracy, training_samples,
                         validation_samples, feature_count, training_time, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        pair, timeframe, model_name, model_info['accuracy'],
                        train_samples, val_samples, feature_count, training_time,
                        int(time.time())
                    ))
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error storing model performance: {e}")
    
    def schedule_pair_retraining(self, pair):
        """Schedule retraining for a specific pair"""
        try:
            # This would be implemented with a proper task queue in production
            # For now, we'll just mark it for retraining
            if not hasattr(self, 'retraining_queue'):
                self.retraining_queue = set()
            
            self.retraining_queue.add(pair)
            print(f"📅 Scheduled retraining for {pair}")
            
        except Exception as e:
            print(f"❌ Error scheduling retraining for {pair}: {e}")
    
    def start_background_processes(self):
        """Start background processes for continuous learning"""
        try:
            # Background retraining thread
            def background_retraining():
                while True:
                    try:
                        # Check for scheduled retraining
                        if hasattr(self, 'retraining_queue') and self.retraining_queue:
                            pair = self.retraining_queue.pop()
                            print(f"🔄 Background retraining for {pair}")
                            self.retrain_pair_models(pair)
                        
                        time.sleep(300)  # Check every 5 minutes
                        
                    except Exception as e:
                        print(f"❌ Background retraining error: {e}")
                        time.sleep(600)  # Wait 10 minutes on error
            
            retraining_thread = threading.Thread(target=background_retraining, daemon=True)
            retraining_thread.start()
            
            print("🔄 Background processes started")
            
        except Exception as e:
            print(f"❌ Error starting background processes: {e}")
    
    def retrain_pair_models(self, pair):
        """Retrain models for a specific pair using latest data"""
        try:
            print(f"🔄 Retraining models for {pair}...")
            
            # This would fetch fresh data and retrain
            # Implementation depends on integration with data fetching system
            # For now, this is a placeholder
            
            return True
            
        except Exception as e:
            print(f"❌ Error retraining {pair}: {e}")
            return False

# Global instance
institutional_ml = None

def initialize_institutional_ml():
    """Initialize the institutional ML system"""
    global institutional_ml
    if institutional_ml is None:
        institutional_ml = InstitutionalMLSystem()
    return institutional_ml

def get_institutional_prediction(pair, timeframe='1h'):
    """Get prediction from institutional ML system"""
    global institutional_ml
    if institutional_ml is None:
        institutional_ml = initialize_institutional_ml()
    
    # Implementation for getting predictions
    return None

def train_pair_specific_models(pairs_list):
    """Train models for specific pairs"""
    global institutional_ml
    if institutional_ml is None:
        institutional_ml = initialize_institutional_ml()
    
    # Implementation for training specific pairs
    return True

def update_trade_outcome(pair, signal_id, prediction, confidence, entry_price, 
                        exit_price=None, pnl_percentage=None, success=None):
    """Update trade outcome for self-learning"""
    global institutional_ml
    if institutional_ml is None:
        institutional_ml = initialize_institutional_ml()
    
    institutional_ml.store_trade_outcome(
        pair, signal_id, prediction, confidence, entry_price,
        exit_price, pnl_percentage, success
    )

if __name__ == "__main__":
    # Initialize and test the system
    system = InstitutionalMLSystem()
    print("🏛️  Institutional ML System initialized successfully!")
