# Core (FastAPI)

Minimalistyczny **collector** przyjmujący batch JSON i robiący rzeczy „ostatniej mili”:
- waliduje/limit rozmiaru **body** i liczby **elementów**,
- **liczy metryki** (latencja, liczba rekordów, poziomy logów, bajty),
- (opcjonalnie) **zapisuje NDJSON** do plików dziennych,
- udostępnia **/metrics**, **/healthz** i proste endpointy debugowe.

> Core **nie normalizuje** logów i nie maskuje PII — to robi Ingest Gateway.
> Core może przyjmować ruch **bezpośrednio** (dev/test) albo **z Ingesta** (prod-flow).

Pliki źródłowe:
- Aplikacja: `services/core/app.py`

---

## Endpointy

- `GET /healthz` — szybki status aplikacji.
- `GET /metrics` — metryki Prometheus (exposition format).
- `GET /_debug/hdrs` — echo nagłówków + podgląd aktualnej konfiguracji (ENV).
- `GET /_debug/stats` — próbka z bufora „ostatnie N rekordów”.
- `POST /v1/logs` — przyjmuje **JSON** (obiekt lub tablica obiektów), liczy metryki, opcjonalnie zapisuje NDJSON i zwraca `{ "accepted": <n> }`.

---

## Kontrakt `/v1/logs`

### Nagłówki (opcjonalne, ale zalecane)

- `X-Emitter: <nazwa>` — identyfikator źródła (używany w metrykach i dopisywany do NDJSON).
- `X-Scenario-Id: <id>` *(albo starszy `X-Scenario`)* — identyfikator scenariusza/testu.

> Jeśli brak nagłówków:
> - `emitter` = `"unknown"`
> - `scenario_id` = `"na"`

### Body

- **Tylko JSON**:
  - **obiekt** → traktowany jako 1 rekord,
  - **tablica obiektów** → batch rekordów.
- Elementy muszą być **słownikami** (JSON object). Złe elementy w tablicy → `422`, gdy **wszystkie** są nieprawidłowe.

### Odpowiedzi

- `200` — `{"accepted": N}`.
- `400` — zły JSON (`{"detail":"bad json"}`) lub brak możliwości odczytu body (`{"detail":"cannot read body"}`).
- `413` — backpressure w Core:
  - `{"detail":"payload too large"}` — body za duże (patrz `CORE_MAX_BODY_BYTES`),
  - `{"detail":"too many items"}` — za dużo elementów w tablicy (patrz `CORE_MAX_ITEMS`).
- `422` — tablica zawiera wyłącznie nie-JSON-owe elementy (`{"detail":"invalid items in array"}`).

---

## Flow

Typowy przepływ:
```
Emitery → (AuthGW) → IngestGW → Core → (opcjonalny) NDJSON → Promtail → Loki → Grafana
```

Tryb „skrót” (dev/test bez normalizacji):
```
Emitery (JSON już znormalizowany) → Core
```

> **CSV / syslog-like** wysyłaj do **IngestGW**, nie bezpośrednio do Core.

---

## Konfiguracja (ENV)

Core trzyma się zasady **S13 — brak twardych ścieżek**: wszystko konfigurowalne ENV-ami.

- `CORE_MAX_BODY_BYTES` *(int, domyślnie `1048576`)* — maksymalny rozmiar body (bytes) dla `/v1/logs`.
- `CORE_MAX_ITEMS` *(int, domyślnie `5000`)* — maksymalna liczba elementów w JSON-array.
- `CORE_SINK_FILE` *(bool, domyślnie `false`)* — włącz/wyłącz zapis NDJSON do plików dziennych.
- **Katalog wyjściowy NDJSON (priorytet):**
  1. `LOGOPS_SINK_DIR` *(jeśli ustawione — globalny S13)*,
  2. `CORE_SINK_DIR`,
  3. fallback: `./data/ingest`.
- `CORE_DEBUG_SAMPLE` *(bool, domyślnie `false`)* — czy do próbki debugowej zrzucać treści.
- `CORE_DEBUG_SAMPLE_SIZE` *(int, domyślnie `10`)* — rozmiar próbki.
- `CORE_RING_SIZE` *(int, domyślnie `200`)* — pojemność bufora „ostatnich rekordów” (do `/_debug/stats`).

> Booleany: wartości włączające to wszystko poza `""`, `"0"`, `"false"`, `"no"`, `"off"` (case-insensitive).

---

## Metryki Prometheus

Definiowane w `services/core/app.py`:

