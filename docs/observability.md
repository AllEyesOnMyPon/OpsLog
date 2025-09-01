# Observability (Loki + Promtail + Prometheus + Grafana)

Ten dokument opisuje **aktualny** stan obserwowalności LogOps: konfiguracje komponentów, reguły alertów (w tym **SLO/p95**), templating Alertmanagera (Slack), provisioning Grafany, szybkie testy oraz scenariusze ruchu.  
Źródła i ścieżki poniżej odpowiadają plikom z repo (sekcja „Konfiguracje – pełne fragmenty”).

---

## Architektura i przepływ

```
Emitery → (opcjonalnie) AuthGW (/ingest) → IngestGW (/v1/logs) → NDJSON (data/ingest/*.ndjson)
         ↘ (RL / HMAC / Backpressure / Retry+CB)                            ↘ Promtail → Loki → Grafana (Explore/Logs)
                                                                            ↘ Prometheus (metryki) → Alertmanager (Slack)
```

- **Promtail** wciąga NDJSON z `data/ingest/*.ndjson`, wyciąga etykiety (`level`, `emitter`, `app`) i `ts`.
- **Loki** przechowuje logi (filesystem), retencja i limity jak niżej.
- **Prometheus** scrapuje:
  - **Ingest Gateway**: `host.docker.internal:8080/metrics`
  - **Auth Gateway**: `host.docker.internal:8090/metrics`
  - **Prometheus** self, **Loki**, **Promtail**
- **Alertmanager** renderowany z szablonu `.tmpl.yml` na podstawie ENV i wysyła alerty do Slacka.
- **Grafana** ma dane z Prometheusa i Loki; dashboard `docs/grafana_dashboard.json`.

> `X-Emitter` jest nadawany przez emitery lub doklejany przez **AuthGW** (po weryfikacji klucza/HMAC), dzięki czemu etykieta `emitter` jest spójna w logach i metrykach.

---

## Uruchamianie stacka

```bash
# Observability stack
make up            # uruchamia Loki/Promtail/Prometheus/Grafana (compose)
make down          # zatrzymuje

# Przeładuj Prometheusa po zmianie reguł
make prom-reload

# Alertmanager (templating + start + reload + smoke)
export ALERTMANAGER_SLACK_WEBHOOK=...
export ALERTMANAGER_SLACK_WEBHOOK_LOGOPS=...
make am-render     # renderuje z .tmpl do rendered/alertmanager.yml (envsubst)
make am-up         # podnosi usługę alertmanagera (compose)
make am-reload     # POST /-/reload
make am-synthetic  # syntetyczny alert do Slacka (AM API)
make am-health     # health AM + czy Prom widzi AM + lista grup reguł

# Loki szybkie zapytanie
make loki-query    # bazowe zapytanie po etykietach
```

---

## Promtail (parsowanie NDJSON)

- **Konfiguracja**: `infra/docker/promtail/promtail-config.yml`
- **Źródło**: `./data/ingest/*.ndjson` montowane jako `/var/logops/data/ingest/*.ndjson`
- **Pozycje/offsety**: `/var/lib/promtail/positions.yaml` (trwałe via volume)

Fragment (aktualny):
```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://logops-loki:3100/loki/api/v1/push

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

> Przykładowe `positions.yaml` (stan odczytu plików):
```yaml
positions:
  /var/logops/data/ingest/20250827.ndjson: "3650"
  /var/logops/data/ingest/20250828.ndjson: "573"
```

---

## Loki (retencja i limity)

- **Konfiguracja**: `infra/docker/loki/loki-config.yml`
- **Retencja**: `table_manager.retention_period: 48h`
- **Odrzuć bardzo stare próbki**: `limits_config.reject_old_samples_max_age: 168h`

Fragment (kluczowe pola):
```yaml
limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h

table_manager:
  retention_deletes_enabled: true
  retention_period: 48h
