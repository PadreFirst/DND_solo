#!/bin/bash
# One-time setup: install cloudflared and create a systemd service for a quick tunnel.
# After running, check: journalctl -u cloudflared -n 20 | grep "https://"
# Then set WEBAPP_URL in .env to the printed URL.

set -e

echo "=== Installing cloudflared ==="
if ! command -v cloudflared &>/dev/null; then
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
    dpkg -i /tmp/cloudflared.deb
    rm -f /tmp/cloudflared.deb
fi
echo "cloudflared version: $(cloudflared --version)"

echo "=== Creating systemd service ==="
cat > /etc/systemd/system/cloudflared.service <<'UNIT'
[Unit]
Description=Cloudflare Tunnel for DND Bot Mini App
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:8080 --no-autoupdate
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable cloudflared
systemctl restart cloudflared

sleep 5
echo "=== Tunnel URL (set this as WEBAPP_URL in .env) ==="
journalctl -u cloudflared -n 30 --no-pager | grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1

echo "=== Done ==="
