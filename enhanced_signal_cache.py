#!/usr/bin/env python3
"""
Enhanced Signal Caching System with 1-Hour Time-Based Expiration and Opposite Direction Logic
Designed for integration with binance_hunter_talib.py
"""

import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import threading

@dataclass
class CachedSignal:
    """Represents a cached trading signal"""
    pair: str
    timeframe: str
    signal_type: str  # 'BUY', 'SELL', 'NEUTRAL'
    confidence: float
    price: float
    timestamp: float
    features_hash: str
    signal_id: str
    metadata: Dict[str, Any]
    expiry_time: float
    
    def is_expired(self) -> bool:
        """Check if the signal has expired"""
        return time.time() > self.expiry_time
    
    def is_opposite_direction(self, new_signal_type: str) -> bool:
        """Check if new signal is opposite direction"""
        opposites = {
            'BUY': 'SELL',
            'SELL': 'BUY',
            'NEUTRAL': None
        }
        return opposites.get(self.signal_type) == new_signal_type

class EnhancedSignalCache:
    """
    Enhanced signal caching system with time-based expiration and opposite direction logic
    """
    
    def __init__(self, cache_duration_hours: float = 1.0, db_path: str = "signal_cache.db"):
        self.cache_duration_hours = cache_duration_hours
        self.cache_duration_seconds = cache_duration_hours * 3600
        
        # Statistics
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'opposite_direction_overrides': 0,
            'expired_signals_removed': 0,
            'total_signals_cached': 0
        }
        
        print(f"🗄️  Enhanced Signal Cache initialized (Redis-backed)")
        print(f"   Cache duration: {cache_duration_hours} hours")
    
    def _generate_cache_key(self, pair: str, timeframe: str, features_hash: str) -> str:
        """Generate unique cache key for signal"""
        key_string = f"{pair}_{timeframe}_{features_hash}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _generate_features_hash(self, features: Dict[str, Any]) -> str:
        """Generate hash from features for cache key"""
        # Sort features for consistent hashing
        sorted_features = json.dumps(features, sort_keys=True, default=str)
        return hashlib.md5(sorted_features.encode()).hexdigest()
    
    async def cache_signal(self, pair: str, timeframe: str, signal_type: str, 
                    confidence: float, price: float, features: Dict[str, Any],
                    metadata: Optional[Dict[str, Any]] = None) -> str:
        """Cache a trading signal with automatic expiration"""
        from dashboard.redis_cache import set_signal, get_all_signals
        
        features_hash = self._generate_features_hash(features)
        cache_key = self._generate_cache_key(pair, timeframe, features_hash)
        signal_id = f"{pair}_{timeframe}_{int(time.time())}_{cache_key[:8]}"
        
        current_time = time.time()
        expiry_time = current_time + self.cache_duration_seconds
        
        # Check existing signals in Redis
        all_signals = await get_all_signals()
        
        existing_signal_dict = None
        for sid, sdata in all_signals.items():
            if sdata.get('cache_key') == cache_key and sdata.get('expiry_time', 0) > current_time:
                existing_signal_dict = sdata
                break
                
        if existing_signal_dict:
            # Reconstruct CachedSignal to check opposite direction
            existing_signal = CachedSignal(**{k: v for k, v in existing_signal_dict.items() if k != 'cache_key'})
            if existing_signal.is_opposite_direction(signal_type):
                print(f"🔄 Opposite direction detected for {pair} {timeframe}: {existing_signal.signal_type} -> {signal_type}")
                self.stats['opposite_direction_overrides'] += 1
            else:
                if confidence <= existing_signal.confidence:
                    print(f"📊 Existing signal has higher confidence for {pair} {timeframe}")
                    return existing_signal.signal_id
        
        cached_signal = CachedSignal(
            pair=pair,
            timeframe=timeframe,
            signal_type=signal_type,
            confidence=confidence,
            price=price,
            timestamp=current_time,
            features_hash=features_hash,
            signal_id=signal_id,
            metadata=metadata or {},
            expiry_time=expiry_time
        )
        
        # Store in Redis
        payload = asdict(cached_signal)
        payload['cache_key'] = cache_key
        await set_signal(signal_id, payload)
        self.stats['total_signals_cached'] += 1
        
        print(f"💾 Cached {signal_type} signal for {pair} {timeframe} (confidence: {confidence:.3f})")
        return signal_id
    
    async def get_cached_signal(self, pair: str, timeframe: str, 
                         features: Dict[str, Any]) -> Optional[CachedSignal]:
        """Retrieve cached signal if available and not expired"""
        from dashboard.redis_cache import get_all_signals, delete_signal
        
        features_hash = self._generate_features_hash(features)
        cache_key = self._generate_cache_key(pair, timeframe, features_hash)
        
        all_signals = await get_all_signals()
        current_time = time.time()
        
        for sid, sdata in all_signals.items():
            if sdata.get('cache_key') == cache_key:
                if sdata.get('expiry_time', 0) <= current_time:
                    await delete_signal(sid)
                    self.stats['expired_signals_removed'] += 1
                    self.stats['cache_misses'] += 1
                    return None
                
                self.stats['cache_hits'] += 1
                signal = CachedSignal(**{k: v for k, v in sdata.items() if k != 'cache_key'})
                print(f"🎯 Cache hit for {pair} {timeframe}: {signal.signal_type} (confidence: {signal.confidence:.3f})")
                return signal
                
        self.stats['cache_misses'] += 1
        return None
    
    async def invalidate_signal(self, signal_id: str) -> bool:
        """Invalidate a specific cached signal"""
        from dashboard.redis_cache import get_all_signals, delete_signal
        
        all_signals = await get_all_signals()
        if signal_id in all_signals:
            await delete_signal(signal_id)
            print(f"🗑️  Invalidated signal: {signal_id}")
            return True
        return False
    
    async def invalidate_pair_signals(self, pair: str, timeframe: Optional[str] = None) -> int:
        """Invalidate all cached signals for a specific pair/timeframe"""
        from dashboard.redis_cache import get_all_signals, delete_signal
        
        all_signals = await get_all_signals()
        count = 0
        for sid, sdata in all_signals.items():
            if sdata.get('pair') == pair:
                if timeframe is None or sdata.get('timeframe') == timeframe:
                    await delete_signal(sid)
                    count += 1
        
        if count:
            print(f"🗑️  Invalidated {count} signals for {pair}" + (f" {timeframe}" if timeframe else ""))
        return count
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        from dashboard.redis_cache import get_all_signals
        all_signals = await get_all_signals()
        current_time = time.time()
        
        active_signals = sum(1 for s in all_signals.values() if s.get('expiry_time', 0) > current_time)
        
        stats = self.stats.copy()
        stats.update({
            'active_signals': active_signals,
            'total_cached_signals': len(all_signals),
            'cache_hit_rate': (self.stats['cache_hits'] / 
                             max(1, self.stats['cache_hits'] + self.stats['cache_misses'])),
            'cache_duration_hours': self.cache_duration_hours
        })
        return stats
    
    async def get_active_signals(self, pair: Optional[str] = None) -> List[CachedSignal]:
        """Get list of active (non-expired) signals"""
        from dashboard.redis_cache import get_all_signals
        all_signals = await get_all_signals()
        current_time = time.time()
        
        active_signals = []
        for sdata in all_signals.values():
            if sdata.get('expiry_time', 0) > current_time:
                if pair is None or sdata.get('pair') == pair:
                    signal = CachedSignal(**{k: v for k, v in sdata.items() if k != 'cache_key'})
                    active_signals.append(signal)
        
        active_signals.sort(key=lambda s: s.timestamp, reverse=True)
        return active_signals
    
    async def clear_cache(self) -> int:
        """Clear all cached signals"""
        from dashboard.redis_cache import get_all_signals, delete_signal
        all_signals = await get_all_signals()
        for sid in all_signals.keys():
            await delete_signal(sid)
            
        print(f"🗑️  Cleared {len(all_signals)} cached signals")
        return len(all_signals)

