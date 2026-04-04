import json
import time
import os
from datetime import datetime
from utils_logger import log_message
from constants import *
from shared_state import *
from data_fetcher import *
from performance_tracker import (
    load_open_signals_tracker, load_active_trades_monitor, 
    load_learning_insights, track_signal_performance
)

CACHE_FILE = SIGNAL_CACHE_FILE # Alias for consistency
CACHE_DURATION = SIGNAL_CACHE_TTL # Alias for consistency
CLEANUP_INTERVAL = 1800 # 30 minutes
LAST_CACHE_CLEANUP = 0

def initialize_cache_system():
    """Initialize the enhanced signal caching system with signal limit management"""
    try:
        load_cache_from_file()
        load_open_signals_tracker()
        load_active_trades_monitor()
        load_learning_insights()
        log_message("Enhanced signal cache system with limit management initialized")
        return True
    except Exception as e:
        log_message(f"Cache system initialization error: {e}")
        return False

def get_cache_entry_details(pair):
    """Get detailed information about a cached entry"""
    if pair not in SIGNAL_CACHE:
        return None
    
    entry = SIGNAL_CACHE[pair]
    current_time = time.time()
    age = current_time - entry['timestamp']
    remaining = CACHE_DURATION - age
    
    return {
        'pair': pair,
        'signal': entry['signal'],
        'price': entry.get('price'),
        'confidence': entry.get('confidence'),
        'age_seconds': age,
        'remaining_seconds': remaining,
        'expired': age > CACHE_DURATION,
        'entry_id': entry.get('entry_id'),
        'normalized_signal': entry.get('normalized_signal')
    }

def force_cache_entry(pair, signal, price=None, confidence=None, override_existing=True):
    """Force a cache entry regardless of existing entries (for testing/manual override)"""
    if not override_existing and is_signal_cached(pair):
        log_message(f"Cache entry already exists for {pair} and override_existing=False")
        return False
    
    cache_signal(pair, signal, price, confidence, {'forced': True, 'override': override_existing})
    log_message(f"Forced cache entry for {pair}: {signal}")
    return True

def remove_cache_entry(pair):
    """Remove a specific cache entry"""
    if pair in SIGNAL_CACHE:
        removed_entry = SIGNAL_CACHE.pop(pair)
        log_message(f"Removed cache entry for {pair}: {removed_entry['signal']}")
        save_cache_to_file()
        return True
    return False

def get_cache_performance_metrics():
    """Get performance metrics for the cache system"""
    current_time = time.time()
    total_entries = len(SIGNAL_CACHE)
    
    if total_entries == 0:
        return {
            'total_entries': 0,
            'hit_rate': 0,
            'average_age': 0,
            'memory_usage_kb': 0
        }
    
    ages = []
    for entry in SIGNAL_CACHE.values():
        age = current_time - entry['timestamp']
        ages.append(age)
    
    # Estimate memory usage (rough calculation)
    import sys
    memory_usage = sys.getsizeof(SIGNAL_CACHE)
    for entry in SIGNAL_CACHE.values():
        memory_usage += sys.getsizeof(entry)
    
    return {
        'total_entries': total_entries,
        'average_age': sum(ages) / len(ages) if ages else 0,
        'oldest_entry': max(ages) if ages else 0,
        'newest_entry': min(ages) if ages else 0,
        'memory_usage_kb': memory_usage / 1024
    }

