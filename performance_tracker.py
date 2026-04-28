import json
import time
import os
from datetime import datetime, timezone
from utils_logger import log_message
from constants import *
from shared_state import *
from data_fetcher import *

PERFORMANCE_FILE = SIGNAL_PERFORMANCE_FILE # Alias for consistency
LAST_SIGNAL_CHECK = 0  # Local tracker for monitor_active_trades() interval

def load_open_signals_tracker():
    """Load open signals tracker from file.
    
    IMPORTANT: We use .clear() + .update() to mutate the dict in-place
    so that every module that imported OPEN_SIGNALS_TRACKER sees the data.
    Reassigning with `= json.load(f)` would create a new dict object,
    leaving other modules still pointing at the old empty dict.
    """
    try:
        if os.path.exists(OPEN_SIGNALS_FILE):
            with open(OPEN_SIGNALS_FILE, 'r') as f:
                data = json.load(f)
            OPEN_SIGNALS_TRACKER.clear()
            OPEN_SIGNALS_TRACKER.update(data)
            log_message(f"Loaded {len(OPEN_SIGNALS_TRACKER)} open signals")
    except Exception as e:
        log_message(f"Error loading open signals tracker: {e}")

def save_open_signals_tracker():
    """Save open signals tracker to file"""
    try:
        with open(OPEN_SIGNALS_FILE, 'w') as f:
            json.dump(OPEN_SIGNALS_TRACKER, f, indent=2)
        log_message(f"Saved {len(OPEN_SIGNALS_TRACKER)} open signals")
    except Exception as e:
        log_message(f"Error saving open signals tracker: {e}")

def load_active_trades_monitor():
    """Load active trades monitor from file (in-place mutation)"""
    try:
        if os.path.exists(TRADE_MONITOR_FILE):
            with open(TRADE_MONITOR_FILE, 'r') as f:
                data = json.load(f)
            ACTIVE_TRADES_MONITOR.clear()
            ACTIVE_TRADES_MONITOR.update(data)
            log_message(f"Loaded {len(ACTIVE_TRADES_MONITOR)} active trades")
    except Exception as e:
        log_message(f"Error loading active trades monitor: {e}")

def save_active_trades_monitor():
    """Save active trades monitor to file"""
    try:
        with open(TRADE_MONITOR_FILE, 'w') as f:
            json.dump(ACTIVE_TRADES_MONITOR, f, indent=2)
        log_message(f"Saved {len(ACTIVE_TRADES_MONITOR)} active trades")
    except Exception as e:
        log_message(f"Error saving active trades monitor: {e}")

def load_learning_insights():
    """Load learning insights from file (in-place mutation)"""
    try:
        if os.path.exists(LEARNING_INSIGHTS_FILE):
            with open(LEARNING_INSIGHTS_FILE, 'r') as f:
                data = json.load(f)
            LEARNING_INSIGHTS.clear()
            LEARNING_INSIGHTS.update(data)
            log_message(f"Loaded {len(LEARNING_INSIGHTS)} learning insights")
    except Exception as e:
        log_message(f"Error loading learning insights: {e}")

def save_learning_insights():
    """Save learning insights to file"""
    try:
        with open(LEARNING_INSIGHTS_FILE, 'w') as f:
            json.dump(LEARNING_INSIGHTS, f, indent=2)
        log_message(f"Saved {len(LEARNING_INSIGHTS)} learning insights")
    except Exception as e:
        log_message(f"Error saving learning insights: {e}")

def check_signal_limit():
    """Check if we can send a new signal without exceeding the limit"""
    try:
        current_time = time.time()
        
        # Clean up expired signals first
        cleanup_expired_open_signals()
        
        # Count currently open signals
        open_count = len(OPEN_SIGNALS_TRACKER)
        
        if open_count >= MAX_OPEN_SIGNALS:
            log_message(f"Signal limit reached: {open_count}/{MAX_OPEN_SIGNALS} open signals")
            return False, f"Signal limit reached ({open_count}/{MAX_OPEN_SIGNALS})"
        
        log_message(f"Signal limit check passed: {open_count}/{MAX_OPEN_SIGNALS} open signals")
        return True, f"Within limit ({open_count}/{MAX_OPEN_SIGNALS})"
        
    except Exception as e:
        log_message(f"Error checking signal limit: {e}")
        return True, "Limit check failed - allowing signal"

def add_open_signal(signal_id, pair, signal_type, entry_price, timestamp=None,
                    stop_loss=None, targets=None, leverage=1, exchange='binance'):
    """Add a signal to the open signals tracker"""
    try:
        if timestamp is None:
            timestamp = time.time()

        signal_entry = {
            'signal_id':   signal_id,
            'pair':        pair,
            'signal_type': signal_type,
            'entry_price': entry_price,
            'stop_loss':   stop_loss,
            'targets':     targets or [],
            'leverage':    leverage,
            'timestamp':   timestamp,
            'status':      'OPEN',
            'last_updated': timestamp,
            'exchange':    exchange,
        }
        
        OPEN_SIGNALS_TRACKER[signal_id] = signal_entry
        save_open_signals_tracker()
        
        log_message(f"Added open signal {signal_id} for {pair}: {signal_type} at {entry_price}")
        return True
        
    except Exception as e:
        log_message(f"Error adding open signal: {e}")
        return False

def close_open_signal(signal_id, close_reason="MANUAL", pnl=None):
    """Close an open signal with full feedback loop integration"""
    try:
        if signal_id in OPEN_SIGNALS_TRACKER:
            signal_entry = OPEN_SIGNALS_TRACKER[signal_id]
            signal_entry['status'] = 'CLOSED'
            signal_entry['close_reason'] = close_reason
            signal_entry['close_timestamp'] = time.time()
            signal_entry['last_updated'] = time.time()
            
            if pnl is not None:
                signal_entry['pnl'] = pnl
                # Update Circuit Breaker
                try:
                    CIRCUIT_BREAKER.update_pnl(pnl)
                except Exception as cb_err:
                    log_message(f"Error updating circuit breaker: {cb_err}")
                # Update Auto-Blacklist win/loss tracking
                try:
                    pair = signal_entry.get('pair', '')
                    is_win = pnl > 0
                    AUTO_BLACKLIST.record_outcome(pair, is_win)
                    # Phase 7: RL-inspired Performance Feedback
                    try:
                        REGIME_SIZER.record_outcome(is_win)
                        log_message(f"🧠 RL Feedback: Position multiplier now x{REGIME_SIZER.multiplier:.2f} (win={is_win})")
                    except Exception as sizer_err:
                        log_message(f"Error updating regime sizer: {sizer_err}")
                        
                    if not is_win:
                        log_message(f"📉 Loss recorded for {pair} (consecutive: {AUTO_BLACKLIST.consecutive_losses.get(pair, 0)})")
                except Exception as bl_err:
                    log_message(f"Error updating auto-blacklist: {bl_err}")
            
            # Post-Mortem Trigger: Wire self-healing loop for SL events
            if close_reason in ('SL_HIT', 'BLACK_SWAN_EMERGENCY'):
                try:
                    from ai_auto_healer import AUTO_HEAL_ENGINE
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(AUTO_HEAL_ENGINE.perform_post_mortem(signal_id))
                    except RuntimeError:
                        asyncio.run(AUTO_HEAL_ENGINE.perform_post_mortem(signal_id))
                    log_message(f"🔬 Post-Mortem triggered for {signal_id} ({close_reason})")
                except Exception as pm_err:
                    log_message(f"Post-mortem trigger error: {pm_err}")
            
            # Persist close_reason to signal_registry.db
            try:
                from shared_state import SIGNAL_REGISTRY
                update_payload = {
                    'status': 'CLOSED',
                    'close_reason': close_reason,
                    'closed_timestamp': time.time()
                }
                if pnl is not None:
                    update_payload['pnl'] = pnl
                SIGNAL_REGISTRY.update_signal(signal_id, update_payload)
            except Exception as reg_err:
                log_message(f"Warning: Could not update signal_registry for {signal_id}: {reg_err}")
            
            # Move to closed signals and remove from open
            del OPEN_SIGNALS_TRACKER[signal_id]
            save_open_signals_tracker()
            
            log_message(f"Closed signal {signal_id}: {close_reason}")
            return True
        else:
            log_message(f"Signal {signal_id} not found in open signals")
            return False
            
    except Exception as e:
        log_message(f"Error closing signal {signal_id}: {e}")
        return False

