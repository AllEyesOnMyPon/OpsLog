# Auth Gateway (FastAPI)

Warstwa pośrednia **autoryzacji, limitowania i backpressure** przed Ingest Gateway.
Weryfikuje żądania (HMAC / API key / none), stosuje **rate-limit (token bucket)**, ma **limity rozmiaru body**, a następnie **forwarduje** payload 1:1 do IngestGW z **retry** i **circuit breakerem**.
Eksponuje **/healthz**, **/health** oraz **/metrics**.

**Pliki źródłowe:**
- Aplikacja: `services/authgw/app.py`
- Forwarding / Retry / Circuit Breaker: `services/authgw/downstream.py`
- HMAC/API key middleware: `services/authgw/hmac_mw.py`
- Rate limiting middleware: `services/authgw/ratelimit_mw.py`
- Konfiguracje przykładowe: `services/authgw/config.yaml`, `config.example.yaml`, `config.rltest.yaml`
- Narzędzie do weryfikacji podpisu: `tools/verify_hmac_against_signer.py`

> AuthGW **nie normalizuje** logów — to robi Ingest Gateway. AuthGW pełni funkcje kontrolne i proxy.

---

## Endpointy

- `GET /healthz` — status (jeśli skonfigurowany Redis → wykonywany `PING`; błąd Redis ustawia `ok=false`).
- `GET /health` — alias `healthz`.
- `GET /metrics` — metryki Prometheus (exposition format).
- `POST /ingest` — przyjmuje dowolny `Content-Type` (najczęściej JSON/CSV/text), weryfikuje (auth, RL, backpressure) i **proxy** do Ingest `/v1/logs`.

---

## Przepływ żądania (high-level)

1. **HmacAuthMiddleware** — autoryzacja wg `auth.mode` (`none` / `api_key` / `hmac` / `any`).
   W trybie HMAC: walidacja czasu (`X-Timestamp`), (opcjonalnie) **nonce** `X-Nonce` (anti-replay, Redis/in-memory), hash ciała `X-Content-SHA256` i podpis `X-Signature`.
   Middleware uzupełnia `request.state` (m.in. `emitter`, `api_key`, `scenario_id`, `client_ip`).
2. **TokenBucketRL** — per-emitter token bucket; niedobór tokenów → **`429`** + nagłówki `X-RateLimit-*`.
3. **Backpressure (app.py)** — limit rozmiaru body (w bajtach) → **`413`**.
4. **Forwarding** — 1:1 do IngestGW (`/v1/logs`) z **timeoutami**, **retry** i **circuit breakerem** (zob. niżej).

---

## Kontrakt `/ingest`

### Nagłówki transportowe

- `X-Emitter: <nazwa>` — identyfikator emitera/klienta (do RL i metryk).
  Gdy brak → `"unknown"`. W trybach `api_key`/`hmac` middleware może ustawić `emitter` z `secrets.clients`.
- `X-Scenario-Id: <id>` — identyfikator scenariusza (propagowany dalej).

**Autoryzacja:**
- `auth.mode = "none"` — brak wymagań.
- `auth.mode = "api_key"` — **wymagany** `X-Api-Key: <public_id>`; walidacja w `secrets.clients`.
- `auth.mode = "hmac"` — wymagany komplet nagłówków (poniżej).
- `auth.mode = "any"` — akceptuje **samo** `X-Api-Key` *albo* pełny HMAC.

### HMAC — nagłówki i kanoniczny string

W trybie `hmac` (lub `any` z kompletem HMAC) oczekiwane są:

- `X-Api-Key` — publiczny identyfikator klienta; `secrets.clients[<api_key>]` zawiera `secret` i opcjonalnie `emitter`.
- `X-Timestamp` — ISO-8601; wspierane `Z` **oraz offsety** (np. `2025-08-31T12:00:00Z` lub `2025-08-31T14:00:00+02:00`).
- `X-Content-SHA256` — **hex** SHA-256 z **surowego** body (bytes).
- `X-Signature` — **base64** z `HMAC_SHA256(secret, canonical)`.
- `X-Nonce` — **wymagany**, gdy `require_nonce=true`; anti-replay (Redis lub cache in-memory).

**Kanoniczny string** (zgodny z `services/authgw/hmac_mw.py`):

```
<METHOD_UPPER>
<PATH_ONLY>         # bez query string!
<SHA256_HEX(body)>
<X-Timestamp>
<X-Nonce>           # pusty string, gdy nonce wyłączony
```

**Weryfikacja:**
- Parsowanie `X-Timestamp` (ISO-8601 + `Z`/offset) → tolerancja zegara `clock_skew_sec` (domyślnie 300 s).
- Gdy `require_nonce=true`:
  - brak nagłówka → `401`
  - ponowny `nonce` (cache/Redis) → `401` (`nonce replay`)
- Obliczenie `sha256(body)` i porównanie z `X-Content-SHA256` (różnica → `400`).
- `expected = base64(hmac_sha256(secret, canonical))` i bezpieczne porównanie z `X-Signature` (mismatch → `401`).

