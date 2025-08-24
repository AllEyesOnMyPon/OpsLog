# Observability

Zestaw: **Promtail + Loki + Prometheus + Grafana**.

## Promtail

- Konfiguracja: `infra/docker/promtail/promtail-config.yml`
- Źródło: `data/ingest/*.ndjson` (montowane do kontenera jako `/var/logops/data/ingest/*.ndjson`)
- Parsowanie JSON → etykiety i timestamp:
  - Labels: `job="logops-ndjson"`, `app="logops"`, `level`, `emitter`
  - Timestamp: `ts` w formacie `RFC3339` (przy błędzie → `action_on_failure: skip`)
- Pozycje/offsety: `/var/lib/promtail/positions.yaml` (bind-mount `./promtail/positions`)

Fragment configu (kluczowe części):
```yaml
positions:
  filename: /var/lib/promtail/positions.yaml

scrape_configs:
  - job_name: logops-ndjson
    static_configs:
      - targets: [localhost]
        labels:
          job: logops-ndjson
          app: logops
          __path__: /var/logops/data/ingest/*.ndjson

    pipeline_stages:
      - json:
          expressions:
            ts: ts
            level: level
            msg: msg
            emitter: emitter
      - timestamp:
          source: ts
          format: RFC3339
          action_on_failure: skip
      - labels:
          level:
          app:
          emitter:
      - output:
          source: msg
```
## Loki

- Konfiguracja: `infra/docker/loki/loki-config.yml`

- Storage: filesystem (`/loki`), retention danych: **48h** (`table_manager.retention_period`)

- Odrzucanie bardzo starych próbek: **168h** (`limits_config.reject_old_samples_max_age`)

- API zapytań: `http://localhost:3100/loki/api/v1/query`

Przykładowe zapytanie:
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```
## Prometheus

- Konfiguracja: `infra/docker/prometheus/prometheus.yml`

- Scrape:

    - `prometheus:9090` (self)

    - `logops_gateway` → `host.docker.internal:8080/metrics` (gateway poza Compose)

    - `logops-loki:3100`

    - `logops-promtail:9080`

- Metryki gatewaya (przykłady):

    - `logops_accepted_total`

    - `logops_missing_ts_total`

    - `logops_missing_level_total`

    - `logops_inflight`

## Alerty (10 reguł)
Plik: `infra/docker/prometheus/alert_rules.yml`
Grupa: `logops.alerts`, `interval: 15s`.

- **LogOpsGatewayDown** — `up{job="logops_gateway"} == 0` (≥1m)

- **LogOpsNoIngest5m** — `increase(logops_accepted_total[5m]) <= 0` (≥2m)

- **LogOpsLowIngest** — `rate(logops_accepted_total[5m]) < 0.2` (≥5m)

- **LogOpsHighIngestBurst** — `rate(logops_accepted_total[1m]) > 20` (≥1m)

- **LogOpsHighMissingTS** — udział braków TS > 20% przy ≥100 logach w 5m (≥2m)

- **LogOpsVeryHighMissingTS** — udział braków TS > 50% przy ≥200 logach w 5m (≥2m)

- **LogOpsHighMissingLevel** — udział braków level > 20% przy ≥100 logach w 5m (≥2m)

- **LogOpsVeryHighMissingLevel** — udział braków level > 50% przy ≥200 logach w 5m (≥2m)

- **LogOpsInflightStuckHigh** — l`ogops_inflight > 5` (≥2m)

- **LogOpsMetricsAbsent** — `absent(up{job="logops_gateway"})` (≥2m)

## Grafana
- URL: `http://localhost:3000` (admin/admin)

- Datasources provisioning: infra/docker/grafana/provisioning/datasources/

- Import dashboardu: docs/grafena_dashboard.json
**Dashboards → New → Import → Upload JSON → wybierz Loki/Prometheus jako datasource.**

## Szybkie sprawdzenie

**Linux/macOS (curl):**
```bash
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```
**Windows PowerShell (irm):**
```powershell
irm "http://localhost:3100/loki/api/v1/query?query={job='logops-ndjson',app='logops',emitter='emitter_csv'}"
```
**Housekeeping** (gateway) może usuwać/archiwizować starsze `*.ndjson` w `data/ingest/`.
Jeśli włączony, starsze logi mogą zniknąć z widoku Promtail/Loki. Szczegóły: `docs/tools/housekeeping.md`.