def validate_cache_integrity():
    """Validate cache integrity and fix any issues"""
    issues_found = 0
    current_time = time.time()
    
    # Check for corrupted entries
    corrupted_pairs = []
    for pair, entry in SIGNAL_CACHE.items():
        try:
            # Validate required fields
            if not isinstance(entry, dict):
                corrupted_pairs.append(pair)
                continue
            
            required_fields = ['signal', 'timestamp', 'normalized_signal']
            for field in required_fields:
                if field not in entry:
                    log_message(f"Missing field {field} in cache entry for {pair}")
                    issues_found += 1
            
            # Validate timestamp
            if 'timestamp' in entry:
                age = current_time - entry['timestamp']
                if age < 0:  # Future timestamp
                    log_message(f"Future timestamp detected for {pair}")
                    issues_found += 1
                elif age > CACHE_DURATION * 2:  # Very old entry
                    log_message(f"Very old entry detected for {pair}: {age}s")
                    issues_found += 1
            
        except Exception as e:
            log_message(f"Error validating cache entry for {pair}: {e}")
            corrupted_pairs.append(pair)
            issues_found += 1
    
    # Remove corrupted entries
    for pair in corrupted_pairs:
        del SIGNAL_CACHE[pair]
        log_message(f"Removed corrupted cache entry for {pair}")
        issues_found += 1
    
    if issues_found > 0:
        save_cache_to_file()
        log_message(f"Cache validation completed: {issues_found} issues found and fixed")
    
    return issues_found

def export_cache_data(filename=None):
    """Export cache data for analysis or backup"""
    if filename is None:
        filename = f"cache_export_{int(time.time())}.json"
    
    try:
        export_data = {
            'export_timestamp': time.time(),
            'cache_duration': CACHE_DURATION,
            'total_entries': len(SIGNAL_CACHE),
            'entries': SIGNAL_CACHE.copy()
        }
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        log_message(f"Cache data exported to {filename}")
        return filename
    except Exception as e:
        log_message(f"Error exporting cache data: {e}")
        return None

# Signal ID tracking and Cornix integration (canonical instances in shared_state.py)
SIGNAL_REGISTRY_FILE = "signal_registry.json"
CORNIX_SIGNALS_FILE = "cornix_signals.json"

def load_cache_from_file():
    """Load cache from persistent storage (optional)"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                current_time = time.time()
                
                # Only load non-expired entries
                for pair, entry in cache_data.items():
                    if current_time - entry['timestamp'] <= CACHE_DURATION:
                        SIGNAL_CACHE[pair] = entry
                        
                log_message(f"Loaded {len(SIGNAL_CACHE)} valid cache entries from file")
    except Exception as e:
        log_message(f"Error loading cache from file: {e}")

def save_cache_to_file():
    """Save cache to persistent storage (optional)"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(SIGNAL_CACHE, f, indent=2)
        log_message(f"Saved {len(SIGNAL_CACHE)} cache entries to file")
    except Exception as e:
        log_message(f"Error saving cache to file: {e}")

def is_signal_cached(pair):
    """Check if a valid cached signal exists for the pair"""
    if pair not in SIGNAL_CACHE:
        return False
    
    cached_entry = SIGNAL_CACHE[pair]
    current_time = time.time()
    
    # Check if cache has expired
    if current_time - cached_entry['timestamp'] > CACHE_DURATION:
        # Remove expired entry
        del SIGNAL_CACHE[pair]
        log_message(f"Cache expired for {pair}, removed from cache")
        return False
    
    return True

def get_cached_signal(pair):
    """Retrieve cached signal information for the pair"""
    if pair in SIGNAL_CACHE:
        cached_entry = SIGNAL_CACHE[pair]
        current_time = time.time()
        
        # Double-check expiration
        if current_time - cached_entry['timestamp'] <= CACHE_DURATION:
            return cached_entry
        else:
            # Remove expired entry
            del SIGNAL_CACHE[pair]
            log_message(f"Removed expired cache entry for {pair}")
            return None
    return None

def normalize_signal(signal):
    """Normalize signal names for consistent comparison - ONLY LONG/SHORT output"""
    if not signal:
        return "NEUTRAL"
    
    signal_upper = str(signal).upper().strip()
    
    # Normalize to standard format - ONLY LONG/SHORT
    if signal_upper in ['LONG', 'BUY', 'BULLISH']:
        return "LONG"
    elif signal_upper in ['SHORT', 'SELL', 'BEARISH']:
        return "SHORT"
    else:
        return "NEUTRAL"

def are_signals_opposite(signal1, signal2):
    """Check if two signals are opposite directions"""
    norm_signal1 = normalize_signal(signal1)
    norm_signal2 = normalize_signal(signal2)
    
    opposite_pairs = [
        ("LONG", "SHORT"),
        ("SHORT", "LONG")
    ]
    
    return (norm_signal1, norm_signal2) in opposite_pairs