**Typowe błędy HMAC:** `401` (`missing X-Api-Key`, `invalid api key`, `missing hmac headers`, `timestamp skew`, `missing X-Nonce`, `nonce replay`, `bad signature`) oraz `400` (`bad X-Timestamp`, `bad X-Content-SHA256`).

### Body

- JSON (obiekt) **lub** JSON (tablica) **albo** inne typy (`text/csv`, `text/plain`) — AuthGW **nie** dotyka treści.
- Do IngestGW przekazywany jest oryginalny `Content-Type` (zachowana tylko część przed `;`).

### Odpowiedzi

- `2xx` — proxy **statusu i body** z IngestGW (np. liczba przyjętych rekordów).
- `400` — błąd odczytu body (`{"error":"cannot read request body"}`) lub walidacji.
- `401` — błędy HMAC/API key.
- `413` — backpressure (za duże body) + `X-Backpressure-Reason: too_large|too_large_hdr`.
- `429` — rate limit exceeded (z RL middleware) + `X-RateLimit-*`.
- `502` — błąd downstream (wyczerpane retry / błąd sieci).
- `503` — `{"error":"circuit_open"}` — breaker jest otwarty.

---

## Backpressure (w `app.py`)

Konfiguracja (`backpressure` w YAML):

```yaml
backpressure:
  enabled: true
  max_body_bytes: 200000
```

Zasady:

1. Jeżeli nagłówek `Content-Length` przekracza limit → natychmiast **`413`** z
   `X-Backpressure-Reason: too_large_hdr` i payloadem:
   ```json
   {"error":"payload too large","max_body_bytes":200000,"content_length_hdr": <X>}
   ```
2. Jeżeli faktyczny rozmiar `actual_len` przekracza limit → **`413`** z
   `X-Backpressure-Reason: too_large` i:
   ```json
   {"error":"payload too large","max_body_bytes":200000,"actual_bytes": <X>}
   ```

> AuthGW nie limituje liczby elementów w JSON array (to możesz egzekwować po stronie Ingest/Core).

---

## Rate limiting (middleware `TokenBucketRL`)

- **Model:** per-emitter token bucket (in-memory) lub Redis (jeśli `storage.redis_url`).
- **Odnawianie:** `refill_per_sec` do maksimum `capacity`.
- **Nagłówki informacyjne:**
  - `X-RateLimit-Limit: <capacity>`
  - `X-RateLimit-Remaining: 1|0`

Konfiguracja:

```yaml
ratelimit:
  per_emitter:
    capacity: 100
    refill_per_sec: 50
```

---

## Forwarding + Retry + Circuit Breaker

Forward odbywa się przez `post_with_retry(...)` z `services/authgw/downstream.py`:

- **Retry:** dla błędów sieci/transportu; backoff wykładniczy
  `delay = min(base_delay_ms * 2^(attempt-1), max_delay_ms)`.
- **Breaker (`Breaker`):**
  - Stany: `closed` → `open` (po przekroczeniu progu błędów) → `half_open` (po czasie) → `closed` na sukces.
  - Próg błędów konfigurowany **procentem** (np. `20`) lub **ułamkiem** (`0.2`) → w app przeliczany do `0–1`.
  - Gdy breaker jest **open**, `post_with_retry` natychmiast zwraca błąd `RuntimeError("circuit_open")` → mapowany na **`503`**.

**Wybrane parametry (YAML):**
```yaml
forward:
  url: "http://127.0.0.1:8080/v1/logs"
  timeout_sec: 5               # read timeout; connect ~2s (w kodzie)

retries:
  max_attempts: 3
  base_delay_ms: 100
  max_delay_ms: 1500

breaker:
  failure_threshold: 20        # procent (20) lub ułamek (0.2)
  window_sec: 30
  half_open_after_sec: 20

# (opcjonalnie) dodatkowe nagłówki do forwardu przez templating:
forward:
  headers:
    X-Forwarded-For: "{client_ip}"
    X-Emitter: "{emitter}"
    X-Scenario-Id: "{scenario_id}"
```

W app czasu używamy jako:
- `connect_ms ≈ 2000`, `read_ms = timeout_sec * 1000`, `write = 5s`, `pool = 2s`.

---

## Konfiguracja (YAML) i ENV

Domyślna ścieżka: `services/authgw/config.yaml`
Nadpisanie: `AUTHGW_CONFIG=/ścieżka/do/pliku.yaml`

Główne sekcje:

