#!/bin/bash
# Deploy script for DND bot on the server
# Usage: ssh root@77.221.151.64 'bash -s' < deploy.sh

set -e

APP_DIR="/root/DND_solo"
SERVICE="dndbot"
DB_FILE="$APP_DIR/dnd_bot.db"

echo "=== DND Bot Deploy ==="

cd "$APP_DIR"

echo "[1/6] Stopping bot..."
systemctl stop "$SERVICE" 2>/dev/null || true
sleep 1

echo "[2/6] Pulling latest code..."
git fetch origin
git reset --hard origin/main

echo "[3/6] Installing dependencies..."
pip install -r requirements.txt -q

echo "[4/6] Removing old DB (fresh schema)..."
rm -f "$DB_FILE"

echo "[5/6] Starting bot..."
systemctl start "$SERVICE"
sleep 2

echo "[6/6] Verifying..."
if systemctl is-active --quiet "$SERVICE"; then
    VERSION=$(python3 -c "from bot.config import BOT_VERSION; print(BOT_VERSION)" 2>/dev/null || echo "unknown")
    echo "OK: Bot is running, version $VERSION"
else
    echo "FAIL: Bot did not start!"
    journalctl -u "$SERVICE" --no-pager -n 30
    exit 1
fi

echo "=== Deploy complete ==="
