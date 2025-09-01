# Auth Gateway (FastAPI)

Warstwa pośrednia **autoryzacji i limitowania** przed Ingest Gateway. Weryfikuje żądania (HMAC/API key/none), egzekwuje **rate limit (token bucket)**, stosuje **backpressure** (limity rozmiaru body i liczby elementów), a następnie **forwarduje** payload do Ingest Gateway z **retry** i **circuit breakerem**. Eksponuje **/healthz** i **/metrics**.

Pliki źródłowe:
- Aplikacja: `services/authgw/app.py`
- Forwarding/Retry/CB: `services/authgw/downstream.py`
- HMAC/API key middleware: `services/authgw/hmac_mw.py`
- Rate limiting middleware: `services/authgw/ratelimit_mw.py`
- Konfiguracje przykładowe: `services/authgw/config.yaml`, `config.example.yaml`, `config.rltest.yaml`

---

## Endpointy

- `GET /healthz` — status bramy (jeśli skonfigurowany Redis → wykonywany `PING`; błąd Redis ustawia `ok=false`).
- `GET /metrics` — metryki Prometheus (exposition format).
- `POST /ingest` — przyjmuje JSON (obiekt lub tablica), weryfikuje (auth, RL, backpressure) i **proxy** do Ingest `/v1/logs`.

> Uwaga: AuthGW **nie normalizuje** logów. To robi Ingest Gateway. AuthGW pełni funkcje kontrolne i proxy.

---

## Przepływ żądania (high level)

1. **HmacAuthMiddleware**: autoryzacja wg `auth.mode` (`none`/`api_key`/`hmac`/`any`). W trybie HMAC weryfikuje timestamp, (opcjonalnie) `nonce` z Redis, hash ciała i podpis. Dokleja `X-Emitter` z bazy klientów.
2. **TokenBucketRL**: per-emitter token bucket; niedobór tokenów → `429` + `X-RateLimit-*`.
3. **Backpressure** (w `app.py`): limity `max_body_bytes` i `max_items` (dla JSON array) → `413`.
4. **Forwarder**: `post_with_retry()` wysyła do Ingest `/v1/logs` z timeoutami, retry, backoff i **Breakerem** (CB).

---

## Kontrakt `/ingest`

### Nagłówki

- `X-Emitter: <nazwa>` — identyfikator emitera/klienta (do RL i metryk).  
  - Jeśli brak, przyjmowane `"unknown"`.  
  - W trybach `api_key`/`hmac` **middleware dokleja** `X-Emitter` z bazy klientów (`secrets.clients`).

- **Autoryzacja**:
  - `auth.mode = "none"` — brak wymagań.
  - `auth.mode = "api_key"` — **wymagany** `X-Api-Key: <public_id>`; middleware waliduje w `secrets.clients`.
  - `auth.mode = "hmac"` — wymagany komplet nagłówków (poniżej).
  - `auth.mode = "any"` — akceptuje **samo** `X-Api-Key` lub pełny HMAC.

### HMAC — szczegóły nagłówków (middleware `hmac_mw.py`)

W trybie `hmac` (lub `any` z kompletem HMAC) oczekiwane są:

- `X-Api-Key` — publiczny identyfikator klienta; w `secrets.clients[<api_key>]` trzymany jest `secret` i powiązany `emitter`.
- `X-Timestamp` — ISO8601 (obsługuje sufiks `Z`), np. `2025-08-31T12:00:00Z`.
- `X-Content-SHA256` — **hex** SHA-256 z **surowego** body (bytes).
- `X-Signature` — **base64** z `HMAC-SHA256(secret, canonical_string)`.
- `X-Nonce` — (wymagany, gdy `require_nonce=true`) unikatowa wartość na żądanie; przy Redis wykrywa replay.

Kanoniczny string podpisu:
```
<HTTP_METHOD_UPPER>
<PATH_WITH_OPTIONAL_QUERY>
<X-Timestamp>
<X-Content-SHA256>
```

