#!/usr/bin/env bash
set -euo pipefail

# Run on the model-family Google server after switch_to_prod.sh passes.
# It updates channel 86 to point at the new Codex Admin/API service and keeps old Codex channels out of primary groups.

APP_DIR="${APP_DIR:-/home/apple/codex-admin}"
KEY_FILE="${KEY_FILE:-$APP_DIR/codex-admin/data/model-family-codex-api-key.txt}"
CHANNEL_ID="${CHANNEL_ID:-86}"
BASE_URL="${BASE_URL:-http://codex-api.4yailab.com}"
MODELS="${MODELS:-gpt-5.4,gpt-5.2-codex,gpt-5.1-codex-max,gpt-5.4-mini,gpt-5.3-codex,gpt-5.3-codex-spark,gpt-5.2,gpt-5.1-codex-mini}"
CHANNEL_GROUPS="${CHANNEL_GROUPS:-vip,vip-2,kevin-self}"
OLD_CODEX_CHANNELS="${OLD_CODEX_CHANNELS:-16,37,80}"

if [ ! -s "$KEY_FILE" ]; then
  echo "missing key file: $KEY_FILE" >&2
  exit 1
fi
API_KEY=$(cat "$KEY_FILE")

SQL=$(cat <<SQL_EOF
BEGIN;
UPDATE channels
SET status = 1,
    auto_ban = 0,
    priority = 100,
    base_url = '$BASE_URL',
    key = '$API_KEY',
    models = '$MODELS',
    "group" = '$CHANNEL_GROUPS',
    tag = 'codex'
WHERE id = $CHANNEL_ID;

UPDATE channels
SET "group" = 'sssvip,boss,codex'
WHERE id IN ($OLD_CODEX_CHANNELS);

DELETE FROM abilities WHERE channel_id = $CHANNEL_ID;
INSERT INTO abilities ("group", model, channel_id, enabled, priority, weight, tag)
SELECT g, m, $CHANNEL_ID, true, 100, 0, 'codex'
FROM regexp_split_to_table('$CHANNEL_GROUPS', ',') AS g
CROSS JOIN regexp_split_to_table('$MODELS', ',') AS m;

COMMIT;

SELECT id,status,auto_ban,priority,"group",models,base_url,tag
FROM channels
WHERE id IN ($OLD_CODEX_CHANNELS,$CHANNEL_ID)
ORDER BY id;
SQL_EOF
)

printf '%s\n' "$SQL" | sudo -n docker exec -i model-family-postgres psql -v ON_ERROR_STOP=1 -U mf_service -d model_family -P pager=off

cat <<'NEXT'

Next verification:
1. Use admin001 token_id=75 to call https://www.model-family.com/v1/chat/completions with model gpt-5.4.
2. Query logs where token_id=75 and model_name='gpt-5.4' after the probe.
3. Confirm channel_id=86.

NEXT
