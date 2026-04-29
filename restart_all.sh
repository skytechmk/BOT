#!/bin/bash

echo "🔄 Restarting System Services (requires sudo)..."
sudo systemctl restart anunnaki-dashboard
sudo systemctl restart anunnaki-bot

echo "🔄 Restarting User Services..."
systemctl --user restart mcp-aladdin
systemctl --user restart openclaw-gateway

echo "✅ All services restarted successfully!"
