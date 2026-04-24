import json
import re
import asyncio

def robust_json_loads(s):
    """Attempt to parse JSON even if it is truncated or slightly malformed."""
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Try to fix truncated JSON by closing braces/brackets/quotes
        # 1. Fix unterminated string
        if s.count('"') % 2 != 0:
            s += '"'
        
        # 2. Add missing closing brackets/braces
        open_braces = s.count('{') - s.count('}')
        open_brackets = s.count('[') - s.count(']')
        s += '}' * max(0, open_braces)
        s += ']' * max(0, open_brackets)
        
        try:
            return json.loads(s)
        except:
            # Fallback to regex-based extraction if still failing
            try:
                # Try to find something that looks like an object
                match = re.search(r'\{.*\}', s, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except:
                pass
            raise # Re-raise if all recovery fails
import time
import uuid
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
from telegram.request import HTTPXRequest
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

# S.P.E.C.T.R.E. AI chat is handled natively by OpenClaw gateway (@nikola_s_bot).
# The /claw command (openclaw_bridge.py) provides direct CLI access for debugging.

# Larger connection pool to avoid "Pool timeout" errors under concurrent load
_tg_request = HTTPXRequest(connection_pool_size=30, connect_timeout=30.0, read_timeout=30.0)
bot = Bot(token=TELEGRAM_TOKEN, request=_tg_request) if TELEGRAM_TOKEN else None
closed_signals_bot = Bot(token=CLOSED_SIGNALS_TOKEN, request=HTTPXRequest(connection_pool_size=10, connect_timeout=30.0, read_timeout=30.0)) if CLOSED_SIGNALS_TOKEN else None
ops_bot = Bot(token=OPS_TELEGRAM_TOKEN, request=HTTPXRequest(connection_pool_size=10, connect_timeout=30.0, read_timeout=30.0)) if OPS_TELEGRAM_TOKEN else None


# SIGNAL_REGISTRY_FILE is imported from constants.py via shared_state

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
            'features': features,  # Store full technical context (key must match set_signal reader)
            'timestamp': time.time(),
            'status': 'SENT',
            'telegram_message_id': telegram_message_id,
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
    """Deprecated: SQLite auto-saves on write"""
    pass

def load_signal_registry():
    """Deprecated: Initialized via shared_state.py"""
    log_message("Signal Registry is now managed via SQLite DB")

def save_cornix_signals():
    """Deprecated — Cornix integration removed."""
    pass

def load_cornix_signals():
    """Deprecated — Cornix integration removed."""
    pass

def parse_cornix_message(message_text):
    """Deprecated — Cornix integration removed."""
    return {}

def process_cornix_response(message_text, reply_id=None):
    """Deprecated — Cornix integration removed."""
    return False

def learn_from_cornix_result(signal_id, signal_data, performance_data):
    """Deprecated — Cornix integration removed."""
    pass

def generate_cornix_learning_insights(signal_id, performance_data):
    """Deprecated — Cornix integration removed."""
    return []

def get_cornix_performance_report():
    """Deprecated — Cornix integration removed."""
    return "Cornix integration has been removed."

async def setup_telegram_listener():
    """Setup Telegram bot to listen for Ops commands and /claw agent."""
    async def claw_command(update, context):
        """Forces the prompt directly to the OpenClaw Agent, bypassing S.P.E.C.T.R.E. local API logic."""
        if str(update.message.chat_id) != OPS_TELEGRAM_CHAT_ID: return
        prompt = " ".join(context.args)
        if not prompt:
            await update.message.reply_text("Usage: /claw <your prompt for the OpenClaw agent>")
            return
            
        await update.message.reply_text("🦞 Querying OpenClaw agent (local CLI)...")
        from openclaw_bridge import ask_openclaw
        openclaw_resp = await ask_openclaw(prompt)
        await update.message.reply_text(f"🦞 {openclaw_resp}")

    async def explain_command(update, context):
        """[Phase 6 Ultra] Explain a past/open signal using stored ML Ultra
        payload (calibrated probs + conformal CI + SHAP top-3). Ops-only for now.

        Usage:
          /explain <signal_id_prefix>   (8+ chars — shown as 🆔 in signal msgs)
        """
        if str(update.message.chat_id) != OPS_TELEGRAM_CHAT_ID: return
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: `/explain <signal_id>` (8+ char prefix from the 🆔 line)",
                parse_mode='Markdown'
            )
            return
        sid_prefix = args[0].strip()
        if len(sid_prefix) < 6:
            await update.message.reply_text("Signal ID prefix must be ≥ 6 characters.")
            return

        # Lookup — SIGNAL_REGISTRY is SQLite-backed, iterate keys and match prefix
        try:
            matches = [sid for sid in SIGNAL_REGISTRY.keys() if sid.startswith(sid_prefix)]
        except Exception as e:
            await update.message.reply_text(f"Registry read failed: {e}")
            return

        if not matches:
            await update.message.reply_text(f"❌ No signal found with prefix `{sid_prefix}`.", parse_mode='Markdown')
            return
        if len(matches) > 1:
            await update.message.reply_text(
                f"⚠️ Ambiguous prefix — {len(matches)} matches. Use at least "
                f"{len(sid_prefix)+2} characters."
            )
            return

        sid  = matches[0]
        sig  = SIGNAL_REGISTRY[sid]
        feat = sig.get('features') or {}
        pair = sig.get('pair', '?')
        side = sig.get('signal', '?')

        # ── Extract Ultra payload ────────────────────────────────────
        prob_s = feat.get('ml_prob_short')
        prob_n = feat.get('ml_prob_neutral')
        prob_l = feat.get('ml_prob_long')
        ci_lo  = feat.get('ml_ci_low')
        ci_hi  = feat.get('ml_ci_high')
        pset   = feat.get('ml_prediction_set') or ''
        shap_s = feat.get('ml_shap_top') or ''
        explain_s = feat.get('ml_explain') or ''
        sqi_s  = feat.get('sqi_score', '?')
        sqi_g  = feat.get('sqi_grade', '?')
        ml_val = feat.get('sqi_ml_ensemble_val', '?')

        lines = [
            f"🧠 *Signal Explanation — {pair} {side}*",
            f"🆔 `{sid[:8]}`  |  SQI: *{sqi_s}/134 ({sqi_g})*",
            "",
            "*ML Ensemble (calibrated)*",
        ]
        if prob_l is not None and prob_s is not None and prob_n is not None:
            lines.append(
                f"  LONG {prob_l:.2f}  |  NEUTRAL {prob_n:.2f}  |  SHORT {prob_s:.2f}"
            )
        else:
            lines.append(f"  {ml_val}")
        if ci_lo is not None and ci_hi is not None:
            lines.append(f"  90% CI on top-class: \\[{ci_lo:.2f}, {ci_hi:.2f}]")
        if pset:
            lines.append(f"  Prediction set: {{{pset}}}")

        if shap_s or explain_s:
            lines.append("")
            lines.append("*Top drivers (SHAP Δprob)*")
            if shap_s:
                for item in shap_s.split(';'):
                    if ':' in item:
                        name, contrib = item.rsplit(':', 1)
                        arrow = '🟢' if contrib.startswith('+') else '🔴'
                        lines.append(f"  {arrow} `{name}` {contrib}")
            elif explain_s:
                lines.append(f"  {explain_s}")

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    try:
        from ai_auto_healer import setup_ops_listeners
        # Use primary token for unified listener if available, otherwise fallback
        effective_token = TELEGRAM_TOKEN or OPS_TELEGRAM_TOKEN
        if not effective_token:
            log_message("TELEGRAM_TOKEN not found - listener disabled")
            return None
            
        # Create application with custom request (larger pool)
        application = Application.builder().token(effective_token).request(_tg_request).build()
        
        # 1. Register Ops Commands
        await setup_ops_listeners(application)
        from telegram.ext import CommandHandler
        application.add_handler(CommandHandler("claw", claw_command))
        application.add_handler(CommandHandler("explain", explain_command))
        
        # Start polling in background
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        log_message("Telegram ops listener started")
        return application
        
    except Exception as e:
        log_message(f"Error setting up Telegram listener: {e}")
        return None