def cleanup_expired_open_signals():
    """Remove expired open signals (older than 7 days)"""
    try:
        current_time = time.time()
        expired_signals = []
        
        # Find signals older than 7 days
        for signal_id, signal_entry in OPEN_SIGNALS_TRACKER.items():
            age = current_time - signal_entry['timestamp']
            if age > (7 * 24 * 3600):  # 7 days
                expired_signals.append(signal_id)
        
        # Remove expired signals
        for signal_id in expired_signals:
            sig = OPEN_SIGNALS_TRACKER.get(signal_id, {})
            estimated_pnl = _estimate_pnl(sig)
            close_open_signal(signal_id, "EXPIRED", pnl=estimated_pnl)
            log_message(f"Expired signal {signal_id} removed from open signals")
        
        if expired_signals:
            log_message(f"Cleaned up {len(expired_signals)} expired open signals")
        
        return len(expired_signals)
        
    except Exception as e:
        log_message(f"Error cleaning up expired signals: {e}")
        return 0

def get_open_signals_report():
    """Generate a report of currently open signals"""
    try:
        current_time = time.time()
        cleanup_expired_open_signals()
        
        open_count = len(OPEN_SIGNALS_TRACKER)
        
        if open_count == 0:
            return "📊 **Open Signals Report**\n🔹 No open signals currently"
        
        report = [
            f"📊 **Open Signals Report**",
            f"🔹 Total Open: {open_count}/{MAX_OPEN_SIGNALS}",
            f"🔹 Available Slots: {MAX_OPEN_SIGNALS - open_count}"
        ]
        
        # Group by signal type
        signal_types = {}
        pairs_count = {}
        
        for signal_entry in OPEN_SIGNALS_TRACKER.values():
            signal_type = signal_entry['signal_type']
            pair = signal_entry['pair']
            
            signal_types[signal_type] = signal_types.get(signal_type, 0) + 1
            pairs_count[pair] = pairs_count.get(pair, 0) + 1
        
        if signal_types:
            report.append("\n🔹 By Signal Type:")
            for signal_type, count in signal_types.items():
                report.append(f"   • {signal_type}: {count}")
        
        # Show top pairs
        if pairs_count:
            top_pairs = sorted(pairs_count.items(), key=lambda x: x[1], reverse=True)[:5]
            report.append("\n🔹 Top Pairs:")
            for pair, count in top_pairs:
                report.append(f"   • {pair}: {count}")
        
        # Age analysis
        ages = []
        for signal_entry in OPEN_SIGNALS_TRACKER.values():
            age_hours = (current_time - signal_entry['timestamp']) / 3600
            ages.append(age_hours)
        
        if ages:
            avg_age = sum(ages) / len(ages)
            oldest_age = max(ages)
            report.extend([
                f"\n🔹 Average Age: {avg_age:.1f} hours",
                f"🔹 Oldest Signal: {oldest_age:.1f} hours"
            ])
        
        return "\n".join(report)
        
    except Exception as e:
        log_message(f"Error generating open signals report: {e}")
        return "Error generating open signals report"

def monitor_active_trades():
    """Monitor active trades for performance tracking"""
    try:
        global LAST_SIGNAL_CHECK
        current_time = time.time()
        
        # Only check every minute
        if current_time - LAST_SIGNAL_CHECK < SIGNAL_CHECK_INTERVAL:
            return
        
        LAST_SIGNAL_CHECK = current_time
        
        # Update active trades monitor
        for signal_id, signal_entry in OPEN_SIGNALS_TRACKER.items():
            if signal_id not in ACTIVE_TRADES_MONITOR:
                # Add new trade to monitor
                ACTIVE_TRADES_MONITOR[signal_id] = {
                    'signal_id': signal_id,
                    'pair': signal_entry['pair'],
                    'signal_type': signal_entry['signal_type'],
                    'entry_price': signal_entry['entry_price'],
                    'entry_timestamp': signal_entry['timestamp'],
                    'last_price_check': current_time,
                    'price_history': [],
                    'max_profit': 0.0,
                    'max_loss': 0.0,
                    'current_pnl': 0.0
                }
        
        # Clean up closed trades from monitor
        closed_trades = []
        for signal_id in ACTIVE_TRADES_MONITOR.keys():
            if signal_id not in OPEN_SIGNALS_TRACKER:
                closed_trades.append(signal_id)
        
        for signal_id in closed_trades:
            del ACTIVE_TRADES_MONITOR[signal_id]
        
        save_active_trades_monitor()
        
        log_message(f"Active trades monitor updated: {len(ACTIVE_TRADES_MONITOR)} trades being monitored")
        
    except Exception as e:
        log_message(f"Error monitoring active trades: {e}")

def update_trade_performance(signal_id, current_price):
    """Update performance metrics for an active trade"""
    try:
        if signal_id not in ACTIVE_TRADES_MONITOR:
            return
        
        trade_data = ACTIVE_TRADES_MONITOR[signal_id]
        entry_price = trade_data['entry_price']
        signal_type = trade_data['signal_type']
        
        # Calculate current PnL
        if signal_type.upper() in ['LONG', 'BUY']:
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:  # SHORT
            pnl_pct = (entry_price - current_price) / entry_price * 100
        
        # Update metrics
        trade_data['current_pnl'] = pnl_pct
        trade_data['last_price_check'] = time.time()
        trade_data['max_profit'] = max(trade_data['max_profit'], pnl_pct)
        trade_data['max_loss'] = min(trade_data['max_loss'], pnl_pct)
        
        # Add to price history (keep last 100 entries)
        trade_data['price_history'].append({
            'timestamp': time.time(),
            'price': current_price,
            'pnl_pct': pnl_pct
        })
        
        if len(trade_data['price_history']) > 100:
            trade_data['price_history'] = trade_data['price_history'][-100:]
        
        save_active_trades_monitor()
        
    except Exception as e:
        log_message(f"Error updating trade performance for {signal_id}: {e}")

