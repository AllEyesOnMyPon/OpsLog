# Overview (lite)

**LogOps** = mini-platforma do generowania, przyjmowania i obserwowania logów w devie.

---

## Składniki

- **Emitery + Orkiestracja**
  - Emitery: `csv`, `json`, `minimal`, `noise`, `syslog`
  - Scenariusze: `scenarios/*.yaml` (quiet/spike/burst/ramp/errors)
  - Runner: `tools/run_scenario.py` (EPS, ramp, jitter, seed, JSONL)
  - CLI Orchestratora: `orch_cli.py` (`list/start/stop` po HTTP)

- **Gatewaye**
  - **AuthGW**: HMAC/API-Key/none, rate-limit (token bucket, opcj. Redis), backpressure, **retry + circuit breaker**, proxy do Ingest.
  - **IngestGW**: `POST /v1/logs` (JSON/CSV/syslog-like), normalizacja (`ts/level/msg`, PII mask/enc), NDJSON sink, metryki, forward do Core.
  - **Core**: lekki kolektor (limity, ring debug, NDJSON sink, metryki `core_*`).

- **Observability (Compose)**
  - Promtail → Loki (logi), Prometheus (metryki) → Alertmanager (Slack), Grafana (dashboard).

- **Narzędzia**
  - `tools/sign_hmac.py`, `tools/hmac_curl.sh`, `tools/verify_hmac_against_signer.py`
  - `tools/housekeeping.py` (retencja/ZIP NDJSON)

---

## Szybki start

```bash
# 1) Stack observability
docker compose -f infra/docker/docker-compose.observability.yml up -d

# 2) Gatewaye
uvicorn services.ingest.app:app --port 8080 --reload &
uvicorn services.core.app:app   --port 8095 --reload &
uvicorn services.authgw.app:app --port 8081 --reload &  # opcjonalnie

# 3) Ruch
python tools/run_scenario.py -s scenarios/spike.yaml
```

---

## Przepływ

Emitery → (opcjonalnie) **AuthGW** → **IngestGW** → **Core** →
NDJSON → Promtail → Loki | Metryki → Prometheus → Alertmanager → Grafana

---

## Dalej

Pełne szczegóły: **AuthGW**, **IngestGW**, **Core**, **Observability/Infra**, **Tools**, **Scenarios/Orch** — zob. główne README (sekcja linków).
