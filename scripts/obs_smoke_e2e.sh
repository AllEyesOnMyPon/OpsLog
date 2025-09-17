#!/usr/bin/env bash
set -Eeuo pipefail

# ===== Config / Defaults =====
export PYTHONPATH="${PYTHONPATH:-$PWD}"

ENTRYPOINT_URL="${ENTRYPOINT_URL:-http://127.0.0.1:8081/ingest}"  # AuthGW POST endpoint
INGEST_URL="${INGEST_URL:-http://127.0.0.1:8080/v1/logs}"         # IngestGW
CORE_URL="${CORE_URL:-http://127.0.0.1:8095/v1/logs}"             # Core (echo/stub)
PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
LOKI_URL="${LOKI_URL:-http://127.0.0.1:3100}"

export LOGOPS_API_KEY="${LOGOPS_API_KEY:-demo-pub-1}"
export LOGOPS_SECRET="${LOGOPS_SECRET:-demo-priv-1}"

# Ruch generatorów – można nadpisać envami (np. DURATION=10 EPS=8 make e2e)
DURATION="${DURATION:-3}"
EPS="${EPS:-4}"
BATCH="${BATCH:-1}"

# Okna zapytań Prom
PROM_RATE_WINDOW="${PROM_RATE_WINDOW:-2m}"
P95_WINDOW="${P95_WINDOW:-2m}"

# Warm-up (sekundy) przed zapytaniami do Prom
WARMUP_SECS="${WARMUP_SECS:-2}"

# Emitery (możesz zawęzić: EMITTERS=(json syslog))
if declare -p EMITTERS &>/dev/null; then
  _EMITTERS=("${EMITTERS[@]}")
else
  _EMITTERS=(json csv syslog minimal noise)
fi

# POZWÓL NADPISAĆ z env, a jak brak – wygeneruj
SCENARIO_ID="${SCENARIO_ID:-sc-e2e-$(date +%s)}"

# Flags
QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then QUIET=1; shift; fi

# ===== Pretty helpers =====
BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; CYAN=$'\e[36m'; RED=$'\e[31m'; RESET=$'\e[0m'
say() { [[ $QUIET -eq 0 ]] && echo -e "$*"; }
ok()  { say "  ${GREEN}OK${RESET} $*"; }
warn(){ say "  ${YELLOW}WARN${RESET} $*"; }
fail(){ echo -e "  ${RED}ERR${RESET} $*" >&2; exit 1; }

hdr() { say "${BOLD}$*${RESET}"; }
stage(){ say "\n${BOLD}[STAGE]${RESET} $*"; }
tool(){  say "• ${DIM}[tool]${RESET} $*"; }
step(){  say "  → $*"; }

mkdir -p data/e2e data/reports

# ===== Intro / Map =====
say "${BOLD}LogOps E2E Smoke${RESET}  ${DIM}scenario_id=${SCENARIO_ID}${RESET}"
say "• Plan: emiters → AuthGW(HMAC+RL) → IngestGW(normalize+labels+NDJSON+metrics) → Core → Promtail → Loki → Prometheus"
say "• ENTRYPOINT: ${ENTRYPOINT_URL} | INGEST: ${INGEST_URL} | CORE: ${CORE_URL}"
say "• PROM: ${PROM_URL} | LOKI: ${LOKI_URL}"
say "• Load: DURATION=${DURATION}s, EPS=${EPS}, BATCH=${BATCH} | Prom windows: rate=${PROM_RATE_WINDOW}, p95=${P95_WINDOW}"

say "\n${CYAN}Komponenty i role:${RESET}"
step "8081 ${BOLD}AuthGW${RESET} – HMAC + rate-limit; proxy do IngestGW z zachowaniem nagłówków"
step "8080 ${BOLD}IngestGW${RESET} – parse/normalize, NDJSON sink, metryki, forward do Core"
step "Promtail → ${BOLD}Loki${RESET}"
step "Prometheus – metryki logops_*"

# ===== Preflight =====
stage "Preflight (health/ready + narzędzia)"
curl -fsS -X GET "${ENTRYPOINT_URL%/ingest}/healthz" >/dev/null && ok "AuthGW /healthz żyje" || fail "AuthGW /healthz nie działa"
curl -fsS -X GET "${INGEST_URL%/v1/logs}/metrics" >/dev/null && ok "IngestGW /metrics żyje" || fail "IngestGW /metrics niedostępne"
curl -fsS -X GET "${LOKI_URL}/ready" >/dev/null && ok "Loki /ready" || fail "Loki nie gotowy"
curl -fsS -X GET "${PROM_URL}/-/ready" >/dev/null && ok "Prometheus /-/ready" || fail "Prometheus nie gotowy"

