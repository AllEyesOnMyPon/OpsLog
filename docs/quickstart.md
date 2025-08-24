# Quickstart

Instrukcja uruchomienia środowiska LogOps w trybie lokalnym.

---

## 1. Wymagania
- Docker + Docker Compose  
- Python 3.11 (dla emiterów)  
- Uvicorn (`pip install uvicorn[standard] fastapi`)  
- `requests` (`pip install requests`)  

---

## 2. Uruchom stack observability
W katalogu głównym repo:
```bash
docker compose -f infra/docker/docker-compose.observability.py up -d
```
**Usługi:**

- Prometheus → http://localhost:9090

- Grafana → http://localhost:3000
 (login: admin, hasło: admin)

- Loki API → http://localhost:3100

## 3. Uruchom ingest gateway
```bash
uvicorn services.ingest_gateway.gateway:app --host 0.0.0.0 --port 8080 --reload
```
Health check: http://localhost:8080/healthz

Metryki Prometheus: http://localhost:8080/metrics
## Wyślij sample logi z emitera CSV
```bash
python emitters/emitter_csv.py -n 10 --partial-ratio 0.3
```
Wyśle POST /v1/logs z Content-Type text/csv.
## 5. Sprawdź logi w Lokim

**Linux/macOS (curl):**
```bash
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```
**Windows PowerShell (irm):**
```powershell
irm "http://localhost:3100/loki/api/v1/query?query={job='logops-ndjson',app='logops',emitter='emitter_csv'}"
```
## 6. Podejrzyj w Grafanie

1. Wejdź na http://localhost:3000

2. Wybierz Explore → Loki datasource

3. Wpisz zapytanie:
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```
4. Powinieneś zobaczyć logi wygenerowane przez emitter_csv.
## 7. (Opcjonalnie) Import gotowego dashboardu Grafany

W repo znajduje się gotowy dashboard w pliku: docs/grafena_dashboard.json.
Możesz go natychmiast zaimportować w UI Grafany:

1. W Grafanie: Dashboards → New → Import

2. Kliknij Upload JSON file i wskaż docs/grafena_dashboard.json

3. Wybierz datasource Loki (jeśli jest wymagane) i Import

Po imporcie pojawi się dashboard z widokiem logów/metryk dopasowany do LogOps.