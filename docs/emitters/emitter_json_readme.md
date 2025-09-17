# emitter_json

Generator ustrukturyzowanych logów **JSON** (typowe logi aplikacyjne) wysyłanych **w batchu**.

- **Kod:** `emitters/json.py`
- **Domyślny endpoint:** `http://127.0.0.1:8081/ingest` (AuthGW, HMAC)
- **Content-Type:** `application/json`

> Uwaga: domyślnie wysyłamy przez **AuthGW** (HMAC). Aby ominąć HMAC i trafić bezpośrednio do IngestGW, użyj `--ingest-url http://127.0.0.1:8080/v1/logs`.

---

## Wymagania

- Działające usługi (np. `make stack-start` albo po prostu `make demo`).
- Dla trybu przez AuthGW ustaw klucze klienta (zgodne z `make authgw-config`):
  ```bash
  export LOGOPS_API_KEY=demo-pub-1
  export LOGOPS_SECRET=demo-priv-1
  ```

---

## Uruchomienie

### Najprościej (modułowo)
```bash
python -m emitters.json \
  --scenario-id "sc-json-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 3 \
  --partial-ratio 0.3
```

### Bezpośrednio (skrypt)
```bash
./emitters/json.py \
  --scenario-id "sc-json-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 3 \
  --partial-ratio 0.3
```

**Parametry**

- `--ingest-url` – endpoint wejściowy (domyślnie **AuthGW** `http://127.0.0.1:8081/ngest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (do etykiet/logów)
- `--emitter` – nazwa emitera (domyślnie: `json`)
- `--eps` – średnia liczba rekordów/sek (domyślnie: `10`)
- `--duration` – czas trwania w sekundach (domyślnie: `60`)
- `--batch-size` – ile rekordów w jednym żądaniu (domyślnie: `10`)
- `--jitter-ms` – losowy jitter (ms) między batchami (domyślnie: `0`)
- `--partial-ratio` – odsetek rekordów bez `timestamp/level` (`0.0–1.0`, domyślnie: `0.3`)
- `--seed` – ziarno RNG (powtarzalność)

Na końcu program wypisze statystykę:
```
SC_STAT {"sent": <liczba_wysłanych_rekordów>}
```

---

## Format danych (przykład rekordu)

```json
{
  "timestamp": "2025-08-24T15:22:10+0200",
  "level": "warning",
  "message": "request served #1",
  "service": "emitter-json",
  "env": "dev",
  "host": "my-host",
  "request_id": "req-000001",
  "user_email": "user1@example.com",
  "client_ip": "83.11.23.45",
  "attrs": { "path": "/api/v1/resource", "method": "GET", "latency_ms": 123, "version": "1.0.0" }
}
```

> `--partial-ratio` steruje udziałem rekordów bez `timestamp` i/lub `level` (pomaga testować normalizację i liczniki błędów).

---

## Co zrobi gateway

Po stronie **IngestGW** (`services/ingestgw/app.py`):

- sparsuje batch JSON i **znormalizuje** rekordy (patrz `normalize.py`),
- potraktuje `timestamp` jako `ts` (gdy brakuje → doda bieżący UTC),
- zmapuje `level` (`warning→WARN` itp., ujednolicenie do UPPER),
- **nadpisze/doklei** etykiety z nagłówków: `emitter`, `scenario_id`, + `app="logops"`, `source="ingest"`,
- policzy metryki Prometheus: m.in. `logops_ingested_total`, `logops_accepted_total`, `logops_missing_ts_total`, `logops_missing_level_total`, histogram p95 (`logops_batch_latency_seconds_bucket`),
- opcjonalnie zapisze NDJSON do `./data/ingest/YYYYMMDD.ndjson` (jeśli `LOGOPS_SINK_FILE=true`),
- przy włączonym szyfrowaniu PII (`LOGOPS_ENCRYPT_PII=true`) zaszyfruje wskazane pola (np. `user_email`, `client_ip`) i doda `*_enc`.

---

## Loki / Grafana (Explore)

Klient dokleja nagłówki `X-Emitter` i `X-Scenario-Id`, więc w Loki masz etykiety:

```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="json", scenario_id="sc-..."}
```

Szerzej:
```logql
{job="logops-ndjson", app="logops", source="ingest"}
```

> Nazwa `job="logops-ndjson"` pochodzi z konfiguracji Promtail (compose). Jeśli ją zmienisz, zaktualizuj filtr.

---

## Flow

JSON batch → `POST /ingest` (AuthGW, HMAC) → IngestGW (`/v1/logs`) → normalizacja + metryki → *(opcjonalnie)* NDJSON → Promtail → Loki → Grafana

*(Alternatywa bez HMAC: JSON → `POST /v1/logs` bezpośrednio do IngestGW przy `--ingest-url http://127.0.0.1:8080/v1/logs`.)*
