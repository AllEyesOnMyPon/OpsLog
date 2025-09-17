# Observability (Loki + Promtail + Prometheus + Grafana)

Ten dokument opisuje **aktualny** stan obserwowalności LogOps: przepływ danych, konfiguracje komponentów, reguły alertów (w tym **SLO/p95**), provisioning Grafany, szybkie testy oraz scenariusze ruchu.
Odwołania do kodu: **AuthGW** (`services/authgw`), **IngestGW** (`services/ingest`), **Core** (`services/core`), narzędzia (`tools/*`), orkiestracja/emitery (`tools/run_scenario.py`, `emitters/*`), oraz Docker Compose (`infra/docker/docker-compose.observability.yml`).

---

## Architektura i przepływ

```
Emitery / Orchestrator → (opcjonalnie) AuthGW :8081 (/ingest)
                     ↘ IngestGW :8080 (/v1/logs) → NDJSON (data/ingest/*.ndjson)
                                             ↘ Core :8095 (/v1/logs)
NDJSON → Promtail → Loki → Grafana (Explore/Logs)
Metryki (AuthGW/Ingest/Core/Promtail/Loki/Prometheus) → Prometheus → Alertmanager (Slack)
```

- **AuthGW**: autoryzacja (HMAC/API key), rate-limit, backpressure, retry + **circuit breaker**; proxy do IngestGW.
- **IngestGW**: parsowanie (JSON/CSV/syslog-like), **normalizacja** (ts / level / maskowanie PII / opcjonalne szyfrowanie), metryki, opcjonalny sink **NDJSON**.
- **Core**: szybki odbiór już znormalizowanych rekordów, metryki i opcjonalny sink NDJSON (z etykietami `emitter`, `scenario_id`).
- **Promtail**: czyta `data/ingest/*.ndjson`, etykiety: `app`, `emitter`, `level`, `ts`.
- **Loki**: przechowuje logi.
- **Prometheus**: scrapuje metryki (`/metrics`).
- **Alertmanager**: Slack (szablon → render z ENV).
- **Grafana**: dashboard `docs/grafana_dashboard.json`.

> `X-Emitter` / `X-Scenario-Id` są propagowane przez **AuthGW** i **Ingest/Core** do metryk i NDJSON (patrz nagłówki/etykiety w kodzie serwisów).

---

## Uruchamianie stacka

```bash
# Observability stack (Loki/Promtail/Prometheus/Grafana/Alertmanager)
docker compose -f infra/docker/docker-compose.observability.yml up -d
# zatrzymanie
docker compose -f infra/docker/docker-compose.observability.yml down
```

**Scrape z hosta (bramy poza Compose):**
- Ingest: `host.docker.internal:8080/metrics`
- AuthGW: `host.docker.internal:8081/metrics`
- Core:   `host.docker.internal:8095/metrics`

> Na Linuksie, jeśli `host.docker.internal` nie działa, użyj IP hosta (np. `172.17.0.1`).

**Szybkie sanity checki:**
- Grafana: <http://localhost:3000> (`admin`/`admin`)
- Prometheus: <http://localhost:9090> → **Status → Targets**
- Alertmanager: <http://localhost:9093>
- Loki health: <http://localhost:3100/ready>

---

## Promtail (parsowanie NDJSON)

- **Compose** montuje repozytoryjne `data/ingest` pod: `/var/log/logops:ro`
- **Konfiguracja**: `infra/docker/promtail/promtail-config.yml`
- **Pozycje**: (w zależności od Twojej konfiguracji) np. plik w volume /tmp/ itp.

Minimalny fragment (dopasowany do aktualnego Compose):

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml  # lub /var/lib/promtail/positions.yaml, jeśli tak ustawisz mount

