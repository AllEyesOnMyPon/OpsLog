# LogOps

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-dashboard-F46800?logo=grafana&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-alerts-E6522C?logo=prometheus&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-v0.5-blue.svg)

System do **emisji, zbierania i obserwowalności logów** w środowisku deweloperskim.

**Przepływ:** emitery → (opcjonalnie) **AuthGW** (HMAC/RL/backpressure) → **IngestGW** (normalizacja) → **Core** (przyjęcie/sink/metryki) → Promtail/Loki → Grafana/Prometheus/Alertmanager.

---

## Quickstart (TL;DR)

### Opcja A — wszystko jednym poleceniem (demo)
```bash
make demo
```
To uruchomi stack observability (Loki/Promtail/Prometheus/Grafana/Alertmanager), wystartuje **Core**, **IngestGW** (forward do Core) i (opcjonalnie) **AuthGW**, a następnie odpali przykładowy scenariusz ruchu.

### Opcja B — ręcznie, krok po kroku
```bash
# 1) Observability stack
docker compose -f infra/docker/observability/docker-compose.yml up -d

# 2) Serwisy (dev)
uvicorn services.core.app:app     --host 0.0.0.0 --port 8095 --reload &
uvicorn services.ingestgw.app:app --host 0.0.0.0 --port 8080 --reload &
uvicorn services.authgw.app:app   --host 0.0.0.0 --port 8081 --reload &   # opcjonalnie

# 3) Prosty ruch z emitera (CSV)
python emitters/csv.py -n 10 --partial-ratio 0.2

# 4) Logi w Loki
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops"}'
```

Grafana: <http://localhost:3000> (admin / admin) • Prometheus: <http://localhost:9090> • Alertmanager: <http://localhost:9093>

---

## Najważniejsze funkcje

- **Emitery**: CSV / JSON / minimal / noise / syslog + gotowe **scenariusze** (`scenarios/*.yaml`).
- **Auth Gateway**: HMAC (`X-Api-Key`, `X-Timestamp`, `X-Content-SHA256`, `X-Signature`, `X-Nonce`), **rate limit** (token bucket), **backpressure**, retry + **circuit breaker**.
- **Ingest Gateway**: normalizacja (ts/level/PII), metryki, **forward do Core**.
- **Core**: przyjęcie `/v1/logs`, metryki (`*_accepted_total`, `*_request_latency_seconds`, `*_rejected_total`), opcjonalny **NDJSON sink**.
- **Observability**: Promtail/Loki + Prometheus/Alertmanager + Grafana (dashboard SLO/p95).
- **Narzędzia**: `tools/run_scenario.py`, `tools/orch_cli.py`, `tools/sign_hmac.py`, `tools/hmac_curl.sh`, `tools/verify_hmac_against_signer.py`, `tools/housekeeping.py`.

---

## Endpointy (dev)

### Core
- `GET /healthz` — zdrowie
- `GET /metrics` — metryki Prometheus
- `POST /v1/logs` — przyjęcie logów (JSON/NDJSON/CSV), opcjonalny zapis do `data/core/` (gdy włączony sink)

### IngestGW
- `GET /healthz`, `GET /metrics`
- `POST /v1/logs` — normalizacja → **forward do Core** (adres z `CORE_URL`)

### AuthGW (opcjonalnie przed Ingest)
- `GET /healthz`, `GET /metrics`
- `POST /ingest` — HMAC/RL/backpressure → **forward do Ingest** (adres z `forward.url`)

---

## Scenariusze i orkiestracja

- Szybko uruchom gotowe profile:
  ```bash
  make scenario-default
  make scenario-spike
  make scenario-high-errors
  ```
- Runner (ticki, rampy, jitter, seed, JSONL z metadanymi):
  ```bash
  python tools/run_scenario.py -s scenarios/burst-then-ramp.yaml --log-file logs/scenario-default.jsonl
  ```
- Orchestrator CLI (HTTP do usługi orchestratora):
  ```bash
  python tools/orch_cli.py list
  python tools/orch_cli.py start --yaml-path scenarios/spike.yaml --debug
  python tools/orch_cli.py stop <SCENARIO_ID>
  ```

---

## HMAC — narzędzia

- Generowanie nagłówków (kanonikalizacja **PATH-only**, bez query):
  ```bash
  python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' '{"msg":"hello"}' --nonce
  ```
- Wygodny wrapper:
  ```bash
  tools/hmac_curl.sh --nonce -d '{"msg":"hello"}' -- -i
  ```
- Offline weryfikacja podpisu (nagłówki z `stdin`, sekret z `LOGOPS_SECRET`):
  ```bash
  tools/hmac_curl.sh --nonce -d '{"msg":"hello"}' --echo-headers \
  | LOGOPS_SECRET=demo-priv-1 python tools/verify_hmac_against_signer.py \
      --url http://127.0.0.1:8081/ingest --method POST --body-file <(printf '{"msg":"hello"}')
  ```

---

## Struktura repo (skrót)

```
.
├── docs/                       # dokumentacja (services/, tools/, releases/, infra, observability)
├── services/
│   ├── core/                   # Core FastAPI (app.py)
│   ├── ingestgw/               # Ingest FastAPI (app.py, normalize/metrics/parsers)
│   ├── authgw/                 # AuthGW (HMAC/RL/backpressure/retry+CB)
│   └── orchestrator/           # API do zarządzania scenariuszami
├── emitters/                   # emitery: csv/json/minimal/noise/syslog
├── tools/                      # run_scenario, orch_cli, HMAC tools, housekeeping
├── infra/docker/observability/ # docker-compose + loki/promtail/prometheus/grafana/alertmanager
├── scenarios/                  # gotowe scenariusze
├── data/                       # NDJSON dla ingest/core, wyniki scenariuszy
└── logs/ & run/                # logi i pid-y uruchomionych procesów
```

---

## Dokumentacja szczegółowa

- **Overview:** `docs/overview.md`
- **Observability:** `docs/observability.md`
- **Infra (Compose):** `docs/infra.md`
- **Env (.env):** `docs/env.md`

**Serwisy**
- **Core:** `docs/services/core/core_app_readme.md`
- **IngestGW:** `docs/services/ingestGW/ingestGW_app_readme.md`
- **AuthGW:** `docs/services/authGW/authGW_app_readme.md`

**Tools**
- **Scenariusze (runner):** `docs/tools/run_scenario.md`
- **Orch CLI:** `docs/tools/orch_cli_readme.md`
- **HMAC signer:** `docs/tools/sign_hmac.md`
- **HMAC curl wrapper:** `docs/tools/hmac_curl.md`
- **HMAC verify:** `docs/tools/verify_hmac_against_signer_readme.md`
- **Housekeeping:** `docs/tools/housekeeping.md`

**Releases**
- `docs/releases/v0.5.md` (najnowsze)
- `docs/releases/v0.4.md`, `v0.3.md`, `v0.2.md`, `v0.1.md`

---

## Testy & jakość

```bash
# testy
pytest -q

# format/lint (pre-commit)
pre-commit run --all-files
```

---

## Licencja

MIT
