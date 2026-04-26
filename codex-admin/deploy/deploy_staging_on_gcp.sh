#!/usr/bin/env bash
set -euo pipefail

# Run on the Google server as user apple.
# This deploys the new Codex Admin/API project first on 8092 for smoke testing.

REPO_URL="${REPO_URL:-https://github.com/guokun666/ChatGPT.git}"
BRANCH="${BRANCH:-dev}"
APP_DIR="${APP_DIR:-/home/apple/codex-admin}"
LEGACY_DIR="${LEGACY_DIR:-/home/apple/codex-multi-proxy}"
STAGING_PORT="${STAGING_PORT:-8092}"
PROD_PORT="${PROD_PORT:-8091}"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  cd "$APP_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR/codex-admin"
mkdir -p data

cat > docker-compose.staging.yml <<YAML
services:
  codex-admin:
    build: .
    container_name: codex-admin-new
    restart: unless-stopped
    environment:
      CODEX_ADMIN_DB: /app/data/codex-admin.sqlite3
      CODEX_ADMIN_MODELS_CACHE: /app/data/models_cache.json
      PORT: 8091
    ports:
      - "${STAGING_PORT}:8091"
    volumes:
      - ./data:/app/data
    healthcheck:
      test: ["CMD", "python", "-c", "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8091/api/health')); raise SystemExit(0 if data.get('status') == 'ok' else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
YAML

sudo -n docker compose -f docker-compose.staging.yml up -d --build
sleep 5
curl -fsS "http://127.0.0.1:${STAGING_PORT}/api/health"

PYTHONPATH="$APP_DIR/codex-admin/backend" \
CODEX_ADMIN_DB="$APP_DIR/codex-admin/data/codex-admin.sqlite3" \
LEGACY_ACCOUNTS_FILE="$LEGACY_DIR/data/accounts.json" \
python3 "$APP_DIR/codex-admin/deploy/migrate_legacy_accounts.py"

# Restart staging after migration so health/account counts reflect latest DB.
sudo -n docker compose -f docker-compose.staging.yml restart
sleep 3
curl -fsS "http://127.0.0.1:${STAGING_PORT}/api/health"

cat <<'NEXT'

Staging is up. Smoke test examples on the server:

  KEY=$(cat /home/apple/codex-admin/codex-admin/data/model-family-codex-api-key.txt)
  curl -sS -H "Authorization: Bearer $KEY" http://127.0.0.1:8092/v1/models | python3 -m json.tool

If staging is healthy, run:

  bash /home/apple/codex-admin/codex-admin/deploy/switch_to_prod.sh

NEXT
