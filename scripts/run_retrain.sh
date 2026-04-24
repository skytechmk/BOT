#!/bin/bash
# run_retrain.sh — wrapper for aladdin-retrain.service
# Stops telegram-member-monitor (shares spectre_user.session),
# runs retrain_advanced.py, then restarts it.

set -e
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
PYTHON=/root/miniconda3/bin/python3
WORKDIR=/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA

echo "[retrain] Stopping telegram-member-monitor..."
systemctl --user stop telegram-member-monitor.service 2>/dev/null || true
sleep 2

echo "[retrain] Starting retrain_advanced.py..."
cd "$WORKDIR"
"$PYTHON" "$WORKDIR/scripts/retrain_advanced.py" --n 60 --trials 40
EXIT_CODE=$?

echo "[retrain] Restarting telegram-member-monitor..."
systemctl --user start telegram-member-monitor.service 2>/dev/null || true

exit $EXIT_CODE