def should_send_signal(pair, new_signal, new_price=None, new_confidence=None):
    """
    Enhanced logic to determine if a new signal should be sent based on cache
    Returns: (should_send: bool, reason: str)
    """
    # Automatic cleanup check
    auto_cleanup_cache()
    
    if not is_signal_cached(pair):
        return True, "No cached signal"
    
    cached_signal = get_cached_signal(pair)
    if not cached_signal:
        return True, "Cache entry invalid"
    
    cached_signal_type = cached_signal['signal']
    current_time = time.time()
    cache_age = current_time - cached_signal['timestamp']
    remaining_time = CACHE_DURATION - cache_age
    
    # Normalize signals for comparison
    norm_cached = normalize_signal(cached_signal_type)
    norm_new = normalize_signal(new_signal)
    
    # Check if new signal is opposite direction
    if are_signals_opposite(cached_signal_type, new_signal):
        log_message(f"Opposite signal detected for {pair}: {cached_signal_type} -> {new_signal} (cache age: {cache_age:.0f}s)")
        
        # Additional validation for opposite signals
        if cache_age < 300:  # Less than 5 minutes - might be noise
            log_message(f"Opposite signal too soon for {pair} (only {cache_age:.0f}s), requiring confirmation")
            
            # Check price movement significance
            if new_price and cached_signal.get('price'):
                price_change_pct = abs(new_price - cached_signal['price']) / cached_signal['price'] * 100
                if price_change_pct < 1.0:  # Less than 1% price change
                    log_message(f"Insufficient price movement for opposite signal {pair}: {price_change_pct:.2f}%")
                    return False, f"Opposite signal with insufficient price movement ({price_change_pct:.2f}%)"
        
        return True, f"Opposite direction signal ({cached_signal_type} -> {new_signal})"
    
    # Same direction signal - check various conditions
    if norm_cached == norm_new:
        # Check if it's been long enough for a repeat signal
        if cache_age > CACHE_DURATION * 0.75:  # 75% of cache duration
            return True, f"Same direction signal near expiration ({remaining_time:.0f}s remaining)"
        
        # Check for significant price movement
        if new_price and cached_signal.get('price'):
            price_change_pct = abs(new_price - cached_signal['price']) / cached_signal['price'] * 100
            if price_change_pct > 5.0:  # More than 5% price change
                return True, f"Same direction signal with significant price movement ({price_change_pct:.2f}%)"
        
        # Check for confidence improvement
        if new_confidence and cached_signal.get('confidence'):
            confidence_improvement = new_confidence - cached_signal['confidence']
            if confidence_improvement > 0.2:  # 20% confidence improvement
                return True, f"Same direction signal with improved confidence (+{confidence_improvement:.1%})"
        
        log_message(f"Same direction signal blocked for {pair}: {new_signal} (cached: {cached_signal_type}, remaining: {remaining_time:.0f}s)")
        return False, f"Same direction signal cached (remaining: {remaining_time:.0f}s)"
    
    # Different signal types (neither same nor opposite)
    return True, f"Different signal type ({cached_signal_type} -> {new_signal})"

def cache_signal(pair, signal, price=None, confidence=None, additional_data=None):
    """Store a new signal in the cache with enhanced metadata and self-learning"""
    current_time = time.time()
    
    # Check if we're updating an existing signal for performance tracking
    if pair in SIGNAL_CACHE:
        old_entry = SIGNAL_CACHE[pair]
        # Track signal performance for self-learning
        track_signal_performance(pair, old_entry, price)
    
    # Prepare cache entry
    cache_entry = {
        'signal': signal,
        'timestamp': current_time,
        'price': price,
        'confidence': confidence,
        'normalized_signal': normalize_signal(signal),
        'performance_tracked': False,
        'entry_id': f"{pair}_{current_time}"
    }
    
    # Add additional data if provided
    if additional_data:
        cache_entry.update(additional_data)
    
    # Store in cache
    SIGNAL_CACHE[pair] = cache_entry
    
    log_message(f"Cached signal for {pair}: {signal} at {price} (confidence: {confidence})")
    
    # Optional: Save to file for persistence
    try:
        save_cache_to_file()
    except Exception as e:
        log_message(f"Warning: Could not save cache to file: {e}")

