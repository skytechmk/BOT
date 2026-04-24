#!/bin/bash
# Master restart script for Aladdin Trading Bot system

echo "🔄 RESTARTING ALL ALADDIN PROCESSES AND SCRIPTS..."

# 1. Restart managed systemd services
echo "📦 Restarting systemd user services..."
systemctl --user restart openclaw-gateway
systemctl --user restart openclaw-forwarder
systemctl --user restart mcp-aladdin
systemctl --user restart telegram-service

# 2. Kill existing standalone python processes
echo "🧹 Killing existing standalone processes..."
pkill -f "python.*main\.py"
pkill -f "python.*telegram_service\.py"
pkill -f "python.*openrouter_rotator\.py"
pkill -f "python.*free_model_rotator\.py"
pkill -f "python.*monitor_free_models\.py"
pkill -f "python.*dashboard/app\.py"
pkill -f "python.*dashboard.*app\.py"

# Wait for cleanup
sleep 3

# 3. Restart standalone scripts in background
echo "🚀 Starting standalone scripts..."

# Set environment variables for free models if needed (as seen in restart_with_free_models.sh)
export FORCE_FREE_MODELS=true
export DISABLE_PAID_MODELS=true

# Start services
nohup /root/miniconda3/bin/python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.py > /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.log 2>&1 &
echo "   ✅ Started main.py"

echo "   ✅ telegram_service.py managed by systemd (telegram-service.service)"

nohup /root/miniconda3/bin/python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py > /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/dashboard.log 2>&1 &
echo "   ✅ Started dashboard/app.py"

# Check if openrouter_rotator exists, otherwise use free_model_rotator or monitor_free_models
if [ -f "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/openrouter_rotator.py" ]; then
    nohup /root/miniconda3/bin/python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/openrouter_rotator.py > /tmp/rotator.log 2>&1 &
    echo "   ✅ Started openrouter_rotator.py"
elif [ -f "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/free_model_rotator.py" ]; then
    nohup /root/miniconda3/bin/python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/free_model_rotator.py > /tmp/rotator.log 2>&1 &
    echo "   ✅ Started free_model_rotator.py"
fi

echo ""
echo "📊 Current running python processes:"
ps aux | grep -E "main\.py|telegram_service\.py|rotator" | grep -v grep

echo ""
echo "✅ All processes restarted."
