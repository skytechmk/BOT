import json
import time
import pandas as pd
import asyncio
from datetime import datetime, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Binance client
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
client = Client(API_KEY, API_SECRET)

# Telegram Bot configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CLOSED_SIGNALS_TOKEN = os.getenv('CLOSED_SIGNALS_TOKEN')
CLOSED_SIGNALS_CHAT_ID = os.getenv('CLOSED_SIGNALS_CHAT_ID')

from telegram import Bot
closed_signals_bot = Bot(token=CLOSED_SIGNALS_TOKEN)

# File paths
OPEN_SIGNALS_FILE = "open_signals.json"
SIGNAL_REGISTRY_FILE = "signal_registry.json"
LOG_FILE = "debug_log10.txt"

def log_message(message, level="INFO"):
    """Log message to file"""
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"{datetime.now().isoformat()} - {level} - {message}\n")
    print(f"{datetime.now().isoformat()} - {level} - {message}")

def load_open_signals():
    """Load open signals from file"""
    try:
        if os.path.exists(OPEN_SIGNALS_FILE):
            with open(OPEN_SIGNALS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        log_message(f"Error loading open signals: {e}")
        return {}

def load_signal_registry():
    """Load signal registry from file"""
    try:
        if os.path.exists(SIGNAL_REGISTRY_FILE):
            with open(SIGNAL_REGISTRY_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        log_message(f"Error loading signal registry: {e}")
        return {}

def save_open_signals(open_signals):
    """Save open signals to file"""
    try:
        with open(OPEN_SIGNALS_FILE, 'w') as f:
            json.dump(open_signals, f, indent=2)
        log_message(f"Saved {len(open_signals)} open signals")
    except Exception as e:
        log_message(f"Error saving open signals: {e}")

def save_signal_registry(signal_registry):
    """Save signal registry to file"""
    try:
        with open(SIGNAL_REGISTRY_FILE, 'w') as f:
            json.dump(signal_registry, f, indent=2)
        log_message(f"Saved {len(signal_registry)} signals to registry")
    except Exception as e:
        log_message(f"Error saving signal registry: {e}")

async def send_closed_signal_message(message):
    """Send message to the closed signals channel"""
    try:
        await closed_signals_bot.send_message(chat_id=CLOSED_SIGNALS_CHAT_ID, text=message)
        log_message(f"Closed signal message sent: {message[:100]}...")
    except Exception as e:
        log_message(f"Failed to send closed signal message: {e}")

def fetch_historical_klines(pair, start_time, end_time, interval='1m'):
    """Fetch historical klines data from Binance"""
    try:
        # Convert timestamps to milliseconds
        start_time_ms = int(start_time * 1000)
        end_time_ms = int(end_time * 1000)
        
        log_message(f"Fetching historical data for {pair} from {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}")
        
        # Fetch klines data
        klines = client.futures_klines(
            symbol=pair,
            interval=interval,
            startTime=start_time_ms,
            endTime=end_time_ms,
            limit=1000
        )
        
        if not klines:
            log_message(f"No historical data found for {pair}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        # Convert timestamp and numeric columns
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)
        
        log_message(f"Fetched {len(df)} historical candles for {pair}")
        return df
        
    except BinanceAPIException as e:
        log_message(f"Binance API error fetching historical data for {pair}: {e}")
        return pd.DataFrame()
    except Exception as e:
        log_message(f"Error fetching historical data for {pair}: {e}")
        return pd.DataFrame()

def check_signal_targets_hit(signal_data, registry_data, historical_df):
    """Check if signal targets or stop loss were hit in historical data"""
    try:
        pair = signal_data['pair']
        signal_type = signal_data['signal_type']
        entry_price = signal_data['entry_price']
        entry_timestamp = signal_data['timestamp']
        
        # Get targets and stop loss from registry
        targets = registry_data.get('targets', [])
        stop_loss = registry_data.get('stop_loss')
        
        if not targets or not stop_loss:
            log_message(f"Missing targets or stop loss for signal {signal_data['signal_id']}")
            return None, None, None, None
        
        target_1 = targets[0] if targets else None
        
        # Filter historical data to only include data after signal entry
        entry_time = pd.to_datetime(entry_timestamp, unit='s')
        historical_df = historical_df[historical_df['timestamp'] > entry_time].copy()
        
        if historical_df.empty:
            log_message(f"No historical data after entry time for {pair}")
            return None, None, None, None
        
        log_message(f"Checking {len(historical_df)} candles for {pair} {signal_type} signal")
        log_message(f"Entry: {entry_price:.6f}, Target 1: {target_1:.6f}, Stop Loss: {stop_loss:.6f}")
        
        # Check each candle for target/stop loss hits
        for idx, row in historical_df.iterrows():
            candle_time = row['timestamp']
            candle_high = row['high']
            candle_low = row['low']
            candle_close = row['close']
            
            if signal_type.upper() in ['LONG', 'BUY']:
                # Long position: check if price hit target 1 (above) or stop loss (below)
                if candle_high >= target_1:
                    # Target 1 hit
                    pnl_pct = (target_1 - entry_price) / entry_price * 100
                    log_message(f"🎯 LONG Target 1 hit for {pair} at {candle_time}: {target_1:.6f} (+{pnl_pct:.2f}%)")
                    return "TARGET_1_HIT", target_1, pnl_pct, candle_time.timestamp()
                elif candle_low <= stop_loss:
                    # Stop loss hit
                    pnl_pct = (stop_loss - entry_price) / entry_price * 100
                    log_message(f"🛑 LONG Stop Loss hit for {pair} at {candle_time}: {stop_loss:.6f} ({pnl_pct:.2f}%)")
                    return "STOP_LOSS_HIT", stop_loss, pnl_pct, candle_time.timestamp()
                    
            elif signal_type.upper() in ['SHORT', 'SELL']:
                # Short position: check if price hit target 1 (below) or stop loss (above)
                if candle_low <= target_1:
                    # Target 1 hit
                    pnl_pct = (entry_price - target_1) / entry_price * 100
                    log_message(f"🎯 SHORT Target 1 hit for {pair} at {candle_time}: {target_1:.6f} (+{pnl_pct:.2f}%)")
                    return "TARGET_1_HIT", target_1, pnl_pct, candle_time.timestamp()
                elif candle_high >= stop_loss:
                    # Stop loss hit
                    pnl_pct = (entry_price - stop_loss) / entry_price * 100
                    log_message(f"🛑 SHORT Stop Loss hit for {pair} at {candle_time}: {stop_loss:.6f} ({pnl_pct:.2f}%)")
                    return "STOP_LOSS_HIT", stop_loss, pnl_pct, candle_time.timestamp()
        
        log_message(f"No targets or stop loss hit for {pair} in historical data")
        return None, None, None, None
        
    except Exception as e:
        log_message(f"Error checking signal targets for {signal_data['signal_id']}: {e}")
        return None, None, None, None

async def check_and_close_historical_signals():
    """Check all open signals against historical data and close those that hit targets/stop loss"""
    try:
        log_message("🔍 Starting historical signal check...")
        
        # Load data
        open_signals = load_open_signals()
        signal_registry = load_signal_registry()
        
        if not open_signals:
            log_message("No open signals to check")
            return
        
        log_message(f"Checking {len(open_signals)} open signals against historical data")
        
        signals_to_close = []
        current_time = time.time()
        
        for signal_id, signal_data in open_signals.items():
            try:
                pair = signal_data['pair']
                entry_timestamp = signal_data['timestamp']
                signal_type = signal_data['signal_type']
                entry_price = signal_data['entry_price']
                
                # Check if signal is in registry
                if signal_id not in signal_registry:
                    log_message(f"Signal {signal_id} not found in registry, marking for removal")
                    signals_to_close.append((signal_id, "REGISTRY_MISSING", None, None, None))
                    continue
                
                registry_data = signal_registry[signal_id]
                
                # Skip very recent signals (less than 5 minutes old)
                signal_age = current_time - entry_timestamp
                if signal_age < 300:  # 5 minutes
                    log_message(f"Skipping recent signal {signal_id} for {pair} (age: {signal_age:.0f}s)")
                    continue
                
                # Fetch historical data from entry time to now
                historical_df = fetch_historical_klines(
                    pair=pair,
                    start_time=entry_timestamp,
                    end_time=current_time,
                    interval='1m'
                )
                
                if historical_df.empty:
                    log_message(f"No historical data available for {pair}")
                    continue
                
                # Check if targets or stop loss were hit
                close_reason, exit_price, pnl_pct, exit_timestamp = check_signal_targets_hit(
                    signal_data, registry_data, historical_df
                )
                
                if close_reason:
                    signals_to_close.append((signal_id, close_reason, exit_price, pnl_pct, exit_timestamp))
                    log_message(f"Signal {signal_id} for {pair} should be closed: {close_reason}")
                
                # Small delay to avoid rate limits
                time.sleep(0.5)
                
            except Exception as e:
                log_message(f"Error checking signal {signal_id}: {e}")
                continue
        
        # Close all signals that hit targets/stop loss
        if signals_to_close:
            log_message(f"Found {len(signals_to_close)} signals to close")
            
            for signal_id, close_reason, exit_price, pnl_pct, exit_timestamp in signals_to_close:
                try:
                    signal_data = open_signals[signal_id]
                    pair = signal_data['pair']
                    signal_type = signal_data['signal_type']
                    entry_price = signal_data['entry_price']
                    entry_timestamp = signal_data['timestamp']
                    
                    # Update signal registry
                    if signal_id in signal_registry:
                        signal_registry[signal_id]['status'] = 'CLOSED'
                        signal_registry[signal_id]['close_reason'] = close_reason
                        signal_registry[signal_id]['close_timestamp'] = exit_timestamp or current_time
                        if exit_price:
                            signal_registry[signal_id]['exit_price'] = exit_price
                        if pnl_pct is not None:
                            signal_registry[signal_id]['pnl_percentage'] = pnl_pct
                    
                    # Remove from open signals
                    del open_signals[signal_id]
                    
                    # Send notification to closed signals channel
                    if close_reason != "REGISTRY_MISSING" and exit_price and pnl_pct is not None:
                        profit_emoji = "💰" if pnl_pct > 0 else "📉"
                        close_emoji = "🎯" if "TARGET" in close_reason else "🛑"
                        
                        # Calculate duration
                        duration_hours = (exit_timestamp - entry_timestamp) / 3600 if exit_timestamp else 0
                        
                        notification = (
                            f"{close_emoji} **SIGNAL CLOSED** {profit_emoji}\n"
                            f"🆔 Signal ID: {signal_id}\n"
                            f"💰 Pair: {pair}\n"
                            f"📊 Type: {signal_type}\n"
                            f"🔸 Entry: {entry_price:.6f}\n"
                            f"🔸 Exit: {exit_price:.6f}\n"
                            f"📈 PnL: {pnl_pct:+.2f}%\n"
                            f"🔔 Reason: {close_reason.replace('_', ' ')}\n"
                            f"⏰ Duration: {duration_hours:.1f} hours\n"
                            f"🔍 Source: Historical Data Check"
                        )
                        
                        await send_closed_signal_message(notification)
                        log_message(f"✅ Sent historical closure notification for {signal_id}")
                    
                    log_message(f"Successfully closed historical signal {signal_id}: {close_reason}")
                    
                except Exception as e:
                    log_message(f"Error closing historical signal {signal_id}: {e}")
            
            # Save updated data
            save_open_signals(open_signals)
            save_signal_registry(signal_registry)
            
            log_message(f"✅ Historical check completed: {len(signals_to_close)} signals closed")
            
            # Send summary to closed signals channel
            summary_message = (
                f"📊 **Historical Signal Check Complete**\n"
                f"🔍 Checked: {len(open_signals) + len(signals_to_close)} signals\n"
                f"✅ Closed: {len(signals_to_close)} signals\n"
                f"📈 Remaining Open: {len(open_signals)} signals\n"
                f"⏰ Check Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            await send_closed_signal_message(summary_message)
            
        else:
            log_message("No historical signals found that need closing")
            
    except Exception as e:
        log_message(f"Error in historical signal check: {e}")

async def main():
    """Main function to run historical signal check"""
    try:
        log_message("🚀 Starting Historical Signal Checker...")
        await check_and_close_historical_signals()
        log_message("✅ Historical Signal Checker completed")
    except Exception as e:
        log_message(f"Historical Signal Checker error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
