#!/usr/bin/env bash
set -euo pipefail

# żeby działało `python -m emitters.*`
export PYTHONPATH="${PYTHONPATH:-$PWD}"

# Domyślnie strzelamy w AuthGW (S2)
export ENTRYPOINT_URL="${ENTRYPOINT_URL:-http://127.0.0.1:8081/ingest}"

# Demo-klucze do HMAC (możesz nadpisać swoimi)
export LOGOPS_API_KEY="${LOGOPS_API_KEY:-demo-pub-1}"
export LOGOPS_SECRET="${LOGOPS_SECRET:-demo-priv-1}"

SCENARIO_ID="sc-s2-$(date +%s)"
echo "== S2 emitters smoke (scenario: $SCENARIO_ID) =="

run() {
  local name="$1"; shift || true
  local extra_args=("$@")
  echo "--> $name"
  set +e
  OUT=$(python -m "emitters.$name" \
        --scenario-id "$SCENARIO_ID" \
        --emitter "$name" \
        --duration 1 --eps 1 --batch-size 1 \
        "${extra_args[@]}" 2>&1)
  RC=$?
  set -e
  if [ $RC -eq 0 ]; then
    echo "PASS $name :: ${OUT#SC_STAT }"
  else
    echo "FAIL $name ($RC)"
    echo "$OUT"
  fi
}

# szybki health AuthGW (opcjonalnie)
curl -fsS http://127.0.0.1:8081/healthz >/dev/null || echo "WARN: /healthz AuthGW nie odpowiada"

run json
run csv
run syslog
run minimal
run noise --chaos 0.5

echo "== runs done =="

# Loki: pokaż jakie emitery dotarły dla tego scenariusza (opcjonalne)
if curl -fsS "http://127.0.0.1:3100/ready" >/dev/null 2>&1; then
  echo "== loki check (emitter labels) =="
  curl -Gs "http://127.0.0.1:3100/loki/api/v1/query" \
    --data-urlencode "query={app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}" \
  | jq '.data.result | map(.stream.emitter) | unique'
fi