clients:
  - url: http://logops-loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: logops-ndjson
    static_configs:
      - targets: [localhost]
        labels:
          job: logops-ndjson
          app: logops
          __path__: /var/log/logops/*.ndjson   # <— uwaga: nowa ścieżka z Compose
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

> W Compose dodaliśmy też bind-mounty do hosta:
> `../../../logs → /var/log/logops-hosts/logs:ro` oraz
> `../../../data/orch/scenarios → /var/log/logops-hosts/scenarios:ro`
> Jeśli chcesz je scrapować, dodaj odrębne `scrape_configs` z właściwymi `__path__`.

---

## Loki (retencja i limity)

- **Konfiguracja**: `infra/docker/loki/loki-config.yml`
- **Retencja** (przykład): `table_manager.retention_period: 48h`
- **Stare próbki**: `limits_config.reject_old_samples_max_age: 168h`

```yaml
limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h

table_manager:
  retention_deletes_enabled: true
  retention_period: 48h
```

---

## Prometheus (scrape + reguły alertów)

### Scrape targets (przykład)

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

  # Bramki scrapowane z hosta
  - job_name: 'logops_ingest'
    static_configs:
      - targets: ['host.docker.internal:8080']

  - job_name: 'logops_authgw'
    static_configs:
      - targets: ['host.docker.internal:8081']

  - job_name: 'logops_core'
    static_configs:
      - targets: ['host.docker.internal:8095']

  # (opcjonalnie) wgląd w usługi w Compose
  - job_name: 'loki'
    static_configs:
      - targets: ['loki:3100']

  - job_name: 'promtail'
    static_configs:
      - targets: ['promtail:9080']
```

### Reguły alertów (SLO/p95 i zdrowie)

`infra/docker/prometheus/alert_rules.yml` (zaktualizowane nazwy jobów i panele jakości):

```yaml
groups:
  - name: logops.health
    interval: 15s
    rules:
      - alert: LogOpsIngestDown
        expr: up{job="logops_ingest"} == 0
        for: 1m
        labels: { severity: critical, service: logops }
        annotations:
          summary: "IngestGW is down"
          description: "up{job='logops_ingest'} == 0 przez ≥1m."

      - alert: LogOpsAuthGWDown
        expr: up{job="logops_authgw"} == 0
        for: 1m
        labels: { severity: critical, service: logops }
        annotations:
          summary: "AuthGW is down"
          description: "up{job='logops_authgw'} == 0 przez ≥1m."

      - alert: LogOpsCoreDown
        expr: up{job="logops_core"} == 0
        for: 1m
        labels: { severity: critical, service: logops }
        annotations:
          summary: "Core is down"
          description: "up{job='logops_core'} == 0 przez ≥1m."

      - alert: LogOpsNoIngest5m
        expr: increase(logops_accepted_total[5m]) <= 0
        for: 2m
        labels: { severity: warning, service: logops }
        annotations:
          summary: "No logs ingested for 5 minutes"
          description: "Brak przyrostu logops_accepted_total w oknie 5m przez ≥2m."

      - alert: LogOpsInflightStuckHigh
        expr: logops_inflight > 5
        for: 2m
        labels: { severity: warning, service: logops }
        annotations:
          summary: "Inflight gauge high"
          description: "logops_inflight > 5 przez ≥2m (przeciążenie/zator)."

  - name: logops.quality
    interval: 15s
    rules:
      - alert: LogOpsHighMissingTS
        expr: increase(logops_accepted_total[5m]) >= 100
          and ( increase(logops_missing_ts_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.20
        for: 2m
        labels: { severity: warning, service: logops }
        annotations:
          summary: "High share of missing timestamps"
          description: "Udział braków TS > 20% przy ≥100 logach w 5m."

      - alert: LogOpsVeryHighMissingTS
        expr: increase(logops_accepted_total[5m]) >= 200
          and ( increase(logops_missing_ts_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.50
        for: 2m
        labels: { severity: critical, service: logops }
        annotations:
          summary: "Very high share of missing timestamps"
          description: "Udział braków TS > 50% przy ≥200 logach w 5m."

      - alert: LogOpsHighMissingLevel
        expr: increase(logops_accepted_total[5m]) >= 100
          and ( increase(logops_missing_level_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.20
        for: 2m
        labels: { severity: warning, service: logops }
        annotations:
          summary: "High share of missing levels"
          description: "Udział braków level > 20% przy ≥100 logach w 5m."

      - alert: LogOpsVeryHighMissingLevel
        expr: increase(logops_accepted_total[5m]) >= 200
          and ( increase(logops_missing_level_total[5m])
                / clamp_min(increase(logops_accepted_total[5m]), 1) ) > 0.50
        for: 2m
        labels: { severity: critical, service: logops }
        annotations:
          summary: "Very high share of missing levels"
          description: "Udział braków level > 50% przy ≥200 logach w 5m."

      - alert: AuthGWRejectedSpikes
        expr: sum(increase(logops_rejected_total[5m])) by (reason) > 0
        for: 2m
        labels: { severity: info, service: logops }
        annotations:
          summary: "AuthGW rejections present"
          description: "Wzrost logops_rejected_total w 5m (powód: {{ $labels.reason }})."

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
          description: "Obecnie {{ $value | printf \"%.2f\" }} < 0.99; sprawdź load/IO."

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
          description: "p95={{ $value | printf \"%.3f\" }}s; zweryfikuj obciążenie/backpressure."
```

> Metryki w powyższych regułach pochodzą z **IngestGW** (`logops_*`) i **AuthGW** (`logops_rejected_total`). **Core** posiada własne metryki (`core_*`), które możesz dodać do osobnych alertów (np. `increase(core_rejected_total[5m])`).

---

## Alertmanager (templating + Slack)

- **Szablon**: `infra/docker/alertmanager/alertmanager.tmpl.yml`
- **Render**: `make am-render` (wymaga ENV: `ALERTMANAGER_SLACK_WEBHOOK`, `ALERTMANAGER_SLACK_WEBHOOK_LOGOPS`)
- **Uruchomienie**: `make am-up`, przeładowanie: `make am-reload`, zdrowie: `make am-health`

Fragment szablonu (skrót):

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

> **Bezpieczeństwo:** `alertmanager.yml` po renderze zawiera pełne URL-e webhooków – **nie commituj** go (dodany do `.gitignore`).

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
  Import: **Dashboards → New → Import → Upload JSON** → wskaż **Prometheus** i **Loki**.

Panele (sugestie):
- Throughput: `sum(rate(logops_accepted_total[1m]))`
- In-flight (`logops_inflight`)
- **SLO % < 500ms** (udział kubełków `<=0.5s`) i **p95 (5m)** z `logops_batch_latency_seconds`
- Jakość: `increase(logops_missing_ts_total[5m])`, `increase(logops_missing_level_total[5m])`, `increase(logops_parse_errors_total[5m])`
- Odrzucenia AuthGW: `sum by (reason) (increase(logops_rejected_total[5m]))`
- Explore (Loki): filtry `app`, `emitter`, `level`

---

## Szybkie zapytania

**Loki (Explore / API):**
```logql
{job="logops-ndjson", app="logops"}
```
```logql
{job="logops-ndjson", app="logops", emitter="json"} |= "error"
```

**Prometheus (p95 – okno 5m):**
```promql
histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
```

**SLO % < 500ms (30m):**
```promql
100 *
( sum(rate(logops_batch_latency_seconds_bucket{le="0.5"}[30m]))
/ sum(rate(logops_batch_latency_seconds_count[30m])) )
```

---

## Scenariusze ruchu (traffic generator)

- **Pliki**: `scenarios/*.yaml`
- **Runner**: `tools/run_scenario.py` (sterowanie EPS/ramp/jitter/seed; integruje się z emiterami)
- **CLI Orchestratora**: `orch_cli.py` (start/stop/list scenariuszy przez HTTP)
- **Makefile**: cele `scenario-*`, `scenario-run SCEN=...`

Przykłady:
```bash
make scenario-default
make scenario-spike
python tools/run_scenario.py -s scenarios/burst-then-ramp.yaml --log-file data/scenario_runs/ramp.jsonl
```

Efekt:
- NDJSON trafia do `data/ingest/*.ndjson` → Promtail → Loki.
- Metryki ingest/SLO widoczne w Prometheus/Grafana.
- W torze z **AuthGW** pojawią się ewentualne odrzucenia (`logops_rejected_total{reason}`).

---

## Housekeeping (retencja NDJSON)

Narzędzie: `tools/housekeeping.py` (używane także przez gatewaye w trybie **autorun**)
Kluczowe ENV: `LOGOPS_SINK_DIR`, `LOGOPS_RETENTION_DAYS`, `LOGOPS_ARCHIVE_MODE` (`delete|zip`)
Szczegóły: `docs/tools/housekeeping.md`

---

## Higiena repo

Przykładowe wpisy `.gitignore`:

```
/data/ingest/*.ndjson
infra/docker/alertmanager/rendered/alertmanager.yml
infra/docker/promtail/positions/positions.yaml
.venv/
**/__pycache__/
*.py[cod]
```

---

## Powiązane dokumenty

- `docs/services/ingest_gateway.md` — parsowanie, normalizacja, metryki, NDJSON.
- `docs/services/auth_gateway.md` — tryby auth (HMAC/API key/any), RL, backpressure, **retry + circuit breaker**.
- `docs/services/core.md` — sink NDJSON, metryki per `core_*`.
- `docs/tools/hmac_curl.md` — wrapper `curl` z podpisem HMAC.
- `docs/tools/sign_hmac.md` — generator nagłówków HMAC.
- `docs/tools/verify_hmac_against_signer.md` — weryfikator poprawności nagłówków vs sekret.
- `docs/tools/housekeeping.md` — retencja/archiwizacja NDJSON.
- `docs/infra.md` — uruchamianie Compose/stack i mounty Promtail.
