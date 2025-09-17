#!/usr/bin/env bash
set -euo pipefail

AUTHGW=http://127.0.0.1:8081
INGEST=http://127.0.0.1:8080
CORE=http://127.0.0.1:8095

EMITTER="json"
SCENARIO="sc-e2e-$(date +%s)"
BODY=/tmp/e2e_body.json
HDRS_AUTH_RAW=/tmp/e2e_hdrs.auth.raw
HDRS_AUTH_TXT=/tmp/e2e_hdrs.auth.txt

echo '[{"ts":"2025-09-04T10:00:00Z","level":"INFO","msg":"E2E test"}]' > "$BODY"

echo "== sanity: ports =="
ss -ltnp | egrep ':8080|:8081|:8095' || true
echo

echo "== health =="
curl -fsS "$AUTHGW/healthz" && echo
# jeśli masz /healthz także na Ingest/Core, odkomentuj:
# curl -fsS "$INGEST/healthz" && echo
# curl -fsS "$CORE/healthz" && echo
echo

echo "== sign HMAC for AuthGW =="
python tools/sign_hmac.py "$LOGOPS_API_KEY" "$LOGOPS_SECRET" POST "$AUTHGW/ingest" \
  --body-file "$BODY" --nonce --one-per-line > "$HDRS_AUTH_RAW"

# zamień output signera na listę -H "Header: value"
sed -E 's/ -H "/\n-H "/g' "$HDRS_AUTH_RAW" \
| sed -n 's/^-H "\(.*\)"$/\1/p' > "$HDRS_AUTH_TXT"

# zbuduj tablicę dla curl
HDRS=(); while IFS= read -r l; do HDRS+=(-H "$l"); done < "$HDRS_AUTH_TXT"

echo "== E2E hop #1: client -> 8081 (AuthGW) -> 8080 (IngestGW) =="
curl -fsSi -X POST "$AUTHGW/ingest" \
  -H 'Content-Type: application/json' \
  -H "X-Emitter: $EMITTER" \
  -H "X-Scenario-Id: $SCENARIO" \
  --data-binary @"$BODY" \
  "${HDRS[@]}" | tee /tmp/e2e_auth_resp.txt | sed -n '1,40p'

# szybka asercja: HTTP/1.1 200
grep -q '^HTTP/1.1 200' /tmp/e2e_auth_resp.txt && echo "OK 200 from AuthGW"

# szybka asercja: w JSON powinna być propagacja emitter/scenario_id
if awk 'f{print} /^$/{f=1}' /tmp/e2e_auth_resp.txt | jq -e ".emitter==\"$EMITTER\" and .scenario_id==\"$SCENARIO\"" >/dev/null 2>&1; then
  echo "OK propagation emitter/scenario_id via AuthGW -> IngestGW"
else
  echo "WARN: response doesn't show expected emitter/scenario_id"
fi
echo

echo "== direct hop #2: client -> 8080 (IngestGW) =="
curl -fsSi -X POST "$INGEST/v1/logs" \
  -H 'Content-Type: application/json' \
  -H "X-Emitter: $EMITTER" \
  -H "X-Scenario-Id: $SCENARIO" \
  --data-binary @"$BODY" | tee /tmp/e2e_ingest_resp.txt | sed -n '1,40p'
grep -q '^HTTP/1.1 200' /tmp/e2e_ingest_resp.txt && echo "OK 200 from IngestGW"
echo

echo "== direct hop #3: client -> 8095 (Core) =="
curl -fsSi -X POST "$CORE/v1/logs" \
  -H 'Content-Type: application/json' \
  --data-binary @"$BODY" | tee /tmp/e2e_core_resp.txt | sed -n '1,40p' || {
  echo "WARN: Core may not be up or route differs; check $CORE"
}
echo

echo "== metrics spot-checks (optional) =="
# AuthGW licznik żądań:
curl -fsS "$AUTHGW/metrics" | egrep 'auth_requests_total\{|auth_request_latency_seconds_bucket\{|x-ratelimit' | head -n 10 || true
echo
# IngestGW liczniki:
curl -fsS "$INGEST/metrics" | egrep 'ACCEPTED_TOTAL\{|BATCH_LATENCY\{|INGESTED_TOTAL\{' | head -n 10 || true
echo

echo "All done."