- `core_inflight` *(Gauge)* — liczba aktualnie obsługiwanych żądań.
- `core_request_latency_seconds{emitter,scenario_id}` *(Histogram)* — latencja obsługi `/v1/logs`.
- `core_accepted_total{emitter,scenario_id}` *(Counter)* — liczba przyjętych rekordów.
- `core_level_total{level}` *(Counter)* — rozkład poziomów logów.
- `core_bytes_total` *(Counter)* — bajty odebrane (suma `len(body)`).
- `core_rejected_total{reason}` *(Counter)* — odrzucenia:
  - `reason="too_large"` — body przekracza `CORE_MAX_BODY_BYTES`,
  - `reason="too_many_items"` — liczba elementów > `CORE_MAX_ITEMS`.

---

## NDJSON (opcjonalne)

Gdy `CORE_SINK_FILE=true`, Core dopisuje każdy rekord do dziennego pliku:
```
<DIR>/<YYYYMMDD>.ndjson
```
gdzie `<DIR>` to (w tej kolejności): `LOGOPS_SINK_DIR` → `CORE_SINK_DIR` → `./data/ingest`.

Do każdego rekordu dopisywane są (jeśli brak):
- `app="logops"`, `source="core"`,
- `emitter` (z nagłówka lub `"unknown"`),
- `scenario_id` (z nagłówka lub `"na"`).

---

## Przykłady

### 1) Prosty batch (array)
```bash
curl -s http://127.0.0.1:8095/v1/logs \
  -H "Content-Type: application/json" \
  -H "X-Emitter: json" \
  -H "X-Scenario-Id: sc-local" \
  -d '[{"ts":"2025-09-09T10:00:00Z","level":"INFO","msg":"hello"},{"level":"WARN","msg":"oops"}]'
```
Odpowiedź:
```json
{"accepted":2}
```

### 2) Pojedynczy obiekt
```bash
curl -s http://127.0.0.1:8095/v1/logs \
  -H "Content-Type: application/json" \
  -d '{"level":"error","msg":"single"}'
```

### 3) Za duże body (`413`)
```bash
python - <<'PY'
print("A" * (2*1024*1024))
PY > big.json
curl -s http://127.0.0.1:8095/v1/logs \
  -H "Content-Type: application/json" \
  --data-binary @big.json
# {"detail":"payload too large"}
```

### 4) Za dużo elementów (`413`)
```bash
python - <<'PY'
import json
print(json.dumps([{"i": i} for i in range(6000)]))
PY > many.json
curl -s http://127.0.0.1:8095/v1/logs \
  -H "Content-Type: application/json" \
  --data-binary @many.json
# {"detail":"too many items"}
```

### 5) Debug
- `GET /_debug/hdrs` — podgląd nagłówków i wartości ENV, które Core widzi.
- `GET /_debug/stats` — ostatnie rekordy (ucięte `msg` do 200 znaków dla czytelności).

---

## Uruchomienie lokalne

Uvicorn:
```bash
uvicorn services.core.app:app --host 0.0.0.0 --port 8095 --reload
```

Przykładowe ENV (bash):
```bash
export CORE_SINK_FILE=true
export LOGOPS_SINK_DIR=./data/ingest
export CORE_MAX_BODY_BYTES=1048576
export CORE_MAX_ITEMS=5000
```

---

## Uwagi operacyjne

- **Nagłówki transportowe**: jeśli wysyłasz przez AuthGW/IngestGW, pamiętaj o przekazywaniu `X-Emitter` i `X-Scenario-Id`, by metryki w Core miały sensowną kardynalność.
- **Bufor debugowy**: to tylko „podgląd” ostatnich rekordów — nie traktuj jako trwałego storage.
- **NDJSON**: jeśli jednocześnie Ingest i Core zapisują NDJSON, uzgodnij, które źródło jest „prawdziwe” dla Promtail (unikniesz duplikatów).
- **Limity**: `CORE_MAX_BODY_BYTES` i `CORE_MAX_ITEMS` w Core **nie zastępują** backpressure u upstreamów — to ostatnia linia obrony.

---

## Checklist

- [ ] Core uruchomiony (`/healthz` zwraca `{"ok": true}`).
- [ ] `X-Emitter` / `X-Scenario-Id` przekazywane w łańcuchu proxy.
- [ ] `CORE_SINK_FILE` i *DIR* ustawione zgodnie z polityką artefaktów.
- [ ] Monitorujesz `core_request_latency_seconds`, `core_accepted_total`, `core_level_total`, `core_rejected_total`.
- [ ] Limity (`CORE_MAX_BODY_BYTES`, `CORE_MAX_ITEMS`) dopasowane do typowych batchy.

---
