# Overview

**LogOps** to środowisko deweloperskie do emisji, zbierania i obserwowalności logów.  
Celem projektu jest stworzenie modularnego systemu, który pozwala:

- **generować ruch testowy** z wielu źródeł logów (emitery),
- **przyjmować i walidować** logi w gatewayach (Ingest GW i Auth GW),
- **normalizować i przesyłać** je do stacku obserwowalności,
- **monitorować, analizować i alarmować** na podstawie metryk i logów.

---

## Aktualny zakres (MVP v0.4)

### Emitery
- CSV, JSON, minimal, noise, syslog
- scenariusze (`scenarios/*.yaml`) pozwalające na testowanie różnych profili ruchu (quiet, spike, burst, high-errors, ramp-up/down)
- narzędzie `tools/run_scenario.py` do orkiestracji wielu emiterów i zapisywania wyników

### Gatewaye
- **Ingest Gateway** (FastAPI):
  - endpointy `/healthz`, `/metrics`, `/v1/logs`
  - normalizacja i zliczanie braków pól (`ts`, `level`)
- **Auth Gateway**:
  - middleware HMAC (`hmac_mw.py`) — podpisywanie i weryfikacja żądań
  - middleware rate-limit (`ratelimit_mw.py`)
  - mechanizm backpressure (limity body / liczby elementów)
  - downstream forwarding z retry i circuit breakerem (`downstream.py`)
  - konfiguracja przykładowa (`config.rltest.yaml`) oraz wrappery `tools/sign_hmac.py`, `tools/hmac_curl.sh`

### Observability stack (Docker Compose)
- **Promtail**: zbiera i parsuje logi NDJSON
- **Loki**: storage i query logów (retencja 48h)
- **Prometheus**: zbieranie metryk (Ingest GW, Auth GW, Promtail, Loki, self)
- **Alertmanager**: routing alertów do Slacka
- **Grafana**: dashboardy (metryki + logi live-tail)

### Monitoring i alerty
- ~10 reguł Prometheus (brak ingestu, burst, brak timestamp/level, inflight stuck, brak metryk z GW)
- dodatkowe SLO reguły (`logops.slo`): p95 latency, % batchy < 500ms
- Dashboard Grafany (`docs/grafana_dashboard.json`) — widok EPS, missing fields, inflight, rejected, p95 latency, top emitters, live tail

### Narzędzia developerskie
- `tools/housekeeping.py` — usuwanie/archiwizacja starych plików ingest NDJSON
- `tools/sign_hmac.py` — generowanie podpisów HMAC
- `tools/hmac_curl.sh` — wrapper `curl` do łatwego testowania AuthGW
- Makefile — skróty dla emiterów, scenariuszy, start/stop GW, observability stacku i testów AuthGW

---

## Out of scope (na teraz)
- uruchamianie w chmurze i Kubernetes
- multi-tenant / multi-user isolation
- długoterminowy storage logów (obecnie tylko filesystem + retencja 48h)

---

## Następne kroki (roadmapa)
- rozbudowa emiterów o dodatkowe formaty (np. Apache/Nginx access log, sysmon/Windows events)
- testy E2E w trybie CI/CD
- integracja z zewnętrznymi systemami (np. ELK stack jako alternatywa)
- dodatkowe reguły alertów (np. na podstawie poziomu błędów aplikacyjnych)
- przygotowanie dokumentacji user-guide (dla DevOps/QA)