# ===== Emitters → AuthGW =====
stage "Emitery → AuthGW (HMAC w klientach)"
for EM in "${_EMITTERS[@]}"; do
  tool "python -m emitters.${EM}  →  AuthGW /ingest (scenario_id=${SCENARIO_ID})"
  if python3 -m "emitters.${EM}" \
      --ingest-url "$ENTRYPOINT_URL" \
      --scenario-id "$SCENARIO_ID" \
      --emitter "$EM" \
      --duration "$DURATION" --eps "$EPS" --batch-size "$BATCH" \
      >/dev/null; then
    ok "emitter=${EM} poszedł"
  else
    warn "emitter=${EM} zwrócił błąd (pomijam)"
  fi
done

# Ręczne 3 formaty przez tools/hmac_curl.sh
stage "Ręczny HMAC → AuthGW (JSON/CSV/PLAIN)"
JSON_BODY='[{"ts":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","level":"INFO","msg":"e2e json","scenario_id":"'"$SCENARIO_ID"'"}]'
CSV_BODY=$'ts,level,msg\n'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"',INFO,e2e csv'
PLAIN_BODY=$'e2e plain INFO line'
tools/hmac_curl.sh --url "$ENTRYPOINT_URL" --data "$JSON_BODY" >/dev/null && ok "JSON accepted" || warn "JSON HMAC request failed"
tools/hmac_curl.sh --url "$ENTRYPOINT_URL" -H 'Content-Type: text/csv' --data "$CSV_BODY" >/dev/null && ok "CSV accepted" || warn "CSV HMAC request failed"
tools/hmac_curl.sh --url "$ENTRYPOINT_URL" -H 'Content-Type: text/plain' --data "$PLAIN_BODY" >/dev/null && ok "PLAIN accepted" || warn "PLAIN HMAC request failed"

# NDJSON sink check
stage "NDJSON sink (Promtail source → Loki)"
TODAY=$(date -u +%Y%m%d)
COUNT=$(jq -r "select(.scenario_id==\"$SCENARIO_ID\") | .emitter" "data/ingest/${TODAY}.ndjson" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
[[ "${COUNT:-0}" -gt 0 ]] && ok "NDJSON zawiera wpisy dla ${SCENARIO_ID} (count=${COUNT})" || warn "Brak wpisów NDJSON dla ${SCENARIO_ID}"

# Warm-up pod histogramy
sleep "$WARMUP_SECS"

# Loki – series + query
stage "Loki (series + query)"
START_NS=$(( $(date +%s%N) - 10*60*1000000000 ))
END_NS=$(date +%s%N)
curl -fsS -G "$LOKI_URL/loki/api/v1/series" \
  --data-urlencode "match[]={app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}" \
  --data-urlencode "start=$START_NS" --data-urlencode "end=$END_NS" >/dev/null && ok "/series OK" || warn "/series pusto"

curl -fsS -G "$LOKI_URL/loki/api/v1/query" \
  --data-urlencode "query=sum(count_over_time({app=\"logops\",source=\"ingest\",scenario_id=\"$SCENARIO_ID\"}[$PROM_RATE_WINDOW]))" >/dev/null \
  && ok "/query count_over_time OK" || warn "Loki /query puste"

# Prometheus – szybkie spot-checks
stage "Prometheus (ingested/accepted + p95 latency)"
curl -fsS -G "$PROM_URL/api/v1/query" \
  --data-urlencode "query=sum by (emitter) (increase(logops_ingested_total[$PROM_RATE_WINDOW]))" >/dev/null && ok "increase(ingested) OK" || warn "ingested empty"

curl -fsS -G "$PROM_URL/api/v1/query" \
  --data-urlencode "query=histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[$P95_WINDOW])))" >/dev/null && ok "p95 OK" || warn "p95 empty"

# Zapisz scenario_id do artefaktu (na potrzeby make report)
echo "$SCENARIO_ID" > data/e2e/last_scenario_id
ok "Zapisano scenario_id do data/e2e/last_scenario_id"

# ===== Summary =====
stage "Podsumowanie"
say "Scenario: ${SCENARIO_ID}"
say "NDJSON: data/ingest/${TODAY}.ndjson"
ok "E2E smoke zakończony"