```yaml
server:
  host: "0.0.0.0"
  port: 8081

auth:
  mode: "hmac"            # none | api_key | hmac | any
  hmac:
    clock_skew_sec: 300
    require_nonce: true

secrets:
  clients:
    demo-pub-1: { secret: "demo-priv-1", emitter: "json" }
    demo-pub-2: { secret: "demo-priv-2", emitter: "minimal" }
    demo-pub-3: { secret: "demo-priv-3", emitter: "csv" }
    demo-pub-4: { secret: "demo-priv-4", emitter: "noise" }
    demo-pub-5: { secret: "demo-priv-5", emitter: "syslog" }

ratelimit:
  per_emitter:
    capacity: 100
    refill_per_sec: 50

forward:
  url: "http://127.0.0.1:8080/v1/logs"
  timeout_sec: 5
  headers:
    X-Emitter: "{emitter}"
    X-Scenario-Id: "{scenario_id}"

retries:
  max_attempts: 3
  base_delay_ms: 100
  max_delay_ms: 1500

breaker:
  failure_threshold: 20
  window_sec: 30
  half_open_after_sec: 20

backpressure:
  enabled: true
  max_body_bytes: 200000

storage:
  redis_url: "redis://127.0.0.1:6379/0"  # opcjonalnie dla nonce/RL
```

---

## Metryki Prometheus (app.py)

- `auth_requests_total{status,emitter,scenario_id}` *(Counter)* — licznik żądań i statusów.
- `auth_request_latency_seconds{emitter,scenario_id}` *(Histogram)* — latencja żądań.
- `logops_rejected_total{reason,emitter}` *(Counter)* — odrzucone żądania (powody m.in.:
  `unauthorized`, `rate_limited`, `too_large`, `too_large_hdr`, `bad_request`,
  `bad_content_type`, `forbidden`, `clock_skew`, `bad_signature`, `bad_nonce`,
  `unknown_client`, `http_4xx/5xx`).

---

## Przykłady

### 1) Tryb `any` z samym API key (bez HMAC)
```bash
curl -s http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: demo-pub-1" \
  -H "X-Emitter: json" \
  -H "X-Scenario-Id: sc-docs-any" \
  --data-binary '{"msg":"hello","level":"info"}' | jq .
```

### 2) Backpressure — zbyt duże body
```bash
dd if=/dev/zero bs=220000 count=1 2>/dev/null | \
curl -s http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: demo-pub-1" \
  --data-binary @- | jq .
```

### 3) HMAC — podpis (Python; **PATH bez query!**)
```python
import base64, hashlib, hmac, json, requests
from datetime import datetime, timezone

api_key = "demo-pub-1"
secret = b"demo-priv-1"
url = "http://localhost:8081/ingest?foo=bar"
method = "POST"
ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
body = json.dumps({"msg":"hello","level":"info"}).encode("utf-8")
body_sha = hashlib.sha256(body).hexdigest()
path_only = "/ingest"  # Uwaga: BEZ query string!

canonical = "\n".join([method, path_only, body_sha, ts, "nonce-123"]).encode("utf-8")
sig_b64 = base64.b64encode(hmac.new(secret, canonical, hashlib.sha256).digest()).decode("ascii")

headers = {
  "Content-Type":"application/json",
  "X-Api-Key": api_key,
  "X-Timestamp": ts,
  "X-Content-SHA256": body_sha,
  "X-Signature": sig_b64,
  "X-Nonce": "nonce-123",
  "X-Scenario-Id":"sc-docs-hmac",
}
r = requests.post(url, headers=headers, data=body)
print(r.status_code, r.text)
```

> W razie wątpliwości użyj `tools/verify_hmac_against_signer.py` — narzędzie porówna nagłówki i podpis z lokalnie wyliczonym.

---

## Uruchomienie lokalne

1) Wskaż konfigurację:
```bash
export AUTHGW_CONFIG="services/authgw/config.yaml"
```

2) Uruchom AuthGW:
```bash
uvicorn services.authgw.app:app --host 0.0.0.0 --port 8081 --reload
```

3) Upewnij się, że IngestGW działa pod `forward.url` (np. `http://127.0.0.1:8080/v1/logs`).

---

## Uwagi operacyjne

- **Redis** (opcjonalnie):
  - Anti-replay dla `X-Nonce` oraz współdzielone liczniki RL między instancjami.
  - Brak Redis → prosty cache nonce in-memory (per proces), RL także in-memory.
- **Timeouty:** `connect_ms≈2000`, `read_ms=timeout_sec*1000`, `write=5s`, `pool=2s`.
- **Breaker tuning:** zbyt niski `failure_threshold` → częste **`503`**. Koreluj z p95 Ingest i 5xx.
- **Diagnoza HMAC:** ustaw `AUTHGW_DEBUG_HMAC=1`, by logować kanoniczny string/oczekiwany podpis.

---

## Checklist

- [ ] `AUTHGW_CONFIG` wskazuje właściwy YAML.
- [ ] `auth.mode` (`none` / `api_key` / `hmac` / `any`) zgodny z klientami.
- [ ] W trybie HMAC: klient ma `secret`, zegary zsynchronizowane, `X-Nonce` unikalny.
- [ ] `ratelimit.per_emitter` (capacity / refill) dopasowane do QPS.
- [ ] `backpressure.max_body_bytes` odpowiada typowemu rozmiarowi batchy.
- [ ] `forward.url` wskazuje IngestGW `/v1/logs`; ewentualne `forward.headers` (X-Emitter/Scenario itp.).
- [ ] Monitorujesz: `auth_requests_total`, `auth_request_latency_seconds`, `logops_rejected_total{reason}`.
