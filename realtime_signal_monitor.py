import asyncio
import json
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import websockets
from binance import AsyncClient
import pandas as pd
from multi_timeframe_ml_system import update_prediction_outcome

class RealTimeSignalMonitor:
    """Enhanced real-time monitoring system for trading signals with robust WebSocket and REST API fallback"""
    
    def __init__(self, telegram_sender, closed_signals_sender, open_signals_tracker, signal_registry):
        self.telegram_sender = telegram_sender
        self.closed_signals_sender = closed_signals_sender
        self.open_signals_tracker = open_signals_tracker
        self.signal_registry = signal_registry
        
        # WebSocket connections
        self.websocket_connections = {}
        self.monitored_pairs = set()
        self.running = False
        self.price_cache = {}
        
        # Monitoring intervals
        self.realtime_interval = 1  # 1 second for real-time checks
        self.websocket_check_interval = 5  # 5 seconds for WebSocket health
        self.rest_api_interval = 10  # 10 seconds for REST API fallback
        self.last_rest_check = 0
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Binance client for REST API
        self.binance_client = None
        
        # Performance tracking
        self.websocket_failures = {}
        self.last_price_updates = {}
        self.monitoring_stats = {
            'signals_checked': 0,
            'targets_hit': 0,
            'stop_losses_hit': 0,
            'websocket_reconnects': 0,
            'rest_api_calls': 0
        }
        
    async def initialize(self, api_key=None, api_secret=None):
        """Initialize the monitoring system"""
        try:
            if api_key and api_secret:
                self.binance_client = await AsyncClient.create(api_key, api_secret)
                self.logger.info("✅ Binance async client initialized for real-time monitoring")
            
            # Test closed signals channel
            try:
                await self.closed_signals_sender("🚀 Real-time Signal Monitor initialized and testing closed signals channel")
                self.logger.info("✅ Closed signals channel test successful")
            except Exception as e:
                self.logger.error(f"❌ Closed signals channel test failed: {e}")
                return False
            
            self.logger.info("🚀 Real-time signal monitor initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize monitor: {e}")
            return False
    
    async def start_monitoring(self):
        """Start the comprehensive real-time monitoring system"""
        self.running = True
        self.logger.info("🚀 Starting comprehensive real-time signal monitoring...")
        
        # Start all monitoring tasks
        asyncio.create_task(self.realtime_monitoring_loop())
        asyncio.create_task(self.websocket_health_manager())
        asyncio.create_task(self.rest_api_fallback_loop())
        asyncio.create_task(self.performance_reporter())
        
        # Send startup notification
        try:
            await self.closed_signals_sender("📡 Real-time Signal Monitor started - monitoring every second for target/stop loss hits")
            await self.telegram_sender("📡 Real-time Signal Monitor started successfully")
        except Exception as e:
            self.logger.error(f"Failed to send startup notification: {e}")
        
        self.logger.info("📡 Real-time monitoring system fully operational")
    
    async def stop_monitoring(self):
        """Stop the monitoring system"""
        self.running = False
        self.logger.info("🛑 Stopping real-time monitoring...")
        
        # Close all WebSocket connections
        for pair, ws in self.websocket_connections.items():
            try:
                await ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket for {pair}: {e}")
        
        if self.binance_client:
            await self.binance_client.close_connection()
        
        self.websocket_connections.clear()
        self.monitored_pairs.clear()
        
        # Send shutdown notification
        try:
            await self.closed_signals_sender("🛑 Real-time Signal Monitor stopped")
        except:
            pass
        
        self.logger.info("🛑 Real-time monitoring stopped")
    
    async def add_pair_monitoring(self, pair: str, signal_data: Dict):
        """Add a pair to real-time monitoring"""
        try:
            if pair not in self.monitored_pairs:
                self.monitored_pairs.add(pair)
                self.websocket_failures[pair] = 0
                self.last_price_updates[pair] = 0
                
                # Start WebSocket for this pair
                asyncio.create_task(self.start_pair_websocket(pair))
                
                self.logger.info(f"📡 Added {pair} to real-time monitoring")
                
                # Send notification
                try:
                    await self.closed_signals_sender(f"📡 Now monitoring {pair} in real-time for signal closures")
                except:
                    pass
                
        except Exception as e:
            self.logger.error(f"Error adding {pair} to monitoring: {e}")
    
    async def remove_pair_monitoring(self, pair: str):
        """Remove a pair from monitoring"""
        try:
            if pair in self.monitored_pairs:
                self.monitored_pairs.remove(pair)
                
                # Close WebSocket
                if pair in self.websocket_connections:
                    try:
                        await self.websocket_connections[pair].close()
                        del self.websocket_connections[pair]
                    except Exception as e:
                        self.logger.error(f"Error closing WebSocket for {pair}: {e}")
                
                # Clean up tracking data
                if pair in self.price_cache:
                    del self.price_cache[pair]
                if pair in self.websocket_failures:
                    del self.websocket_failures[pair]
                if pair in self.last_price_updates:
                    del self.last_price_updates[pair]
                
                self.logger.info(f"📡 Removed {pair} from monitoring")
                
        except Exception as e:
            self.logger.error(f"Error removing {pair} from monitoring: {e}")
    
    async def start_pair_websocket(self, pair: str):
        """Start WebSocket connection for a specific pair with robust error handling"""
        stream_name = f"{pair.lower()}@ticker"
        uri = f"wss://fstream.binance.com/ws/{stream_name}"
        
        while self.running and pair in self.monitored_pairs:
            try:
                self.logger.info(f"🔌 Connecting WebSocket for {pair}...")
                
                # Enhanced connection with proper timeout
                websocket = await asyncio.wait_for(
                    websockets.connect(
                        uri,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5,
                        max_size=2**20,
                        compression=None,
                        open_timeout=10
                    ),
                    timeout=15
                )
                
                self.websocket_connections[pair] = websocket
                self.websocket_failures[pair] = 0
                
                self.logger.info(f"✅ WebSocket connected for {pair}")
                
                # Listen for messages
                try:
                    async for message in websocket:
                        if not self.running or pair not in self.monitored_pairs:
                            break
                        
                        try:
                            data = json.loads(message)
                            await self.process_websocket_price_update(pair, data)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            self.logger.error(f"Error processing WebSocket message for {pair}: {e}")
                            
                except websockets.exceptions.ConnectionClosed:
                    self.logger.warning(f"WebSocket connection closed for {pair}")
                except Exception as e:
                    self.logger.warning(f"WebSocket error for {pair}: {e}")
                    
            except Exception as e:
                self.websocket_failures[pair] = self.websocket_failures.get(pair, 0) + 1
                self.monitoring_stats['websocket_reconnects'] += 1
                self.logger.warning(f"WebSocket connection failed for {pair} (attempt {self.websocket_failures[pair]}): {e}")
            
            # Cleanup connection on error
            if pair in self.websocket_connections:
                try:
                    await self.websocket_connections[pair].close()
                except:
                    pass
                del self.websocket_connections[pair]
            
            # Wait before retry (exponential backoff)
            if self.running and pair in self.monitored_pairs:
                wait_time = min(5 * (2 ** min(self.websocket_failures.get(pair, 0), 4)), 60)
                await asyncio.sleep(wait_time)
        
        # Final cleanup
        if pair in self.websocket_connections:
            try:
                await self.websocket_connections[pair].close()
                del self.websocket_connections[pair]
            except:
                pass
    
    async def process_websocket_price_update(self, pair: str, data: Dict):
        """Process WebSocket price updates"""
        try:
            if 'c' not in data:
                return
            
            current_price = float(data['c'])
            timestamp = time.time()
            
            # Update price cache
            self.price_cache[pair] = {
                'price': current_price,
                'timestamp': timestamp,
                'source': 'websocket'
            }
            
            self.last_price_updates[pair] = timestamp
            
            # Check signals immediately
            await self.check_pair_signals(pair, current_price)
            
        except Exception as e:
            self.logger.error(f"Error processing WebSocket price update for {pair}: {e}")
    
    async def get_current_price_rest_api(self, pair: str) -> Optional[float]:
        """Get current price using REST API"""
        try:
            if not self.binance_client:
                return None
            
            ticker = await self.binance_client.get_symbol_ticker(symbol=pair)
            price = float(ticker['price'])
            
            # Update cache
            self.price_cache[pair] = {
                'price': price,
                'timestamp': time.time(),
                'source': 'rest_api'
            }
            
            self.monitoring_stats['rest_api_calls'] += 1
            return price
            
        except Exception as e:
            self.logger.error(f"REST API error for {pair}: {e}")
            return None
    
    async def get_current_price(self, pair: str) -> Optional[float]:
        """Get current price with WebSocket priority and REST API fallback"""
        try:
            current_time = time.time()
            
            # Check WebSocket cache first
            if pair in self.price_cache:
                cache_data = self.price_cache[pair]
                # Use WebSocket price if it's less than 5 seconds old
                if (cache_data['source'] == 'websocket' and 
                    current_time - cache_data['timestamp'] < 5):
                    return cache_data['price']
                # Use REST API price if it's less than 30 seconds old
                elif (cache_data['source'] == 'rest_api' and 
                      current_time - cache_data['timestamp'] < 30):
                    return cache_data['price']
            
            # Fallback to REST API
            return await self.get_current_price_rest_api(pair)
            
        except Exception as e:
            self.logger.error(f"Error getting current price for {pair}: {e}")
            return None
    
    async def realtime_monitoring_loop(self):
        """Main real-time monitoring loop - checks every second"""
        self.logger.info("📊 Starting real-time monitoring loop (1-second intervals)...")
        
        while self.running:
            try:
                start_time = time.time()
                
                # Get all open signals
                open_signals = dict(self.open_signals_tracker)
                
                if open_signals:
                    # Check each signal
                    for signal_id, signal_data in open_signals.items():
                        try:
                            pair = signal_data['pair']
                            
                            # Ensure pair is being monitored
                            if pair not in self.monitored_pairs:
                                await self.add_pair_monitoring(pair, signal_data)
                            
                            # Get current price (WebSocket preferred, REST API fallback)
                            current_price = await self.get_current_price(pair)
                            
                            if current_price is not None:
                                await self.check_signal_for_closure(signal_id, signal_data, current_price)
                                self.monitoring_stats['signals_checked'] += 1
                            
                        except Exception as e:
                            self.logger.error(f"Error checking signal {signal_id}: {e}")
                
                # Clean up monitoring for pairs with no open signals
                await self.cleanup_monitoring()
                
                # Maintain 1-second intervals
                elapsed = time.time() - start_time
                sleep_time = max(0, self.realtime_interval - elapsed)
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                self.logger.error(f"Error in real-time monitoring loop: {e}")
                await asyncio.sleep(1)
    
    async def check_signal_for_closure(self, signal_id: str, signal_data: Dict, current_price: float):
        """Check if a signal should be closed and handle multi-target scenarios"""
        try:
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            
            # Get signal details from registry
            if signal_id not in self.signal_registry:
                return
            
            registry_data = self.signal_registry[signal_id]
            targets = registry_data.get('targets', [])
            stop_loss = registry_data.get('stop_loss')
            
            if not targets or not stop_loss:
                return
            
            # PROPOSAL 5: Dynamic Trailing Stop-Loss
            is_long = signal_type.upper() in ['LONG', 'BUY']
            if is_long:
                current_pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                current_pnl_pct = (entry_price - current_price) / entry_price * 100
            
            if current_pnl_pct > 2.0:
                # Trail SL to lock in 40% of unrealized gains when +2%
                trail_pct = current_pnl_pct * 0.40
                
                updated_sl = False
                if is_long:
                    new_sl = entry_price * (1 + trail_pct / 100)
                    if new_sl > stop_loss:
                        registry_data['stop_loss'] = new_sl
                        stop_loss = new_sl
                        updated_sl = True
                else:
                    new_sl = entry_price * (1 - trail_pct / 100)
                    if new_sl < stop_loss:
                        registry_data['stop_loss'] = new_sl
                        stop_loss = new_sl
                        updated_sl = True
                        
                if updated_sl:
                    # Notify Cornix without spamming (only update if it moved by > 0.5%)
                    last_cornix = registry_data.get('last_cornix_sl', entry_price if is_long else entry_price*2)
                    diff_pct = abs(new_sl - last_cornix) / last_cornix * 100
                    if diff_pct > 0.5:
                        msg_id = registry_data.get('telegram_message_id')
                        if msg_id:
                            cornix_cmd = f"Stop: {new_sl:.6f}"
                            try:
                                asyncio.create_task(self.telegram_sender(cornix_cmd, reply_to_message_id=msg_id))
                                registry_data['last_cornix_sl'] = new_sl
                                self.logger.info(f"📈 Sent Trailing SL command to Cornix for {signal_id}: {cornix_cmd}")
                            except Exception as e:
                                self.logger.error(f"Failed to tell Cornix to trail SL: {e}")
            
            if current_pnl_pct > 5.0:
                # Tighter trail at +5%: lock in 60% of gains
                trail_pct = current_pnl_pct * 0.60
                
                updated_sl = False
                if is_long:
                    new_sl = entry_price * (1 + trail_pct / 100)
                    if new_sl > stop_loss:
                        registry_data['stop_loss'] = new_sl
                        stop_loss = new_sl
                        updated_sl = True
                else:
                    new_sl = entry_price * (1 - trail_pct / 100)
                    if new_sl < stop_loss:
                        registry_data['stop_loss'] = new_sl
                        stop_loss = new_sl
                        updated_sl = True
                        
                if updated_sl:
                    last_cornix = registry_data.get('last_cornix_sl', entry_price if is_long else entry_price*2)
                    diff_pct = abs(new_sl - last_cornix) / last_cornix * 100
                    if diff_pct > 0.5:
                        msg_id = registry_data.get('telegram_message_id')
                        if msg_id:
                            cornix_cmd = f"Stop: {new_sl:.6f}"
                            try:
                                asyncio.create_task(self.telegram_sender(cornix_cmd, reply_to_message_id=msg_id))
                                registry_data['last_cornix_sl'] = new_sl
                                self.logger.info(f"📈 Sent Tighter Trailing SL command to Cornix for {signal_id}")
                            except Exception as e:
                                self.logger.error(f"Failed to update tighter Cornix trail: {e}")
            
            # Track which targets have been hit
            targets_hit = registry_data.get('targets_hit', [])
            
            # Check for closure conditions
            closure_result = None
            
            if signal_type.upper() in ['LONG', 'BUY']:
                # Long position - check stop loss first
                if current_price <= stop_loss:
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    closure_result = {
                        'reason': 'STOP_LOSS_HIT',
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'target_hit': 0,
                        'close_signal': True
                    }
                    self.monitoring_stats['stop_losses_hit'] += 1
                else:
                    # Check targets in order
                    for i, target in enumerate(targets):
                        target_num = i + 1
                        if target_num not in targets_hit and current_price >= target:
                            pnl_pct = (current_price - entry_price) / entry_price * 100
                            
                            # Mark this target as hit
                            if 'targets_hit' not in registry_data:
                                registry_data['targets_hit'] = []
                            registry_data['targets_hit'].append(target_num)
                            
                            # Check if this is the final target
                            is_final_target = target_num == len(targets)
                            
                            closure_result = {
                                'reason': f'TARGET_{target_num}_HIT',
                                'exit_price': current_price,
                                'pnl_pct': pnl_pct,
                                'target_hit': target_num,
                                'close_signal': is_final_target,
                                'partial_close': not is_final_target
                            }
                            self.monitoring_stats['targets_hit'] += 1
                            break
            
            elif signal_type.upper() in ['SHORT', 'SELL']:
                # Short position - check stop loss first
                if current_price >= stop_loss:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    closure_result = {
                        'reason': 'STOP_LOSS_HIT',
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'target_hit': 0,
                        'close_signal': True
                    }
                    self.monitoring_stats['stop_losses_hit'] += 1
                else:
                    # Check targets in order
                    for i, target in enumerate(targets):
                        target_num = i + 1
                        if target_num not in targets_hit and current_price <= target:
                            pnl_pct = (entry_price - current_price) / entry_price * 100
                            
                            # Mark this target as hit
                            if 'targets_hit' not in registry_data:
                                registry_data['targets_hit'] = []
                            registry_data['targets_hit'].append(target_num)
                            
                            # Check if this is the final target
                            is_final_target = target_num == len(targets)
                            
                            closure_result = {
                                'reason': f'TARGET_{target_num}_HIT',
                                'exit_price': current_price,
                                'pnl_pct': pnl_pct,
                                'target_hit': target_num,
                                'close_signal': is_final_target,
                                'partial_close': not is_final_target
                            }
                            self.monitoring_stats['targets_hit'] += 1
                            break
            
            # Process closure if needed
            if closure_result:
                await self.process_signal_closure(signal_id, signal_data, closure_result)
            
        except Exception as e:
            self.logger.error(f"Error checking signal closure for {signal_id}: {e}")
    
    async def process_signal_closure(self, signal_id: str, signal_data: Dict, closure_result: Dict):
        """Process signal closure and send notifications"""
        try:
            pair = signal_data['pair']
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            
            reason = closure_result['reason']
            exit_price = closure_result['exit_price']
            pnl_pct = closure_result['pnl_pct']
            target_hit = closure_result.get('target_hit', 0)
            close_signal = closure_result.get('close_signal', True)
            partial_close = closure_result.get('partial_close', False)
            
            # Create notification message
            if 'TARGET' in reason:
                emoji = "🎯"
                status_emoji = "💰" if pnl_pct > 0 else "📉"
                title = f"TARGET {target_hit} HIT"
                
                if partial_close:
                    status_text = f"🟡 TARGET {target_hit} ACHIEVED - SIGNAL CONTINUES"
                else:
                    status_text = "🔴 ALL TARGETS HIT - SIGNAL CLOSED"
            else:
                emoji = "🛑"
                status_emoji = "📉" if pnl_pct < 0 else "💰"
                title = "TRAILING STOP HIT" if pnl_pct > 0 else "STOP LOSS HIT"
                status_text = "🔴 SIGNAL CLOSED"
            
            # Get registry data for additional info
            registry_data = self.signal_registry.get(signal_id, {})
            targets = registry_data.get('targets', [])
            targets_hit_list = registry_data.get('targets_hit', [])
            
            # Calculate duration
            entry_timestamp = signal_data.get('timestamp', time.time())
            duration_hours = (time.time() - entry_timestamp) / 3600
            
            notification = (
                f"{emoji} **{title}** {status_emoji}\n"
                f"🆔 Signal ID: {signal_id}\n"
                f"💰 Pair: {pair}\n"
                f"📊 Type: {signal_type}\n"
                f"🔸 Entry: {entry_price:.6f}\n"
                f"🔸 Exit: {exit_price:.6f}\n"
                f"📈 PnL: {pnl_pct:+.2f}%\n"
                f"🔔 Reason: {reason.replace('_', ' ')}\n"
                f"⏰ Duration: {duration_hours:.1f} hours\n"
                f"🔍 Source: Real-time Monitor\n"
            )
            
            # Add target progress for multi-target signals
            if targets and len(targets) > 1:
                targets_progress = f"🎯 Targets Hit: {len(targets_hit_list)}/{len(targets)}\n"
                notification += targets_progress
            
            notification += f"{status_text}"
            
            # Send notification to MAIN channel
            try:
                await self.telegram_sender(notification)
                self.logger.info(f"✅ Sent notification to MAIN channel for {signal_id}")
                
                # Also send a copy to closed signals channel for records
                await self.closed_signals_sender(notification)
            except Exception as e:
                self.logger.error(f"❌ Failed to send closure notification: {e}")
            
            # Update signal registry
            if signal_id in self.signal_registry:
                if close_signal:
                    # Signal is fully closed
                    self.signal_registry[signal_id]['status'] = 'CLOSED'
                    self.signal_registry[signal_id]['close_reason'] = reason
                    self.signal_registry[signal_id]['close_timestamp'] = time.time()
                    self.signal_registry[signal_id]['exit_price'] = exit_price
                    self.signal_registry[signal_id]['pnl_percentage'] = pnl_pct
                else:
                    # Partial close - update target hit info
                    self.signal_registry[signal_id][f'target_{target_hit}_hit_price'] = exit_price
                    self.signal_registry[signal_id][f'target_{target_hit}_hit_time'] = time.time()
                    self.signal_registry[signal_id][f'target_{target_hit}_pnl'] = pnl_pct
            
            # Remove from open signals tracker only if fully closed
            if close_signal:
                if signal_id in self.open_signals_tracker:
                    del self.open_signals_tracker[signal_id]
                self.logger.info(f"🔴 Closed signal {signal_id}: {reason} with {pnl_pct:+.2f}% PnL")
                
                # SELF-LEARNING FEEDBACK: Link ID/Features to Outcome
                try:
                    outcome = "SUCCESS" if ("TARGET" in reason or pnl_pct > 0) else "FAILURE"
                    # Capture signal details for learning
                    if signal_id in self.signal_registry:
                        reg_entry = self.signal_registry[signal_id]
                        # Use the 15m timeframe as the standard learning timeframe for the ensemble
                        update_prediction_outcome(pair, signal_type, outcome, "15m")
                except Exception as learning_err:
                    self.logger.error(f"Failed to update self-learning for {signal_id}: {learning_err}")
            else:
                self.logger.info(f"🎯 Target {target_hit} hit for signal {signal_id}: {pnl_pct:+.2f}% PnL - signal continues")
            
        except Exception as e:
            self.logger.error(f"Error processing signal closure for {signal_id}: {e}")
    
    async def check_pair_signals(self, pair: str, current_price: float):
        """Check all signals for a specific pair"""
        try:
            pair_signals = {
                signal_id: signal_data 
                for signal_id, signal_data in self.open_signals_tracker.items() 
                if signal_data['pair'] == pair
            }
            
            for signal_id, signal_data in pair_signals.items():
                await self.check_signal_for_closure(signal_id, signal_data, current_price)
                    
        except Exception as e:
            self.logger.error(f"Error checking signals for {pair}: {e}")
    
    async def cleanup_monitoring(self):
        """Remove monitoring for pairs with no open signals"""
        try:
            # Get pairs with open signals
            pairs_with_signals = set()
            for signal_data in self.open_signals_tracker.values():
                pairs_with_signals.add(signal_data['pair'])
            
            # Remove monitoring for pairs without signals
            pairs_to_remove = self.monitored_pairs - pairs_with_signals
            
            for pair in pairs_to_remove:
                await self.remove_pair_monitoring(pair)
                
        except Exception as e:
            self.logger.error(f"Error in cleanup monitoring: {e}")
    
    async def websocket_health_manager(self):
        """Manage WebSocket health and reconnections"""
        while self.running:
            try:
                current_time = time.time()
                
                # Check for stale WebSocket connections
                for pair in list(self.monitored_pairs):
                    last_update = self.last_price_updates.get(pair, 0)
                    
                    # If no WebSocket update in 30 seconds, restart connection
                    if current_time - last_update > 30:
                        if pair in self.websocket_connections:
                            self.logger.warning(f"Restarting stale WebSocket for {pair}")
                            try:
                                await self.websocket_connections[pair].close()
                                del self.websocket_connections[pair]
                            except:
                                pass
                            
                            # Restart WebSocket
                            asyncio.create_task(self.start_pair_websocket(pair))
                
                await asyncio.sleep(self.websocket_check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in WebSocket health manager: {e}")
                await asyncio.sleep(10)
    
    async def rest_api_fallback_loop(self):
        """REST API fallback loop for pairs with WebSocket issues"""
        while self.running:
            try:
                current_time = time.time()
                
                # Only run every 10 seconds
                if current_time - self.last_rest_check < self.rest_api_interval:
                    await asyncio.sleep(1)
                    continue
                
                self.last_rest_check = current_time
                
                # Check pairs that might need REST API fallback
                for pair in list(self.monitored_pairs):
                    try:
                        # If WebSocket is failing or stale, use REST API
                        last_update = self.last_price_updates.get(pair, 0)
                        websocket_stale = current_time - last_update > 15
                        
                        if websocket_stale or self.websocket_failures.get(pair, 0) > 3:
                            current_price = await self.get_current_price_rest_api(pair)
                            if current_price:
                                await self.check_pair_signals(pair, current_price)
                    
                    except Exception as e:
                        self.logger.error(f"Error in REST API fallback for {pair}: {e}")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error in REST API fallback loop: {e}")
                await asyncio.sleep(10)
    
    async def performance_reporter(self):
        """Report monitoring performance every hour"""
        while self.running:
            try:
                await asyncio.sleep(3600)  # 1 hour
                
                if not self.running:
                    break
                
                # Generate performance report
                report = (
                    f"📊 **Real-time Monitor Performance Report**\n"
                    f"🔍 Signals Checked: {self.monitoring_stats['signals_checked']}\n"
                    f"🎯 Targets Hit: {self.monitoring_stats['targets_hit']}\n"
                    f"🛑 Stop Losses Hit: {self.monitoring_stats['stop_losses_hit']}\n"
                    f"🔌 WebSocket Reconnects: {self.monitoring_stats['websocket_reconnects']}\n"
                    f"📡 REST API Calls: {self.monitoring_stats['rest_api_calls']}\n"
                    f"📈 Monitored Pairs: {len(self.monitored_pairs)}\n"
                    f"🔗 Active WebSockets: {len(self.websocket_connections)}\n"
                    f"⏰ Report Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                try:
                    await self.closed_signals_sender(report)
                except:
                    await self.telegram_sender(report)
                
                # Reset stats
                self.monitoring_stats = {
                    'signals_checked': 0,
                    'targets_hit': 0,
                    'stop_losses_hit': 0,
                    'websocket_reconnects': 0,
                    'rest_api_calls': 0
                }
                
            except Exception as e:
                self.logger.error(f"Error in performance reporter: {e}")
    
    async def get_monitoring_status(self) -> Dict:
        """Get current monitoring status"""
        return {
            'running': self.running,
            'monitored_pairs': list(self.monitored_pairs),
            'websocket_connections': len(self.websocket_connections),
            'open_signals': len(self.open_signals_tracker),
            'price_cache_size': len(self.price_cache),
            'stats': self.monitoring_stats.copy()
        }