```

---

## Prometheus (scrape + alerty)

### Scrape targets

`infra/docker/prometheus/prometheus.yml`:
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - /etc/prometheus/alert_rules.yml

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['prometheus:9090']

  - job_name: 'logops-gateway'   # legacy alias (zachowany dla zgodności)
    metrics_path: /metrics
    static_configs:
      - targets: ['host.docker.internal:8080']

  - job_name: 'logops_ingest'
    static_configs:
      - targets: ['host.docker.internal:8080']

  - job_name: 'logops_authgw'
    static_configs:
      - targets: ['host.docker.internal:8090']
```

### Reguły alertów (w tym SLO/p95)

`infra/docker/prometheus/alert_rules.yml` (wycinek całości – aktualne reguły):

```yaml
groups:
  - name: logops.alerts
    interval: 15s
    rules:
      - alert: LogOpsGatewayDown
        expr: up{job="logops-gateway"} == 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Gateway is down"
          description: "Target up{job='logops-gateway'} == 0 przez ≥1m."

      - alert: LogOpsNoIngest5m
        expr: increase(logops_accepted_total[5m]) <= 0
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "No logs ingested for 5 minutes"
          description: "Brak przyrostu logops_accepted_total w oknie 5m przez ≥2m."

      - alert: LogOpsLowIngest
        expr: rate(logops_accepted_total[5m]) < 0.2
        for: 5m
        labels: { severity: info }
        annotations:
          summary: "Low ingest rate"
          description: "Średnia szybkość ingestu < 0.2 loga/s przez ≥5m."

      - alert: LogOpsHighIngestBurst
        expr: rate(logops_accepted_total[1m]) > 20
        for: 1m
        labels: { severity: warning }
        annotations:
          summary: "High ingest burst"
          description: "Szybkość ingestu > 20 logów/s przez ≥1m (sprawdź źródła)."

      - alert: LogOpsHighMissingTS
        expr: increase(logops_accepted_total[5m]) >= 100
          and ( increase(logops_missing_ts_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.20
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "High share of missing timestamps"
          description: "Udział braków TS > 20% przy ≥100 logach w 5m."

      - alert: LogOpsVeryHighMissingTS
        expr: increase(logops_accepted_total[5m]) >= 200
          and ( increase(logops_missing_ts_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.50
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "Very high share of missing timestamps"
          description: "Udział braków TS > 50% przy ≥200 logach w 5m."

      - alert: LogOpsHighMissingLevel
        expr: increase(logops_accepted_total[5m]) >= 100
          and ( increase(logops_missing_level_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.20
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "High share of missing levels"
          description: "Udział braków level > 20% przy ≥100 logach w 5m."

      - alert: LogOpsVeryHighMissingLevel
        expr: increase(logops_accepted_total[5m]) >= 200
          and ( increase(logops_missing_level_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.50
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "Very high share of missing levels"
          description: "Udział braków level > 50% przy ≥200 logach w 5m."

      - alert: LogOpsInflightStuckHigh
        expr: logops_inflight > 5
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "Inflight gauge high"
          description: "logops_inflight > 5 przez ≥2m (przeciążenie lub zator)."

      - alert: LogOpsMetricsAbsent
        expr: absent(up{job="logops-gateway"})
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "No metrics scraped from gateway"
          description: "Prometheus nie widzi żadnych metryk z job='logops-gateway' przez ≥2m."

  - name: logops.slo
    interval: 15s
    rules:
      - alert: LogOpsSLOUnder99
        expr: |
          (
            sum(rate(logops_batch_latency_seconds_bucket{le="0.5"}[30m]))
          /
            sum(rate(logops_batch_latency_seconds_count[30m]))
          ) < 0.99
        for: 30m
        labels: { severity: warning, service: logops, team: platform }
        annotations:
          summary: "SLO: <99% batchy <500ms (30m)"
          description: "Obecnie {{ $value | printf \"%.2f\" }} < 0.99; sprawdź przeciążenie/IO."

      - alert: LogOpsP95LatencyHigh
        expr: |
          histogram_quantile(
            0.95,
            sum by (le) (rate(logops_batch_latency_seconds_bucket[5m]))
          ) > 0.5
        for: 5m
        labels: { severity: critical, service: logops, team: platform }
        annotations:
          summary: "p95 batch latency > 500ms (≥5m)"
          description: "p95={{ $value | printf \"%.3f\" }}s; zweryfikuj load, CPU, disk, backpressure."
```

