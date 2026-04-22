#!/usr/bin/env bash
set -euo pipefail

# =====================================================
# DND Bot — deploy script for akspavel.ru
# Run on the server: bash deploy.sh
# =====================================================

APP_DIR="/opt/dnd_bot"
NGINX_CONF="/etc/nginx/sites-enabled/akspavel.ru"
SERVICE_NAME="dnd-bot"

echo "=== 1. Creating app directory ==="
mkdir -p "$APP_DIR"

echo "=== 2. Copying project files ==="
# This script assumes the DND project has already been uploaded
# to /opt/dnd_bot (via scp, rsync, or git clone).
# If you're running this manually after uploading:
#   scp -r ./* root@77.221.151.64:/opt/dnd_bot/

echo "=== 3. Installing Python deps ==="
cd "$APP_DIR"
pip3 install --upgrade pip
pip3 install -r requirements.txt 2>/dev/null || pip3 install \
  aiogram httpx pydantic sqlalchemy aiosqlite uvicorn fastapi python-dotenv

echo "=== 4. Adding nginx location blocks ==="
# Detect which config file contains the akspavel.ru server block
NGINX_FILE=""
for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
  [ -f "$f" ] || continue
  if grep -q "akspavel.ru" "$f" 2>/dev/null; then
    NGINX_FILE="$f"
    break
  fi
done

if [ -z "$NGINX_FILE" ]; then
  echo "ERROR: Could not find nginx config for akspavel.ru"
  echo "Please add the location blocks manually (see below)."
else
  echo "Found nginx config: $NGINX_FILE"

  if grep -q "location /dnd_bot/" "$NGINX_FILE" 2>/dev/null; then
    echo "  /dnd_bot/ location already exists, skipping."
  else
    echo "  Adding /dnd_bot/ and /api/ proxy locations..."
    # Insert before the last closing brace of the server block
    # We create a snippet and insert it
    cat > /tmp/dnd_nginx_snippet.conf <<'SNIPPET'

    # --- DND Bot Mini App (static files) ---
    location /dnd_bot/ {
        proxy_pass http://127.0.0.1:8080/dnd_bot/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # --- DND Bot API ---
    location /api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
SNIPPET

    # Backup original config
    cp "$NGINX_FILE" "${NGINX_FILE}.bak.$(date +%s)"

    # Insert snippet before last closing brace
    # Find line number of last }
    LAST_BRACE=$(grep -n "}" "$NGINX_FILE" | tail -1 | cut -d: -f1)
    if [ -n "$LAST_BRACE" ]; then
      sed -i "${LAST_BRACE}i\\
$(cat /tmp/dnd_nginx_snippet.conf | sed 's/$/\\/' | sed '$ s/\\$//')
" "$NGINX_FILE"
      echo "  Inserted location blocks."
    else
      echo "  WARNING: Could not find closing brace. Add manually."
      cat /tmp/dnd_nginx_snippet.conf
    fi
  fi
fi

echo "=== 5. Testing nginx config ==="
nginx -t

echo "=== 6. Reloading nginx ==="
systemctl reload nginx

echo "=== 7. Creating systemd service ==="
cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=DND Telegram Bot + API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/python3 -m bot.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "=== 8. Starting bot service ==="
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

echo ""
echo "=== DONE ==="
echo "Mini-app:  https://akspavel.ru/dnd_bot/"
echo "API:       https://akspavel.ru/api/character/{user_id}"
echo "Bot logs:  journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "Check status: systemctl status ${SERVICE_NAME}"
