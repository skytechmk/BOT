import asyncio
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging

from live_price_feed import LIVE_FEED

# Poll interval for the price-check loop (seconds).  1 s gives sub-second
# reaction time without measurable CPU cost — we're just reading a dict.
_POLL_INTERVAL = 1.0

# How often to re-sync the monitored pair set from disk (seconds).
_PAIR_SYNC_INTERVAL = 10.0


class BinanceWebSocketMonitor:
    """Real-time signal monitoring via the global LIVE_FEED singleton.

    Instead of opening a dedicated WebSocket per pair, this class polls the
    in-memory LIVE_FEED dictionary (populated by live_price_feed.py which
    already runs multiplexed !markPrice@arr@1s + !bookTicker streams for
    every USDT-M perp symbol).  This reduces connection count from O(pairs)
    to exactly 2 shared WebSockets regardless of how many signals are open.
    """

    def __init__(self, signal_manager, telegram_sender):
        self.signal_manager = signal_manager
        self.telegram_sender = telegram_sender
        self.monitored_pairs: set = set()
        self.running = False

        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    async def start_monitoring(self):
        """Start the monitoring system"""
        self.running = True
        self.logger.info("🚀 Starting signal monitor (LIVE_FEED polling mode)...")
        asyncio.create_task(self._price_poll_loop())

    async def stop_monitoring(self):
        """Stop the monitoring system"""
        self.running = False
        self.monitored_pairs.clear()
        self.logger.info("🛑 Signal monitor stopped")

    # ── Pair set management ──────────────────────────────────────────────

    async def add_pair_monitoring(self, pair: str, signal_data: Dict):
        """Add a trading pair to the monitored set"""
        if pair not in self.monitored_pairs:
            self.monitored_pairs.add(pair)
            self.logger.info(f"📡 Added {pair} to real-time monitoring")

    async def remove_pair_monitoring(self, pair: str):
        """Remove a trading pair from the monitored set"""
        if pair in self.monitored_pairs:
            self.monitored_pairs.discard(pair)
            self.logger.info(f"📡 Removed {pair} from real-time monitoring")

    async def check_pair_should_be_monitored(self, pair: str) -> bool:
        """Check if a pair should still be monitored based on open signals"""
        try:
            open_signals = self.signal_manager.get_open_signals_for_pair(pair)
            return len(open_signals) > 0
        except Exception as e:
            self.logger.error(f"Error checking if {pair} should be monitored: {e}")
            return False

    # ── Core polling loop (replaces per-pair WebSocket tasks) ────────────

    async def _price_poll_loop(self):
        """Single async loop: syncs the pair set periodically and polls
        LIVE_FEED for every monitored pair each second."""

        last_pair_sync = 0.0

        while self.running:
            try:
                now = time.time()

                # ── Periodic pair-set sync (every _PAIR_SYNC_INTERVAL) ───
                if now - last_pair_sync >= _PAIR_SYNC_INTERVAL:
                    await self._sync_monitored_pairs()
                    last_pair_sync = now

                # ── Price check for every monitored pair ─────────────────
                for pair in list(self.monitored_pairs):
                    price_data = LIVE_FEED.get(pair)
                    if price_data is None:
                        continue  # no data yet or stale — skip this tick

                    current_price = price_data.get('mark') or price_data.get('mid')
                    timestamp = price_data.get('mark_ts', now)

                    if current_price and current_price > 0:
                        await self.check_signal_targets(pair, float(current_price), float(timestamp))

                await asyncio.sleep(_POLL_INTERVAL)

            except Exception as e:
                self.logger.error(f"Error in price poll loop: {e}")
                await asyncio.sleep(2)

        self.logger.info("📊 Price poll loop stopped")

    async def _sync_monitored_pairs(self):
        """Reload signals from disk and reconcile the monitored pair set."""
        try:
            self.signal_manager.load_signals()
            open_signals = self.signal_manager.get_all_open_signals()

            active_pairs = {sd['pair'] for sd in open_signals.values()}

            # Add new pairs
            for pair in active_pairs - self.monitored_pairs:
                await self.add_pair_monitoring(pair, {})

            # Remove stale pairs
            for pair in self.monitored_pairs - active_pairs:
                await self.remove_pair_monitoring(pair)

            if active_pairs:
                self.logger.debug(
                    f"📈 Monitoring {len(open_signals)} signals across "
                    f"{len(self.monitored_pairs)} pairs via LIVE_FEED"
                )

        except Exception as e:
            self.logger.error(f"Error syncing monitored pairs: {e}")

    # ── Signal target evaluation (unchanged) ─────────────────────────────

    async def check_signal_targets(self, pair: str, current_price: float, timestamp: float):
        """Check if current price hits any targets or stop loss for open signals"""
        try:
            open_signals = self.signal_manager.get_open_signals_for_pair(pair)
            
            for signal_id, signal_data in open_signals.items():
                await self.evaluate_signal_targets(signal_id, signal_data, current_price, timestamp)
                
        except Exception as e:
            self.logger.error(f"Error checking signal targets for {pair}: {e}")
            
    async def evaluate_signal_targets(self, signal_id: str, signal_data: Dict, current_price: float, timestamp: float):
        """Evaluate if a specific signal has hit targets or stop loss"""
        try:
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            targets = signal_data.get('targets', [])
            stop_loss = signal_data.get('stop_loss')
            targets_hit = signal_data.get('targets_hit', [])
            
            if signal_type.upper() in ['LONG', 'BUY']:
                # Check targets (ascending order for long)
                for i, target in enumerate(targets):
                    if i not in targets_hit and current_price >= target:
                        await self.handle_target_hit(signal_id, signal_data, i + 1, target, current_price, timestamp)
                        targets_hit.append(i)
                        
                # Check stop loss
                if stop_loss and current_price <= stop_loss:
                    await self.handle_stop_loss_hit(signal_id, signal_data, current_price, timestamp)
                    
            elif signal_type.upper() in ['SHORT', 'SELL']:
                # Check targets (descending order for short)
                for i, target in enumerate(targets):
                    if i not in targets_hit and current_price <= target:
                        await self.handle_target_hit(signal_id, signal_data, i + 1, target, current_price, timestamp)
                        targets_hit.append(i)
                        
                # Check stop loss
                if stop_loss and current_price >= stop_loss:
                    await self.handle_stop_loss_hit(signal_id, signal_data, current_price, timestamp)
                    
            # Update targets hit
            signal_data['targets_hit'] = targets_hit
            
            # Check if all targets are hit
            if len(targets_hit) >= len(targets):
                await self.handle_all_targets_hit(signal_id, signal_data, current_price, timestamp)
                
        except Exception as e:
            self.logger.error(f"Error evaluating signal targets for {signal_id}: {e}")
            
    async def handle_target_hit(self, signal_id: str, signal_data: Dict, target_number: int, target_price: float, current_price: float, timestamp: float):
        """Handle when a target is hit"""
        try:
            pair = signal_data['pair']
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            
            # Calculate PnL
            if signal_type.upper() in ['LONG', 'BUY']:
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                
            # Create target hit message
            target_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][target_number - 1]
            message = (
                f"🎯 **TARGET {target_number} HIT** 💰\n"
                f"🆔 Signal ID: {signal_id}\n"
                f"💰 Pair: {pair}\n"
                f"📊 Type: {signal_type}\n"
                f"🔸 Entry: {entry_price:.6f}\n"
                f"🎯 Target {target_number}: {target_price:.6f}\n"
                f"💹 Current: {current_price:.6f}\n"
                f"📈 PnL: +{pnl_pct:.2f}%\n"
                f"⏰ Time: {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}"
            )
            
            # Send notification with error handling
            try:
                if asyncio.iscoroutinefunction(self.telegram_sender):
                    await self.telegram_sender(message)
                else:
                    self.telegram_sender(message)
                self.logger.info(f"📤 Target {target_number} notification sent for {signal_id}")
            except Exception as notification_error:
                self.logger.error(f"Failed to send target hit notification for {signal_id}: {notification_error}")
            
            # Log the event
            self.logger.info(f"🎯 Target {target_number} hit for {signal_id} ({pair}): {current_price:.6f}")
            
            # Update signal data and save
            signal_data['last_target_hit'] = target_number
            signal_data['last_target_price'] = target_price
            signal_data['last_target_time'] = timestamp
            self.signal_manager.save_signals()
            
        except Exception as e:
            self.logger.error(f"Error handling target hit for {signal_id}: {e}")
            
    async def handle_stop_loss_hit(self, signal_id: str, signal_data: Dict, current_price: float, timestamp: float):
        """Handle when stop loss is hit"""
        try:
            pair = signal_data['pair']
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            stop_loss = signal_data['stop_loss']
            
            # Calculate PnL
            if signal_type.upper() in ['LONG', 'BUY']:
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                
            # Create stop loss message
            message = (
                f"🛑 **STOP LOSS HIT** 📉\n"
                f"🆔 Signal ID: {signal_id}\n"
                f"💰 Pair: {pair}\n"
                f"📊 Type: {signal_type}\n"
                f"🔸 Entry: {entry_price:.6f}\n"
                f"🛑 Stop Loss: {stop_loss:.6f}\n"
                f"💹 Current: {current_price:.6f}\n"
                f"📉 PnL: {pnl_pct:+.2f}%\n"
                f"⏰ Time: {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}\n"
                f"🔴 Status: SIGNAL CLOSED"
            )
            
            # Send notification with error handling
            try:
                if asyncio.iscoroutinefunction(self.telegram_sender):
                    await self.telegram_sender(message)
                else:
                    self.telegram_sender(message)
                self.logger.info(f"📤 Stop loss notification sent for {signal_id}")
            except Exception as notification_error:
                self.logger.error(f"Failed to send stop loss notification for {signal_id}: {notification_error}")
            
            # Log the event
            self.logger.info(f"🛑 Stop loss hit for {signal_id} ({pair}): {current_price:.6f}")
            
            # Close signal first, then check if pair should still be monitored
            await self.signal_manager.close_signal(signal_id, "STOP_LOSS_HIT", pnl_pct)
            
            # Only remove pair monitoring if no other signals exist for this pair
            if not await self.check_pair_should_be_monitored(pair):
                await self.remove_pair_monitoring(pair)
                self.logger.info(f"🔴 No more signals for {pair}, removed from monitoring")
            
        except Exception as e:
            self.logger.error(f"Error handling stop loss hit for {signal_id}: {e}")
            
    async def handle_all_targets_hit(self, signal_id: str, signal_data: Dict, current_price: float, timestamp: float):
        """Handle when all targets are hit"""
        try:
            pair = signal_data['pair']
            signal_type = signal_data['signal_type']
            entry_price = signal_data['entry_price']
            targets = signal_data['targets']
            
            # Calculate final PnL
            if signal_type.upper() in ['LONG', 'BUY']:
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                
            # Create completion message
            message = (
                f"🏆 **ALL TARGETS COMPLETED** 🎉\n"
                f"🆔 Signal ID: {signal_id}\n"
                f"💰 Pair: {pair}\n"
                f"📊 Type: {signal_type}\n"
                f"🔸 Entry: {entry_price:.6f}\n"
                f"🎯 Final Target: {targets[-1]:.6f}\n"
                f"💹 Current: {current_price:.6f}\n"
                f"📈 Total PnL: +{pnl_pct:.2f}%\n"
                f"⏰ Completed: {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}\n"
                f"🟢 Status: SIGNAL CLOSED - ALL TARGETS HIT"
            )
            
            # Send notification with error handling
            try:
                if asyncio.iscoroutinefunction(self.telegram_sender):
                    await self.telegram_sender(message)
                else:
                    self.telegram_sender(message)
                self.logger.info(f"📤 All targets completion notification sent for {signal_id}")
            except Exception as notification_error:
                self.logger.error(f"Failed to send completion notification for {signal_id}: {notification_error}")
            
            # Log the event
            self.logger.info(f"🏆 All targets completed for {signal_id} ({pair})")
            
            # Close signal first, then check if pair should still be monitored
            await self.signal_manager.close_signal(signal_id, "ALL_TARGETS_HIT", pnl_pct)
            
            # Only remove pair monitoring if no other signals exist for this pair
            if not await self.check_pair_should_be_monitored(pair):
                await self.remove_pair_monitoring(pair)
                self.logger.info(f"🟢 No more signals for {pair}, removed from monitoring")
            
        except Exception as e:
            self.logger.error(f"Error handling all targets hit for {signal_id}: {e}")


