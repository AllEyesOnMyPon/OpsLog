# Ingest Gateway (FastAPI)

Przyjmuje logi (JSON/CSV/syslog-like), **normalizuje** je (timestamp/level/PII), opcjonalnie **zapisuje do NDJSON**, odsłania **metryki Prometheus** i **health**.

> Wersja: `v7-pii-encryption`  
> Plik: `services/ingest_gateway/gateway.py`

---

## Endpointy

- `GET /healthz` — status serwisu i konfiguracji
- `GET /metrics` — metryki Prometheus (exposition format)
- `POST /v1/logs` — ingest logów

---

## `/v1/logs` — formaty wejściowe

**Nagłówek opcjonalny**
- `X-Emitter: <nazwa>` — uzupełnia pole `emitter` dla każdego rekordu, jeśli nie ma go w payloadzie.

**Content-Types obsługiwane:**
1. `application/json`
   - Pojedynczy obiekt **lub** tablica obiektów.
2. `text/csv`
   - Wymagany nagłówek kolumn: `ts,level,msg`  
   - Pola dodatkowe wspierane: `user_email, client_ip`
3. `text/plain`
   - Syslog-like, **1 linia = 1 rekord**, regex wyciąga `ts`, `level`, `message`.

---

## Normalizacja (co robi gateway)

- **Timestamp (`ts`)**
  - Wejście: `ts`/`timestamp`/`time`; jeśli brak → **dodaje** `now()` w UTC.
- **Poziom (`level`)**
  - Mapa: `debug→DEBUG`, `warn/warning→WARN`, `fatal→ERROR`, brak→`INFO`.
- **Wiadomość (`msg`)**
  - Z `message`/`msg`/`log`/`raw`; **maskowanie PII** w tekście:
    - e-mail → `j***@domena`
    - IP → `a.b.x.x`
- **PII encryption (opcjonalnie)**
  - Jeśli `LOGOPS_ENCRYPT_PII=true` i podasz `LOGOPS_SECRET_KEY` (Fernet):
    - Dokłada pola: `msg_enc`, oraz `<pole>_enc` dla nazw z `LOGOPS_ENCRYPT_FIELDS` (domyślnie `user_email,client_ip`).
    - Jednocześnie pozostawia zamaskowane `user_email`/`client_ip` (czytelne, ale bez pełnych danych).
- **SINK do pliku (opcjonalnie)**
  - Jeśli `LOGOPS_SINK_FILE=true`, dopisuje NDJSON do `LOGOPS_SINK_DIR` (domyślnie `./data/ingest`) w pliku `YYYYMMDD.ndjson`.

**Flagi techniczne (wewnętrzne, nie zapisuje do NDJSON):**
- `_missing_ts: bool`, `_missing_level: bool`

---

## Metryki Prometheus

- `logops_accepted_total` — liczba przyjętych rekordów
- `logops_missing_ts_total` — ile rekordów bez `ts`
- `logops_missing_level_total` — ile rekordów bez `level`
- `logops_inflight` (Gauge) — aktualnie przetwarzane rekordy

---

## ENV (kluczowe)

- `LOGOPS_ENCRYPT_PII` (`true|false`, domyślnie `false`)
- `LOGOPS_SECRET_KEY` (wymagane, gdy szyfrowanie = true; klucz **Fernet**)
- `LOGOPS_ENCRYPT_FIELDS` (CSV pól do szyfrowania; domyślnie `user_email,client_ip`)
- `LOGOPS_DEBUG_SAMPLE` (`true|false`) + `LOGOPS_DEBUG_SAMPLE_SIZE` (domyślnie `2`)
- `LOGOPS_SINK_FILE` (`true|false`) + `LOGOPS_SINK_DIR` (domyślnie `./data/ingest`)
- `LOGOPS_HOUSEKEEP_AUTORUN` (`true|false`) + `LOGOPS_HOUSEKEEP_INTERVAL_SEC` (sekundy)

`GET /healthz` zwraca kluczowe info (czy włączone szyfrowanie/sink itp.).

---

## Przykłady wywołań

### JSON (tablica)
```bash
curl -s http://localhost:8080/v1/logs \
  -H "Content-Type: application/json" -H "X-Emitter: emitter_json" \
  -d '[{"ts":"2025-08-23T12:00:00Z","level":"warn","msg":"user john@example.com from 10.1.2.3"}]'
```
### CSV
```bash
python emitters/emitter_csv.py -n 5 --partial-ratio 0.2
# wysyła text/csv: ts,level,msg  (+ ewent. user_email,client_ip)
```
### text/plain (syslog-like)
```bash
curl -s http://localhost:8080/v1/logs \
  -H "Content-Type: text/plain" -H "X-Emitter: emitter_syslog" \
  --data-binary $'2025-08-23 12:00:00 INFO nginx[1234]: GET /health from 192.168.1.23'
```
### PowerShell (Windows) — JSON (obiekt)
```powershell
irm "http://localhost:8080/v1/logs" -Method Post -ContentType "application/json" `
  -Headers @{ "X-Emitter" = "emitter_json" } `
  -Body '{"msg":"hello from ps","level":"info"}'
```
Odpowiedź (przykład) — przy `LOGOPS_DEBUG_SAMPLE=true`:
```json
{
  "accepted": 5,
  "ts": "2025-08-23T12:00:00.123456+00:00",
  "missing_ts": 1,
  "missing_level": 1,
  "sample": [
    {"ts":"...","level":"INFO","msg":"masked ...","emitter":"..."}
  ]
}
```
## Przepływ do observability

`/v1/logs` → (opcjonalny) **NDJSON** w `./data/ingest/*.ndjson` → **Promtail** (labels: `job="logops-ndjson"`, `app="logops"`, `level`, `emitter`) → **Loki** → **Grafana**

### Szybkie zapytanie (Explore/Loki):
```bash
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```

