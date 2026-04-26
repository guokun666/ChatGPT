#!/usr/bin/env bash
set -euo pipefail

# Run on the Google server after staging smoke tests pass.
# This stops the legacy codex-multi-proxy container on 8091 and starts Codex Admin/API on 8091.

APP_DIR="${APP_DIR:-/home/apple/codex-admin}"
cd "$APP_DIR/codex-admin"

# Preserve legacy directory and data. Stop only the legacy container/compose service.
if sudo -n docker ps --format '{{.Names}}' | grep -qx 'codex-multi-proxy'; then
  (cd /home/apple/codex-multi-proxy && sudo -n docker compose down) || sudo -n docker stop codex-multi-proxy
fi

sudo -n docker compose up -d --build
sleep 5
sudo -n docker compose ps
curl -fsS http://127.0.0.1:8091/api/health

KEY_FILE="$APP_DIR/codex-admin/data/model-family-codex-api-key.txt"
if [ ! -s "$KEY_FILE" ]; then
  echo "missing API key file: $KEY_FILE" >&2
  exit 1
fi

echo "Production Codex Admin/API is listening on 127.0.0.1:8091. API key file: $KEY_FILE"
