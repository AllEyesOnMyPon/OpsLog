# LogOps

System do emisji, zbierania i obserwowalności logów w środowisku deweloperskim.  
Przepływ: **emitery → ingest gateway (FastAPI) → Promtail/Loki → Grafana/Prometheus**.  
Gateway wspiera normalizację logów, opcjonalny zapis do pliku NDJSON, maskowanie/szyfrowanie danych PII oraz mechanizm **housekeeping** do utrzymywania katalogu z logami.


---

## Szybki start

### 1. Uruchom stack observability (Loki, Promtail, Prometheus, Grafana)
```bash
docker compose -f infra/docker/docker-compose.observability.py up -d
```
Usługi dostępne lokalnie:

Gateway (FastAPI): http://localhost:8080/healthz

Prometheus: http://localhost:9090

Grafana: http://localhost:3000
 (login: admin / hasło: admin)

Loki API: http://localhost:3100

### 2. Uruchom gateway

```bash
uvicorn services.ingest_gateway.gateway:app --host 0.0.0.0 --port 8080 --reload
```
### 3. Wyślij sample logi z emitera CSV

```bash
python emitters/emitter_csv.py -n 10 --partial-ratio 0.3
```
### 4. Sprawdź logi w Lokim
**Linux/macOS (curl):**
```bash
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```
**Windows PowerShell (irm):**
```powershell
irm "http://localhost:3100/loki/api/v1/query?query={job='logops-ndjson',app='logops',emitter='emitter_csv'}"
```
## Endpointy gatewaya

- GET /healthz – status + wersja

- GET /metrics – metryki Prometheus

- POST /v1/logs – przyjmowanie logów (json, text/csv, text/plain syslog-like)

Przykładowy rekord (po normalizacji):
```json
{
  "ts": "2025-08-23T12:00:00+00:00",
  "level": "INFO",
  "msg": "masked message...",
  "emitter": "emitter_csv"
}
```
## Housekeeping

Housekeeping to proces utrzymania plików NDJSON w katalogu `data/ingest/`.

- Usuwa lub archiwizuje stare pliki (`*.ndjson`) starsze niż `LOGOPS_RETENTION_DAYS`.  
- Tryby: `delete` (domyślny) lub `zip`.  
- Może działać cyklicznie w tle (sterowane ENV w gatewayu) lub być uruchamiany ręcznie.  

👉 Szczegóły: [docs/tools/housekeeping.md](docs/tools/housekeeping.md)

## Struktura repo
```bash
logops/
├── data/ingest/                         # pliki NDJSON (opcjonalny sink)
├── docs/                                # dokumentacja szczegółowa
├── emitters/                            # generatory logów (CSV/JSON/minimal/noise/syslog)
├── infra/docker/                        # stack observability (Loki, Promtail, Prometheus, Grafana)
├── services/ingest_gateway/gateway.py   # FastAPI: /healthz /metrics /v1/logs
├── tools/housekeeping.py                # housekeeping: cleanup/archiwizacja logów
└── tests/                               # testy jednostkowe i e2e

```
## Dokumentacja szczegółowa

- [Przegląd](docs/overview.md)  
- [Architektura](docs/architecture.md)  
- [Quickstart](docs/quickstart.md)  
- [Observability](docs/observability.md)  
- [Ingest Gateway (API)](docs/services/ingest_gateway.md)  
- [Emitery](docs/services/emitters.md)  
- [Housekeeping](docs/tools/housekeeping.md)  
- [Infrastruktura (Docker)](docs/infra.md)  
- [Testy](docs/testing.md)  
- [Roadmap](docs/roadmap.md)

## Testy
```bash
pytest -q
```
## Licencja

MIT