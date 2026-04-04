import os
import sys
import traceback
import json
import time
import ast
import re
from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from utils_logger import log_message
from constants import *
from shared_state import OPENROUTER_INTEL, SIGNAL_REGISTRY
from datetime import datetime

class AutoHealer:
    """Institutional-grade Self-Healing & Diagnostic Engine"""
    def __init__(self):
        self.ops_token = os.getenv('OPS_TELEGRAM_TOKEN')
        self.ops_chat_id = os.getenv('OPS_TELEGRAM_CHAT_ID')
        self.ops_bot = Bot(token=self.ops_token) if self.ops_token else None
        self.proposed_fixes = {} # bug_id -> fix_data
        self.fixes_file = 'proposed_fixes.json'
        self.load_fixes()
        self.SAFE_FILES = [
            'main.py',                # Core orchestration
            'data_fetcher.py', 
            'telegram_handler.py', 
            'performance_tracker.py', 
            'signal_generator.py', # Logic only, not execution core
            'technical_indicators.py',
            'trading_utilities.py',  # Monte Carlo and utilities
            'shared_state.py'        # Configuration and state
        ]
        
    def load_fixes(self):
        if os.path.exists(self.fixes_file):
            try:
                with open(self.fixes_file, 'r') as f:
                    self.proposed_fixes = json.load(f)
            except Exception as e:
                log_message(f"Error loading fixes: {e}")

    def save_fixes(self):
        try:
            with open(self.fixes_file, 'w') as f:
                json.dump(self.proposed_fixes, f, indent=2)
        except Exception as e:
            log_message(f"Error saving fixes: {e}")

    def save_suggestion_to_file(self, bug_id, fix_data):
        """Save AI strategy suggestion to a markdown file in /SUGGESTIONS"""
        try:
            os.makedirs('SUGGESTIONS', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_label = fix_data.get('file', 'general').replace('/', '_').replace('.py', '')
            filename = f"SUGGESTIONS/{bug_id}_{timestamp}_{file_label}.md"
            
            content = f"""# 🧠 Aladdin AI Suggestion: {bug_id}
**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Type:** {fix_data.get('type', 'ERROR_FIX')}
**Target File:** `{fix_data.get('file', 'N/A')}`

## 📝 Institutional Analysis
{fix_data.get('explanation', 'No explanation provided.')}

## 🛠 Proposed Code Change
```python
{fix_data.get('new_code', '# No code provided')}
```

## 🚀 Implementation Logic
This change was generated automatically in response to a {'system error' if fix_data.get('type') != 'STRATEGY' else 'Stop Loss event'}. 
To apply this patch immediately, use the command:
`/apply_logic {bug_id}`
"""
            with open(filename, 'w') as f:
                f.write(content)
            log_message(f"✅ AI Suggestion saved to: {filename}")
            return filename
        except Exception as e:
            log_message(f"Error saving suggestion file: {e}")
            return None
        
    async def report_error(self, error_report):
        """Send detailed crash report to Ops Channel"""
        if not self.ops_bot or not self.ops_chat_id: return
        
        msg = (f"🚨 **CRASH DETECTED**\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"❌ **Error:** `{error_report['type']}: {error_report['value']}`\n"
               f"📂 **File:** `{error_report['file']}` (Line {error_report['line']})\n"
               f"\n🧠 **AI Analysis Incoming...**")
        
        try:
            await self.ops_bot.send_message(chat_id=self.ops_chat_id, text=msg, parse_mode='Markdown')
        except Exception as e:
            log_message(f"Error sending Ops report: {e}")

    async def analyze_and_suggest_fix(self, error_report):
        """Consult OpenRouter for a fix and present it to the Operator"""
        try:
            # Prepare context for AI
            with open(error_report['file'], 'r') as f:
                code_context = f.readlines()
            
            # Get surrounding lines
            start = max(0, error_report['line'] - 20)
            end = min(len(code_context), error_report['line'] + 20)
            snippet = "".join(code_context[start:end])
            
            prompt = (f"SYSTEM: You are a Senior Python Expert for a High-Frequency Trading Bot.\n"
                      f"TASK: Fix the following error in the provided code snippet.\n"
                      f"ERROR: {error_report['type']}: {error_report['value']}\n"
                      f"FILE: {error_report['file']}\n"
                      f"TRACEBACK: {error_report['traceback']}\n\n"
                      f"CODE SNIPPET (Lines {start+1}-{end}):\n{snippet}\n\n"
                      f"RULES:\n"
                      f"1. Return ONLY a JSON object with: 'explanation', 'file', 'start_line', 'end_line', 'new_code'.\n"
                      f"2. Ensure 'new_code' is valid Python and fixes the root cause.\n"
                      f"3. Do not include markdown code blocks, return ONLY the raw JSON.")
            
            ai_response = OPENROUTER_INTEL.query_ai(prompt) # Uses default model from .env
            
            # Clean AI response for JSON parsing
            clean_json = re.sub(r'```json|```', '', ai_response).strip()
            fix_data = json.loads(clean_json)
            
            bug_id = f"BUG-{int(time.time() % 10000)}"
            self.proposed_fixes[bug_id] = fix_data
            self.save_fixes()
            self.save_suggestion_to_file(bug_id, fix_data)
            
            msg = (f"🧠 **AI DIAGNOSIS ({bug_id})**\n"
                   f"━━━━━━━━━━━━━━━━━━━━\n"
                   f"📝 **Analysis:** {fix_data['explanation']}\n\n"
                   f"🛠️ **Proposed Change:**\n"
                   f"```python\n"
                   f"{fix_data['new_code']}\n"
                   f"```\n"
                   f"✅ `/apply_logic {bug_id}` to patch\n"
                   f"❌ `/reject {bug_id}` to ignore")
            
            await self.ops_bot.send_message(chat_id=self.ops_chat_id, text=msg, parse_mode='Markdown')
            
        except Exception as e:
            log_message(f"Error in AI diagnosis: {e}")

    async def perform_post_mortem(self, signal_id):
        """Analyze a Stop Loss event and suggest algorithm improvements"""
        try:
            signal_data = SIGNAL_REGISTRY.get(signal_id)
            if not signal_data: return
            
            pair = signal_data['pair']
            features = signal_data.get('features_snapshot', {})
            
            prompt = (f"SYSTEM: Institutional Trading Post-Mortem.\n"
                      f"EVENT: Stop Loss achieved for {pair} {signal_data['signal']}.\n"
                      f"CONTEXT: The trade failed. Why did our technical indicators fail here?\n"
                      f"DATA SNAPSHOT: {json.dumps(features, indent=2)}\n\n"
                      f"TASK: Recommend a logic change to prevent this specific failure pattern in the future.\n"
                      f"Return JSON with 'explanation' and 'strategy_patch_code' for signal_generator.py.")
            
            ai_response = OPENROUTER_INTEL.query_ai(prompt)
            clean_json = re.sub(r'```json|```', '', ai_response).strip()
            
            bug_id = f"STRAT-{int(time.time() % 10000)}"
            try:
                fix_data = json.loads(clean_json)
                self.proposed_fixes[bug_id] = {
                    'file': 'signal_generator.py',
                    'explanation': fix_data.get('explanation', 'No explanation provided.'),
                    'new_code': fix_data.get('strategy_patch_code', '# No code provided'),
                    'type': 'STRATEGY'
                }
                self.save_fixes()
                self.save_suggestion_to_file(bug_id, self.proposed_fixes[bug_id])
                
                msg = (f"📉 **STOP LOSS POST-MORTEM ({bug_id})**\n"
                       f"💰 **Pair:** {pair}\n"
                       f"🧠 **AI Insight:** {fix_data.get('explanation', 'No explanation provided.')}\n\n"
                       f"🎯 **Strategy Refinement:**\n"
                       f"```python\n"
                       f"{fix_data.get('strategy_patch_code', '')}\n"
                       f"```\n"
                       f"🚀 `/apply_logic {bug_id}` to enhance strategy.")
            except Exception as json_e:
                log_message(f"JSON parsing failed for AI response, sending raw format: {json_e}")
                self.proposed_fixes[bug_id] = {
                    'file': 'signal_generator.py',
                    'explanation': 'Raw text fallback, cannot be automatically applied.',
                    'new_code': '# JSON parse failed\n' + ai_response,
                    'type': 'STRATEGY_RAW'
                }
                self.save_fixes()
                msg = (f"📉 **STOP LOSS POST-MORTEM ({bug_id})**\n"
                       f"💰 **Pair:** {pair}\n"
                       f"⚠️ **Note:** AI response was not perfectly formatted JSON.\n\n"
                       f"🧠 **AI Insight & Proposed Strategy (Raw):**\n"
                       f"{ai_response[:3000]}") # Truncate if too long for Telegram
            
            await self.ops_bot.send_message(chat_id=self.ops_chat_id, text=msg, parse_mode='Markdown')
            
        except Exception as e:
            log_message(f"Error in Post-Mortem Analysis: {e}")

    def apply_patch(self, bug_id):
        """Apply a validated code patch to the codebase"""
        try:
            if bug_id not in self.proposed_fixes: return "Invalid Bug ID"
            fix = self.proposed_fixes[bug_id]
            if fix.get('type') == 'STRATEGY_RAW':
                return f"ABORT: Fix {bug_id} was raw text and cannot be automatically applied. Please review it manually."
            file_path = fix['file']
            
            # Security Check
            if os.path.basename(file_path) not in self.SAFE_FILES:
                return "CRITICAL: Target file outside of Safe Zone!"
            
            # AST Validation of new code
            try:
                ast.parse(fix['new_code'])
            except SyntaxError as e:
                return f"ABORT: AI code has syntax errors: {e}"
            
            # Simple replacement logic (can be enhanced with more precise line detection)
            # For simplicity in this version, it targets the specific lines provided by AI
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            # lines is 0-indexed, AI returns 1-indexed
            start = fix['start_line'] - 1
            end = fix['end_line']
            
            # Note: This is a placeholder for a more robust diff/patch mechanism
            # In a production environment, we'd use line markers or specific search patterns
            # Here we trust the specific line range + manual verification via /apply_logic
            
            # Update file with the AI-provided fix
            lines[start:end] = [fix['new_code'] + '\n']
            with open(file_path, 'w') as f:
                f.writelines(lines)
            
            del self.proposed_fixes[bug_id]
            self.save_fixes()
            return f"✅ Patch {bug_id} applied successfully to {file_path} (lines {start+1}-{end})"
            
        except Exception as e:
            return f"Error applying patch: {e}"

# Singleton Instance
AUTO_HEAL_ENGINE = AutoHealer()

def exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception hook to trigger the healer"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Format detailed error
    error_report = {
        'type': exc_type.__name__,
        'value': str(exc_value),
        'file': traceback.extract_tb(exc_traceback)[-1].filename,
        'line': traceback.extract_tb(exc_traceback)[-1].lineno,
        'traceback': "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    }
    
    log_message(f"🚨 CRITICAL FAILURE: {error_report['type']} in {error_report['file']}")
    
    # Run reporting in new event loop if necessary, or integrated with main
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(AUTO_HEAL_ENGINE.report_error(error_report))
        loop.create_task(AUTO_HEAL_ENGINE.analyze_and_suggest_fix(error_report))
    except RuntimeError:
        asyncio.run(AUTO_HEAL_ENGINE.report_error(error_report))
        asyncio.run(AUTO_HEAL_ENGINE.analyze_and_suggest_fix(error_report))
    except Exception as e:
        print(f"Failed to trigger auto-healer: {e}")

async def setup_ops_listeners(application):
    """Setup Telegram Command Handlers for the Ops Channel"""
    async def apply_cmd(update, context):
        if str(update.message.chat_id) != AUTO_HEAL_ENGINE.ops_chat_id: return
        if not context.args: return
        
        bug_id = context.args[0]
        result = AUTO_HEAL_ENGINE.apply_patch(bug_id)
        await update.message.reply_text(f"🛠️ **Update Log:** {result}")
        
    async def reject_cmd(update, context):
        if str(update.message.chat_id) != AUTO_HEAL_ENGINE.ops_chat_id: return
        if not context.args: return
        bug_id = context.args[0]
        if bug_id in AUTO_HEAL_ENGINE.proposed_fixes:
            del AUTO_HEAL_ENGINE.proposed_fixes[bug_id]
            AUTO_HEAL_ENGINE.save_fixes()
            await update.message.reply_text(f"❌ Fix {bug_id} rejected and cleared.")

    application.add_handler(CommandHandler("apply_logic", apply_cmd))
    application.add_handler(CommandHandler("reject", reject_cmd))
    log_message("Ops Command Handlers active on the secure channel.")