def generate_learning_insight(insight_type, data):
    """Generate and store learning insights"""
    try:
        insight_id = f"{insight_type}_{int(time.time())}"
        
        insight_entry = {
            'insight_id': insight_id,
            'type': insight_type,
            'timestamp': time.time(),
            'data': data,
            'applied': False
        }
        
        LEARNING_INSIGHTS[insight_id] = insight_entry
        save_learning_insights()
        
        log_message(f"Generated learning insight: {insight_type}")
        return insight_id
        
    except Exception as e:
        log_message(f"Error generating learning insight: {e}")
        return None

def track_signal_performance(pair, old_entry, current_price):
    """Track performance of previous signals for self-learning with enhanced criteria"""
    try:
        if not old_entry or old_entry.get('performance_tracked', False):
            return
        
        entry_price = old_entry.get('price')
        entry_signal = old_entry.get('signal')
        entry_time = old_entry.get('timestamp')
        entry_confidence = old_entry.get('confidence', 0.5)
        
        if not entry_price or not entry_signal or not entry_time:
            return
        
        # Calculate performance metrics
        price_change_pct = (current_price - entry_price) / entry_price * 100
        time_held = time.time() - entry_time
        
        # Enhanced success criteria with multiple levels
        success = False
        success_level = 'failure'
        
        if entry_signal.upper() in ['LONG', 'BUY']:
            if price_change_pct >= 3.0:
                success = True
                success_level = 'excellent'  # 3%+ gain
            elif price_change_pct >= 1.5:
                success = True
                success_level = 'good'  # 1.5%+ gain
            elif price_change_pct >= 0.5:
                success = True
                success_level = 'partial'  # 0.5%+ gain
            elif price_change_pct >= -0.5:
                success_level = 'breakeven'  # Small loss/gain
            else:
                success_level = 'failure'  # Significant loss
                
        elif entry_signal.upper() in ['SHORT', 'SELL']:
            if price_change_pct <= -3.0:
                success = True
                success_level = 'excellent'  # 3%+ drop
            elif price_change_pct <= -1.5:
                success = True
                success_level = 'good'  # 1.5%+ drop
            elif price_change_pct <= -0.5:
                success = True
                success_level = 'partial'  # 0.5%+ drop
            elif price_change_pct <= 0.5:
                success_level = 'breakeven'  # Small loss/gain
            else:
                success_level = 'failure'  # Significant loss
        
        # Time-based performance adjustment
        hours_held = time_held / 3600
        if hours_held < 0.5:  # Less than 30 minutes
            time_factor = 'too_quick'
        elif hours_held < 2:  # Less than 2 hours
            time_factor = 'quick'
        elif hours_held < 12:  # Less than 12 hours
            time_factor = 'normal'
        elif hours_held < 48:  # Less than 48 hours
            time_factor = 'extended'
        else:
            time_factor = 'very_long'
        
        # Store enhanced performance data
        _signal_id = old_entry.get('signal_id', '')
        performance_entry = {
            'signal_id':       _signal_id,
            'pair':            pair,
            'signal':          entry_signal,
            'entry_price':     entry_price,
            'stop_loss':       old_entry.get('stop_loss'),
            'targets':         old_entry.get('targets', []),
            'leverage':        old_entry.get('leverage', 1),
            'exit_price':      current_price,
            'price_change_pct': price_change_pct,
            'time_held':       time_held,
            'hours_held':      hours_held,
            'success':         success,
            'success_level':   success_level,
            'time_factor':     time_factor,
            'confidence':      entry_confidence,
            'timestamp':       entry_time,
            'exit_timestamp':  time.time(),
            'source':          'PRICE_RECONCILE',
            'market_conditions': get_market_conditions_at_time(pair, entry_time)
        }

        # Add to performance history — deduplicate by signal_id
        if pair not in PERFORMANCE_HISTORY:
            PERFORMANCE_HISTORY[pair] = []
        if _signal_id and any(e.get('signal_id') == _signal_id for e in PERFORMANCE_HISTORY[pair]):
            PERFORMANCE_HISTORY[pair] = [
                performance_entry if e.get('signal_id') == _signal_id else e
                for e in PERFORMANCE_HISTORY[pair]
            ]
        else:
            PERFORMANCE_HISTORY[pair].append(performance_entry)
        
        # Keep only last 200 entries per pair (increased from 100)
        if len(PERFORMANCE_HISTORY[pair]) > 200:
            PERFORMANCE_HISTORY[pair] = PERFORMANCE_HISTORY[pair][-200:]
        
        # Mark as tracked
        old_entry['performance_tracked'] = True
        
        log_message(f"Enhanced performance tracked for {pair}: {entry_signal} -> {price_change_pct:.2f}% ({success_level}, {time_factor}, {hours_held:.1f}h)")
        
        # Save performance data
        save_performance_data()
        
        # Update ML models with enhanced performance feedback
        if MULTI_TF_ML_AVAILABLE:
            try:
                # Use success level for more nuanced learning
                outcome_value = success_level if success_level != 'failure' else False
                update_prediction_outcome(pair, entry_signal, outcome_value, '1h')  # Default timeframe
            except Exception as e:
                log_message(f"Error updating ML with performance data: {e}")
        
    except Exception as e:
        log_message(f"Error tracking signal performance for {pair}: {e}")

def save_performance_data():
    """Save performance history to file"""
    try:
        with open(PERFORMANCE_FILE, 'w') as f:
            json.dump(PERFORMANCE_HISTORY, f, indent=2)
        log_message(f"Saved performance data for {len(PERFORMANCE_HISTORY)} pairs")
    except Exception as e:
        log_message(f"Error saving performance data: {e}")

def load_performance_data():
    """Load performance history from file.

    IMPORTANT: We use .clear() + .update() to mutate the dict in-place
    so that every module that imported PERFORMANCE_HISTORY sees the data.
    Reassigning with `= json.load(f)` would create a new dict object,
    leaving other modules still pointing at the old empty dict.
    """
    try:
        if os.path.exists(PERFORMANCE_FILE):
            with open(PERFORMANCE_FILE, 'r') as f:
                data = json.load(f)
            PERFORMANCE_HISTORY.clear()
            PERFORMANCE_HISTORY.update(data)
            log_message(f"Loaded performance data for {len(PERFORMANCE_HISTORY)} pairs")
    except Exception as e:
        log_message(f"Error loading performance data: {e}")

