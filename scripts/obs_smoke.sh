#!/usr/bin/env bash
set -euo pipefail

PROM=http://127.0.0.1:9090
LOKI=http://127.0.0.1:3100
GRAF=http://127.0.0.1:3000

echo "== health checks =="
curl -fsS "$PROM/-/ready"   >/dev/null && echo "Prometheus READY"
curl -fsS "$LOKI/ready"     >/dev/null && echo "Loki READY"
curl -fsS "$GRAF/login"     >/dev/null && echo "Grafana reachable"

echo "== Prometheus targets =="
curl -fsS "$PROM/api/v1/targets" | jq '.data.activeTargets[] | {job: .labels.job, up: .health, endpoint: .discoveredLabels.__address__}' | head

echo "== Loki: push + query roundtrip =="
NOW_NS=$(($(date +%s%N)))      # timestamp w ns
PAYLOAD=$(cat <<JSON
{
  "streams": [{
    "stream": {"job":"smoke","app":"logops","level":"INFO"},
    "values": [["$NOW_NS","obs-smoke: hello from test"]]
  }]
}
JSON
)
curl -fsS -X POST "$LOKI/loki/api/v1/push" -H 'Content-Type: application/json' --data-raw "$PAYLOAD" >/dev/null
sleep 1
Q='{job="smoke",app="logops"}'
curl -fsS --get "$LOKI/loki/api/v1/query" --data-urlencode "query=$Q" --data-urlencode "limit=5" | jq -r '.data.result[].values[] | @tsv' | head
echo "OK: Loki push+query"
