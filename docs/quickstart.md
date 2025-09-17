# Quickstart (dev)

Szybka, dwutorowa instrukcja: **(A) jeden make** albo **(B) manual**.

---

## A) Najprościej: `make demo`

Wymagania: Docker + Compose, Python 3.11.

```bash
# 1) Podnieś cały stack observability
docker compose -f infra/docker/docker-compose.observability.yml up -d

# 2) Uruchom serwisy i demo-ruch (komenda z Makefile)
make demo
```

Co dostajesz:
- **Prometheus** → http://localhost:9090
- **Grafana** → http://localhost:3000 (admin / admin)
- **Loki API** → http://localhost:3100
- **Ruch**: odpala scenariusz z `scenarios/${DEMO_SCENARIO}.yaml` (konfig w `.env`)

> Tip: `DEMO_SCENARIO=spike make demo` – szybki spike.

---

## B) Manualnie (pełna kontrola)

### 1) Wymagania (Python)
```bash
pip install "uvicorn[standard]" fastapi requests
```

### 2) Observability stack
```bash
docker compose -f infra/docker/docker-compose.observability.yml up -d
```

### 3) Serwisy LogOps
W trzech terminalach (lub w tle):

```bash
# IngestGW
uvicorn services.ingest.app:app --host 0.0.0.0 --port 8080 --reload
# Core
uvicorn services.core.app:app   --host 0.0.0.0 --port 8095 --reload
# (opcjonalnie) AuthGW – HMAC/RL/backpressure + retry/CB
uvicorn services.authgw.app:app --host 0.0.0.0 --port 8081 --reload
```

Health / metryki:
- Ingest: `http://localhost:8080/healthz`, `/metrics`
- Core:   `http://localhost:8095/healthz`, `/metrics`
- AuthGW: `http://localhost:8081/healthz`, `/metrics`

### 4) Wygeneruj ruch

#### Opcja 1 — scenariusz (zalecane)
```bash
# przez AuthGW (domyślka runnera)
python tools/run_scenario.py -s scenarios/spike.yaml

# albo bez AuthGW (bez HMAC) – wyślij prosto do IngestGW:
python tools/run_scenario.py -s scenarios/spike.yaml \
  --log-file data/scenario_runs/spike.jsonl
# (jeśli NIE uruchamiasz AuthGW, runner i emitery użyją URL z .env/INGEST_URL)
```

#### Opcja 2 — szybki cURL (bez HMAC)
```bash
curl -s http://localhost:8080/v1/logs \
  -H "Content-Type: application/json" \
  -d '{"msg":"hello","level":"info"}'
```

#### Opcja 3 — cURL z HMAC przez AuthGW
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello","level":"info"}'
```

### 5) Zobacz wyniki

**Loki (Explore w Grafanie):**
```logql
{job="logops-ndjson", app="logops", emitter="json"}
```

**Prometheus – p95 (5m):**
```promql
histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
```

**Dashboard Grafany:**
- Importuj `docs/grafana_dashboard.json` → wybierz datasources Prometheus/Loki.

---

## Przydatne skróty (Makefile)

```bash
make up             # start Loki/Promtail/Prometheus/Grafana
make down           # stop stack
make scenario-spike # uruchom gotowy scenariusz spike
make prom-reload    # przeładuj reguły Prometheusa
```

---

## Notatki

- Domyślne adresy:
  IngestGW `:8080`, AuthGW `:8081`, Core `:8095`.
- NDJSON: `./data/ingest/*.ndjson` (czytane przez Promtail do Loki).
- Housekeeping: `tools/housekeeping.py` (retencja/zip wg `.env`).
- W razie błędów HMAC użyj:
  `tools/verify_hmac_against_signer.py` (waliduje kanoniczny podpis offline).

Pełne instrukcje i szczegóły: patrz dokumentacje **AuthGW**, **IngestGW**, **Core**, **Observability/Infra**, **Tools**.
