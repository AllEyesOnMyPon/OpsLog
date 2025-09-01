#!/usr/bin/env bash
set -euo pipefail

URL="http://127.0.0.1:8090/ingest"
METHOD="POST"
API_KEY="${LOGOPS_API_KEY:-demo-pub-1}"
SECRET="${LOGOPS_SECRET:-demo-priv-1}"
BODY=""
BODY_FILE=""
ADD_NONCE=0
TS=""
TS_OFFSET=""

CURL_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--url)        URL="$2"; shift 2;;
    -X|--method)     METHOD="$2"; shift 2;;
    -k|--key)        API_KEY="$2"; shift 2;;
    -s|--secret)     SECRET="$2"; shift 2;;
    -d|--data)       BODY="$2"; BODY_FILE=""; shift 2;;
    -f|--file)       BODY_FILE="$2"; shift 2;;
    --nonce)         ADD_NONCE=1; shift;;
    --ts)            TS="$2"; shift 2;;
    --ts-offset)     TS_OFFSET="$2"; shift 2;;
    --echo-headers)
      if [[ -n "$BODY_FILE" ]]; then
        python tools/sign_hmac.py "$API_KEY" "$SECRET" "$METHOD" "$URL" "{}" \
          ${ADD_NONCE:+--nonce} ${TS:+--ts "$TS"} ${TS_OFFSET:+--ts-offset "$TS_OFFSET"} \
          --body-file "$BODY_FILE" --one-per-line | paste -sd' ' -
      else
        TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
        printf '%s' "${BODY:-{}}" > "$TMP"
        python tools/sign_hmac.py "$API_KEY" "$SECRET" "$METHOD" "$URL" "{}" \
          ${ADD_NONCE:+--nonce} ${TS:+--ts "$TS"} ${TS_OFFSET:+--ts-offset "$TS_OFFSET"} \
          --body-file "$TMP" --one-per-line | paste -sd' ' -
      fi
      exit 0;;
    --) shift; CURL_ARGS+=("$@"); break;;
    *)  CURL_ARGS+=("$1"); shift;;
  esac
done

cleanup() { [[ -n "${TMP_BODY:-}" && -f "${TMP_BODY:-}" ]] && rm -f "$TMP_BODY"; }
trap cleanup EXIT

if [[ -n "$BODY_FILE" ]]; then
  BODY_SRC="$BODY_FILE"
else
  TMP_BODY="$(mktemp)"
  if [[ -z "${BODY:-}" ]]; then
    printf '{}' > "$TMP_BODY"
  else
    printf '%s' "$BODY" > "$TMP_BODY"
  fi
  BODY_SRC="$TMP_BODY"
fi

mapfile -t HDR_LINES < <(python tools/sign_hmac.py "$API_KEY" "$SECRET" "$METHOD" "$URL" "{}" \
  ${ADD_NONCE:+--nonce} ${TS:+--ts "$TS"} ${TS_OFFSET:+--ts-offset "$TS_OFFSET"} \
  --body-file "$BODY_SRC" --one-per-line)

HDR_ARGS=()
for l in "${HDR_LINES[@]}"; do
  h=${l#-H }
  h=${h#\"}
  h=${h%\"}
  HDR_ARGS+=(-H "$h")
done

curl -s -X "$METHOD" "$URL" -H 'Content-Type: application/json' \
  "${HDR_ARGS[@]}" \
  --data-binary "@$BODY_SRC" \
  "${CURL_ARGS[@]}"