def get_signal_success_rate(pair=None, signal_type=None, days=30):
    """Get success rate for signals with self-learning insights"""
    try:
        cutoff_time = time.time() - (days * 24 * 3600)
        total_signals = 0
        successful_signals = 0
        
        pairs_to_check = [pair] if pair else PERFORMANCE_HISTORY.keys()
        
        for p in pairs_to_check:
            if p not in PERFORMANCE_HISTORY:
                continue
                
            for entry in PERFORMANCE_HISTORY[p]:
                if entry['timestamp'] < cutoff_time:
                    continue
                    
                if signal_type and entry['signal'].upper() != signal_type.upper():
                    continue
                    
                total_signals += 1
                if entry['success']:
                    successful_signals += 1
        
        success_rate = (successful_signals / total_signals * 100) if total_signals > 0 else 0
        
        return {
            'success_rate': success_rate,
            'total_signals': total_signals,
            'successful_signals': successful_signals,
            'failed_signals': total_signals - successful_signals
        }
        
    except Exception as e:
        log_message(f"Error calculating success rate: {e}")
        return {'success_rate': 0, 'total_signals': 0, 'successful_signals': 0, 'failed_signals': 0}

def get_performance_insights():
    """Generate performance insights for self-learning optimization"""
    try:
        insights = []
        
        # Overall performance
        overall_stats = get_signal_success_rate()
        insights.append(f"📊 **Overall Performance (30 days)**:")
        insights.append(f"   • Success Rate: {overall_stats['success_rate']:.1f}%")
        insights.append(f"   • Total Signals: {overall_stats['total_signals']}")
        insights.append(f"   • Successful: {overall_stats['successful_signals']}")
        insights.append(f"   • Failed: {overall_stats['failed_signals']}")
        
        # Performance by signal type
        long_stats = get_signal_success_rate(signal_type='LONG')
        short_stats = get_signal_success_rate(signal_type='SHORT')
        
        insights.append(f"\n📈 **Long Signals**: {long_stats['success_rate']:.1f}% ({long_stats['total_signals']} total)")
        insights.append(f"📉 **Short Signals**: {short_stats['success_rate']:.1f}% ({short_stats['total_signals']} total)")
        
        # Best performing pairs
        pair_performance = {}
        for pair, entries in PERFORMANCE_HISTORY.items():
            recent_entries = [e for e in entries if e['timestamp'] > time.time() - (30 * 24 * 3600)]
            if len(recent_entries) >= 3:  # At least 3 signals
                success_rate = sum(1 for e in recent_entries if e['success']) / len(recent_entries) * 100
                pair_performance[pair] = {
                    'success_rate': success_rate,
                    'total': len(recent_entries)
                }
        
        if pair_performance:
            best_pairs = sorted(pair_performance.items(), key=lambda x: x[1]['success_rate'], reverse=True)[:5]
            insights.append(f"\n🏆 **Top Performing Pairs**:")
            for pair, stats in best_pairs:
                insights.append(f"   • {pair}: {stats['success_rate']:.1f}% ({stats['total']} signals)")
        
        # Learning recommendations
        insights.append(f"\n🧠 **Self-Learning Insights**:")
        if overall_stats['success_rate'] > 60:
            insights.append("   • ✅ System performing well - continue current strategy")
        elif overall_stats['success_rate'] > 40:
            insights.append("   • ⚠️ Moderate performance - consider parameter tuning")
        else:
            insights.append("   • 🔴 Low performance - strategy review needed")
        
        if long_stats['success_rate'] > short_stats['success_rate'] + 10:
            insights.append("   • 📈 Long signals outperforming - bias toward bullish markets")
        elif short_stats['success_rate'] > long_stats['success_rate'] + 10:
            insights.append("   • 📉 Short signals outperforming - bias toward bearish markets")
        
        return "\n".join(insights)
        
    except Exception as e:
        log_message(f"Error generating performance insights: {e}")
        return "Performance insights unavailable"

def get_market_conditions_at_time(pair, entry_time):
    """Get market conditions at the time of signal entry for enhanced learning context"""
    try:
        # Fetch recent data for market condition analysis
        df = fetch_data(pair, '1h', retries=2)
        
        if df.empty:
            return {'volatility': 'unknown', 'trend': 'unknown', 'volume': 'unknown'}
        
        # Calculate market conditions
        conditions = {}
        
        # Volatility analysis using ATR
        if len(df) > 14:
            # Calculate ATR if not present
            if 'ATR' not in df.columns:
                df = calculate_atr(df)
            
            if 'ATR' in df.columns:
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
        else:
            conditions['volatility'] = 'unknown'
        
        # Trend analysis using SMA
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
        log_message(f"Error getting market conditions for {pair}: {e}")
        return {'volatility': 'unknown', 'trend': 'unknown', 'volume': 'unknown'}

def adaptive_confidence_adjustment(pair, signal, base_confidence):
    """Adjust signal confidence based on historical performance (self-learning)"""
    try:
        if pair not in PERFORMANCE_HISTORY:
            return base_confidence
        
        # Get recent performance for this pair and signal type
        recent_entries = [
            e for e in PERFORMANCE_HISTORY[pair] 
            if e['timestamp'] > time.time() - (7 * 24 * 3600) and  # Last 7 days
               e['signal'].upper() == signal.upper()
        ]
        
        if len(recent_entries) < 3:  # Need at least 3 recent signals
            return base_confidence
        
        # Calculate recent success rate
        success_rate = sum(1 for e in recent_entries if e['success']) / len(recent_entries)
        
        # Adjust confidence based on performance
        if success_rate > 0.7:  # 70%+ success rate
            adjusted_confidence = min(base_confidence * 1.2, 1.0)  # Boost by 20%
            log_message(f"Confidence boosted for {pair} {signal}: {base_confidence:.2f} -> {adjusted_confidence:.2f} (success rate: {success_rate:.1%})")
        elif success_rate < 0.3:  # Less than 30% success rate
            adjusted_confidence = max(base_confidence * 0.8, 0.1)  # Reduce by 20%
            log_message(f"Confidence reduced for {pair} {signal}: {base_confidence:.2f} -> {adjusted_confidence:.2f} (success rate: {success_rate:.1%})")
        else:
            adjusted_confidence = base_confidence
        
        return adjusted_confidence
        
    except Exception as e:
        log_message(f"Error adjusting confidence for {pair}: {e}")
        return base_confidence


