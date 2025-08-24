# emitter_json

Generator ustrukturyzowanych logów **JSON** (jak typowe logi aplikacyjne) wysyłanych w **batchu**.

- **Kod:** `emitters/emitter_json/emit_json.py`
- **Endpoint:** `http://127.0.0.1:8080/v1/logs`
- **Content-Type:** `application/json` (automatycznie przez `requests.post(..., json=...)`)

## Uruchomienie
```bash
python emitters/emitter_json/emit_json.py -n 10 --partial-ratio 0.3
```
**Parametry**

- `-n, --num` – liczba rekordów (domyślnie: 10)

- `--partial-ratio` – odsetek rekordów bez timestamp/level (0.0–1.0; domyślnie: 0.3)
## Format danych (przykład jednego rekordu)
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
## Co zrobi gateway

- `timestamp` potraktuje jako `ts` (gdy brakuje → doda bieżący UTC)

- zmapuje `level` (`warning→WARN`, itp.)

- zmaskuje PII w `message`; przy `LOGOPS_ENCRYPT_PII=true` doda `msg_enc`, `user_email_enc`, `client_ip_enc`
## Loki / Grafana (Explore)
Jeśli dostaniesz etykietę `emitter` (np. dodając nagłówek `X-Emitter`: `emitter_json`):
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_json"}
```
Inaczej:
```arduino
{job="logops-ndjson", app="logops"}
```
## Flow

JSON batch → `POST /v1/logs` → normalizacja → (opcjonalnie) NDJSON → Promtail → Loki → Grafana