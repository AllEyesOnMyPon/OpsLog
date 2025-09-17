# emitter_syslog

Emituje linie tekstowe **syslog-like** i wysyła je jako `text/plain`.

- **Kod:** `emitters/syslog.py`
- **Domyślny endpoint:** `http://127.0.0.1:8081/ingest` (AuthGW, HMAC)
- **Content-Type:** `text/plain`

> Uwaga: domyślnie wysyłamy przez **AuthGW** (HMAC). Aby pominąć HMAC i trafić bezpośrednio do IngestGW, użyj `--ingest-url http://127.0.0.1:8080/v1/logs`.

---

## Wymagania

- Działające usługi (`make stack-start` lub `make demo`).
- Jeśli idziesz przez AuthGW, ustaw klucze klienta (zgodne z `make authgw-config`):
  ```bash
  export LOGOPS_API_KEY=demo-pub-5
  export LOGOPS_SECRET=demo-priv-5
  ```

---

## Uruchomienie

### Najprościej (modułowo)
```bash
python -m emitters.syslog \
  --scenario-id "sc-syslog-$(date +%s)" \
  --duration 8 --eps 12 --batch-size 8 \
  --partial-ratio 0.3 --seed 123
```

### Bezpośrednio (skrypt)
```bash
./emitters/syslog.py \
  --scenario-id "sc-syslog-$(date +%s)" \
  --duration 8 --eps 12 --batch-size 8 \
  --partial-ratio 0.3 --seed 123
```

**Parametry**

- `--ingest-url` – endpoint wejściowy (domyślnie **AuthGW** `http://127.0.0.1:8081/ingest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (etykieta w logach/metrykach)
- `--emitter` – nazwa emitera (domyślnie: `syslog`)
- `--eps` – średnia liczba linii/sek (domyślnie: `10`)
- `--duration` – czas trwania w sekundach (domyślnie: `60`)
- `--batch-size` – ile linii w jednym żądaniu (domyślnie: `10`)
- `--jitter-ms` – losowy jitter (ms) między batchami (domyślnie: `0`)
- `--partial-ratio` – udział „uboższych” linii bez poziomu/hosta `0.0–1.0` (domyślnie: `0.3`)
- `--seed` – ziarno RNG (opcjonalnie)

Na końcu program wypisze statystykę:
```
SC_STAT {"sent": <liczba_wysłanych_linii>}
```

---

## Format linii (przykład)

```text
2025-08-24 15:22:10 INFO my-host web[1234]: request served #1 user=user1@example.com ip=83.11.23.45
```

Linie są budowane w wariancie „pełnym” lub uproszczonym (gdy działa `--partial-ratio`), np. bez `level/host`.

---

## Co zrobi gateway (IngestGW)

- **Parsowanie:** regexem wyciąga `ts` i ewentualnie `level`; cała reszta trafia do pola `msg`.
- **Normalizacja:** mapowanie poziomów (`WARN → WARN`, itp.), uzupełnianie braków (`ts`, `level`).
- **PII:** maskowanie/szyfrowanie e-maili i IP (jeśli włączone).
- **Etykiety:** dokleja `app="logops"`, `source="ingest"`, `emitter`, `scenario_id` (z nagłówków).
- **Metryki Prometheus:** m.in. `logops_ingested_total{level,...}`, błędy parsowania, histogram p95.
- **NDJSON (opcjonalnie):** zapis do `./data/ingest/YYYYMMDD.ndjson` przy `LOGOPS_SINK_FILE=true`.

---

## Loki / Grafana (Explore)

Z nagłówkami `X-Emitter: syslog`, `X-Scenario-Id: sc-…`:

```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="syslog", scenario_id="sc-..."}
```

Albo szerzej:
```logql
{job="logops-ndjson", app="logops", source="ingest"}
```

---

## Flow

`text/plain` syslog-like → `POST /ingest` (AuthGW, HMAC) → IngestGW (`/v1/logs`) → normalizacja + metryki → *(opcjonalnie)* NDJSON → Promtail → Loki → Grafana

*(Alternatywa bez HMAC: `POST /v1/logs` bezpośrednio do IngestGW przy `--ingest-url http://127.0.0.1:8080/v1/logs`.)*