async def emergency_de_risk(severity="HIGH"):
    """
    Emergency de-risking logic for Black Swan events.
    Now estimates PnL before closing so the system 'remembers' the crisis.
    """
    try:
        from telegram_handler import send_telegram_message
        
        open_count = len(OPEN_SIGNALS_TRACKER)
        if open_count == 0:
            return
            
        log_message(f"🚨 EMERGENCY DE-RISKING TRIGGERED (Severity: {severity})")
        
        def _estimate_pnl(sig):
            """Estimate current PnL from entry price"""
            try:
                entry = sig.get('entry_price', 0)
                pair = sig.get('pair', '')
                direction = sig.get('signal_type', 'LONG').upper()
                if entry <= 0 or not pair: return -5.0  # Assume worst case
                
                current_data = client.futures_mark_price(symbol=pair)
                current_price = float(current_data['markPrice'])
                
                if direction in ('LONG', 'BUY'):
                    return ((current_price - entry) / entry) * 100
                else:
                    return ((entry - current_price) / entry) * 100
            except Exception:
                return -5.0  # Assume -5% if we can't check
        
        # 1. Critical Panic: Close all positions immediately
        if severity == "CRITICAL":
            # DISABLED: Emergency broadcast
            # await send_telegram_message("☢️ **SYSTEMIC BLACK SWAN DETECTED** ☢️\nEmergency protocol: Closing ALL positions.")
            log_message("☢️ SYSTEMIC BLACK SWAN DETECTED - Emergency protocol: Closing ALL positions.")
            
            signal_ids = list(OPEN_SIGNALS_TRACKER.keys())
            for sid in signal_ids:
                sig = OPEN_SIGNALS_TRACKER.get(sid, {})
                estimated_pnl = _estimate_pnl(sig)
                close_open_signal(sid, "BLACK_SWAN_EMERGENCY", pnl=estimated_pnl)
            return
            
        # 2. High Risk: Close non-performing or low-confidence positions
        if severity == "HIGH":
            # DISABLED: Emergency broadcast
            # await send_telegram_message("⚠️ **HIGH SYSTEMIC RISK** ⚠️\nReducing exposure: Closing low-confidence positions.")
            log_message("⚠️ HIGH SYSTEMIC RISK - Reducing exposure: Closing low-confidence positions.")
            
            signal_ids = list(OPEN_SIGNALS_TRACKER.keys())
            closed_count = 0
            for sid in signal_ids:
                sig = OPEN_SIGNALS_TRACKER.get(sid, {})
                if sig.get('confidence', 1.0) < 0.6:
                    estimated_pnl = _estimate_pnl(sig)
                    close_open_signal(sid, "RISK_REDUCTION", pnl=estimated_pnl)
                    closed_count += 1
            
            # DISABLED: Emergency de-risk broadcast messages
            # if closed_count > 0:
            #     await send_telegram_message(f"✅ Closed {closed_count} high-risk positions.")
            # else:
            #     await send_telegram_message("ℹ️ No low-confidence positions found to close.")
            log_message(f"Emergency de-risk: Closed {closed_count} high-risk positions.")
        # Also signal global risk state (was previously only in the old main.py stub)
        try:
            from macro_risk_engine import MacroRiskEngine
            macro = MacroRiskEngine()
            macro.state['market_regime'] = 'SYSTEMIC_PANIC'
            macro.save_state()
        except Exception:
            pass
                
    except Exception as e:
        log_message(f"Error during emergency de-risk: {e}")

