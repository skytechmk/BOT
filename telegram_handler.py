import json
import time
import uuid
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
import re
from utils_logger import log_message
from constants import *
from shared_state import *
from performance_tracker import save_performance_data

# Global variables for Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip("'\"")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip("'\"")
CLOSED_SIGNALS_TOKEN = os.getenv('CLOSED_SIGNALS_TOKEN', '').strip("'\"")
CLOSED_SIGNALS_CHAT_ID = os.getenv('CLOSED_SIGNALS_CHAT_ID', '').strip("'\"")
OPS_TELEGRAM_TOKEN = os.getenv('OPS_TELEGRAM_TOKEN', '').strip("'\"")
OPS_TELEGRAM_CHAT_ID = os.getenv('OPS_TELEGRAM_CHAT_ID', '').strip("'\"")

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None
closed_signals_bot = Bot(token=CLOSED_SIGNALS_TOKEN) if CLOSED_SIGNALS_TOKEN else None
ops_bot = Bot(token=OPS_TELEGRAM_TOKEN) if OPS_TELEGRAM_TOKEN else None

SIGNAL_REGISTRY_FILE = "signal_registry.json"
CORNIX_SIGNALS_FILE = "cornix_signals.json"

async def send_telegram_message(message, reply_to_message_id=None):
    try:
        if bot:
            msg = await bot.send_message(chat_id=CHAT_ID, text=message, reply_to_message_id=reply_to_message_id)
            log_message(f"Telegram message sent: {message[:50]}...")
            return msg.message_id
        else:
            log_message("Telegram bot not initialized")
            return None
    except Exception as e:
        log_message(f"Failed to send Telegram message: {e}")
        return None

async def send_closed_signal_message(message):
    """Send message to the closed signals channel"""
    try:
        if closed_signals_bot:
            await closed_signals_bot.send_message(chat_id=CLOSED_SIGNALS_CHAT_ID, text=message)
            log_message(f"Closed signal message sent: {message[:50]}...")
        else:
            log_message("Closed signals bot not initialized")
    except Exception as e:
        log_message(f"Failed to send closed signal message: {e}")

