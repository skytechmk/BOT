# Multi-Timeframe ML System Documentation

## Overview

The Multi-Timeframe ML System is an advanced machine learning framework that implements trading signal generation across multiple timeframes with pattern correlation analysis, automatic retraining every 6 hours, and a self-learning system for improved accuracy.

## Key Features

### 1. Multi-Timeframe Analysis
- **Supported Timeframes**: 1m, 5m, 15m, 1h, 4h, 1d
- **Correlation Analysis**: Calculates correlations between different timeframes
- **Consensus Building**: Combines predictions from all timeframes with weighted voting
- **Timeframe-Specific Features**: Each timeframe gets specialized feature engineering

### 2. Advanced ML Models
- **Ensemble Learning**: XGBoost, Random Forest, Gradient Boosting
- **Model Selection**: Automatically selects best performing model per timeframe
- **Feature Engineering**: 134+ comprehensive technical indicators and features
- **Adaptive Labeling**: Dynamic thresholds based on volatility (ATR)

### 3. Automatic Retraining
- **Schedule**: Every 6 hours automatically
- **Fresh Data**: Fetches latest historical data for training
- **Incremental Learning**: Combines new data with existing knowledge
- **Performance Monitoring**: Tracks model accuracy over time

### 4. Self-Learning System
- **Prediction Tracking**: Records all predictions and actual outcomes
- **Performance Analysis**: Monitors accuracy per symbol and timeframe
- **Adaptive Retraining**: Triggers retraining when performance drops below threshold
- **Learning History**: Maintains up to 1000 recent predictions per symbol

### 5. Enhanced Signal Generation
- **ML Override**: High-confidence ML predictions can override technical signals
- **Confidence Scoring**: Each prediction includes confidence percentage
- **Multi-TF Consensus**: Weighted consensus across participating timeframes
- **Signal Enhancement**: Enriched Telegram messages with ML insights

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Timeframe ML System                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │    Data     │  │   Feature   │  │   Model     │  │  Self   │ │
│  │  Fetching   │→ │ Engineering │→ │  Training   │→ │Learning │ │
│  │             │  │             │  │             │  │         │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
│         │                 │                 │             │     │
│         ▼                 ▼                 ▼             ▼     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │ Correlation │  │ Prediction  │  │ Consensus   │  │ Signal  │ │
│  │  Analysis   │  │ Generation  │  │  Building   │  │ Output  │ │
│  │             │  │             │  │             │  │         │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
/home/MAIN_BOT/
├── multi_timeframe_ml_system.py      # Main ML system implementation
├── binance_hunter_talib.py           # Enhanced trading bot with ML integration
├── test_multi_timeframe_system.py    # Comprehensive test suite
├── ml_models/                        # Model storage directory
│   ├── model_1m.joblib              # 1-minute timeframe models
│   ├── model_5m.joblib              # 5-minute timeframe models
│   ├── model_15m.joblib             # 15-minute timeframe models
│   ├── model_1h.joblib              # 1-hour timeframe models
│   ├── model_4h.joblib              # 4-hour timeframe models
│   ├── model_1d.joblib              # 1-day timeframe models
│   ├── scaler_1m.joblib             # Feature scalers per timeframe
│   └── ...
├── performance_logs/                 # Performance tracking
│   ├── performance_summary.json     # Model performance metrics
│   └── self_learning_data.json      # Self-learning history
└── historical_data/                  # Data cache directory
```

## Configuration

The system is configured through the `config` dictionary in `MultiTimeframeMLSystem`:

```python
self.config = {
    'retrain_interval': 6 * 3600,              # 6 hours in seconds
    'min_accuracy_threshold': 0.55,            # Minimum acceptable accuracy
    'correlation_threshold': 0.7,              # High correlation threshold
    'max_features': 200,                       # Maximum number of features
    'ensemble_models': ['xgboost', 'random_forest', 'gradient_boosting'],
    'prediction_confidence_threshold': 0.6     # Minimum confidence for predictions
}
```

## Usage Examples

### 1. Initialize the System

```python
from multi_timeframe_ml_system import initialize_ml_system

# Initialize the global ML system
ml_system = initialize_ml_system()
```

### 2. Get Multi-Timeframe Prediction

```python
from multi_timeframe_ml_system import get_multi_timeframe_prediction

# Get prediction for BTCUSDT
prediction = get_multi_timeframe_prediction('BTCUSDT')

if prediction:
    consensus = prediction['consensus']
    print(f"Signal: {consensus['signal']}")
    print(f"Confidence: {consensus['confidence']:.1%}")
    print(f"Participating Timeframes: {consensus['participating_timeframes']}")
```

### 3. Train All Models

```python
from multi_timeframe_ml_system import train_all_models

# Train models for all timeframes
success = train_all_models()
if success:
    print("All models trained successfully!")
