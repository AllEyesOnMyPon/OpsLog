# Infrastruktura (Docker)

Środowisko observability uruchamiasz z pliku:
`infra/docker/docker-compose.observability.py`.

## Usługi

- **Loki** — `grafana/loki:2.9.6`
  - Port: `3100:3100`
  - Konfiguracja: `infra/docker/loki/loki-config.yml`
  - Dane: wolumen `loki-data` montowany pod `/loki`
  - Sieć: `obs`

- **Promtail** — `grafana/promtail:2.9.6`
  - Konfiguracja: `infra/docker/promtail/promtail-config.yml`
  - Źródło logów: **bind-mount** `../../data/ingest → /var/logops/data/ingest:ro`
  - Pozycje/offsety: **bind-mount** `./promtail/positions → /var/lib/promtail`
  - Zależności: `depends_on: [loki]`
  - Sieć: `obs`

- **Prometheus** — `prom/prometheus:v2.54.0`
  - Port: `9090:9090`
  - Konfiguracja: `infra/docker/prometheus/prometheus.yml`
  - Reguły alertów: `infra/docker/prometheus/alert_rules.yml`
  - Dane: wolumen `prometheus-data` pod `/prometheus`
  - Sieć: `obs`

- **Grafana** — `grafana/grafana:10.4.0`
  - Port: `3000:3000`
  - Admin pass: `GF_SECURITY_ADMIN_PASSWORD=admin`
  - Datasources provisioning: `infra/docker/grafana/provisioning/datasources → /etc/grafana/provisioning/datasources:ro`
  - Dane: wolumen `grafana-data` pod `/var/lib/grafana`
  - Zależności: `depends_on: [loki, prometheus]`
  - Sieć: `obs`

## Sieci i wolumeny

- Sieć: `obs` (wspólna dla wszystkich usług)
- Wolumeny:
  - `loki-data`, `prometheus-data`, `grafana-data`
  - `promtail-data` — *zdefiniowany*, ale **w aktualnym compose nieużywany** (Promtail korzysta z bind-mountu `./promtail/positions`). Możesz go użyć zamiennie, np.:
    ```yaml
    - promtail-data:/var/lib/promtail
    ```

## Uruchomienie

```bash
docker compose -f infra/docker/docker-compose.observability.py up -d
# zatrzymanie
docker compose -f infra/docker/docker-compose.observability.py down
```

**Gateway poza Compose**: w `prometheus.yml` scrape odbywa się na `host.docker.internal:8080/metrics.`
Na Linuxie zamień to w razie potrzeby na IP hosta (np. `172.17.0.1:8080`).

## Pliki konfiguracyjne

- Loki: `infra/docker/loki/loki-config.yml`

- Promtail: `infra/docker/promtail/promtail-config.yml`

- Prometheus: `infra/docker/prometheus/prometheus.yml`

- Alerty: `infra/docker/prometheus/alert_rules.yml`

Housekeeping (gateway) może usuwać/archiwizować starsze `*.ndjson` w `data/ingest/`.
To wpływa na to, co jeszcze może odczytać Promtail. Szczegóły: `docs/tools/housekeeping.md`.