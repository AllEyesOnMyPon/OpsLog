#!/usr/bin/env bash
set -Eeuo pipefail

# === Ustawienia domyślne / adresy ===
export PYTHONPATH="${PYTHONPATH:-$PWD}"

ENTRYPOINT_URL="${ENTRYPOINT_URL:-http://127.0.0.1:8081/ingest}"
INGEST_URL_INTERNAL="${INGEST_URL_INTERNAL:-http://127.0.0.1:8080/v1/logs}"
CORE_URL_INTERNAL="${CORE_URL_INTERNAL:-http://127.0.0.1:8095/v1/logs}"

PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
LOKI_URL="${LOKI_URL:-http://127.0.0.1:3100}"

# Loki ma max_entries_limit=5000 (domyślnie) — trzymajmy się poniżej.
LOKI_LIMIT="${LOKI_LIMIT:-1000}"

# === Klucze HMAC (dla AuthGW) ===
export LOGOPS_API_KEY="${LOGOPS_API_KEY:-demo-pub-1}"
export LOGOPS_SECRET="${LOGOPS_SECRET:-demo-priv-1}"

# === Lista emiterów ===
if declare -p EMITTERS &>/dev/null; then
  _EMITTERS=("${EMITTERS[@]}")
else
  _EMITTERS=(json csv syslog minimal noise)
fi

SCENARIO_ID="sc-obs-$(date +%s)"
echo "SCENARIO_ID=$SCENARIO_ID"

# --- Preflight (opcjonalny): sprawdź, czy AuthGW żyje ---
if curl -fsS "http://127.0.0.1:8081/healthz" >/dev/null; then
  echo "[preflight] AuthGW /healthz OK"
else
  echo "[preflight] WARN: AuthGW /healthz niedostępne – kontynuuję mimo to"
fi

# --- EMITERY: każdy POST-uje na ENTRYPOINT (AuthGW 8081) ---
echo "== running emitters (scenario: $SCENARIO_ID) =="
for EM in "${_EMITTERS[@]}"; do
  echo "--> emitter=$EM"
  if ! python3 -m "emitters.$EM" \
       --ingest-url "$ENTRYPOINT_URL" \
       --scenario-id "$SCENARIO_ID" \
       --emitter "$EM" \
       --duration 8 --eps 4 --batch-size 1 \
       >/dev/null; then
    echo "WARN: emitter $EM – błąd wysyłki (pomijam)"
  fi
done
echo "== emitters finished =="

# --- Dodatkowy ping przez AuthGW (HMAC) ---
echo "--> authgw test"
AUTH_BODY='[{"ts":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","level":"INFO","msg":"auth smoke"}]'
if ! tools/hmac_curl.sh --url "$ENTRYPOINT_URL" --data "$AUTH_BODY" >/dev/null; then
  echo "WARN: AuthGW test nie przeszedł (sprawdź 8081 / nagłówki)"
fi

# --- krótka pauza na scrapery ---
sleep 3

# --- Prometheus (ingest rośnie + p95 z histogramu) ---
echo "== prometheus checks =="
START_S=$(($(date +%s)-120)); END_S=$(date +%s)

Q_INGEST='sum(increase(logops_ingested_total[1m]))'
Q_P95='histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[1m])))'

echo "--> increase(logops_ingested_total[1m])"
curl -fsS --get "$PROM_URL/api/v1/query_range" \
  --data-urlencode "query=$Q_INGEST" \
  --data-urlencode "start=$START_S" \
  --data-urlencode "end=$END_S" \
  --data-urlencode "step=10s" \
| jq '.data.result | map(.values[-1])'

echo "--> p95 (logops_batch_latency_seconds)"
curl -fsS --get "$PROM_URL/api/v1/query_range" \
  --data-urlencode "query=$Q_P95" \
  --data-urlencode "start=$START_S" \
  --data-urlencode "end=$END_S" \
  --data-urlencode "step=10s" \
| jq '.data.result | map(.values[-1])'

# --- Loki: najpierw wypisz dostępne serie (emittery) dla danego scenariusza ---
echo "== loki check =="

LOOKBACK_NS=$((10*60*1000000000))   # 10 min wstecz
START_NS=$(( $(date +%s%N) - LOOKBACK_NS ))
END_NS=$(date +%s%N)

echo "--> series (powinny zawierać emitery)"
START_NS=$(( $(date +%s%N) - 5*60*1000000000 ))
END_NS=$(date +%s%N)

curl -fsS -G "$LOKI_URL/loki/api/v1/series" \
  --data-urlencode "match[]={app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}" \
  --data-urlencode "start=$START_NS" \
  --data-urlencode "end=$END_NS" \
| jq -r 'try (.data | map(.emitter) | unique // []) catch []'

# Jeżeli pusto, spróbuj agregacji wektorowej (nie zależy od limitów entry)
echo "--> count_over_time by emitter (5m)"
curl -fsS -G "$LOKI_URL/loki/api/v1/query" \
  --data-urlencode "query=sum by (emitter) (count_over_time({app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}[5m]))" \
| jq -r '.data.result[]? | "\(.metric.emitter): \(.value[1])"' || true

# Dodatkowo (opcjonalnie): obejrzyjmy strumienie przez query_range z bezpiecznym limit
echo "--> query_range (limit=$LOKI_LIMIT, backward)"
HTTP=$(curl -sS -w '%{http_code}' -o /tmp/loki_resp.json -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode "query={app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}" \
  --data-urlencode "start=$START_NS" \
  --data-urlencode "end=$END_NS" \
  --data-urlencode "limit=$LOKI_LIMIT" \
  --data-urlencode "direction=backward" )
if [[ "$HTTP" == "200" ]]; then
  jq -r '.data.result | map(.stream.emitter) | unique' /tmp/loki_resp.json
else
  echo "query_range HTTP=$HTTP (pomiń — często to tylko limit/okno czasu)."
fi

echo "== done =="