def auto_cleanup_cache():
    """Automatically clean up expired signals if enough time has passed"""
    global LAST_CACHE_CLEANUP
    current_time = time.time()
    
    if current_time - LAST_CACHE_CLEANUP > CLEANUP_INTERVAL:
        cleanup_expired_signals()
        LAST_CACHE_CLEANUP = current_time

def cleanup_expired_signals():
    """Remove expired signals from cache with enhanced logging"""
    current_time = time.time()
    expired_pairs = []
    
    for pair, cached_entry in SIGNAL_CACHE.items():
        if current_time - cached_entry['timestamp'] > CACHE_DURATION:
            expired_pairs.append(pair)
    
    for pair in expired_pairs:
        expired_entry = SIGNAL_CACHE[pair]
        del SIGNAL_CACHE[pair]
        log_message(f"Cleaned up expired cache entry for {pair}: {expired_entry['signal']} (age: {current_time - expired_entry['timestamp']:.0f}s)")
    
    if expired_pairs:
        log_message(f"Cache cleanup: removed {len(expired_pairs)} expired entries")
        # Update persistent storage
        try:
            save_cache_to_file()
        except Exception as e:
            log_message(f"Warning: Could not update cache file after cleanup: {e}")

def get_cache_statistics():
    """Get comprehensive cache statistics for monitoring"""
    current_time = time.time()
    total_cached = len(SIGNAL_CACHE)
    
    if total_cached == 0:
        return {
            "total": 0,
            "active": 0,
            "expired": 0,
            "by_signal": {},
            "average_age": 0,
            "oldest_entry": 0,
            "newest_entry": 0
        }
    
    active_count = 0
    expired_count = 0
    signal_counts = {}
    ages = []
    
    for pair, cached_entry in SIGNAL_CACHE.items():
        age = current_time - cached_entry['timestamp']
        ages.append(age)
        
        if age <= CACHE_DURATION:
            active_count += 1
        else:
            expired_count += 1
        
        # Count by signal type
        signal_type = cached_entry.get('normalized_signal', 'UNKNOWN')
        signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
    
    return {
        "total": total_cached,
        "active": active_count,
        "expired": expired_count,
        "by_signal": signal_counts,
        "average_age": sum(ages) / len(ages) if ages else 0,
        "oldest_entry": max(ages) if ages else 0,
        "newest_entry": min(ages) if ages else 0
    }

def get_cache_status_report():
    """Generate a detailed cache status report"""
    stats = get_cache_statistics()
    current_time = time.time()
    
    report = [
        f"📊 **Signal Cache Status Report**",
        f"🔹 Total entries: {stats['total']}",
        f"🔹 Active entries: {stats['active']}",
        f"🔹 Expired entries: {stats['expired']}",
    ]
    
    if stats['by_signal']:
        report.append("🔹 By signal type:")
        for signal_type, count in stats['by_signal'].items():
            report.append(f"   • {signal_type}: {count}")
    
    if stats['total'] > 0:
        report.extend([
            f"🔹 Average age: {stats['average_age']:.0f}s",
            f"🔹 Oldest entry: {stats['oldest_entry']:.0f}s",
            f"🔹 Newest entry: {stats['newest_entry']:.0f}s"
        ])
    
    return "\n".join(report)

def clear_cache():
    """Clear all cached signals (for maintenance)"""
    global SIGNAL_CACHE
    count = len(SIGNAL_CACHE)
    SIGNAL_CACHE.clear()
    log_message(f"Cleared all {count} cached signals")
    
    # Clear persistent storage
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            log_message("Cleared persistent cache file")
    except Exception as e:
        log_message(f"Error clearing cache file: {e}")

def get_cached_pairs():
    """Get list of all pairs with cached signals"""
    return list(SIGNAL_CACHE.keys())

# Unique Signal ID System and Cornix Integration