```

### 4. Update Self-Learning System

```python
from multi_timeframe_ml_system import update_prediction_outcome

# Update with prediction outcome
update_prediction_outcome('BTCUSDT', 'BUY', 'BUY', '1h')  # Correct prediction
update_prediction_outcome('ETHUSDT', 'SELL', 'BUY', '4h') # Wrong prediction
```

## Feature Engineering

The system generates 134+ features per timeframe including:

### Basic Features
- OHLCV data
- Price returns and log returns
- Volatility measures (5, 10, 20 periods)
- Price changes (1, 3, 5, 10 periods)
- Volume ratios

### Technical Indicators
- **Momentum**: RSI, Stochastic, Williams %R, ROC, MOM, CCI, CMO
- **Trend**: ADX, ADXR, DI+, DI-, Aroon, MACD, PPO, TRIX
- **Volatility**: ATR, NATR, True Range
- **Volume**: A/D Line, ADOSC, OBV, MFI
- **Moving Averages**: SMA, EMA, WMA, DEMA, TEMA, TRIMA, KAMA, MAMA, T3
- **Cycle**: Hilbert Transform indicators
- **Statistical**: Beta, Correlation, Linear Regression, Standard Deviation

### Pattern Recognition
- 40+ candlestick patterns using TA-Lib
- Pattern strength and direction
- Pattern-based features

### Multi-Timeframe Features
- Timeframe encoding
- Cross-timeframe momentum
- Volatility regime detection
- Volume profile analysis

### Sentiment Analysis
- Transformer-based market sentiment
- Confidence scoring

## Model Training Process

### 1. Data Collection
```python
# Collect data from multiple symbols and timeframes
training_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', ...]
timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']

for symbol in training_symbols:
    for timeframe in timeframes:
        # Fetch data, calculate features, generate labels
        # Store in timeframe-specific collections
```

### 2. Feature Engineering
```python
# Calculate comprehensive features for each timeframe
features = calculate_comprehensive_features(df, timeframe)

# Add timeframe-specific features
features['timeframe_minutes'] = tf_encoding[timeframe]
features['momentum_5'] = df['close'].pct_change(5)
features['volatility_regime'] = df['ATR'] / df['ATR'].rolling(20).mean()
```

### 3. Label Generation
```python
# Adaptive labeling based on volatility
for i in range(len(df) - future_periods):
    current_price = df['close'].iloc[i]
    future_price = df['close'].iloc[i + future_periods]
    price_change = (future_price - current_price) / current_price
    
    # Dynamic threshold based on ATR
    threshold = max(0.005, atr_threshold * 0.5)
    label = 1 if price_change > threshold else 0
```

### 4. Model Training
```python
# Train ensemble models for each timeframe
models = {
    'xgboost': train_xgboost_model(X, y),
    'random_forest': train_rf_model(X, y),
    'gradient_boosting': train_gb_model(X, y)
}

# Select best performing model
best_model = max(models.keys(), key=lambda k: models[k]['accuracy'])
```

## Prediction Process

### 1. Multi-Timeframe Data Fetching
```python
timeframe_data = {}
for tf in timeframes:
    df = fetch_data(symbol, tf)
    timeframe_data[tf] = df
```

### 2. Feature Calculation
```python
for tf, df in timeframe_data.items():
    features = calculate_comprehensive_features(df, tf)
    # Store features for prediction
```

### 3. Individual Predictions
```python
for tf in timeframes:
    if tf in models:
        # Get ensemble prediction
        predictions = []
        for model_name, model_info in models[tf].items():
            pred = model_info['model'].predict(features)
            predictions.append(pred)
        
        # Weighted average by accuracy
        weights = [models[tf][name]['accuracy'] for name in models[tf].keys()]
        final_pred = np.average(predictions, weights=weights)
```

### 4. Consensus Building
```python
# Weight predictions by timeframe importance and confidence
tf_weights = {
    '1m': 0.1, '5m': 0.15, '15m': 0.2, 
    '1h': 0.25, '4h': 0.2, '1d': 0.1
}

weighted_signals = []
for tf, pred in predictions.items():
    weight = tf_weights[tf] * pred['confidence']
    weighted_signals.append(pred['signal_value'] * weight)

consensus_score = sum(weighted_signals) / sum(weights)
consensus_signal = 'BUY' if consensus_score > 0.5 else 'SELL'
```

## Self-Learning System

### 1. Prediction Tracking
```python
learning_entry = {
    'symbol': symbol,
    'timeframe': timeframe,
    'prediction': prediction,
    'actual_outcome': actual_outcome,
    'timestamp': timestamp,
    'accuracy': 1 if prediction == actual_outcome else 0
}
```

### 2. Performance Analysis
```python
# Calculate recent accuracy
recent_entries = self.self_learning_data[symbol][-100:]
recent_accuracy = sum(entry['accuracy'] for entry in recent_entries) / len(recent_entries)