> **Uwaga:** rozważ dodanie bliźniaczych alertów „down/absent” także dla `job="logops_authgw"` (Health AuthGW).

---

## Alertmanager (templating + Slack)

- **Szablon**: `infra/docker/alertmanager/alertmanager.tmpl.yml`
- **Render**: `make am-render` (wymaga ENV: `ALERTMANAGER_SLACK_WEBHOOK`, `ALERTMANAGER_SLACK_WEBHOOK_LOGOPS`)
- **Render output**: `infra/docker/alertmanager/rendered/alertmanager.yml`
- **Uruchomienie**: `make am-up`, przeładowanie: `make am-reload`

Szablon (fragment):
```yaml
route:
  receiver: slack_default
  group_by: [alertname, service]
  group_wait: 10s
  group_interval: 2m
  repeat_interval: 3h
  routes:
    - matchers: [ service="logops" ]
      receiver: slack_logops

receivers:
  - name: slack_default
    slack_configs:
      - send_resolved: true
        api_url: ${ALERTMANAGER_SLACK_WEBHOOK}
        title: "[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}"
        text: >-
          *Service:* {{ or .CommonLabels.service "unknown" }}
          *Severity:* {{ or .CommonLabels.severity "unknown" }}
          *Summary:* {{ .CommonAnnotations.summary }}
          *Desc:* {{ .CommonAnnotations.description }}

  - name: slack_logops
    slack_configs:
      - send_resolved: true
        api_url: ${ALERTMANAGER_SLACK_WEBHOOK_LOGOPS}
        title: "[{{ .Status | toUpper }}][LogOps] {{ .CommonLabels.alertname }}"
        text: >-
          *Severity:* {{ or .CommonLabels.severity "unknown" }}
          *Summary:* {{ .CommonAnnotations.summary }}
          *Desc:* {{ .CommonAnnotations.description }}
```

> **Bezpieczeństwo:** Nie commituj bezpośrednich URL-i webhooków do repo. Trzymaj tylko `.tmpl.yml` i renderuj plik wynikowy **lokalnie** z ENV → dodaj `rendered/alertmanager.yml` do `.gitignore`.

---

## Grafana (datasources + dashboard)

