# emitter_csv

Generator logów w formacie **CSV** i wysyłka do gatewaya jako `text/csv`.

- **Kod:** `emitters/csv.py`
- **Domyślny endpoint:** `http://127.0.0.1:8081/ingest` (AuthGW, HMAC)
- **Content-Type:** `text/csv`

> Uwaga: Domyślnie wysyłamy przez **AuthGW** (HMAC). Aby ominąć HMAC i trafić bezpośrednio do IngestGW, użyj `--ingest-url http://127.0.0.1:8080/v1/logs`.

---

## Wymagania

- Uruchomione usługi (np. `make stack-start` albo `make demo`).
- Dla trybu przez AuthGW: zmienne środowiskowe z kluczem klienta (spójne z `authgw-config`):
  ```bash
  export LOGOPS_API_KEY=demo-pub-3
  export LOGOPS_SECRET=demo-priv-3
  ```
  (w `make authgw-config` klucz `demo-pub-3` jest przypięty do emitera `csv`).

---

## Uruchomienie

### Najprościej (modułowo)
```bash
python -m emitters.csv \
  --scenario-id "sc-csv-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 3 \
  --partial-ratio 0.3
```

### Bezpośrednio (skrypt)
```bash
./emitters/csv.py \
  --scenario-id "sc-csv-$(date +%s)" \
  --duration 8 --eps 6 --batch-size 3 \
  --partial-ratio 0.3
```

**Parametry**

- `--ingest-url` – endpoint wejściowy (domyślnie: **AuthGW** `http://127.0.0.1:8081/ingest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (doklejany jako etykieta)
- `--emitter` – nazwa emitera (domyślnie: `csv`)
- `--eps` – średnia liczba rekordów/sek (domyślnie: `10`)
- `--duration` – czas trwania w sekundach (domyślnie: `60`)
- `--batch-size` – ile rekordów w jednej paczce/żądaniu (domyślnie: `10`)
- `--jitter-ms` – losowy jitter (ms) między paczkami (domyślnie: `0`)
- `--partial-ratio` – odsetek niepełnych wierszy (bez `ts/level`) w zakresie `0.0–1.0` (domyślnie: `0.3`)
- `--seed` – ziarno RNG dla powtarzalności (domyślnie: brak)

Na końcu program wypisuje statystykę:
```
SC_STAT {"sent": <liczba_wysłanych_rekordów>}
```

---

## Format danych

Nagłówek: `ts,level,msg`

Przykład (częściowo „ubożone” wiersze):
```csv
ts,level,msg
2025-08-24T15:22:10+0200,INFO,"csv event #1"
,,"csv event #2"
```

- Czas `ts` generowany jest w formacie `YYYY-MM-DDTHH:MM:SS±ZZZZ`.
- `partial_ratio` steruje udziałem pustych `ts/level` (test braków).

---

## Co zrobi gateway

Po stronie **IngestGW** (`services/ingestgw/app.py`):

- sparsuje CSV i **znormalizuje** rekordy (patrz `normalize.py`),
- **nadpisze/doklei etykiety** z nagłówków transportowych: `emitter`, `scenario_id`, oraz `app="logops"`, `source="ingest"`,
- policzy metryki Prometheus (np. `logops_ingested_total`, `logops_missing_ts_total`, `logops_missing_level_total`, `logops_accepted_total`, histogram p95),
- opcjonalnie zapisze NDJSON do `./data/ingest/YYYYMMDD.ndjson` jeśli `LOGOPS_SINK_FILE=true`,
- (jeśli włączysz mechanizmy ochrony PII w konfiguracji) **zamaskuje/szyfruje** wybrane pola.

---

## Loki / Grafana (Explore)

Jeśli wysyłasz przez AuthGW/IngestGW z nagłówkami transportowymi (klient dokleja `X-Emitter` i `X-Scenario-Id`), to w Loki masz etykiety:

```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="csv", scenario_id="sc-..."}
```

Możesz też filtrować szerzej:
```logql
{job="logops-ndjson", app="logops", source="ingest"}
```

> Uwaga: Nazwa `job="logops-ndjson"` pochodzi z konfiguracji Promtail (docker). Jeśli ją zmienisz, dopasuj filtr.

---

## Flow

CSV → `POST /ingest` (AuthGW, HMAC) → IngestGW (`/v1/logs`) → normalizacja + metryki → (opcjonalnie) NDJSON → Promtail → Loki → Grafana

*(Alternatywnie, z pominięciem HMAC: CSV → `POST /v1/logs` bezpośrednio do IngestGW przy `--ingest-url http://127.0.0.1:8080/v1/logs`.)*
