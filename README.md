# LogOps

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-dashboard-F46800?logo=grafana&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-alerts-E6522C?logo=prometheus&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-v0.4-blue.svg)

## Quickstart (TL;DR)

```bash
# 1. Uruchom stack observability (Loki, Promtail, Prometheus, Grafana)
docker compose -f infra/docker/docker-compose.observability.yml up -d

# 2. Start Ingest Gateway (FastAPI)
uvicorn services.ingest_gateway.gateway:app --host 0.0.0.0 --port 8080 --reload

# 3. Wyślij sample logi
python emitters/emitter_csv/emit_csv.py -n 10 --partial-ratio 0.3

# 4. Sprawdź logi w Loki
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```


System do **emisji, zbierania i obserwowalności logów** w środowisku deweloperskim.  
Przepływ: **emitery → Auth Gateway (HMAC/RL) → Ingest Gateway (FastAPI) → Promtail/Loki → Grafana/Prometheus/Alertmanager**.  

Obsługiwane funkcje:
- generowanie logów (emitery + scenariusze),
- walidacja i normalizacja w gatewayach,
- podpisy HMAC i limitowanie ruchu,
- zbieranie i query logów (Loki),
- metryki i alerty Prometheus/Alertmanager,
- dashboardy w Grafanie.

---

## Releases

- **v0.4 – Auth Gateway (HMAC, RL, backpressure), scenariusze ruchu, Slack AM**  
[docs/releases/v0.4.md](docs/releases/v0.4.md)

- **v0.3 – CLI orchestration, dashboard & alerts**  
[docs/releases/v0.3.md](docs/releases/v0.3.md)

- **v0.2 – Housekeeping, retention & archive, Docker observability stack**  
[docs/releases/v0.2.md](docs/releases/v0.2.md)

- **v0.1 – Initial gateway, basic emitters, normalization**  
[docs/releases/v0.1.md](docs/releases/v0.1.md)

---

## Szybki start

### 1. Uruchom stack observability (Loki, Promtail, Prometheus, Grafana, Alertmanager)
```bash
make up
```

Usługi:
- **Ingest Gateway**: http://localhost:8080/healthz  
- **Auth Gateway**: http://localhost:8090/healthz  
- **Prometheus**: http://localhost:9090  
- **Grafana**: http://localhost:3000 (admin/admin)  
- **Loki API**: http://localhost:3100  
- **Alertmanager**: http://localhost:9093  

### 2. Uruchom gatewaye (dev)
```bash
make ingest-start
make authgw-start
```

### 3. Wyślij sample logi z emitera CSV
```bash
make emit-csv N=10 PARTIAL=0.2
```

### 4. Sprawdź logi w Loki
```bash
make loki-query
```

---

## Endpointy gatewayów

### Ingest Gateway
- `GET /healthz` – status + wersja  
- `GET /metrics` – metryki Prometheus  
- `POST /v1/logs` – przyjmowanie logów (JSON, CSV, syslog-like)

### Auth Gateway
- `GET /healthz` – status  
- `GET /metrics` – metryki (m.in. `logops_rejected_total`)  
- `POST /ingest` – przyjmowanie logów z walidacją HMAC, rate-limit i backpressure  

---

## Scenarios

Scenariusze w katalogu `scenarios/` pozwalają generować różne profile ruchu: quiet, spike, burst, high-errors, burst-then-ramp.  

Przykład uruchomienia:
```bash
make scenario-default
make scenario-high-errors
make scenario-spike
```

Narzędzie: [tools/run_scenario.py](docs/tools/run_scenario.md)  

---

## Housekeeping

Proces utrzymania plików NDJSON w `data/ingest/`.  
- Usuwa lub archiwizuje pliki starsze niż `LOGOPS_RETENTION_DAYS`.  
- Tryby: `delete` (domyślny) lub `zip`.  

👉 Szczegóły: [docs/tools/housekeeping.md](docs/tools/housekeeping.md)

---

## Testowanie AuthGW (HMAC)

Generowanie nagłówków HMAC:
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST http://127.0.0.1:8090/ingest '{"msg":"hello"}' --nonce
```

Wrapper `curl`:
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello"}' -- -v
```

👉 Szczegóły: [docs/tools/sign_hmac.md](docs/tools/sign_hmac.md), [docs/tools/hmac_curl.md](docs/tools/hmac_curl.md)

---

## Struktura repo
```bash
logops/
├── data/ingest/            # logi NDJSON
├── docs/                   # dokumentacja
├── emitters/               # emitery logów
├── infra/docker/           # stack observability
├── scenarios/              # predefiniowane profile ruchu
├── services/               # Ingest GW + Auth GW
├── tools/                  # narzędzia dev (housekeeping, HMAC, scenariusze)
└── tests/                  # testy jednostkowe
```

---

## Dokumentacja szczegółowa

- [Przegląd](docs/overview.md)  
- [Architektura](docs/architecture.md)  
- [Observability](docs/observability.md)  
- [Emitery](docs/services/emitters.md)  
- [Ingest Gateway](docs/services/ingest_gateway.md)  
- [Auth Gateway](docs/services/auth_gateway.md)  
- [Scenarios](docs/tools/run_scenario.md)  
- [Housekeeping](docs/tools/housekeeping.md)  
- [HMAC tools](docs/tools/sign_hmac.md), [docs/tools/hmac_curl.md](docs/tools/hmac_curl.md)  
- [Infrastruktura (Docker)](docs/infra.md)  
- [Testy](docs/testing.md)  
- [Roadmap](docs/roadmap.md)  

---

## Testy
```bash
pytest -q
```

---

## Licencja

MIT
