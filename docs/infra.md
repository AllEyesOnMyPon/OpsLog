# Infrastruktura (Docker)

Środowisko observability uruchamiasz z pliku:  
`infra/docker/docker-compose.observability.yml`

---

## Usługi

- **Loki** — `grafana/loki:2.9.6`  
  - Port: `3100:3100`  
  - Konfiguracja: `infra/docker/loki/loki-config.yml`  
  - Dane: wolumen `loki-data` montowany pod `/loki`  
  - Sieć: `obs`  

- **Promtail** — `grafana/promtail:2.9.6`  
  - Konfiguracja: `infra/docker/promtail/promtail-config.yml`  
  - Źródło logów: bind-mount `../../data/ingest → /var/logops/data/ingest:ro`  
  - Pozycje/offsety: bind-mount `./promtail/positions → /var/lib/promtail`  
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
  - Hasło admina: `GF_SECURITY_ADMIN_PASSWORD=admin`  
  - Datasources provisioning: `infra/docker/grafana/provisioning/datasources → /etc/grafana/provisioning/datasources:ro`  
  - Dane: wolumen `grafana-data` pod `/var/lib/grafana`  
  - Zależności: `depends_on: [loki, prometheus]`  
  - Sieć: `obs`  

- **Alertmanager** — `prom/alertmanager:v0.27.0`  
  - Port: `9093:9093`  
  - Konfiguracja generowana z szablonu: `infra/docker/alertmanager/alertmanager.tmpl.yml`  
  - Po wygenerowaniu zapisywana w: `infra/docker/alertmanager/rendered/alertmanager.yml`  
  - Sieć: `obs`  
  - Integracja: Slack webhooks (definiowane w `.env`)  
  - Obsługuje reguły z Prometheusa (`alert_rules.yml`)  

---

## Sieci i wolumeny

- Sieć: `obs` (wspólna dla wszystkich usług)  
- Wolumeny:  
  - `loki-data`  
  - `prometheus-data`  
  - `grafana-data`  
  - `promtail-data` — *zdefiniowany*, ale w Compose nieużywany (Promtail korzysta z bind-mountu `./promtail/positions`). Można go użyć alternatywnie:  
    ```yaml
    - promtail-data:/var/lib/promtail
    ```

---

## Uruchomienie

```bash
docker compose -f infra/docker/docker-compose.observability.yml up -d
# zatrzymanie
docker compose -f infra/docker/docker-compose.observability.yml down
```

**Gateway poza Compose**:  
W pliku `prometheus.yml` scrape odbywa się na `host.docker.internal:8080/metrics`.  
Na Linuxie zamień to na IP hosta (np. `172.17.0.1:8080`).  

---

## Pliki konfiguracyjne

- Loki: `infra/docker/loki/loki-config.yml`  
- Promtail: `infra/docker/promtail/promtail-config.yml`  
- Prometheus: `infra/docker/prometheus/prometheus.yml`  
- Alerty Prometheus: `infra/docker/prometheus/alert_rules.yml`  
- Alertmanager:  
  - szablon: `infra/docker/alertmanager/alertmanager.tmpl.yml`  
  - wygenerowany plik: `infra/docker/alertmanager/rendered/alertmanager.yml`  

---

## Uwaga: housekeeping

Proces housekeeping (działający w gatewayu) usuwa lub archiwizuje starsze pliki `*.ndjson` w `data/ingest/`.  
To wpływa na dane dostępne dla Promtail → Loki. Szczegóły: [docs/tools/housekeeping.md](tools/housekeeping.md).