- **Datasources**: `infra/docker/grafana/provisioning/datasources/datasources.yml`
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
```

- **Dashboard**: `docs/grafana_dashboard.json`  
  Import w UI: **Dashboards → New → Import → Upload JSON → wybierz Loki i Prometheus jako datasources**.

Panele (m.in.):
- **EPS** i Accepted (Prometheus).
- **In-flight** (gauge).
- **SLO % < 500ms** i **p95 latency (5m)** (histogram_quantile).
- **Missing TS/Level**, **Parse errors**, **AuthGW rejected** (sum(increase(...[5m]))).
- **Logs/Explore** (Loki) z filtrami `level` i `emitter`.

---

## Szybkie zapytania

**Loki (Explore / API):**
```logql
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```
```bash
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```

**Prometheus (p95 5m):**
```promql
histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
```

---

## Scenariusze ruchu (traffic generator)

- **Pliki**: `scenarios/*.yaml`  
- **Runner**: `tools/run_scenario.py`  
- **Makefile**: `scenario-*`, `scenario-run SCEN=...`

Przykład:
```bash
make scenario-default
make scenario-spike
make scenario-high-errors
make scenario-run SCEN=scenarios/burst_high_error.yaml
```

Efekt:
- Logi trafią do NDJSON → Promtail → Loki.
- Metryki ingest i SLO/p95 pojawią się w Prometheus/Grafana.
- **AuthGW** może odrzucać (backpressure: 413) z przyrostem `logops_rejected_total{reason=...}`.

---

## Konfiguracje – pełne fragmenty (dla referencji)

### Promtail – `infra/docker/promtail/promtail-config.yml`
```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://logops-loki:3100/loki/api/v1/push

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

### Loki – `infra/docker/loki/loki-config.yml`
```yaml
auth_enabled: false
server:
  http_listen_port: 3100
  grpc_listen_port: 9095

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2022-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  enable_api: true

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h

table_manager:
  retention_deletes_enabled: true
  retention_period: 48h
```

### Prometheus – `infra/docker/prometheus/prometheus.yml`
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - /etc/prometheus/alert_rules.yml

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['prometheus:9090']

  - job_name: 'logops-gateway'
    metrics_path: /metrics
    static_configs:
      - targets: ['host.docker.internal:8080']

  - job_name: 'logops_ingest'
    static_configs:
      - targets: ['host.docker.internal:8080']

  - job_name: 'logops_authgw'
    static_configs:
      - targets: ['host.docker.internal:8090']
```

### Alert rules – `infra/docker/prometheus/alert_rules.yml`
```yaml
# (patrz sekcja „Reguły alertów” wyżej — to ten sam plik)
# Wklejony tam w całości dla czytelności i jednego miejsca prawdy.
```

### Alertmanager – szablon `infra/docker/alertmanager/alertmanager.tmpl.yml`
```yaml
# (patrz sekcja „Alertmanager (templating + Slack)”)
```

### Alertmanager – render `infra/docker/alertmanager/rendered/alertmanager.yml`
```yaml
# Plik generowany – nie commituj sekretów!
# Zawiera już „api_url: https://hooks.slack.com/...”
```

### Grafana – datasources
```yaml
# (patrz sekcja „Grafana (datasources + dashboard)”)
```

### Dashboard – `docs/grafana_dashboard.json`
```json
{
  "title": "LogOps – Observability (SLO)",
  "uid": "logops-observability-slo",
  "...": "zob. plik w repo (panele: EPS, inflight, SLO%, p95, rejected, itp.)"
}
```

### Scenariusze – `scenarios/*.yaml`
```yaml
# default.yaml, spike.yaml, high_errors.yaml, burst_high_error.yaml, quiet.yaml, burst-then-ramp.yaml
# (patrz katalog; gotowe profile)
```

### Runner – `tools/run_scenario.py`
```python
# Runner scenariuszy z obsługą EPS, ramp, jitter, seed
# (pełny kod w repo – patrz plik; zgrywa statystyki i poziomy)
```

### Makefile – cele przydatne dla observability
```make
up / down / ps / logs
prom-reload
loki-query
am-render / am-up / am-reload / am-synthetic / am-health / slack-smoke
scenario-* / scenario-run
all-authgw / all-ingest
metrics / metrics-rejected
```

---

## Higiena repo (praktyczne)

Dodaj do `.gitignore` (jeśli jeszcze nie ma):

```
# runtime
/data/ingest/*.ndjson
infra/docker/promtail/positions/positions.yaml
logs/*.out
run/*.pid

# alertmanager (sekrety po renderze)
infra/docker/alertmanager/rendered/alertmanager.yml

# lokalne generaty
big.json
many.json

# klucze / testowe
second
second.pub

# venv / pycache
.venv/
**/__pycache__/
*.py[cod]
```

---

## Powiązane dokumenty

- `docs/services/ingest_gateway.md` — normalizacja, sink, metryki ingest.  
- `docs/services/auth_gateway.md` — autoryzacja (HMAC/API key), RL, backpressure, retry+CB.  
- `docs/tools/housekeeping.md` — retention NDJSON.  
- `docs/infra.md` — uruchamianie Compose/stack.

---