class EnhancedSignalManager:
    """Enhanced signal management system with WebSocket integration"""
    
    def __init__(self):
        self.open_signals = {}
        self.closed_signals = {}
        self.signal_file = "enhanced_open_signals.json"
        self.closed_file = "enhanced_closed_signals.json"
        self.load_signals()
        
    def load_signals(self):
        """Load signals from files"""
        try:
            if os.path.exists(self.signal_file):
                with open(self.signal_file, 'r') as f:
                    self.open_signals = json.load(f)
                    
            if os.path.exists(self.closed_file):
                with open(self.closed_file, 'r') as f:
                    self.closed_signals = json.load(f)
                    
        except Exception as e:
            print(f"Error loading signals: {e}")
            
    def save_signals(self):
        """Save signals to files"""
        try:
            with open(self.signal_file, 'w') as f:
                json.dump(self.open_signals, f, indent=2)
                
            with open(self.closed_file, 'w') as f:
                json.dump(self.closed_signals, f, indent=2)
                
        except Exception as e:
            print(f"Error saving signals: {e}")
            
    def add_signal(self, signal_id: str, signal_data: Dict):
        """Add a new signal to tracking"""
        signal_data['targets_hit'] = []
        signal_data['status'] = 'OPEN'
        signal_data['created_time'] = time.time()
        
        self.open_signals[signal_id] = signal_data
        self.save_signals()
        
    async def close_signal(self, signal_id: str, reason: str, pnl: float):
        """Close a signal and move it to closed signals"""
        if signal_id in self.open_signals:
            signal_data = self.open_signals[signal_id]
            signal_data['status'] = 'CLOSED'
            signal_data['close_reason'] = reason
            signal_data['close_time'] = time.time()
            signal_data['final_pnl'] = pnl
            
            # Move to closed signals
            self.closed_signals[signal_id] = signal_data
            del self.open_signals[signal_id]
            
            self.save_signals()
            
    def get_open_signals_for_pair(self, pair: str) -> Dict:
        """Get all open signals for a specific pair"""
        return {
            signal_id: signal_data 
            for signal_id, signal_data in self.open_signals.items() 
            if signal_data['pair'] == pair
        }
        
    def get_all_open_signals(self) -> Dict:
        """Get all open signals"""
        return self.open_signals.copy()
        
    def get_signal_count(self) -> int:
        """Get count of open signals"""
        return len(self.open_signals)
