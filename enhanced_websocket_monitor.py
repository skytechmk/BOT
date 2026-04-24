import asyncio
import json
import os
import websockets
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging
from binance import AsyncClient
import pandas as pd

class RealTimeSignalMonitor:
    """Enhanced real-time monitoring system for trading signals"""
    
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
        self.websocket_check_interval = 1  # 1 second for WebSocket updates
        self.fallback_check_interval = 10  # 10 seconds for REST API fallback
        self.last_rest_check = 0
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Binance client for fallback
        self.binance_client = None
        
    async def initialize(self, api_key=None, api_secret=None):
        """Initialize the monitoring system"""
        try:
            if api_key and api_secret:
                self.binance_client = await AsyncClient.create(api_key, api_secret)
                self.logger.info("✅ Binance async client initialized")
            
            self.logger.info("🚀 Real-time signal monitor initialized")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize monitor: {e}")
            return False
    
    async def start_monitoring(self):
        """Start the real-time monitoring system"""
        self.running = True
        self.logger.info("🚀 Starting real-time signal monitoring...")
        
        # Start monitoring tasks
        asyncio.create_task(self.monitor_signals_realtime())
        asyncio.create_task(self.websocket_manager())
        
        self.logger.info("📡 Real-time monitoring system started")
    
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
        self.logger.info("🛑 Real-time monitoring stopped")
    
    async def add_pair_monitoring(self, pair: str, signal_data: Dict):
        """Add a pair to real-time monitoring"""
        try:
            if pair not in self.monitored_pairs:
                self.monitored_pairs.add(pair)
                
                # Start WebSocket for this pair
                asyncio.create_task(self.start_pair_websocket(pair))
                
                self.logger.info(f"📡 Added {pair} to real-time monitoring")
                
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
                
                # Remove from price cache
                if pair in self.price_cache:
                    del self.price_cache[pair]
                
                self.logger.info(f"📡 Removed {pair} from monitoring")
                
        except Exception as e:
            self.logger.error(f"Error removing {pair} from monitoring: {e}")
    
    async def start_pair_websocket(self, pair: str):
        """Start WebSocket connection for a specific pair with enhanced timeout handling"""
        stream_name = f"{pair.lower()}@ticker"
        uri = f"wss://fstream.binance.com/ws/{stream_name}"  # Use futures WebSocket
        
        reconnect_attempts = 0
        max_attempts = 3  # Reduced max attempts
        base_delay = 5
        
        while self.running and pair in self.monitored_pairs and reconnect_attempts < max_attempts:
            try:
                self.logger.info(f"🔌 Connecting WebSocket for {pair}...")
                
                # Enhanced connection with timeout and better error handling
                try:
                    websocket = await asyncio.wait_for(
                        websockets.connect(
                            uri,
                            ping_interval=30,     # Increased ping interval
                            ping_timeout=15,      # Increased ping timeout
                            close_timeout=5,      # Reduced close timeout
                            max_size=2**20,       # 1MB max message size
                            compression=None,     # Disable compression for speed
                            open_timeout=10       # 10 second open timeout
                        ),
                        timeout=15  # 15 second total connection timeout
                    )
                    
                    self.websocket_connections[pair] = websocket
                    reconnect_attempts = 0
                    
                    self.logger.info(f"✅ WebSocket connected for {pair}")
                    
                    # Listen for messages with timeout handling
                    try:
                        async for message in websocket:
                            if not self.running or pair not in self.monitored_pairs:
                                break
                            
                            try:
                                data = json.loads(message)
                                await self.process_price_update(pair, data)
                            except json.JSONDecodeError:
                                continue  # Skip invalid JSON
                            except Exception as e:
                                self.logger.error(f"Error processing message for {pair}: {e}")
                                
                    except websockets.exceptions.ConnectionClosed:
                        self.logger.warning(f"WebSocket connection closed for {pair}")
                        break
                    except Exception as e:
                        self.logger.warning(f"WebSocket message error for {pair}: {e}")
                        break
                        
                except asyncio.TimeoutError:
                    self.logger.warning(f"WebSocket connection timeout for {pair}")
                    reconnect_attempts += 1
                except websockets.exceptions.InvalidStatusCode as e:
                    self.logger.warning(f"WebSocket invalid status for {pair}: {e}")
                    reconnect_attempts += 1
                except OSError as e:
                    self.logger.warning(f"WebSocket network error for {pair}: {e}")
                    reconnect_attempts += 1
                except Exception as e:
                    self.logger.warning(f"WebSocket unexpected error for {pair}: {e}")
                    reconnect_attempts += 1
                    
            except Exception as e:
                self.logger.warning(f"WebSocket error for {pair}: {e}")
                reconnect_attempts += 1
            
            # Cleanup connection on error
            if pair in self.websocket_connections:
                try:
                    await self.websocket_connections[pair].close()
                except:
                    pass
                del self.websocket_connections[pair]
            
            # Wait before retry with exponential backoff
            if reconnect_attempts < max_attempts and self.running and pair in self.monitored_pairs:
                wait_time = min(base_delay * (2 ** reconnect_attempts), 60)  # Max 60 seconds
                self.logger.info(f"🔄 Reconnecting {pair} in {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        # Final cleanup
        if pair in self.websocket_connections:
            try:
                await self.websocket_connections[pair].close()
            except:
                pass
            del self.websocket_connections[pair]
        
        if reconnect_attempts >= max_attempts:
            self.logger.warning(f"❌ WebSocket connection failed for {pair} after {max_attempts} attempts - using REST API fallback")
    
    async def process_price_update(self, pair: str, data: Dict):
        """Process real-time price updates"""
        try:
            if 'c' not in data:
                return
            
            current_price = float(data['c'])
            timestamp = time.time()
            
            # Update price cache
            self.price_cache[pair] = {
                'price': current_price,
                'timestamp': timestamp
            }
            
            # Check signals for this pair
            await self.check_pair_signals(pair, current_price, timestamp)
            
        except Exception as e:
            self.logger.error(f"Error processing price update for {pair}: {e}")
    
    async def get_current_price(self, pair: str) -> Optional[float]:
        """Get current price for a pair (REST API prioritized due to WebSocket issues)"""
        try:
            # Check WebSocket cache first (if available and recent)
            if pair in self.price_cache:
                cache_data = self.price_cache[pair]
                # Use cached price if it's less than 3 seconds old
                if time.time() - cache_data['timestamp'] < 3:
                    return cache_data['price']
            
            # Prioritize REST API for reliability
            if self.binance_client:
                try:
                    ticker = await self.binance_client.get_symbol_ticker(symbol=pair)
                    price = float(ticker['price'])
                    
                    # Update cache
                    self.price_cache[pair] = {
                        'price': price,
                        'timestamp': time.time()
                    }
                    
                    return price
                except Exception as api_e:
                    self.logger.warning(f"REST API error for {pair}: {api_e}")
                    
                    # If REST API fails, try WebSocket cache (even if older)
                    if pair in self.price_cache:
                        cache_data = self.price_cache[pair]
                        # Use cached price if it's less than 30 seconds old as last resort
                        if time.time() - cache_data['timestamp'] < 30:
                            self.logger.info(f"Using older WebSocket cache for {pair}")
                            return cache_data['price']
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting current price for {pair}: {e}")
            return None
    
    async def monitor_signals_realtime(self):
        """Main real-time monitoring loop"""
        self.logger.info("📊 Starting real-time signal monitoring loop...")
        
        while self.running:
            try:
                current_time = time.time()
                
                # Get all open signals
                open_signals = dict(self.open_signals_tracker)
                
                if not open_signals:
                    await asyncio.sleep(self.websocket_check_interval)
                    continue
                
                # Check each signal
                signals_to_close = []
                
                for signal_id, signal_data in open_signals.items():
                    try:
                        pair = signal_data['pair']
                        
                        # Ensure pair is being monitored
                        if pair not in self.monitored_pairs:
                            await self.add_pair_monitoring(pair, signal_data)
                        
                        # Get current price
                        current_price = await self.get_current_price(pair)
                        
                        if current_price is None:
                            continue
                        
                        # Check if signal should be closed
                        close_result = await self.check_signal_closure(signal_id, signal_data, current_price)
                        
                        if close_result:
                            signals_to_close.append((signal_id, close_result))
                        
                    except Exception as e:
                        self.logger.error(f"Error checking signal {signal_id}: {e}")
                
                # Process signal closures
                for signal_id, close_data in signals_to_close:
                    await self.close_signal(signal_id, close_data)
                
                # Clean up monitoring for pairs with no open signals
                await self.cleanup_monitoring()
                
                # Wait before next check
                await asyncio.sleep(self.websocket_check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)
    
    async def check_signal_closure(self, signal_id: str, signal_data: Dict, current_price: float) -> Optional[Dict]:
        """Check if a signal should be closed with multi-target support"""
        try:
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            
            # Get signal details from registry
            if signal_id not in self.signal_registry:
                return None
            
            registry_data = self.signal_registry[signal_id]
            targets = registry_data.get('targets', [])
            stop_loss = registry_data.get('stop_loss')
            
            if not targets or not stop_loss:
                return None
            
            # Track which targets have been hit
            targets_hit = registry_data.get('targets_hit', [])
            if isinstance(targets_hit, int):
                targets_hit = list(range(1, targets_hit + 1)) if targets_hit > 0 else []
            elif not isinstance(targets_hit, list):
                targets_hit = []
            
            # Check for closure conditions
            if signal_type.upper() in ['LONG', 'BUY']:
                # Long position - check stop loss first
                if current_price <= stop_loss:
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    return {
                        'reason': 'STOP_LOSS_HIT',
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'target_hit': 0,
                        'close_signal': True
                    }
                
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
                        
                        return {
                            'reason': f'TARGET_{target_num}_HIT',
                            'exit_price': current_price,
                            'pnl_pct': pnl_pct,
                            'target_hit': target_num,
                            'close_signal': is_final_target,
                            'partial_close': not is_final_target
                        }
            
            elif signal_type.upper() in ['SHORT', 'SELL']:
                # Short position - check stop loss first
                if current_price >= stop_loss:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    return {
                        'reason': 'STOP_LOSS_HIT',
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                        'target_hit': 0,
                        'close_signal': True
                    }
                
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
                        
                        return {
                            'reason': f'TARGET_{target_num}_HIT',
                            'exit_price': current_price,
                            'pnl_pct': pnl_pct,
                            'target_hit': target_num,
                            'close_signal': is_final_target,
                            'partial_close': not is_final_target
                        }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking signal closure for {signal_id}: {e}")
            return None
    
    async def close_signal(self, signal_id: str, close_data: Dict):
        """Close a signal and send notifications with multi-target support"""
        try:
            if signal_id not in self.open_signals_tracker:
                return
            
            signal_data = self.open_signals_tracker[signal_id]
            pair = signal_data['pair']
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            
            reason = close_data['reason']
            exit_price = close_data['exit_price']
            pnl_pct = close_data['pnl_pct']
            target_hit = close_data.get('target_hit', 0)
            close_signal = close_data.get('close_signal', True)
            partial_close = close_data.get('partial_close', False)
            
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
                title = "STOP LOSS HIT"
                status_text = "🔴 SIGNAL CLOSED"
            
            # Get registry data for additional info
            registry_data = self.signal_registry.get(signal_id, {})
            targets = registry_data.get('targets', [])
            targets_hit = registry_data.get('targets_hit', [])
            if isinstance(targets_hit, int):
                targets_hit = list(range(1, targets_hit + 1)) if targets_hit > 0 else []
            elif not isinstance(targets_hit, list):
                targets_hit = []

            notification = (
                f"{emoji} **{title}** {status_emoji}\n"
                f"🆔 Signal ID: {signal_id}\n"
                f"💰 Pair: {pair}\n"
                f"📊 Type: {signal_type}\n"
                f"🔸 Entry: {entry_price:.6f}\n"
                f"🔸 Exit: {exit_price:.6f}\n"
                f"📈 PnL: {pnl_pct:+.2f}%\n"
                f"🔔 Reason: {reason.replace('_', ' ')}\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n"
            )
            
            # Add target progress for multi-target signals
            if targets and len(targets) > 1:
                targets_progress = f"🎯 Targets Hit: {len(targets_hit)}/{len(targets)}\n"
                notification += targets_progress
            
            notification += f"{status_text}"
            
            # Send notification to appropriate channel
            try:
                if partial_close:
                    # Send target hit notification to CLOSED SIGNALS channel
                    await self.closed_signals_sender(notification)
                    self.logger.info(f"✅ Sent target {target_hit} notification to CLOSED SIGNALS channel for {signal_id}")
                else:
                    # Send closure notification to closed signals channel
                    await self.closed_signals_sender(notification)
                    self.logger.info(f"✅ Sent closure notification to CLOSED SIGNALS channel for {signal_id}")
            except Exception as e:
                self.logger.error(f"❌ Failed to send notification: {e}")
                # Fallback to main channel
                try:
                    await self.telegram_sender(notification)
                    self.logger.info(f"✅ Sent notification to main channel as fallback")
                except Exception as fallback_e:
                    self.logger.error(f"❌ Failed to send to main channel: {fallback_e}")
            
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
                del self.open_signals_tracker[signal_id]
                self.logger.info(f"🔴 Closed signal {signal_id}: {reason} with {pnl_pct:+.2f}% PnL")
            else:
                self.logger.info(f"🎯 Target {target_hit} hit for signal {signal_id}: {pnl_pct:+.2f}% PnL - signal continues")
            
        except Exception as e:
            self.logger.error(f"Error closing signal {signal_id}: {e}")
    
    async def check_pair_signals(self, pair: str, current_price: float, timestamp: float):
        """Check all signals for a specific pair"""
        try:
            pair_signals = {
                signal_id: signal_data 
                for signal_id, signal_data in self.open_signals_tracker.items() 
                if signal_data['pair'] == pair
            }
            
            for signal_id, signal_data in pair_signals.items():
                close_result = await self.check_signal_closure(signal_id, signal_data, current_price)
                if close_result:
                    await self.close_signal(signal_id, close_result)
                    
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
    
    async def websocket_manager(self):
        """Manage WebSocket connections"""
        while self.running:
            try:
                # Check for disconnected WebSockets
                disconnected_pairs = []
                
                for pair in self.monitored_pairs:
                    if pair not in self.websocket_connections:
                        disconnected_pairs.append(pair)
                
                # Reconnect disconnected pairs
                for pair in disconnected_pairs:
                    asyncio.create_task(self.start_pair_websocket(pair))
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Error in WebSocket manager: {e}")
                await asyncio.sleep(10)
    
    async def get_monitoring_status(self) -> Dict:
        """Get current monitoring status"""
        return {
            'running': self.running,
            'monitored_pairs': list(self.monitored_pairs),
            'websocket_connections': len(self.websocket_connections),
            'open_signals': len(self.open_signals_tracker),
            'price_cache_size': len(self.price_cache)
        }
