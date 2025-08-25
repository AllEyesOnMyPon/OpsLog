# emitter_syslog

Emituje linie tekstowe **syslog-like** (`YYYY-mm-dd HH:MM:SS LEVEL host app[pid]: message ...`) i wysyła jako `text/plain`.

- **Kod:** `emitters/emitter_syslog/emit_syslog.py`
- **Endpoint:** `http://127.0.0.1:8080/v1/logs`
- **Content-Type:** `text/plain`

## Uruchomienie
```bash
python emitters/emitter_syslog/emit_syslog.py -n 10 --partial-ratio 0.3
```
**Parametry**

- `-n, --num` – liczba linii (domyślnie: 10)

- `--partial-ratio` – udział „uboższych” linii (np. bez level/host) `0.0–1.0` (domyślnie: 0.3)
## Format danych (przykład linii)
```perl
2025-08-24 15:22:10 INFO my-host web[1234]: request served #1 user=user1@example.com ip=83.11.23.45
```
## Co zrobi gateway

- regexem wyciągnie `ts` i opcjonalnie `level`, reszta trafi do `msg`

- zmapuje `level`, zmaskuje PII (email/IP), doda `emitter` z nagłówka jeśli podasz

- (opcjonalnie) zapisze NDJSON do `./data/ingest/...`

## Loki / Grafana (Explore)

Z nagłówkiem `X-Emitter`: `emitter_syslog`:
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_syslog"}
```
Bez nagłówka:
```arduino
{job="logops-ndjson", app="logops"}
```
## Flow

text/plain syslog-like → `POST /v1/logs` → normalizacja → (opcjonalnie) NDJSON → Promtail → Loki → Grafana