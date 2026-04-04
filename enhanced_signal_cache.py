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
import sqlite3

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
        self.db_path = Path(db_path)
        
        # In-memory cache for fast access
        self.memory_cache: Dict[str, CachedSignal] = {}
        
        # Thread lock for thread safety
        self.lock = threading.RLock()
        
        # Statistics
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'opposite_direction_overrides': 0,
            'expired_signals_removed': 0,
            'total_signals_cached': 0
        }
        
        # Initialize database
        self._init_database()
        
        # Load existing cache from database
        self._load_cache_from_db()
        
        # Start background cleanup thread
        self._start_cleanup_thread()
        
        print(f"🗄️  Enhanced Signal Cache initialized")
        print(f"   Cache duration: {cache_duration_hours} hours")
        print(f"   Database: {self.db_path}")
        print(f"   Loaded signals: {len(self.memory_cache)}")
    
    def _init_database(self):
        """Initialize SQLite database for persistent cache storage"""
        try:
            self.db_path.parent.mkdir(exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cached_signals (
                        cache_key TEXT PRIMARY KEY,
                        pair TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        price REAL NOT NULL,
                        timestamp REAL NOT NULL,
                        features_hash TEXT NOT NULL,
                        signal_id TEXT NOT NULL,
                        metadata TEXT,
                        expiry_time REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create indexes for performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_pair_timeframe ON cached_signals(pair, timeframe)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_expiry_time ON cached_signals(expiry_time)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_type ON cached_signals(signal_type)')
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error initializing cache database: {e}")
    
    def _load_cache_from_db(self):
        """Load existing cache from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Load non-expired signals
                current_time = time.time()
                cursor.execute('''
                    SELECT cache_key, pair, timeframe, signal_type, confidence, price,
                           timestamp, features_hash, signal_id, metadata, expiry_time
                    FROM cached_signals
                    WHERE expiry_time > ?
                    ORDER BY timestamp DESC
                ''', (current_time,))
                
                rows = cursor.fetchall()
                
                for row in rows:
                    cache_key = row[0]
                    metadata = json.loads(row[9]) if row[9] else {}
                    
                    signal = CachedSignal(
                        pair=row[1],
                        timeframe=row[2],
                        signal_type=row[3],
                        confidence=row[4],
                        price=row[5],
                        timestamp=row[6],
                        features_hash=row[7],
                        signal_id=row[8],
                        metadata=metadata,
                        expiry_time=row[10]
                    )
                    
                    self.memory_cache[cache_key] = signal
                
                # Clean up expired signals from database
                cursor.execute('DELETE FROM cached_signals WHERE expiry_time <= ?', (current_time,))
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error loading cache from database: {e}")
    
    def _save_signal_to_db(self, cache_key: str, signal: CachedSignal):
        """Save signal to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO cached_signals
                    (cache_key, pair, timeframe, signal_type, confidence, price,
                     timestamp, features_hash, signal_id, metadata, expiry_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    cache_key, signal.pair, signal.timeframe, signal.signal_type,
                    signal.confidence, signal.price, signal.timestamp,
                    signal.features_hash, signal.signal_id,
                    json.dumps(signal.metadata), signal.expiry_time
                ))
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error saving signal to database: {e}")
    
    def _generate_cache_key(self, pair: str, timeframe: str, features_hash: str) -> str:
        """Generate unique cache key for signal"""
        key_string = f"{pair}_{timeframe}_{features_hash}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _generate_features_hash(self, features: Dict[str, Any]) -> str:
        """Generate hash from features for cache key"""
        # Sort features for consistent hashing
        sorted_features = json.dumps(features, sort_keys=True, default=str)
        return hashlib.md5(sorted_features.encode()).hexdigest()
    
    def _start_cleanup_thread(self):
        """Start background thread for cache cleanup"""
        def cleanup_expired_signals():
            while True:
                try:
                    time.sleep(300)  # Check every 5 minutes
                    self._cleanup_expired_signals()
                except Exception as e:
                    print(f"❌ Cache cleanup error: {e}")
                    time.sleep(600)  # Wait 10 minutes on error
        
        cleanup_thread = threading.Thread(target=cleanup_expired_signals, daemon=True)
        cleanup_thread.start()
    
    def _cleanup_expired_signals(self):
        """Remove expired signals from cache and database"""
        with self.lock:
            current_time = time.time()
            expired_keys = []
            
            # Find expired signals in memory cache
            for cache_key, signal in self.memory_cache.items():
                if signal.is_expired():
                    expired_keys.append(cache_key)
            
            # Remove expired signals from memory
            for key in expired_keys:
                del self.memory_cache[key]
                self.stats['expired_signals_removed'] += 1
            
            # Clean up database
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM cached_signals WHERE expiry_time <= ?', (current_time,))
                    conn.commit()
            except Exception as e:
                print(f"❌ Error cleaning up database: {e}")
            
            if expired_keys:
                print(f"🧹 Cleaned up {len(expired_keys)} expired signals")
    
    def cache_signal(self, pair: str, timeframe: str, signal_type: str, 
                    confidence: float, price: float, features: Dict[str, Any],
                    metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Cache a trading signal with automatic expiration
        
        Args:
            pair: Trading pair (e.g., 'BTCUSDT')
            timeframe: Timeframe (e.g., '1h', '4h')
            signal_type: Signal type ('BUY', 'SELL', 'NEUTRAL')
            confidence: Signal confidence (0.0 to 1.0)
            price: Current price when signal was generated
            features: Features used to generate the signal
            metadata: Additional metadata
            
        Returns:
            signal_id: Unique identifier for the cached signal
        """
        with self.lock:
            # Generate hashes and keys
            features_hash = self._generate_features_hash(features)
            cache_key = self._generate_cache_key(pair, timeframe, features_hash)
            signal_id = f"{pair}_{timeframe}_{int(time.time())}_{cache_key[:8]}"
            
            current_time = time.time()
            expiry_time = current_time + self.cache_duration_seconds
            
            # Check for existing signal with opposite direction
            existing_signal = self.memory_cache.get(cache_key)
            if existing_signal and not existing_signal.is_expired():
                if existing_signal.is_opposite_direction(signal_type):
                    print(f"🔄 Opposite direction detected for {pair} {timeframe}: {existing_signal.signal_type} -> {signal_type}")
                    self.stats['opposite_direction_overrides'] += 1
                    # Override with new signal (opposite direction logic)
                else:
                    # Same direction, update if confidence is higher
                    if confidence <= existing_signal.confidence:
                        print(f"📊 Existing signal has higher confidence for {pair} {timeframe}")
                        return existing_signal.signal_id
            
            # Create new cached signal
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
            
            # Store in memory cache
            self.memory_cache[cache_key] = cached_signal
            
            # Save to database
            self._save_signal_to_db(cache_key, cached_signal)
            
            self.stats['total_signals_cached'] += 1
            
            print(f"💾 Cached {signal_type} signal for {pair} {timeframe} (confidence: {confidence:.3f})")
            
            return signal_id
    
    def get_cached_signal(self, pair: str, timeframe: str, 
                         features: Dict[str, Any]) -> Optional[CachedSignal]:
        """
        Retrieve cached signal if available and not expired
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            features: Current features to match against cache
            
        Returns:
            CachedSignal if found and valid, None otherwise
        """
        with self.lock:
            features_hash = self._generate_features_hash(features)
            cache_key = self._generate_cache_key(pair, timeframe, features_hash)
            
            cached_signal = self.memory_cache.get(cache_key)
            
            if cached_signal is None:
                self.stats['cache_misses'] += 1
                return None
            
            if cached_signal.is_expired():
                # Remove expired signal
                del self.memory_cache[cache_key]
                self.stats['expired_signals_removed'] += 1
                self.stats['cache_misses'] += 1
                return None
            
            self.stats['cache_hits'] += 1
            print(f"🎯 Cache hit for {pair} {timeframe}: {cached_signal.signal_type} (confidence: {cached_signal.confidence:.3f})")
            
            return cached_signal
    
    def invalidate_signal(self, signal_id: str) -> bool:
        """
        Invalidate a specific cached signal
        
        Args:
            signal_id: Signal ID to invalidate
            
        Returns:
            True if signal was found and invalidated, False otherwise
        """
        with self.lock:
            # Find signal by ID
            cache_key_to_remove = None
            for cache_key, signal in self.memory_cache.items():
                if signal.signal_id == signal_id:
                    cache_key_to_remove = cache_key
                    break
            
            if cache_key_to_remove:
                del self.memory_cache[cache_key_to_remove]
                
                # Remove from database
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM cached_signals WHERE signal_id = ?', (signal_id,))
                        conn.commit()
                except Exception as e:
                    print(f"❌ Error removing signal from database: {e}")
                
                print(f"🗑️  Invalidated signal: {signal_id}")
                return True
            
            return False
    
    def invalidate_pair_signals(self, pair: str, timeframe: Optional[str] = None) -> int:
        """
        Invalidate all cached signals for a specific pair/timeframe
        
        Args:
            pair: Trading pair to invalidate
            timeframe: Optional specific timeframe, if None invalidates all timeframes
            
        Returns:
            Number of signals invalidated
        """
        with self.lock:
            keys_to_remove = []
            
            for cache_key, signal in self.memory_cache.items():
                if signal.pair == pair:
                    if timeframe is None or signal.timeframe == timeframe:
                        keys_to_remove.append(cache_key)
            
            # Remove from memory cache
            for key in keys_to_remove:
                del self.memory_cache[key]
            
            # Remove from database
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    if timeframe:
                        cursor.execute('DELETE FROM cached_signals WHERE pair = ? AND timeframe = ?', 
                                     (pair, timeframe))
                    else:
                        cursor.execute('DELETE FROM cached_signals WHERE pair = ?', (pair,))
                    conn.commit()
            except Exception as e:
                print(f"❌ Error removing signals from database: {e}")
            
            if keys_to_remove:
                print(f"🗑️  Invalidated {len(keys_to_remove)} signals for {pair}" + 
                      (f" {timeframe}" if timeframe else ""))
            
            return len(keys_to_remove)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            current_time = time.time()
            active_signals = sum(1 for signal in self.memory_cache.values() if not signal.is_expired())
            
            stats = self.stats.copy()
            stats.update({
                'active_signals': active_signals,
                'total_cached_signals': len(self.memory_cache),
                'cache_hit_rate': (self.stats['cache_hits'] / 
                                 max(1, self.stats['cache_hits'] + self.stats['cache_misses'])),
                'cache_duration_hours': self.cache_duration_hours
            })
            
            return stats
    
    def get_active_signals(self, pair: Optional[str] = None) -> List[CachedSignal]:
        """
        Get list of active (non-expired) signals
        
        Args:
            pair: Optional pair filter
            
        Returns:
            List of active cached signals
        """
        with self.lock:
            active_signals = []
            
            for signal in self.memory_cache.values():
                if not signal.is_expired():
                    if pair is None or signal.pair == pair:
                        active_signals.append(signal)
            
            # Sort by timestamp (newest first)
            active_signals.sort(key=lambda s: s.timestamp, reverse=True)
            
            return active_signals
    
    def clear_cache(self) -> int:
        """
        Clear all cached signals
        
        Returns:
            Number of signals cleared
        """
        with self.lock:
            count = len(self.memory_cache)
            self.memory_cache.clear()
            
            # Clear database
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM cached_signals')
                    conn.commit()
            except Exception as e:
                print(f"❌ Error clearing database: {e}")
            
            print(f"🗑️  Cleared {count} cached signals")
            return count

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
