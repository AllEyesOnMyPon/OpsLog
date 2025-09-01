# Ingest Gateway (FastAPI)

Przyjmuje logi (JSON/CSV/syslog-like), **normalizuje** je (timestamp/level/PII), opcjonalnie **zapisuje do NDJSON**, odsłania **metryki Prometheus** i **health**.

> Wersja: `v7-pii-encryption`  
> Plik: `services/ingest_gateway/gateway.py`

---

## Endpointy

- `GET /healthz` — status serwisu i konfiguracji (m.in. flaga szyfrowania PII i sink do pliku)
- `GET /metrics` — metryki Prometheus (exposition format)
- `POST /v1/logs` — ingest logów (JSON/CSV/syslog-like)

---

## `/v1/logs` — formaty wejściowe

**Nagłówki opcjonalne**
- `X-Emitter: <nazwa>` — wypełnia pole `emitter` (jeśli brak w rekordzie).
- `X-Scenario: <nazwa>` — etykietuje żądanie scenariuszem (raportowane w odpowiedzi i logach).

**Obsługiwane Content-Type:**
1. `application/json`
   - Pojedynczy obiekt **lub** tablica obiektów.
   - **Walidacja „miękka”** Pydantic: niepoprawne rekordy → **422** z listą indeksów.
2. `text/csv`
   - Wymagany nagłówek kolumn: `ts,level,msg`  
   - Pola dodatkowe wspierane: `user_email, client_ip`
3. `text/plain`
   - Syslog-like, **1 linia = 1 rekord**.  
   - Regex wyciąga `ts` (`YYYY-MM-DD HH:MM:SS`), opcjonalny `LEVEL` i `message`; usuwa prefiksy typu `host app[pid]:`.

**Błędy wejścia:**
- Niepoprawny JSON → **400** (`"Invalid JSON body"`)
- JSON nie będący obiektem/arrayem → **400**
- JSON array z wadliwymi rekordami → **422** + `invalid_indices`

---

## Normalizacja (co robi gateway)

- **Timestamp (`ts`)**
  - Wejście: któreś z `ts` / `timestamp` / `time`.  
  - Jeśli brak → **dodaje** `now()` w UTC (ISO8601).
- **Poziom (`level`)**
  - Mapa: `debug→DEBUG`, `warn|warning→WARN`, `fatal→ERROR`, brak→`INFO`.
- **Wiadomość (`msg`)**
  - Źródło: `message` / `msg` / `log` / `raw` (fallback: `""`).  
  - **Maskowanie PII** w tekście:
    - e-mail → `j***@domena`
    - IPv4 → `a.b.x.x`
- **PII encryption (opcjonalnie)**
  - Jeśli `LOGOPS_ENCRYPT_PII=true` i jest `LOGOPS_SECRET_KEY` (Fernet):
    - Dodaje `msg_enc` (zaszyfrowane **pełne** `raw_msg`).
    - Dla nazw z `LOGOPS_ENCRYPT_FIELDS` (domyślnie `user_email,client_ip`) dodaje `<pole>_enc`.
    - Jednocześnie **zostawia zamaskowane** `user_email`/`client_ip` (czytelne do inspekcji).
- **`emitter`**
  - Jeśli nagłówek `X-Emitter` był ustawiony, a rekord nie ma własnego `emitter`, pole zostanie dopisane.
- **SINK do pliku (opcjonalnie)**
  - Jeśli `LOGOPS_SINK_FILE=true`: dopisuje NDJSON do `LOGOPS_SINK_DIR` (domyślnie `./data/ingest`) w pliku `YYYYMMDD.ndjson`.
  - Do pliku **nie** trafiają pola techniczne zaczynające się od `_`.

**Flagi techniczne (wewnętrzne, nie zapisuje do NDJSON):**
- `_missing_ts: bool`, `_missing_level: bool`

> 🔎 Uwaga: `X-Scenario` jest raportowany w odpowiedzi i logach serwera; nie jest obecnie dołączany do rekordów w NDJSON.

---

## Metryki Prometheus

**Przepływ żądania**
- `logops_inflight` *(Gauge)* — ile żądań `/v1/logs` jest aktualnie przetwarzanych.

**Batch**
- `logops_batch_size` *(Histogram)* — wielkość przychodzących batchy (liczba rekordów).  
- `logops_batch_latency_seconds` *(Histogram)* — czas przetwarzania batcha.  
  ➜ **Używaj do SLO p95** (patrz niżej).

**Akceptacje / braki**
- `logops_ingested_total{emitter,level}` — liczba **przyjętych** rekordów per `emitter` i `level`.
- `logops_missing_ts_total{emitter}` — liczba rekordów bez `ts` po normalizacji.
- `logops_missing_level_total{emitter}` — liczba rekordów bez `level` po normalizacji.

**Walidacja**
- `logops_parse_errors_total{emitter}` — liczba odrzuconych rekordów JSON (walidacja).

*(W kodzie są również zdefiniowane liczniki per-scenario — na razie niewykorzystywane).*

---

