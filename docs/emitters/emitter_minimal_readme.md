# emitter_minimal

Najprostszy smoke-test: wysyła **tylko `msg`** w batchu JSON. Resztę uzupełni gateway.

- **Kod:** `emitters/emitter_minimal/emit_minimal.py`
- **Endpoint:** `http://127.0.0.1:8080/v1/logs`
- **Content-Type:** `application/json`

## Uruchomienie
```bash
python emitters/emitter_minimal/emit_minimal.py -n 10
```
**Parametry**

- `-n, --num` – liczba rekordów (domyślnie: 10)
## Format danych (fragment batcha)
```json
[
  {"msg": "minimal #1"},
  {"msg": "minimal #2"}
]
```
## Co zrobi gateway
- doda `ts` (UTC now) i `level` (`INFO`)

- zmaskuje PII w `msg` (gdyby się pojawiło)

- (opcjonalnie) zapisze NDJSON do `./data/ingest/...` jeśli włączysz sink
## Loki / Grafana (Explore)
Z nagłówkiem `X-Emitter`: `emitter_minimal`:
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_minimal"}
```
Bez nagłówka:
```arduino
{job="logops-ndjson", app="logops"}
```
Flow

JSON (tylko `msg`) → `POST /v1/logs` → normalizacja → (opcjonalnie) NDJSON → Promtail → Loki → Grafana