Weryfikacja:
- Parsowanie `X-Timestamp` → tolerancja zegara `clock_skew_sec` (domyślnie 300 s).  
- Jeśli `require_nonce=true` i `storage.redis_url` ustawiony → `SETNX` (TTL 300 s); kolizja = replay → `401`.  
- Obliczenie `sha256(body)` i porównanie do `X-Content-SHA256`.  
- `expected = base64(hmac_sha256(secret, canonical))` i bezpieczne porównanie z `X-Signature`.

Błędy HMAC: `401` (`missing X-Api-Key`, `invalid api key`, `missing hmac headers`, `timestamp skew`, `missing X-Nonce`, `replay detected`, `body hash mismatch`, `bad signature`) lub `400` (`bad X-Timestamp`).

> Tryb `any`: jeśli **brak** kompletów HMAC, ale jest poprawny `X-Api-Key` → traktowane jak `api_key`.

### Body

- JSON (obiekt) **lub** JSON (tablica obiektów).  
- AuthGW **nie** interpretuje treści; jedynie limity i proxy.

### Odpowiedzi

- `2xx` — proxy **statusu i body** z Ingest Gateway (np. liczba przyjętych rekordów).
- `400` — błędny JSON: `{"error":"bad json"}`.
- `401`/`400` — błędy autoryzacji HMAC/API key (patrz wyżej).
- `413` — backpressure:
  - za duże `Content-Length` → `{"error":"payload too large","max_body_bytes":B,"content_length_hdr":X}` + `X-Backpressure-Reason: too_large_hdr`
  - faktyczny rozmiar > limit → `{"error":"payload too large","max_body_bytes":B,"actual_bytes":X}` + `X-Backpressure-Reason: too_large`
  - zbyt wiele elementów w tablicy → `{"error":"too many items","max_items":N,"actual_items":X}` + `X-Backpressure-Reason: too_many_items`
- `429` — rate limit exceeded (z middleware RL) + nagłówki `X-RateLimit-*`, opcjonalnie `Retry-After`.
- `502` — błąd downstream (wyczerpane retry, 5xx itp.).
- `503` — `circuit_open` (breaker otwarty).

---

## Backpressure (w `app.py`)

Konfiguracja (`backpressure` w YAML):
- `enabled: true|false` — włącza/wyłącza (domyślnie `true`).
- `max_body_bytes: int` — maksymalny rozmiar body (np. `200000`).
- `max_items: int` — maksymalna liczba elementów, gdy body to **tablica JSON** (np. `1000`).

Zasady:
1. Jeśli nagłówek `Content-Length` przekracza limit → szybkie `413` (`too_large_hdr`) bez buforowania całego body.  
2. W przeciwnym razie weryfikowana jest realna długość `actual_len`; przekroczenie → `413` (`too_large`).  
3. Dla JSON array, jeśli `len(array) > max_items` → `413` (`too_many_items`).

Metryka: `logops_rejected_total{reason,emitter}` z `reason ∈ {too_large_hdr, too_large, too_many_items}`.

---

## Rate limiting (middleware `TokenBucketRL`)

- **Model**: per-emitter token bucket. Każde żądanie zużywa 1 token.  
- **Odnawianie**: `refill_per_sec` do maksimum `capacity`.  
- **Źródło stanu**: Redis (`storage.redis_url`) lub lokalna pamięć w procesie.  
- **Odpowiedź**: przy braku tokenów `429` + nagłówki:
  - `X-RateLimit-Limit: <capacity>`
  - `X-RateLimit-Remaining: <remaining>`
  - `Retry-After: <seconds>` (jeśli wyliczony > 0)

Parametry (YAML):
- `ratelimit.per_emitter.capacity` (domyślnie 100)
- `ratelimit.per_emitter.refill_per_sec` (domyślnie 50)
- (na przyszłość) `ratelimit.by_emitter` — per-emitter override