async def send_ops_message(message):
    """Send message to the Ops channel"""
    try:
        if ops_bot:
            await ops_bot.send_message(chat_id=OPS_TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
            log_message(f"Ops message sent: {message[:50]}...")
        elif bot and CHAT_ID == OPS_TELEGRAM_CHAT_ID:
             # Fallback if tokens are the same
             await bot.send_message(chat_id=OPS_TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
        else:
            log_message("Ops bot not initialized")
    except Exception as e:
        log_message(f"Failed to send Ops message: {e}")

def generate_signal_id():
    """Generate a unique signal ID"""
    return str(uuid.uuid4())

def register_signal(signal_id, pair, signal, price, confidence, targets, stop_loss, leverage, features=None, additional_data=None, telegram_message_id=None):
    """Register a signal with its market-feature snapshot for self-learning"""
    try:
        signal_entry = {
            'signal_id': signal_id,
            'pair': pair,
            'signal': signal,
            'price': price,
            'confidence': confidence,
            'targets': targets,
            'stop_loss': stop_loss,
            'leverage': leverage,
            'features_snapshot': features,  # Store full technical context
            'timestamp': time.time(),
            'status': 'SENT',
            'telegram_message_id': telegram_message_id,
            'cornix_response': None,
            'performance_data': None
        }
        
        if additional_data:
            signal_entry.update(additional_data)
        
        SIGNAL_REGISTRY[signal_id] = signal_entry
        
        # Save to persistent storage
        save_signal_registry()
        
        log_message(f"Registered signal {signal_id} for {pair}: {signal} at {price}")
        return signal_id
        
    except Exception as e:
        log_message(f"Error registering signal: {e}")
        return None

def save_signal_registry():
    """Save signal registry to file"""
    try:
        with open(SIGNAL_REGISTRY_FILE, 'w') as f:
            json.dump(SIGNAL_REGISTRY, f, indent=2)
        log_message(f"Saved {len(SIGNAL_REGISTRY)} signals to registry")
    except Exception as e:
        log_message(f"Error saving signal registry: {e}")

def load_signal_registry():
    """Load signal registry from file"""
    try:
        if os.path.exists(SIGNAL_REGISTRY_FILE):
            with open(SIGNAL_REGISTRY_FILE, 'r') as f:
                global SIGNAL_REGISTRY
                SIGNAL_REGISTRY = json.load(f)
            log_message(f"Loaded {len(SIGNAL_REGISTRY)} signals from registry")
    except Exception as e:
        log_message(f"Error loading signal registry: {e}")

def save_cornix_signals():
    """Save Cornix signals to file"""
    try:
        with open(CORNIX_SIGNALS_FILE, 'w') as f:
            json.dump(CORNIX_SIGNALS, f, indent=2)
        log_message(f"Saved {len(CORNIX_SIGNALS)} Cornix signals")
    except Exception as e:
        log_message(f"Error saving Cornix signals: {e}")

def load_cornix_signals():
    """Load Cornix signals from file"""
    try:
        if os.path.exists(CORNIX_SIGNALS_FILE):
            with open(CORNIX_SIGNALS_FILE, 'r') as f:
                global CORNIX_SIGNALS
                CORNIX_SIGNALS = json.load(f)
            log_message(f"Loaded {len(CORNIX_SIGNALS)} Cornix signals")
    except Exception as e:
        log_message(f"Error loading Cornix signals: {e}")

def parse_cornix_message(message_text):
    """Parse incoming Cornix message to extract signal information"""
    try:
        # Common Cornix message patterns
        patterns = {
            'signal_id': r'(?:Signal ID|ID|#)[\s:]*([A-Za-z0-9\-]+)',
            'pair': r'(?:Pair|Symbol|#)[\s:]*([A-Z0-9]+)(?:/| )?(USDT)?',
            'action': r'(?:Action|Type)[\s:]*(\w+)',
            'entry': r'(?:Entry|Price|Average Entry Price)[\s:]*([0-9.]+)',
            'targets': r'(?:Target|TP)[\s:]*([0-9.,\s]+)',
            'stop_loss': r'(?:Stop Loss|SL)[\s:]*([0-9.]+)',
            'status': r'(?:Status)[\s:]*(\w+)',
            'pnl': r'(?:PnL|Profit|Loss)[\s:]*([+-]?[0-9.]+%?)',
            'closed': r'(?:Closed|Filled|Completed|All entries achieved)',
            'target_achieved': r'(?:Target \d+ achieved|Target \d+ Hit|Take-Profit target \d+)',
            'stop_loss_achieved': r'(?:Stop Loss achieved|Stop Target Hit)',
            'cancelled': r'(?:Cancelled|Canceled)'
        }
        
        parsed_data = {}
        
        for key, pattern in patterns.items():
            match = re.search(pattern, message_text, re.IGNORECASE)
            if match:
                if key == 'targets':
                    # Parse multiple targets
                    targets_str = match.group(1)
                    targets = [float(x.strip()) for x in re.findall(r'[0-9.]+', targets_str)]
                    parsed_data[key] = targets
                elif key in ['entry', 'stop_loss']:
                    parsed_data[key] = float(match.group(1))
                elif key in ['closed', 'target_achieved', 'stop_loss_achieved', 'cancelled']:
                    parsed_data['status'] = key.upper()
                else:
                    parsed_data[key] = match.group(1)
        
        # Extract percentage from PnL if present
        if 'pnl' in parsed_data:
            pnl_str = parsed_data['pnl']
            pnl_match = re.search(r'([+-]?[0-9.]+)', pnl_str)
            if pnl_match:
                val = float(pnl_match.group(1))
                if 'loss' in message_text.lower() and val > 0:
                    val = -val
                parsed_data['pnl_value'] = val
                parsed_data['pnl_percentage'] = '%' in pnl_str
        
        # Pair Normalization
        if 'pair' in parsed_data:
            p = parsed_data['pair'].upper()
            if not p.endswith('USDT'):
                p += 'USDT'
            parsed_data['pair'] = p
            
        log_message(f"Parsed Cornix message: {parsed_data}")
        return parsed_data
        
    except Exception as e:
        log_message(f"Error parsing Cornix message: {e}")
        return {}

def process_cornix_response(message_text, reply_id=None):
    """Process incoming Cornix response and update signal registry"""
    try:
        parsed_data = parse_cornix_message(message_text)
        
        if not parsed_data and not reply_id:
            log_message("No valid data parsed from Cornix message")
            return False
        
        # Try to match with existing signals
        signal_id = parsed_data.get('signal_id')
        pair = parsed_data.get('pair')
        
        # 1. Match by Reply ID (Most Reliable)
        matching_signal = None
        if reply_id:
            for sid, signal_data in SIGNAL_REGISTRY.items():
                if signal_data.get('telegram_message_id') == reply_id:
                    matching_signal = signal_data
                    signal_id = sid
                    log_message(f"Matched Cornix response to signal {sid} via Reply ID {reply_id}")
                    break
        
        # 2. Match by Signal ID in text
        if not matching_signal and signal_id and signal_id in SIGNAL_REGISTRY:
            matching_signal = SIGNAL_REGISTRY[signal_id]
            log_message(f"Matched Cornix response to signal {signal_id} via ID in text")
            
        # 3. Match by Pair + Timestamp fallback
        if not matching_signal and pair:
            # Try to find by pair and recent timestamp
            current_time = time.time()
            for sid, signal_data in SIGNAL_REGISTRY.items():
                if (signal_data['pair'] == pair and 
                    current_time - signal_data['timestamp'] < 86400):  # Within 24 hours
                    matching_signal = signal_data
                    signal_id = sid
                    log_message(f"Matched Cornix response to signal {sid} via Pair {pair}")
                    break
        
        if matching_signal:
            # Status Mapping Logic
            new_status = parsed_data.get('status', 'UNKNOWN')
            if "All entries achieved" in message_text:
                new_status = "ENTRY_ACHIEVED"
            elif "Target" in message_text and "achieved" in message_text:
                new_status = "TP_HIT"
            elif "Stop Loss achieved" in message_text or "Stop Target Hit" in message_text:
                new_status = "SL_HIT"
                # Trigger Auto-Healer Post-Mortem
                from ai_auto_healer import AUTO_HEAL_ENGINE
                import asyncio
                asyncio.create_task(AUTO_HEAL_ENGINE.perform_post_mortem(signal_id))
                
            # Update signal with Cornix response
            cornix_entry = {
                'timestamp': time.time(),
                'message': message_text,
                'parsed_data': parsed_data,
                'status': new_status
            }
            
            matching_signal['status'] = new_status
            matching_signal['cornix_response'] = cornix_entry
            
            # Store in Cornix signals tracking
            CORNIX_SIGNALS[signal_id] = cornix_entry
            
            # Process performance data if available
            if 'pnl_value' in parsed_data or new_status in ['TP_HIT', 'SL_HIT']:
                pnl = parsed_data.get('pnl_value', 0.0)
                # If it's a TP/SL but we don't have PnL in text yet, we might want to estimate or wait
                # For now, use 0.0 if not found
                
                performance_data = {
                    'pnl_percentage': pnl,
                    'success': pnl > 0 or new_status == 'TP_HIT',
                    'closed_timestamp': time.time(),
                    'status': new_status
                }
                
                matching_signal['performance_data'] = performance_data
                
                # Learn from this result
                learn_from_cornix_result(signal_id, matching_signal, performance_data)
            
            # Save updated data
            save_signal_registry()
            save_cornix_signals()
            
            log_message(f"Updated signal {signal_id} with Cornix response: {new_status}")
            return True
        else:
            log_message(f"No matching signal found for Cornix message: {pair}")
            return False
            
    except Exception as e:
        log_message(f"Error processing Cornix response: {e}")
        return False

def learn_from_cornix_result(signal_id, signal_data, performance_data):
    """Learn from Cornix trading results to improve future signals"""
    try:
        pair = signal_data['pair']
        signal_type = signal_data['signal']
        entry_price = signal_data['price']
        confidence = signal_data.get('confidence', 0.5)
        pnl_percentage = performance_data['pnl_percentage']
        success = performance_data['success']
        
        # Create enhanced performance entry
        enhanced_performance = {
            'signal_id': signal_id,
            'pair': pair,
            'signal': signal_type,
            'entry_price': entry_price,
            'confidence': confidence,
            'pnl_percentage': pnl_percentage,
            'success': success,
            'timestamp': signal_data['timestamp'],
            'closed_timestamp': performance_data['closed_timestamp'],
            'source': 'CORNIX',
            'targets_hit': 0,  # Could be enhanced with target analysis
            'time_held': performance_data['closed_timestamp'] - signal_data['timestamp']
        }
        
        # Note: PERFORMANCE_HISTORY update might need to be imported or handled via performance_tracker
        from performance_tracker import PERFORMANCE_HISTORY
        
        if pair not in PERFORMANCE_HISTORY:
            PERFORMANCE_HISTORY[pair] = []
        
        PERFORMANCE_HISTORY[pair].append(enhanced_performance)
        
        if len(PERFORMANCE_HISTORY[pair]) > 100:
            PERFORMANCE_HISTORY[pair] = PERFORMANCE_HISTORY[pair][-100:]
        
        save_performance_data()
        
        log_message(f"Learned from Cornix result for {pair}: {signal_type} -> {pnl_percentage:.2f}% ({'Success' if success else 'Failure'})")
        
        # Generate learning insights
        generate_cornix_learning_insights(signal_id, enhanced_performance)
        
    except Exception as e:
        log_message(f"Error learning from Cornix result: {e}")

def generate_cornix_learning_insights(signal_id, performance_data):
    """Generate insights from Cornix trading results"""
    try:
        pair = performance_data['pair']
        signal_type = performance_data['signal']
        pnl = performance_data['pnl_percentage']
        confidence = performance_data['confidence']
        time_held = performance_data['time_held']
        
        insights = []
        
        # Performance analysis
        if pnl > 5:
            insights.append(f"🎯 Excellent result: {pnl:.2f}% profit on {pair} {signal_type}")
        elif pnl > 1:
            insights.append(f"✅ Good result: {pnl:.2f}% profit on {pair} {signal_type}")
        elif pnl > -1:
            insights.append(f"⚖️ Break-even result: {pnl:.2f}% on {pair} {signal_type}")
        elif pnl > -5:
            insights.append(f"⚠️ Small loss: {pnl:.2f}% on {pair} {signal_type}")
        else:
            insights.append(f"🔴 Significant loss: {pnl:.2f}% on {pair} {signal_type}")
        
        # Confidence correlation
        if confidence > 0.8 and pnl > 0:
            insights.append(f"🎯 High confidence ({confidence:.1%}) validated with profit")
        elif confidence > 0.8 and pnl < 0:
            insights.append(f"⚠️ High confidence ({confidence:.1%}) but resulted in loss - review indicators")
        elif confidence < 0.5 and pnl > 0:
            insights.append(f"🍀 Low confidence ({confidence:.1%}) but profitable - potential missed opportunity")
        
        # Time analysis
        hours_held = time_held / 3600
        if hours_held < 1:
            insights.append(f"⚡ Quick trade: {hours_held:.1f} hours")
        elif hours_held > 24:
            insights.append(f"🕐 Long hold: {hours_held:.1f} hours")
        
        # Log insights
        for insight in insights:
            log_message(f"Cornix Learning: {insight}")
        
        return insights
        
    except Exception as e:
        log_message(f"Error generating Cornix insights: {e}")
        return []

def get_cornix_performance_report():
    """Generate comprehensive Cornix performance report"""
    try:
        if not CORNIX_SIGNALS:
            return "No Cornix signals tracked yet."
        
        total_signals = len(CORNIX_SIGNALS)
        profitable_signals = 0
        total_pnl = 0
        
        # Analyze all Cornix signals
        for signal_id, cornix_data in CORNIX_SIGNALS.items():
            parsed_data = cornix_data.get('parsed_data', {})
            if 'pnl_value' in parsed_data:
                pnl = parsed_data['pnl_value']
                total_pnl += pnl
                if pnl > 0:
                    profitable_signals += 1
        
        win_rate = (profitable_signals / total_signals * 100) if total_signals > 0 else 0
        avg_pnl = total_pnl / total_signals if total_signals > 0 else 0
        
        report = [
            f"📊 **Cornix Performance Report**",
            f"🔹 Total Signals: {total_signals}",
            f"🔹 Profitable Signals: {profitable_signals}",
            f"🔹 Win Rate: {win_rate:.1f}%",
            f"🔹 Average PnL: {avg_pnl:.2f}%",
            f"🔹 Total PnL: {total_pnl:.2f}%"
        ]
        
        # Recent performance (last 7 days)
        week_ago = time.time() - (7 * 24 * 3600)
        recent_signals = [
            cornix_data for cornix_data in CORNIX_SIGNALS.values()
            if cornix_data['timestamp'] > week_ago
        ]
        
        if recent_signals:
            recent_profitable = sum(1 for s in recent_signals 
                                  if s.get('parsed_data', {}).get('pnl_value', 0) > 0)
            recent_win_rate = (recent_profitable / len(recent_signals) * 100) if recent_signals else 0
            
            report.extend([
                f"\n📈 **Recent Performance (7 days)**:",
                f"🔹 Recent Signals: {len(recent_signals)}",
                f"🔹 Recent Win Rate: {recent_win_rate:.1f}%"
            ])
        
        return "\n".join(report)
        
    except Exception as e:
        log_message(f"Error generating Cornix performance report: {e}")
        return "Error generating Cornix performance report"

async def setup_telegram_listener():
    """Setup Telegram bot to listen for Cornix messages and Ops commands"""
    try:
        from ai_auto_healer import setup_ops_listeners
        
        # Use primary token for unified listener if available, otherwise fallback
        effective_token = TELEGRAM_TOKEN or OPS_TELEGRAM_TOKEN
        if not effective_token:
            log_message("TELEGRAM_TOKEN not found - listener disabled")
            return None
            
        # Create application
        application = Application.builder().token(effective_token).build()
        
        # 1. Register Ops Commands
        await setup_ops_listeners(application)
        
        # 2. Ops AI Chat Handler (Pure NLP / MCP)
        async def handle_ai_chat(update, context):
            try:
                if str(update.message.chat_id) != OPS_TELEGRAM_CHAT_ID: return
                if update.message.text.startswith('/'): return
                
                chat_id = str(update.message.chat_id).strip("'\"")
                user_text = update.message.text
                
                from chat_memory_manager import CHAT_MEMORY
                from ai_mcp_bridge import get_mcp_tools_schema, MCPBridge
                
                # NLA System Prompt: Pure NLP Control
                system_prompt = (
                    "You are the Aladdin Institutional AI Manager. You have MCP tools to manage the bot.\n"
                    "RULES:\n"
                    "1. For any CODE EDIT or TRADE CANCELLATION, you MUST first explain the logic and ASK for confirmation.\n"
                    "2. DO NOT call 'edit_file' or 'cancel_trade_signal' until the user says 'yes', 'ok', 'da', or similar in the conversation context.\n"
                    "3. Once confirmed, execute the tool immediately.\n"
                    "4. You can freely use 'read_file', 'get_open_signals', and 'get_market_context' for analysis without asking.\n"
                    "5. Answer in the same language the user uses (Macedonian/English).\n"
                    f"Current Context: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                CHAT_MEMORY.add_message(chat_id, "user", user_text)
                
                # Recursive Tool Execution Loop
                max_iterations = 5
                for _ in range(max_iterations):
                    messages = CHAT_MEMORY.get_messages(chat_id, system_prompt=system_prompt)
                    tools = get_mcp_tools_schema()
                    
                    import asyncio
                    response = await asyncio.to_thread(
                        OPENROUTER_INTEL.query_ai,
                        user_text,
                        "You are an institutional trading assistant.",
                        None,
                        tools,
                        messages
                    )
                    
                    # Handle Tool Calls
                    if hasattr(response, 'get') and 'tool_calls' in response:
                        tool_calls = response['tool_calls']
                        CHAT_MEMORY.add_message(chat_id, "assistant", response.get('content', ''), tool_calls=tool_calls)
                        
                        for tc in tool_calls:
                            tool_name = tc['function']['name']
                            tool_args = json.loads(tc['function']['arguments'])
                            
                            # Execute Tool
                            tool_result = MCPBridge.execute_tool(tool_name, tool_args)
                            
                            # Add Tool outcome to memory
                            CHAT_MEMORY.add_message(chat_id, "tool", tool_result, tool_call_id=tc['id'], name=tool_name) 

                        
                        continue # AI needs to process the tool results
                    
                    elif isinstance(response, str):
                        try:
                            await update.message.reply_text(response, parse_mode='Markdown')
                        except Exception as parse_error:
                            log_message(f"Markdown parsing failed, falling back to plain text: {parse_error}")
                            await update.message.reply_text(response)
                        
                        CHAT_MEMORY.add_message(chat_id, "assistant", response)
                        break
                        
            except Exception as e:
                log_message(f"Error in Pure NLP Chat: {e}")
                await update.message.reply_text(f"⚠️ AI Manager Error:\n\n{e}")

        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(int(OPS_TELEGRAM_CHAT_ID) if OPS_TELEGRAM_CHAT_ID else 0), handle_ai_chat))
        
        # 3. Add Cornix Message handler
        async def handle_cornix_message(update, context):
            try:
                # Support both normal group messages and Channel posts
                msg = update.message or update.channel_post
                if not msg or not msg.text:
                    return
                    
                message_text = msg.text
                reply_to_id = None
                if msg.reply_to_message:
                    reply_to_id = msg.reply_to_message.message_id
                
                # Check if message is from Cornix keyword matching
                keywords = ['signal', 'entry', 'target', 'stop loss', 'stop target hit', 'pnl', 'loss', 'closed', 'achieved']
                if any(keyword in message_text.lower() for keyword in keywords):
                    log_message(f"Potential Cornix message received: {message_text[:50]}...")
                    
                    # Process the message
                    success = process_cornix_response(message_text, reply_id=reply_to_id)
                    
                    if success:
                        log_message("Successfully processed Cornix message")
                    else:
                        log_message("Could not match or process Cornix message")
                
            except Exception as e:
                log_message(f"Error handling Cornix message: {e}")
        
        # Add handler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cornix_message))
        
        # Start polling in background
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        log_message("Telegram listener for Cornix messages started")
        return application
        
    except Exception as e:
        log_message(f"Error setting up Telegram listener: {e}")
        return None
