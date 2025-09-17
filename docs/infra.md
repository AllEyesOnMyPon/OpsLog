# Infrastruktura (Docker)

Środowisko observability uruchamiasz z pliku:
`infra/docker/docker-compose.observability.yml`

---

## Usługi

- **Prometheus** — `prom/prometheus:latest`
  Port: `9090:9090`
  Konfiguracja: `infra/docker/prometheus/prometheus.yml` (+ `alert_rules.yml`)
  Dane: wolumen `prometheus-data` pod `/prometheus`
  Przełącznik `--web.enable-lifecycle` pozwala na hot-reload (`/-/reload`).
  `depends_on: [alertmanager]`

- **Promtail** — `grafana/promtail:2.9.0`
  Konfiguracja: `infra/docker/promtail/promtail-config.yml`
  Mounty:
  - `../../../data/ingest → /var/log/logops:ro`  *(NDJSON z gatewaya)*
  - `../../../logs → /var/log/logops-hosts/logs:ro`  *(logi hosta – **NOWE**, przeniesione poza /var/log/logops)*
  - `../../../data/orch/scenarios → /var/log/logops-hosts/scenarios:ro`  *(logi/scenariusze orkiestacji – **NOWE**)*
  - `promtail-tmp → /tmp`  *(pozycje/stan wg konfiguracji – jeśli tak ustawiono w promtail-config.yml)*
  `depends_on: [loki]`

- **Alertmanager** — `prom/alertmanager:latest`
  Port: `9093:9093`
  Konfiguracja: `infra/docker/alertmanager/alertmanager.yml`
  Uruchomiony z `--cluster.advertise-address=0.0.0.0:9094` i `--log.level=debug`.

- **Loki** — `grafana/loki:2.9.0`
  Port: `3100:3100`
  Konfiguracja: `infra/docker/loki/loki-config.yml`
  Dane: wolumen `loki-data` pod `/loki`.

- **Grafana** — `grafana/grafana:latest`
  Port: `3000:3000`
  ENV: `GF_SECURITY_ADMIN_USER=admin`, `GF_SECURITY_ADMIN_PASSWORD=admin`
  Provisioning:
  - `infra/docker/grafana/provisioning/datasources/datasources.yml → /etc/grafana/provisioning/datasources/datasources.yml:ro`
  - `infra/docker/grafana/provisioning/dashboards → /etc/grafana/provisioning/dashboards:ro`
  Dane: wolumen `grafana-data` pod `/var/lib/grafana`
  `depends_on: [prometheus, loki]`

> **Uwaga o ścieżkach:** plik Compose znajduje się w `infra/docker/…`, dlatego bind-mounty są względne do **roota repo** (`../../../…`).

---

## Sieci i wolumeny

- Sieć: domyślna sieć Compose (brak dedykowanej sieci w tym pliku).
- Wolumeny:
  - `grafana-data`
  - `loki-data`
  - `promtail-tmp` — tymczasowy stan/pozycje (jeśli tak skonfigurowano w promtail)
  - `prometheus-data`

---

## Uruchomienie

```bash
docker compose -f infra/docker/docker-compose.observability.yml up -d
# zatrzymanie
docker compose -f infra/docker/docker-compose.observability.yml down
```

**Gateway poza Compose**
Prometheus może scrapować metryki bram działających na hoście:
- Ingest: `host.docker.internal:8080/metrics`
- AuthGW: `host.docker.internal:8081/metrics`
- Core: `host.docker.internal:8095/metrics`

Na Linuxie, jeśli `host.docker.internal` nie działa, użyj IP hosta (np. `172.17.0.1`).

---

## Pliki konfiguracyjne

- **Loki:** `infra/docker/loki/loki-config.yml`
- **Promtail:** `infra/docker/promtail/promtail-config.yml`
- **Prometheus:** `infra/docker/prometheus/prometheus.yml`
- **Reguły alertów (Prometheus):** `infra/docker/prometheus/alert_rules.yml`
- **Alertmanager:** `infra/docker/alertmanager/alertmanager.yml`

---

## Szybkie sanity-checki

- Grafana: <http://localhost:3000> (admin / **admin**)
- Prometheus: <http://localhost:9090> → „Status → Targets” (Loki, Promtail, bramy)
- Alertmanager: <http://localhost:9093>
- Loki API: <http://localhost:3100/ready>

**Explore / Loki (po tym jak powstaną NDJSON w `data/ingest/`):**
```logql
{job="logops-ndjson", app="logops"}
```
lub zawężone:
```logql
{job="logops-ndjson", app="logops", emitter="emitter_json"}
```

---

## Uwaga: housekeeping

Proces housekeeping (narzędzie/gateway) usuwa lub archiwizuje starsze pliki `*.ndjson` w `data/ingest/`.
To wpływa na dane widoczne w Promtail → Loki. Szczegóły: [docs/tools/housekeeping.md](tools/housekeeping.md).

---

## Najczęstsze problemy

- **Brak logów w Loki:** sprawdź, czy powstają pliki w `data/ingest/*.ndjson` oraz czy ścieżki w `promtail-config.yml` wskazują na:
  - `/var/log/logops` (NDJSON z gatewaya)
  - `/var/log/logops-hosts/logs` i `/var/log/logops-hosts/scenarios` (nowe mounty)
- **Prometheus nie widzi bram:** zweryfikuj adresy `host.docker.internal`/IP hosta w `prometheus.yml`.
- **Alerty nie przychodzą:** uzupełnij Slack webhooks w `.env` i sprawdź konfigurację `alertmanager.yml`.