---

## Forwarding + Retry + Circuit Breaker

Implementacja: `services/authgw/downstream.py`

### `Breaker` (CB)
- Stany: `closed` → `open` → `half_open` → `closed`.
- Przejście do `open`, gdy `fails/total ≥ failure_threshold`.  
- W `half_open`:  
  - sukces → `closed` (zerowanie okna),  
  - błąd → ponowne `open` (reset timera).
- Okno licznikowe ma „przycinanie”, by wartości nie rosły bez końca.

### `post_with_retry(...)`
- Retry dla błędów sieciowych (`ConnectTimeout`, `ReadTimeout`, `ConnectError`) **i** `HTTP 5xx`.  
- `HTTP 4xx` → **bez** retry (zwracane od razu).  
- Backoff wykładniczy: `delay = min(base_delay_ms * 2^(attempt-1), max_delay_ms)`.  
- Timeouty `httpx.Timeout` z ms: `(connect_ms, read_ms, write=read_ms, pool=connect_ms)`.  
- Gdy CB `open` → `RuntimeError("circuit_open")` (mapowane na `503`).  
- Po wyczerpaniu prób → `RuntimeError("downstream_error: ...")` (mapowane na `502`).

Parametry (YAML):
```yaml
forward:
  url: "http://127.0.0.1:8080/v1/logs"
  timeout_sec: 5           # → read_ms = 5000, connect_ms = 2000 (z app.py)
retries:
  max_attempts: 3
  base_delay_ms: 100
  max_delay_ms: 1500
breaker:
  failure_threshold: 20    # w procentach; app.py dzieli przez 100 → 0.20
  window_sec: 30
  half_open_after_sec: 20
```

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
  api_keys:
    - "dev-123"           # (dla trybu api_key)
  hmac:
    secret: "supersecret"  # sekret HMAC (dla prostych wdrożeń)
    header: "X-Signature"
    algo: "sha256"
    timestamp_header: "X-Timestamp"
    clock_skew_sec: 300
    require_nonce: true    # w config.example.yaml

secrets:
  clients:
    demo-pub-1: { secret: "demo-priv-1", emitter: "emitter_json" }
    demo-pub-2: { secret: "demo-priv-2", emitter: "emitter_minimal" }

ratelimit:
  per_emitter:
    capacity: 100
    refill_per_sec: 50

forward:
  url: "http://127.0.0.1:8080/v1/logs"
  timeout_sec: 5

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
  max_items: 1000

storage:
  redis_url: "redis://127.0.0.1:6379/0"  # opcjonalnie dla nonce/RL
```

> Masz trzy pliki konfiguracyjne do różnych celów:
> - `config.yaml` — pełny, z sekcją `server`, rozszerzonym `auth` i nagłówkami do forwardu.
> - `config.example.yaml` — czytelny przykład produkcyjny (HMAC, RL, backpressure, breaker, Redis).
> - `config.rltest.yaml` — profil do testów rate limiting (np. refill 100/s).

---

## Metryki Prometheus

Zdefiniowane w `app.py`:
- `logops_rejected_total{reason,emitter}` *(Counter)* — odrzucone żądania przez warstwę backpressure:
  - `reason="too_large_hdr"` — `Content-Length` > `max_body_bytes`
  - `reason="too_large"` — faktyczny rozmiar body > `max_body_bytes`
  - `reason="too_many_items"` — zbyt wiele elementów (JSON array)

Z middleware (nie w `app.py`, ale istotne w obserwowalności):
- **HMAC/API key** — warto zbierać: liczba błędów podpisu, replay, skew (jeśli dodasz metryki w `hmac_mw.py`).
- **Rate limit** — liczba odmów `429` per-emitter (możesz dodać Counter w `ratelimit_mw.py`).

Eksport: `GET /metrics` (`text/plain; version=0.0.4`).

---

## Przykłady

### 1) Prosty request (tryb `none` / `any` z samym `X-Api-Key`)
```bash
curl -s http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: demo-pub-1" \
  -d '{"msg":"hello","level":"info"}' | jq .
