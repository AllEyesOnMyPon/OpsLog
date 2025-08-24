# Overview

**LogOps** to środowisko deweloperskie do emisji, zbierania i obserwowalności logów.  
Cel projektu: stworzyć modularny system, który pozwoli symulować różne źródła logów (emitery), odbierać je w gatewayu (FastAPI), normalizować, a następnie przesyłać do stacku obserwowalności (Promtail → Loki → Grafana/Prometheus).

## Aktualny zakres (MVP)
- **Emitery**: CSV, JSON, minimal, noise, syslog  
- **Ingest Gateway** (FastAPI): endpointy `/healthz`, `/metrics`, `/v1/logs`  
- **Observability stack** (Docker Compose): Loki, Promtail, Prometheus, Grafana  
- **Dashboardy w Grafanie** (logi + metryki)  
- **Alerty w Prometheusie** (~10 zasad)  
- **Format NDJSON** dla logów, z opcjonalnym maskowaniem/szyfrowaniem PII  

## Out of scope (na teraz)
- uruchamianie w chmurze  
- integracja z Kubernetes  
- zaawansowane mechanizmy multi-user / multi-tenant  

## Następne kroki
- Rozbudowa emiterów o dodatkowe formaty (np. Apache/Nginx access log)  
- Testy end-to-end (od emitera do Grafany)  
- Dokumentacja alertów i dashboardów  
