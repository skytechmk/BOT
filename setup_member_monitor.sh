#!/bin/bash
# Setup script for Telegram Member Monitor

set -e

echo "🤖 Telegram Member Monitor Setup"
echo "=================================="
echo ""

# Check if config is set
CONFIG_FILE="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/telethon_config.env"
if grep -q "your_api_id_here" "$CONFIG_FILE" || grep -q "your_api_hash_here" "$CONFIG_FILE"; then
    echo "❌ API credentials not set!"
    echo ""
    echo "You need to get API credentials from Telegram:"
    echo "1. Go to https://my.telegram.org/apps"
    echo "2. Log in with your phone number"
    echo "3. Create a new app (any name works)"
    echo "4. Copy the api_id (numbers only) and api_hash (hex string)"
    echo ""
    echo "Then edit: $CONFIG_FILE"
    echo "Replace:"
    echo "  API_ID=your_api_id_here"
    echo "  API_HASH=your_api_hash_here"
    echo ""
    exit 1
fi

echo "✅ Config file looks valid"
echo ""

# Create data directory
mkdir -p /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/telethon_data

echo "📱 First-time setup: You need to authenticate with Telegram"
echo "   This will create a session file for future runs."
echo ""
echo "Running: python3 member_monitor.py (for 5 seconds to test auth)..."
echo ""

# Try to run once to trigger auth
timeout 10 /root/miniconda3/bin/python3 /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/member_monitor.py || true

echo ""
echo "If you see 'Authorization required' above, you need to:"
echo "1. Run: python3 member_monitor.py manually"
echo "2. Enter your phone number when prompted"
echo "3. Enter the verification code sent to Telegram"
echo "4. (Optional) Enter 2FA password if you have it"
echo ""
echo "Once authenticated, start the service:"
echo "  systemctl --user daemon-reload"
echo "  systemctl --user enable telegram-member-monitor"
echo "  systemctl --user start telegram-member-monitor"
echo ""
echo "Check status:"
echo "  systemctl --user status telegram-member-monitor"
echo "  tail -f /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/telethon_data/monitor.log"
