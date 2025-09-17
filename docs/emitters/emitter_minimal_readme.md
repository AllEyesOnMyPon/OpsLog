# emitter_minimal

Najprostszy smoke-test: wysyła **tylko `msg`** w batchu JSON. Resztę uzupełni **IngestGW**.

- **Kod:** `emitters/minimal.py`
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
python -m emitters.minimal \
  --scenario-id "sc-min-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 5
```

### Bezpośrednio (skrypt)
```bash
./emitters/minimal.py \
  --scenario-id "sc-min-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 5
```

**Parametry**

- `--ingest-url` – endpoint wejściowy (domyślnie **AuthGW** `http://127.0.0.1:8081/ingest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (do etykiet/logów)
- `--emitter` – nazwa emitera (domyślnie: `minimal`)
- `--eps` – średnia liczba rekordów/sek (domyślnie: `10`)
- `--duration` – czas trwania w sekundach (domyślnie: `60`)
- `--batch-size` – ile rekordów w jednym żądaniu (domyślnie: `10`)
- `--jitter-ms` – losowy jitter (ms) między batchami (domyślnie: `0`)

Na końcu program wypisze statystykę:
```
SC_STAT {"sent": <liczba_wysłanych_rekordów>, "level_counts": {"INFO": <...>}}
```

---

## Format danych (fragment batcha)

```json
[
  {"msg": "minimal #1"},
  {"msg": "minimal #2"}
]
```

---

## Co zrobi gateway

Po stronie **IngestGW**:

- nada brakujące pola: `ts` (UTC now) i `level` (domyślnie `INFO`),
- **nadpisze/doklei** etykiety z nagłówków: `emitter`, `scenario_id`, + `app="logops"`, `source="ingest"`,
- policzy metryki Prometheus (m.in. `logops_ingested_total`, `logops_accepted_total`, histogram p95),
- opcjonalnie zapisze NDJSON do `./data/ingest/YYYYMMDD.ndjson` (jeśli `LOGOPS_SINK_FILE=true`),
- przy włączonym szyfrowaniu PII (`LOGOPS_ENCRYPT_PII=true`) zaszyfruje wskazane pola, gdy wystąpią.

---

## Loki / Grafana (Explore)

Dzięki nagłówkom `X-Emitter` i `X-Scenario-Id` możesz filtrować:

```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="minimal", scenario_id="sc-..."}
```

Albo szerzej:
```logql
{job="logops-ndjson", app="logops", source="ingest"}
```

---

## Flow

JSON (tylko `msg`) → `POST /ingest` (AuthGW, HMAC) → IngestGW (`/v1/logs`) → normalizacja + metryki → *(opcjonalnie)* NDJSON → Promtail → Loki → Grafana

*(Alternatywa bez HMAC: JSON → `POST /v1/logs` bezpośrednio do IngestGW przy `--ingest-url http://127.0.0.1:8080/v1/logs`.)*