# Global cache instance
_signal_cache = None

def get_signal_cache(cache_duration_hours: float = 1.0) -> EnhancedSignalCache:
    """Get or create global signal cache instance"""
    global _signal_cache
    if _signal_cache is None:
        _signal_cache = EnhancedSignalCache(cache_duration_hours)
    return _signal_cache

def cache_trading_signal(pair: str, timeframe: str, signal_type: str, 
                        confidence: float, price: float, features: Dict[str, Any],
                        metadata: Optional[Dict[str, Any]] = None) -> str:
    """Convenience function to cache a trading signal"""
    cache = get_signal_cache()
    return cache.cache_signal(pair, timeframe, signal_type, confidence, price, features, metadata)

def get_cached_trading_signal(pair: str, timeframe: str, 
                             features: Dict[str, Any]) -> Optional[CachedSignal]:
    """Convenience function to get cached trading signal"""
    cache = get_signal_cache()
    return cache.get_cached_signal(pair, timeframe, features)

def invalidate_trading_signal(signal_id: str) -> bool:
    """Convenience function to invalidate a trading signal"""
    cache = get_signal_cache()
    return cache.invalidate_signal(signal_id)

def get_cache_statistics() -> Dict[str, Any]:
    """Convenience function to get cache statistics"""
    cache = get_signal_cache()
    return cache.get_cache_stats()

if __name__ == "__main__":
    # Test the enhanced signal cache
    print("🧪 Testing Enhanced Signal Cache...")
    
    cache = EnhancedSignalCache(cache_duration_hours=0.1)  # 6 minutes for testing
    
    # Test caching signals
    features1 = {'rsi': 70, 'macd': 0.5, 'volume': 1000}
    features2 = {'rsi': 30, 'macd': -0.5, 'volume': 1200}
    
    # Cache a BUY signal
    signal_id1 = cache.cache_signal('BTCUSDT', '1h', 'BUY', 0.85, 50000, features1)
    
    # Try to get the cached signal
    cached = cache.get_cached_signal('BTCUSDT', '1h', features1)
    if cached:
        print(f"✅ Retrieved cached signal: {cached.signal_type} with confidence {cached.confidence}")
    
    # Cache opposite direction signal (should override)
    signal_id2 = cache.cache_signal('BTCUSDT', '1h', 'SELL', 0.90, 49500, features1)
    
    # Get updated signal
    cached = cache.get_cached_signal('BTCUSDT', '1h', features1)
    if cached:
        print(f"✅ Retrieved updated signal: {cached.signal_type} with confidence {cached.confidence}")
    
    # Test with different features (should be cache miss)
    cached = cache.get_cached_signal('BTCUSDT', '1h', features2)
    if cached is None:
        print("✅ Cache miss for different features (expected)")
    
    # Print statistics
    stats = cache.get_cache_stats()
    print(f"📊 Cache Statistics: {stats}")
    
    print("🎯 Enhanced Signal Cache test completed!")