# Trigger retraining if below threshold
if recent_accuracy < self.config['min_accuracy_threshold']:
    self.adaptive_retrain_timeframe(timeframe, [symbol])
```

### 3. Adaptive Retraining
```python
def adaptive_retrain_timeframe(self, timeframe, symbol_list):
    # Collect fresh data
    # Retrain specific timeframe model
    # Update performance metrics
```

## Integration with Main Trading Bot

The system is fully integrated with the main trading bot (`binance_hunter_talib.py`):

### 1. Initialization
```python
# Initialize Multi-Timeframe ML System on startup
if MULTI_TF_ML_AVAILABLE:
    ml_system = initialize_ml_system()
    await send_telegram_message("✅ Multi-Timeframe ML System ready!")
```

### 2. Signal Enhancement
```python
# Get multi-timeframe prediction
multi_tf_prediction = get_multi_timeframe_prediction(pair)

# Override or confirm technical signals
if ml_confidence > 0.7 and ml_signal != technical_signal:
    final_signal = ml_signal  # ML override
    ml_info = f"🤖 **ML Override**: {ml_signal} (confidence: {ml_confidence:.1%})"
elif ml_signal == technical_signal:
    ml_info = f"✅ **ML Confirmation**: {ml_signal} (confidence: {ml_confidence:.1%})"
```

### 3. Enhanced Telegram Messages
```python
binance_futures_signal = (
    f"⭐️ NEW Enhanced Binance Futures {final_signal} SIGNAL ⭐️\n"
    f"🔹 **Pair**: {pair}\n"
    f"{pattern_info}"
    f"{ml_info}"
    f"{timeframe_analysis}\n"
    f"🔸 **Entry**: {current_price:.{precision}f}\n"
    # ... rest of signal message
)
```

## Performance Monitoring

### 1. Model Performance Metrics
```json
{
  "timeframe_performance": {
    "1h": {
      "accuracy": 0.87,
      "best_model": "random_forest",
      "training_samples": 1500,
      "test_samples": 375,
      "timestamp": "2025-07-02T23:29:09.475671"
    }
  }
}
```

### 2. Self-Learning Data
```json
{
  "BTCUSDT": [
    {
      "symbol": "BTCUSDT",
      "timeframe": "1h",
      "prediction": "BUY",
      "actual_outcome": "BUY",
      "timestamp": "2025-07-02T23:29:09.475671",
      "accuracy": 1
    }
  ]
}
```

### 3. Correlation Matrix
```json
{
  "correlation_matrix": {
    "1h": {
      "4h": 0.032,
      "1d": -0.035
    }
  }
}
```

## Testing

Run the comprehensive test suite:

```bash
python test_multi_timeframe_system.py
```

The test suite covers:
- System initialization
- Data fetching
- Feature calculation
- Label generation
- Correlation analysis
- Model training
- Prediction generation
- Self-learning updates
- Integration with main bot

## Troubleshooting

### Common Issues

1. **Model Training Fails**
   - Check data availability
   - Verify feature calculation
   - Ensure sufficient training samples (>100)

2. **Prediction Returns None**
   - Check if models are trained
   - Verify feature compatibility
   - Check data quality

3. **Self-Learning Not Working**
   - Verify file permissions for performance_logs/
   - Check JSON file integrity
   - Ensure proper prediction outcome format

### Debug Mode

Enable detailed logging by checking the debug log:

```bash
tail -f debug_log10.txt
```

### Performance Issues

- Monitor memory usage during training
- Adjust training data size if needed
- Check disk space for model storage

## Future Enhancements

1. **Deep Learning Models**: Add LSTM/GRU for sequence modeling
2. **Real-time Streaming**: Implement real-time data streaming
3. **Advanced Ensembles**: Add stacking and blending techniques
4. **Feature Selection**: Implement automatic feature selection
5. **Hyperparameter Optimization**: Add automated hyperparameter tuning
6. **Cross-Validation**: Implement time-series cross-validation
7. **Risk Management**: Add position sizing based on ML confidence
8. **Market Regime Detection**: Implement market regime classification

## Conclusion

The Multi-Timeframe ML System provides a comprehensive, production-ready machine learning framework for cryptocurrency trading. It combines advanced feature engineering, ensemble learning, automatic retraining, and self-learning capabilities to deliver high-accuracy trading signals across multiple timeframes.

The system is designed to be:
- **Robust**: Handles errors gracefully and continues operation
- **Scalable**: Can be extended to more timeframes and symbols
- **Adaptive**: Learns from its mistakes and improves over time
- **Transparent**: Provides detailed logging and performance metrics
- **Integrated**: Seamlessly works with the existing trading bot

With automatic retraining every 6 hours and continuous self-learning, the system maintains high accuracy and adapts to changing market conditions automatically.
