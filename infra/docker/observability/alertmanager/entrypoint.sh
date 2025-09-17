#!/bin/sh
set -euo pipefail

# Wymagany podstawowy webhook:
if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
  echo "[entrypoint] SLACK_WEBHOOK_URL is required (set in .env next to docker-compose.yml)" >&2
  exit 1
fi

# Domyślnie LOGOPS = ten sam webhook, jeśli nie podano osobnego:
: "${SLACK_WEBHOOK_URL_LOGOPS:=${SLACK_WEBHOOK_URL}}"

echo "[entrypoint] Rendering /tmp/alertmanager.yml via envsubst…"
# Uwaga: brak listy zmiennych -> envsubst podmieni wszystkie obecne w środowisku
envsubst < /etc/alertmanager/alertmanager.tmpl.yml > /tmp/alertmanager.yml

echo "[entrypoint] Starting Alertmanager…"
exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --cluster.advertise-address=0.0.0.0:9094 \
  --log.level=debug
