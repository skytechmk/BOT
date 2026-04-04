#!/bin/bash
echo "🔄 EMERGENCY RESTART WITH FREE MODELS..."

# Kill any existing bot
pkill -f "python.*main\.py" 2>/dev/null

# Wait for cleanup
sleep 3

# Start bot with free models enforced
export FORCE_FREE_MODELS=true
export DISABLE_PAID_MODELS=true

echo "🚀 Starting bot with FREE MODELS ONLY..."
nohup python main.py > bot_output.log 2>&1 &

echo "✅ Bot restarted with free models only"
echo "📊 Check logs: tail -f bot_output.log"