```

### 2) Backpressure — zbyt duże body
```bash
dd if=/dev/zero bs=220000 count=1 2>/dev/null | \
curl -s http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: demo-pub-1" \
  --data-binary @- | jq .
```
Odpowiedź:
```json
{"error":"payload too large","max_body_bytes":200000,"actual_bytes":220000}
```

### 3) Backpressure — zbyt wiele elementów
```bash
python - <<'PY'
import json; print(json.dumps([{"i":i} for i in range(1100)]))
PY
```
```bash
python gen.py | curl -s http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: demo-pub-1" \
  --data-binary @- | jq .
```
Odpowiedź:
```json
{"error":"too many items","max_items":1000,"actual_items":1100}
```

### 4) HMAC — kanoniczny podpis (pseudokod)
```python
import base64, hashlib, hmac, json, requests, datetime

api_key = "demo-pub-1"
secret = b"demo-priv-1"
ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
body = json.dumps({"msg":"hello","level":"info"}).encode("utf-8")
body_hash = hashlib.sha256(body).hexdigest()
canonical = "\n".join(["POST","/ingest?foo=bar",ts,body_hash]).encode()
signature = base64.b64encode(hmac.new(secret, canonical, hashlib.sha256).digest()).decode()

headers = {
  "Content-Type":"application/json",
  "X-Api-Key": api_key,
  "X-Timestamp": ts,
  "X-Content-SHA256": body_hash,
  "X-Signature": signature,
  "X-Nonce": "random-uuid-if-required"
}

r = requests.post("http://localhost:8081/ingest?foo=bar", headers=headers, data=body)
print(r.status_code, r.text)
```

---

## Uruchomienie lokalne

1) Skonfiguruj `services/authgw/config.yaml` lub wskaż inny:
```bash
export AUTHGW_CONFIG="services/authgw/config.yaml"
```
2) Uruchom AuthGW (np. uvicorn):
```bash
uvicorn services.authgw.app:app --host 0.0.0.0 --port 8081 --reload
```
3) Upewnij się, że Ingest Gateway działa na `forward.url` (np. `http://127.0.0.1:8080/v1/logs`).

---

## Uwagi operacyjne

- **Redis** (opcjonalny):  
  - Zapewnia anty-replay `X-Nonce` oraz współdzielone liczniki RL między instancjami.  
  - Brak Redis → nonce sprawdzany wyłącznie „nagłówkowo” (unikalność po stronie klienta).

- **Breaker tuning**:  
  - Zbyt niski `failure_threshold` → częste `503`. Koreluj z faktycznym p95 Ingest i błędami 5xx.  
  - Obserwuj przejścia stanów (logi `authgw.downstream`).

- **Timeouty**:  
  - `connect_ms=2000` (ustawione w kodzie), `read_ms = timeout_sec * 1000`.  
  - Dobierz do p95 Ingest; pamiętaj o backoffie i max_attempts.

- **Logowanie**:  
  - Linia `ingest_req ip=<ip> emitter=<emitter> len=<bytes> ua=<agent>` pomaga profilować bursty i źródła ruchu.

---

## Checklist

- [ ] `AUTHGW_CONFIG` wskazuje właściwy YAML.  
- [ ] `auth.mode` i `secrets.clients` skonfigurowane (HMAC/API key).  
- [ ] `ratelimit` (capacity/refill) dopasowany do QPS.  
- [ ] `forward.url` ustawiony na `/v1/logs` Ingest Gateway.  
- [ ] `backpressure` (`max_body_bytes`, `max_items`) zgodny z typowymi batchami.  
- [ ] Monitorujesz: `logops_rejected_total{reason,emitter}`, odsetek `429`, błędy 5xx i stany CB.

---
