#!/usr/bin/env python3
"""
Signal Cache Integration Module for binance_hunter_talib.py
Provides seamless integration of the enhanced signal caching system
"""

import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Union
from enhanced_signal_cache import (
    get_signal_cache, 
    cache_trading_signal, 
    get_cached_trading_signal,
    invalidate_trading_signal,
    get_cache_statistics,
    CachedSignal
)

class SignalCacheManager:
    """
    Manager class for integrating signal caching with trading systems
    """
    
    def __init__(self, cache_duration_hours: float = 1.0):
        self.cache_duration_hours = cache_duration_hours
        self.cache = get_signal_cache(cache_duration_hours)
        
        # Feature extraction configuration
        self.feature_keys = [
            'rsi', 'macd', 'macd_signal', 'macd_histogram',
            'bb_upper', 'bb_middle', 'bb_lower', 'bb_width',
            'volume_sma', 'volume_ratio', 'atr', 'adx',
            'stoch_k', 'stoch_d', 'williams_r', 'cci',
            'momentum', 'roc', 'trix', 'ultimate_oscillator',
            'price_change_pct', 'volume_change_pct'
        ]
        
        print(f"🔗 Signal Cache Manager initialized (cache duration: {cache_duration_hours}h)")
    
    def extract_features_from_data(self, df: pd.DataFrame, 
                                  indicators: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract features from DataFrame for cache key generation
        
        Args:
            df: OHLCV DataFrame
            indicators: Optional pre-calculated indicators
            
        Returns:
            Dictionary of features for caching
        """
        try:
            features = {}
            
            if df.empty:
                return features
            
            # Get latest values
            latest = df.iloc[-1]
            
            # Basic price features
            features['close'] = float(latest['close'])
            features['volume'] = float(latest['volume'])
            features['high'] = float(latest['high'])
            features['low'] = float(latest['low'])
            features['open'] = float(latest['open'])
            
            # Price change percentage
            if len(df) > 1:
                prev_close = df.iloc[-2]['close']
                features['price_change_pct'] = float((latest['close'] - prev_close) / prev_close * 100)
                
                prev_volume = df.iloc[-2]['volume']
                if prev_volume > 0:
                    features['volume_change_pct'] = float((latest['volume'] - prev_volume) / prev_volume * 100)
                else:
                    features['volume_change_pct'] = 0.0
            else:
                features['price_change_pct'] = 0.0
                features['volume_change_pct'] = 0.0
            
            # Extract indicator values if provided
            if indicators:
                for key in self.feature_keys:
                    if key in indicators:
                        value = indicators[key]
                        if isinstance(value, (pd.Series, np.ndarray)):
                            # Get latest value
                            if len(value) > 0:
                                latest_val = value.iloc[-1] if hasattr(value, 'iloc') else value[-1]
                                if not pd.isna(latest_val) and np.isfinite(latest_val):
                                    features[key] = float(latest_val)
                        elif isinstance(value, (int, float)) and np.isfinite(value):
                            features[key] = float(value)
            
            # Round values to reduce cache key variations
            for key, value in features.items():
                if isinstance(value, float):
                    features[key] = round(value, 6)
            
            return features
            
        except Exception as e:
            print(f"❌ Error extracting features: {e}")
            return {}
    
    def should_use_cached_signal(self, pair: str, timeframe: str, 
                                df: pd.DataFrame, indicators: Dict[str, Any],
                                min_confidence: float = 0.6) -> Optional[CachedSignal]:
        """
        Check if a cached signal should be used instead of generating a new one
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            df: OHLCV DataFrame
            indicators: Calculated indicators
            min_confidence: Minimum confidence threshold for using cached signals
            
        Returns:
            CachedSignal if should use cached, None if should generate new
        """
        try:
            # Extract features for cache lookup
            features = self.extract_features_from_data(df, indicators)
            
            if not features:
                return None
            
            # Try to get cached signal
            cached_signal = get_cached_trading_signal(pair, timeframe, features)
            
            if cached_signal and cached_signal.confidence >= min_confidence:
                return cached_signal
            
            return None
            
        except Exception as e:
            print(f"❌ Error checking cached signal: {e}")
            return None
    
    def cache_new_signal(self, pair: str, timeframe: str, signal_type: str,
                        confidence: float, current_price: float,
                        df: pd.DataFrame, indicators: Dict[str, Any],
                        metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Cache a new trading signal
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            signal_type: 'BUY', 'SELL', or 'NEUTRAL'
            confidence: Signal confidence (0.0 to 1.0)
            current_price: Current price
            df: OHLCV DataFrame
            indicators: Calculated indicators
            metadata: Additional metadata
            
        Returns:
            Signal ID of cached signal
        """
        try:
            # Extract features
            features = self.extract_features_from_data(df, indicators)
            
            if not features:
                print(f"⚠️  No features extracted for {pair} {timeframe}")
                return ""
            
            # Add metadata
            if metadata is None:
                metadata = {}
            
            metadata.update({
                'cached_at': time.time(),
                'timeframe': timeframe,
                'pair': pair,
                'feature_count': len(features)
            })
            
            # Cache the signal
            signal_id = cache_trading_signal(
                pair=pair,
                timeframe=timeframe,
                signal_type=signal_type,
                confidence=confidence,
                price=current_price,
                features=features,
                metadata=metadata
            )
            
            return signal_id
            
        except Exception as e:
            print(f"❌ Error caching signal: {e}")
            return ""
    
    def invalidate_pair_cache(self, pair: str, timeframe: Optional[str] = None) -> int:
        """
        Invalidate cached signals for a pair/timeframe
        
        Args:
            pair: Trading pair to invalidate
            timeframe: Optional specific timeframe
            
        Returns:
            Number of signals invalidated
        """
        try:
            return self.cache.invalidate_pair_signals(pair, timeframe)
        except Exception as e:
            print(f"❌ Error invalidating cache: {e}")
            return 0
    
    def get_cache_summary(self) -> Dict[str, Any]:
        """Get cache statistics and summary"""
        try:
            stats = get_cache_statistics()
            
            # Add active signals summary
            active_signals = self.cache.get_active_signals()
            
            signal_summary = {}
            for signal in active_signals:
                key = f"{signal.pair}_{signal.timeframe}"
                if key not in signal_summary:
                    signal_summary[key] = []
                signal_summary[key].append({
                    'type': signal.signal_type,
                    'confidence': signal.confidence,
                    'age_minutes': (time.time() - signal.timestamp) / 60
                })
            
            stats['signal_summary'] = signal_summary
            stats['active_pairs'] = len(signal_summary)
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting cache summary: {e}")
            return {}

# Global cache manager instance
_cache_manager = None

def get_cache_manager(cache_duration_hours: float = 1.0) -> SignalCacheManager:
    """Get or create global cache manager instance"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = SignalCacheManager(cache_duration_hours)
    return _cache_manager

def check_cached_signal(pair: str, timeframe: str, df: pd.DataFrame, 
                       indicators: Dict[str, Any], min_confidence: float = 0.6) -> Optional[CachedSignal]:
    """
    Convenience function to check for cached signals
    
    Returns:
        CachedSignal if found and valid, None otherwise
    """
    manager = get_cache_manager()
    return manager.should_use_cached_signal(pair, timeframe, df, indicators, min_confidence)

def cache_signal(pair: str, timeframe: str, signal_type: str, confidence: float,
                current_price: float, df: pd.DataFrame, indicators: Dict[str, Any],
                metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Convenience function to cache a signal
    
    Returns:
        Signal ID of cached signal
    """
    manager = get_cache_manager()
    return manager.cache_new_signal(pair, timeframe, signal_type, confidence, 
                                   current_price, df, indicators, metadata)

def invalidate_cache(pair: str, timeframe: Optional[str] = None) -> int:
    """
    Convenience function to invalidate cache
    
    Returns:
        Number of signals invalidated
    """
    manager = get_cache_manager()
    return manager.invalidate_pair_cache(pair, timeframe)

def get_cache_info() -> Dict[str, Any]:
    """
    Convenience function to get cache information
    
    Returns:
        Cache statistics and summary
    """
    manager = get_cache_manager()
    return manager.get_cache_summary()

# Integration decorator for signal generation functions
def with_signal_cache(cache_duration_hours: float = 1.0, min_confidence: float = 0.6):
    """
    Decorator to add signal caching to signal generation functions
    
    Usage:
        @with_signal_cache(cache_duration_hours=1.0, min_confidence=0.7)
        def generate_signal(pair, timeframe, df, indicators):
            # Your signal generation logic
            return signal_type, confidence
    """
    def decorator(func):
        def wrapper(pair: str, timeframe: str, df: pd.DataFrame, 
                   indicators: Dict[str, Any], *args, **kwargs):
            
            # Check for cached signal first
            cached_signal = check_cached_signal(pair, timeframe, df, indicators, min_confidence)
            
            if cached_signal:
                print(f"🎯 Using cached {cached_signal.signal_type} signal for {pair} {timeframe}")
                return cached_signal.signal_type, cached_signal.confidence
            
            # Generate new signal
            result = func(pair, timeframe, df, indicators, *args, **kwargs)
            
            if isinstance(result, tuple) and len(result) >= 2:
                signal_type, confidence = result[0], result[1]
                
                # Cache the new signal if confidence is sufficient
                if confidence >= min_confidence:
                    current_price = float(df.iloc[-1]['close']) if not df.empty else 0.0
                    cache_signal(pair, timeframe, signal_type, confidence, 
                               current_price, df, indicators)
            
            return result
        
        return wrapper
    return decorator

if __name__ == "__main__":
    # Test the integration
    print("🧪 Testing Signal Cache Integration...")
    
    # Create test data
    test_df = pd.DataFrame({
        'open': [100, 101, 102],
        'high': [105, 106, 107],
        'low': [99, 100, 101],
        'close': [104, 105, 106],
        'volume': [1000, 1100, 1200]
    })
    
    test_indicators = {
        'rsi': pd.Series([70, 65, 60]),
        'macd': pd.Series([0.5, 0.3, 0.1]),
        'bb_upper': pd.Series([110, 111, 112]),
        'bb_lower': pd.Series([95, 96, 97])
    }
    
    manager = SignalCacheManager(cache_duration_hours=0.1)
    
    # Test feature extraction
    features = manager.extract_features_from_data(test_df, test_indicators)
    print(f"✅ Extracted features: {len(features)} items")
    
    # Test caching a signal
    signal_id = manager.cache_new_signal(
        'BTCUSDT', '1h', 'BUY', 0.85, 106.0, test_df, test_indicators
    )
    print(f"✅ Cached signal: {signal_id}")
    
    # Test retrieving cached signal
    cached = manager.should_use_cached_signal('BTCUSDT', '1h', test_df, test_indicators)
    if cached:
        print(f"✅ Retrieved cached signal: {cached.signal_type} (confidence: {cached.confidence})")
    
    # Test cache summary
    summary = manager.get_cache_summary()
    print(f"📊 Cache summary: {summary}")
    
    print("🎯 Signal Cache Integration test completed!")