## ENV (kluczowe)

- `LOGOPS_ENCRYPT_PII` (`true|false`, domyślnie `false`)
- `LOGOPS_SECRET_KEY` (wymagane, gdy szyfrowanie = true; klucz **Fernet**)
- `LOGOPS_ENCRYPT_FIELDS` (CSV pól do szyfrowania; domyślnie `user_email,client_ip`)
- `LOGOPS_DEBUG_SAMPLE` (`true|false`) + `LOGOPS_DEBUG_SAMPLE_SIZE` (domyślnie `2`)
- `LOGOPS_SINK_FILE` (`true|false`) + `LOGOPS_SINK_DIR` (domyślnie `./data/ingest`)
- `LOGOPS_HOUSEKEEP_AUTORUN` (`true|false`) — jednorazowy housekeeping na starcie i (opcjonalnie) pętla
- `LOGOPS_HOUSEKEEP_INTERVAL_SEC` — interwał dla pętli housekeeping (sekundy; >0 uruchamia pętlę)

`GET /healthz` zwraca m.in. `pii_encryption`, `file_sink` i `file_sink_dir`.

---

## Przykłady wywołań

### JSON (tablica)
```bash
curl -s http://localhost:8080/v1/logs \
  -H "Content-Type: application/json" \
  -H "X-Emitter: emitter_json" \
  -H "X-Scenario: spike" \
  -d '[{"ts":"2025-08-23T12:00:00Z","level":"warn","msg":"user john@example.com from 10.1.2.3"}]'
```

### CSV
```bash
python emitters/emitter_csv/emit_csv.py -n 5 --partial-ratio 0.2
# wysyła text/csv: ts,level,msg (+ ewent. user_email,client_ip)
```

### text/plain (syslog-like)
```bash
curl -s http://localhost:8080/v1/logs \
  -H "Content-Type: text/plain" \
  -H "X-Emitter: emitter_syslog" \
  --data-binary $'2025-08-23 12:00:00 INFO nginx[1234]: GET /health from 192.168.1.23'
```

### PowerShell (Windows) — JSON (obiekt)
```powershell
irm "http://localhost:8080/v1/logs" -Method Post -ContentType "application/json" `
  -Headers @{ "X-Emitter" = "emitter_json"; "X-Scenario" = "default" } `
  -Body '{"msg":"hello from ps","level":"info"}'
```

**Odpowiedź** (gdy `LOGOPS_DEBUG_SAMPLE=true`):
```json
{
  "accepted": 5,
  "ts": "2025-08-23T12:00:00.123456+00:00",
  "emitter": "emitter_json",
  "scenario": "spike",
  "missing_ts": 1,
  "missing_level": 1,
  "levels": {"INFO": 4, "WARN": 1},
  "sample": [
    {"ts":"...","level":"INFO","msg":"masked ...","emitter":"emitter_json"}
  ]
}
```

---

## Przepływ do observability

`/v1/logs` → (opcjonalny) **NDJSON** w `./data/ingest/*.ndjson` → **Promtail** (labels m.in. `job="logops-ndjson"`, `app="logops"`, `level`, `emitter`) → **Loki** → **Grafana**

### Szybkie zapytanie (Explore/Loki):
```logql
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```

---

## SLO p95 (latencja batcha) — Prometheus/Grafana

Histogram `logops_batch_latency_seconds` pozwala policzyć p95:

```promql
histogram_quantile(
  0.95,
  sum(rate(logops_batch_latency_seconds_bucket[5m])) by (le)
)
```

**Przykładowe alerty (zależnie od polityki):**
- p95 > 500ms przez 10m,
- brak metryk z instancji przez 5m,
- gwałtowny wzrost `logops_parse_errors_total`.

---

## Housekeeping

Jeśli `LOGOPS_HOUSEKEEP_AUTORUN=true`:
- przy starcie wywoła się `tools.housekeeping.run_once()`,
- gdy `LOGOPS_HOUSEKEEP_INTERVAL_SEC > 0`, uruchomi się pętla okresowa z zadanym interwałem.

Logi housekeeping oznaczane są prefiksem `[housekeep]`.

---

## Uwagi implementacyjne

- **PII**: Maskowanie zawsze dzieje się na `msg` (widziane w logach/NDJSON). Szyfrowanie dodaje oddzielne pola `*_enc` z pełnymi wartościami (base64), bez ingerencji w wersje zamaskowane do podglądu.  
- **Scenario**: `X-Scenario` służy do raportowania kontekstu wywołania i łatwego grupowania w logach/odpowiedzi. Aktualnie nie jest zapisywany w NDJSON (celowo — by nie „zaśmiecać” danych; można to włączyć w przyszłości).  
- **CSV**: W parserze `ts/level/msg` są kluczowe; `user_email/client_ip` przechodzą, by mogły zostać zamaskowane/szyfrowane.  
- **Syslog-like**: Gdy regex nie zadziała, linia trafia jako `msg` (z `level=INFO`, `ts=now()`), co gwarantuje brak odrzuceń wejścia w tym trybie.