def generate_daily_summary(daily_signal_count, circuit_breaker, auto_blacklist, macro_risk=None,
                            performance_path=SIGNAL_REGISTRY_FILE):
    """Generate a daily performance summary for Telegram"""
    try:
        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime('%Y-%m-%d')
        
        # Determine the start of today in pure seconds since epoch for timestamp comparison
        start_of_today_timestamp = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        total_wins = total_losses = 0
        total_pnl = 0.0
        pair_performance = {}
        
        try:
            if os.path.exists(performance_path):
                with open(performance_path, 'r') as f:
                    signals = json.load(f)
                for sig_id, sig in signals.items():
                    # Only process signals generated today
                    sig_time = sig.get('timestamp', 0)
                    if sig_time < start_of_today_timestamp:
                        continue
                        
                    pair = sig.get('pair', 'UNKNOWN')
                    # Parse PnL from the current schema 
                    pnl = sig.get('pnl_percentage', sig.get('pnl', 0.0))
                    status = sig.get('status', '').upper()
                    
                    
                    if status not in ('CLOSED', 'TP_HIT', 'SL_HIT', 'SUCCESS', 'FAILED'):
                        continue # Skip active or unknown signals
                        
                    if pair not in pair_performance:
                        pair_performance[pair] = {'wins': 0, 'losses': 0, 'pnl': 0}
                        
                    # Determine Win/Loss strictly based on PnL value or Status
                    if pnl > 0 or status in ('TP_HIT', 'SUCCESS'):
                        total_wins += 1
                        pair_performance[pair]['wins'] += 1
                    else:
                        total_losses += 1
                        pair_performance[pair]['losses'] += 1
                        
                    total_pnl += pnl
                    pair_performance[pair]['pnl'] += pnl
        except Exception as e:
            log_message(f"Error reading performance data for summary: {e}")
            pass
        
        total_trades = total_wins + total_losses
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        best_pair = max(pair_performance.items(), key=lambda x: x[1]['pnl'], default=('N/A', {'pnl': 0}))
        worst_pair = min(pair_performance.items(), key=lambda x: x[1]['pnl'], default=('N/A', {'pnl': 0}))
        
        # Get blacklisted pairs
        blacklisted = []
        if auto_blacklist:
            import time as time_module
            blacklisted = [p for p, until in auto_blacklist.blacklisted_until.items() if time_module.time() < until]
            
        cb_state = circuit_breaker.state if circuit_breaker else {}
        
        summary = (
            f"📊 **DAILY PERFORMANCE SUMMARY** ({today_str})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 Signals Today: {daily_signal_count}\n"
            f"📈 Total Trades: {total_trades}\n"
            f"✅ Wins: {total_wins} | ❌ Losses: {total_losses}\n"
            f"🎯 Win Rate: {win_rate:.1f}%\n"
            f"💰 Total PnL: {total_pnl:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Best: {best_pair[0]} ({best_pair[1]['pnl']:+.2f}%)\n"
            f"💀 Worst: {worst_pair[0]} ({worst_pair[1]['pnl']:+.2f}%)\n"
            f"🚫 Blacklisted: {', '.join(blacklisted) if blacklisted else 'None'}\n"
            f"🔋 Circuit Breaker: PnL {cb_state.get('daily_pnl', 0):.2f}% | "
            f"Streak: {cb_state.get('consecutive_losses', 0)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        if macro_risk:
            summary += f"\n{macro_risk.get_summary_report()}"
            
        return summary
    except Exception as e:
        return f"📊 Daily Summary Error: {str(e)[:100]}"

# MAX_DAILY_SIGNALS is defined in constants.py — do not redefine here

def check_daily_signal_limit():
    """Check if we've reached the daily signal limit. Resets at midnight UTC.

    IMPORTANT: We mutate the dict in-place (not reassign) so that every
    module that imported DAILY_SIGNAL_COUNTER from shared_state sees the
    updated values.  Reassignment would create a new dict object, leaving
    main.py reading a stale copy.
    """
    today = datetime.now(timezone.utc).date()
    if DAILY_SIGNAL_COUNTER['date'] != today:
        log_message(f"📅 Daily signal counter reset. Yesterday: {DAILY_SIGNAL_COUNTER['count']} signals")
        DAILY_SIGNAL_COUNTER['count'] = 0
        DAILY_SIGNAL_COUNTER['date'] = today
    
    remaining = MAX_DAILY_SIGNALS - DAILY_SIGNAL_COUNTER['count']
    if remaining <= 0:
        return False, 0
    return True, remaining

def increment_daily_signal_count():
    """Increment the daily signal counter (in-place mutation)."""
    today = datetime.now(timezone.utc).date()
    if DAILY_SIGNAL_COUNTER['date'] != today:
        DAILY_SIGNAL_COUNTER['count'] = 0
        DAILY_SIGNAL_COUNTER['date'] = today
    DAILY_SIGNAL_COUNTER['count'] += 1
    return DAILY_SIGNAL_COUNTER['count']

def can_send_direction(pair, requested_direction, same_direction_window_hours=24):
    """
    Ensure the bot doesn't spam the same direction for a pair.
    Requires a direction flip OR that the last same-direction signal is older than
    same_direction_window_hours (default 24h). This prevents permanent lock-out in
    trending/bear markets where a pair keeps generating signals in the same direction.
    """
    from shared_state import SIGNAL_REGISTRY
    import time as _time

    last_time = 0
    last_direction = None

    for sid, sdata in SIGNAL_REGISTRY.items():
        if sdata.get('pair') == pair and sdata.get('status') in ['SENT', 'CLOSED']:
            t = sdata.get('timestamp', 0)
            if t > last_time:
                last_time = t
                last_direction = sdata.get('signal')

    if not last_direction:
        return True  # First time trading this pair

    last_norm = 'LONG' if last_direction.upper() in ['LONG', 'BUY'] else 'SHORT'
    req_norm = 'LONG' if requested_direction.upper() in ['LONG', 'BUY'] else 'SHORT'

    if last_norm == req_norm:
        elapsed_hours = (_time.time() - last_time) / 3600
        if elapsed_hours < same_direction_window_hours:
            log_message(f"🚫 Signal Rejected for {pair}: Sequential {req_norm} signal within {same_direction_window_hours}h window ({elapsed_hours:.1f}h since last).")
            return False
        # Enough time has passed — allow re-entry in same direction
        log_message(f"✅ Direction re-entry allowed for {pair}: {req_norm} (last {req_norm} was {elapsed_hours:.1f}h ago)")

    return True


def check_direction_balance(requested_direction, window_hours=6, max_ratio=0.60):
    """
    S3: Prevent directional clustering — reject a signal if sending it would
    push the same-direction ratio above max_ratio in the last window_hours.

    E.g. if 8/10 signals in the past 6h are SHORT and we try to send another
    SHORT, this returns False (the 9th SHORT would be 90% > 60% cap).
    """
    from shared_state import SIGNAL_REGISTRY
    import time as _time

    cutoff = _time.time() - window_hours * 3600
    req_norm = 'LONG' if requested_direction.upper() in ('LONG', 'BUY') else 'SHORT'

    recent = [
        'LONG' if s.get('signal', '').upper() in ('LONG', 'BUY') else 'SHORT'
        for s in SIGNAL_REGISTRY.values()
        if s.get('timestamp', 0) >= cutoff
    ]

    if len(recent) < 3:          # Not enough history — allow freely
        return True

    same = recent.count(req_norm)
    total_after = len(recent) + 1
    ratio_after = (same + 1) / total_after

    if ratio_after > max_ratio:
        opposite = 'SHORT' if req_norm == 'LONG' else 'LONG'
        log_message(
            f"🚫 Direction Balance Cap: {req_norm} would be {ratio_after:.0%} of last-{window_hours}h signals "
            f"({same + 1}/{total_after}) — max allowed {max_ratio:.0%}. "
            f"Waiting for more {opposite} setups."
        )
        return False
    return True


def _reconcile_sent_signals(max_age_hours=72):
    """
    Auto-close SENT signals whose SL or max-TP has been hit at ANY point since
    the signal was opened. Uses kline HIGH/LOW (not just current ticker) to
    catch peaks/troughs that occurred between the real-time monitor's ticks.

    Resolution order per signal:
      1. Fetch 1m klines from signal.timestamp → now
      2. For LONG: check if any HIGH ≥ TP, any LOW ≤ SL
         For SHORT: check if any LOW ≤ TP, any HIGH ≥ SL
      3. Reconstruct chronological order (SL before TP vs TP before SL)
         to determine actual outcome
      4. Only close at the FINAL TP (not partials) so trailing logic can upgrade
    """
    import json as _json
    import time as _t
    import sqlite3 as _sql
    from data_fetcher import client as _client

    con = _sql.connect('signal_registry.db')
    con.row_factory = _sql.Row
    cur = con.cursor()
    # Ensure trailing-SL columns exist so the SELECT below can reference them.
    # The actual trail-SL persist + fan-out is handled async in main.py via
    # trailing_engine.run_trailing_cycle() (so announcements can fire).
    try:
        from trailing_engine import ensure_schema as _trail_ensure
        _trail_ensure()
    except Exception as _te:
        log_message(f"[trailing] schema-ensure skipped: {_te}")

    cur.execute(
        "SELECT signal_id, pair, signal, price, targets_json, stop_loss, leverage, "
        "timestamp, targets_hit, "
        "COALESCE(trail_sl, 0) AS trail_sl, "
        "COALESCE(exchange, 'binance') AS exchange "
        "FROM signals WHERE status IN ('SENT','OPEN') ORDER BY timestamp DESC"
    )
    rows = cur.fetchall()

    now = _t.time()
    age_cutoff = now - max_age_hours * 3600
    updates          = []       # (pnl, targets_hit, closed_ts, close_reason, sid, pair, sig) for close
    partial_updates  = []       # (targets_hit, sid) for partial TP only
    void_updates     = []       # (closed_ts, sid) for instant-fake-win voids
    sl_count = tp_count = age_count = void_count = 0

    # Threshold: ALL TPs hit within this many seconds of signal creation
    # AND price moved more than this % from entry → likely stale entry geometry
    INSTANT_VOID_MAX_AGE  = 900   # 15 minutes
    INSTANT_VOID_MIN_MOVE = 5.0   # 5% move required to reach max TP

    for r in rows:
        sid = r['signal_id']
        entry   = float(r['price'] or 0)
        sl      = float(r['stop_loss'] or 0)
        try:
            lev_early = int(r['leverage'] or 1)
        except (ValueError, TypeError):
            lev_early = 1
        is_long_early = r['signal'].upper() in ('LONG', 'BUY')

        if r['timestamp'] < age_cutoff:
            # Fix: record actual PnL at current price instead of 0.0
            # Also: recalculate targets_hit from price if DB still has 0
            _aged_targets = _json.loads(r['targets_json']) if r['targets_json'] else []
            try:
                from live_price_feed import LIVE_FEED as _LF
                _px_now = (_LF.get(r['pair']) or {}).get('mark', 0)
                if _px_now and _px_now > 0 and entry > 0:
                    _raw = (((_px_now - entry) / entry) if is_long_early else ((entry - _px_now) / entry)) * 100
                    aged_pnl = round(_raw * lev_early, 2)
                else:
                    _px_now = 0
                    aged_pnl = 0.0
            except Exception:
                _px_now = 0
                aged_pnl = 0.0
            # Recalculate targets_hit: if DB has 0 but price moved past TPs, fix it
            _existing_th = int(r['targets_hit'] or 0) if str(r['targets_hit']).lstrip('-').isdigit() else 0
            if _existing_th == 0 and _px_now > 0 and _aged_targets:
                _calc_th = 0
                for _ti, _tp in enumerate(_aged_targets):
                    if (is_long_early and _px_now >= _tp) or (not is_long_early and _px_now <= _tp):
                        _calc_th = _ti + 1
                    else:
                        break
                # Also infer from PnL: if leveraged PnL exceeds what TP1 would give,
                # at least TP1 must have been hit at some point
                if _calc_th == 0 and aged_pnl > 0 and _aged_targets:
                    _tp1_raw = abs(_aged_targets[0] - entry) / entry * 100 if entry > 0 else 999
                    _tp1_lev = _tp1_raw * lev_early
                    if aged_pnl >= _tp1_lev * 0.95:  # within 5% tolerance
                        _calc_th = 1
                        for _ti in range(1, len(_aged_targets)):
                            _tpn_raw = abs(_aged_targets[_ti] - entry) / entry * 100 if entry > 0 else 999
                            _tpn_lev = _tpn_raw * lev_early
                            if aged_pnl >= _tpn_lev * 0.95:
                                _calc_th = _ti + 1
                            else:
                                break
                _existing_th = _calc_th
            # Derive close_reason from targets_hit and PnL for aged signals
            if _existing_th > 0:
                _aged_reason = f'TP{_existing_th}_HIT'
            elif aged_pnl <= -0.01:
                _aged_reason = 'SL_HIT'
            else:
                _aged_reason = 'EXPIRED'
            updates.append((aged_pnl, _existing_th, now, _aged_reason, sid, r['pair'], r['signal']))
            age_count += 1
            continue
        targets = _json.loads(r['targets_json']) if r['targets_json'] else []
        if not entry or not sl or not targets:
            continue
        try:
            lev = int(r['leverage'] or 1)
        except (ValueError, TypeError):
            lev = 1
        is_long  = r['signal'].upper() in ('LONG', 'BUY')

        # ── Dynamic Trailing SL: if TP1 already hit, use best of ─────────
        # (original_sl, entry, trail_sl).  The trailing_engine writes
        # `trail_sl` every 5-min reconcile tick using Chandelier Exit on 1h.
        # Falls back to breakeven (entry) if trailing engine is disabled.
        _targets_hit_so_far = int(r['targets_hit'] or 0) if str(r['targets_hit']).lstrip('-').isdigit() else 0
        try:
            _trail = float(r['trail_sl'] or 0)
        except Exception:
            _trail = 0.0
        if _targets_hit_so_far >= 1:
            if is_long:
                sl = max(sl, entry, _trail) if _trail > 0 else max(sl, entry)
            else:
                sl = min(sl, entry, _trail) if _trail > 0 else min(sl, entry)

        # ── Fetch 1m klines from signal timestamp → now ───────────────────
        start_ms = int(r['timestamp'] * 1000)
        end_ms   = int(now * 1000)
        _sig_exchange = r['exchange'] if 'exchange' in r.keys() else 'binance'
        try:
            if _sig_exchange == 'mexc':
                # MEXC kline fetch — returns {time:[], open:[], high:[], low:[], close:[], vol:[]}
                import requests as _mreq
                from mexc_data_fetcher import _to_mexc
                _mexc_sym = _to_mexc(r['pair'])
                _mr = _mreq.get(
                    f'https://api.mexc.com/api/v1/contract/kline/{_mexc_sym}',
                    params={'interval': 'Min1', 'start': int(start_ms / 1000), 'end': int(end_ms / 1000)},
                    timeout=15
                )
                _mr.raise_for_status()
                _mkd = _mr.json().get('data', {})
                # Convert to Binance kline format: [[open_time, o, h, l, c, v, ...], ...]
                _times = _mkd.get('time', [])
                _opens = _mkd.get('open', [])
                _highs = _mkd.get('high', [])
                _lows = _mkd.get('low', [])
                _closes = _mkd.get('close', [])
                _vols = _mkd.get('vol', [])
                klines = []
                for _ki in range(min(len(_times), len(_opens), len(_highs), len(_lows), len(_closes))):
                    klines.append([int(_times[_ki]) * 1000, _opens[_ki], _highs[_ki], _lows[_ki], _closes[_ki], _vols[_ki] if _ki < len(_vols) else 0])
            else:
                klines = _client.futures_klines(
                    symbol=r['pair'], interval='1m',
                    startTime=start_ms, endTime=end_ms, limit=1500
                )
        except Exception as e:
            _err_str = str(e)
            if 'restricted location' in _err_str.lower():
                try:
                    import requests as _req
                    _r = _req.get(
                        'https://fapi.binance.com/fapi/v1/klines',
                        params={'symbol': r['pair'], 'interval': '1m',
                                'startTime': start_ms, 'endTime': end_ms, 'limit': 1500},
                        proxies={}, timeout=15
                    )
                    _r.raise_for_status()
                    klines = _r.json()
                except Exception as _e2:
                    log_message(f"Reconcile: kline direct-IP fallback also failed for {r['pair']}: {_e2}")
                    continue
            else:
                log_message(f"Reconcile: kline fetch failed for {r['pair']}: {e}")
                continue
        if not klines:
            continue

        # ── Walk klines chronologically to find first hit ────────────────
        # Each kline: [open_time, o, h, l, c, v, close_time, ...]
        # Track highest TP pierced BEFORE the close event — if SL fires after
        # TP1+TP2 hit, we want targets_hit=2 not 0 in the closed row.
        reason = None       # 'SL_HIT' or 'TP{N}_HIT'
        tp_hit = 0          # final close target index (if TP exit) — for tier increment / status
        partial_tp_hit = 0  # highest TP pierced at any point pre-close (for targets_hit field)
        hit_price = None
        hit_ts = None
        for k in klines:
            hi = float(k[2])
            lo = float(k[3])
            # Update partial_tp_hit BEFORE checking SL/max-TP so that any TPs
            # pierced inside this same bar (or earlier bars) are recorded.
            for i, tp in enumerate(targets):
                tn = i + 1
                if tn <= partial_tp_hit:
                    continue
                reached = (is_long and hi >= tp) or (not is_long and lo <= tp)
                if reached:
                    partial_tp_hit = tn

            # SL check first — whichever was hit FIRST wins
            sl_hit = (is_long and lo <= sl) or (not is_long and hi >= sl)
            # Max-TP hit check
            max_tp = targets[-1]
            max_tp_hit = (is_long and hi >= max_tp) or (not is_long and lo <= max_tp)

            if sl_hit and max_tp_hit:
                # Both hit in same bar — conservative: assume SL first
                reason = 'SL_HIT'
                hit_price = sl
                hit_ts = int(k[0]) / 1000
                break
            elif sl_hit:
                reason = 'SL_HIT'
                hit_price = sl
                hit_ts = int(k[0]) / 1000
                break
            elif max_tp_hit:
                tp_hit = len(targets)
                reason = f'TP{tp_hit}_HIT'
                hit_price = max_tp
                hit_ts = int(k[0]) / 1000
                break

        # If neither SL nor max-TP fired during the whole window, the signal
        # is still open but may have hit some intermediate TPs — record those
        # as partials (no close).
        if reason is None:
            tp_hit = partial_tp_hit

        # ── Persist result ────────────────────────────────────────────────
        if reason == 'SL_HIT':
            raw_pct = ((sl - entry) / entry * 100) if is_long else ((entry - sl) / entry * 100)
            pnl = round(raw_pct * lev, 2)
            # Preserve highest TP pierced before SL (e.g. trailing-SL after TP2 → targets_hit=2)
            updates.append((pnl, partial_tp_hit, hit_ts or now, 'SL_HIT', sid, r['pair'], r['signal']))
            sl_count += 1
        elif reason and reason.startswith('TP') and tp_hit == len(targets):
            # Final TP hit — check for instant fake-win before counting it.
            # Pattern: ALL TPs hit within 15 min AND price gapped >5% from entry
            # → the entry price was stale (e.g. stock token off-hours freeze).
            # Void the signal so it doesn't pollute win-rate statistics.
            tp_price   = targets[tp_hit - 1]
            signal_age = (hit_ts or now) - r['timestamp']
            price_move = abs(tp_price - entry) / entry * 100 if entry > 0 else 0
            if signal_age < INSTANT_VOID_MAX_AGE and price_move > INSTANT_VOID_MIN_MOVE:
                log_message(
                    f"🚫 VOID [{r['pair']}]: ALL TPs hit {signal_age:.0f}s after open "
                    f"with {price_move:.1f}% move from entry — stale entry geometry, not counted"
                )
                void_updates.append((hit_ts or now, sid, r['pair']))
                void_count += 1
                continue
            raw_pct  = ((tp_price - entry) / entry * 100) if is_long else ((entry - tp_price) / entry * 100)
            pnl = round(raw_pct * lev, 2)
            updates.append((pnl, tp_hit, hit_ts or now, f'TP{tp_hit}_HIT', sid, r['pair'], r['signal']))
            tp_count += 1
        elif tp_hit > 0:
            # Partial TP only — update progress, don't close
            current_th = int(r['targets_hit'] or 0) if str(r['targets_hit']).isdigit() else 0
            if tp_hit > current_th:
                partial_updates.append((tp_hit, sid))

    if void_updates:
        cur.executemany(
            "UPDATE signals SET status='VOIDED', pnl=0.0, targets_hit=0, closed_timestamp=? WHERE signal_id=?",
            [(ts, sid) for ts, sid, _pair in void_updates],
        )
        con.commit()
        log_message(f"🚫 Voided {void_count} instant-fake-win signals (stale entry geometry)")

    if updates:
        cur.executemany(
            "UPDATE signals SET status='CLOSED', pnl=?, targets_hit=?, closed_timestamp=?, close_reason=? WHERE signal_id=?",
            [(pnl, th, ts, cr, sid) for pnl, th, ts, cr, sid, _pair, _sig in updates],
        )
        con.commit()
        log_message(
            f"📊 Signal reconciliation: closed {len(updates)} "
            f"(SL={sl_count}, TP={tp_count}, aged={age_count})"
        )

        # ── Wire feedback loops ──────────────────────────────────────────
        # AUTO_BLACKLIST is ALWAYS updated — even after a restart when the
        # signal is no longer in OPEN_SIGNALS_TRACKER.  close_open_signal()
        # is only called when the signal is still in-memory (for CB + RL).
        for pnl_val, _th, _close_ts, _cr, sid, pair, sig_dir in updates:
            is_win = pnl_val > 0
            # ── Meta-Labeler outcome logging ────────
            try:
                from ml_engine_archive.meta_labeler import get_meta_labeler
                meta = get_meta_labeler()
                outcome = 'TP' if is_win else 'SL'
                if pnl_val == 0.0: outcome = 'EXPIRED'
                meta.log_outcome(pair, sig_dir, outcome)
            except Exception as ml_err:
                log_message(f"Meta-labeler log_outcome error for {pair}: {ml_err}")

            # ── Always update blacklist regardless of memory state ────────
            try:
                AUTO_BLACKLIST.record_outcome(pair, is_win)
                if not is_win:
                    log_message(f"📉 Loss recorded for {pair} via reconciler "
                                f"(consecutive: {AUTO_BLACKLIST.consecutive_losses.get(pair, 0)})")
                # Large-loss guard: any leveraged loss > 30% → immediate 48h blacklist
                if pnl_val <= -30.0:
                    import time as _tmod
                    AUTO_BLACKLIST.blacklisted_until[pair] = _tmod.time() + 48 * 3600
                    AUTO_BLACKLIST.save_state()
                    log_message(f"🚨 Large-loss blacklist: {pair} blocked 48h (pnl={pnl_val:.1f}%)")
            except Exception as _bl_err:
                log_message(f"Reconcile blacklist error for {pair}: {_bl_err}")
            # ── in-memory feedback (CB + RL) only when still tracked ─────
            if sid in OPEN_SIGNALS_TRACKER:
                _close_reason = 'SL_HIT' if pnl_val <= -0.01 else ('TP_HIT' if pnl_val >= 0.01 else 'EXPIRED')
                try:
                    close_open_signal(sid, _close_reason, pnl=pnl_val)
                except Exception as _fb_err:
                    log_message(f"Reconcile feedback error for {sid}: {_fb_err}")

    # ── Partial TP progress (signal stays open, progress persists) ─────────
    if partial_updates:
        cur.executemany(
            "UPDATE signals SET targets_hit=? WHERE signal_id=?",
            partial_updates,
        )
        con.commit()
        log_message(f"📈 Signal reconciliation: {len(partial_updates)} partial TP updates")

    con.close()

