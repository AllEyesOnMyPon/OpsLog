# Architektura LogOps (v0.4)

Dokument opisuje architekturę systemu LogOps z wykorzystaniem metodyki **C4 model**.  
Diagramy są definiowane w [Structurizr DSL](https://structurizr.com/dsl) i uruchamiane lokalnie przez obraz `structurizr/lite`.

Nowości v0.4:
- Dodany **Auth Gateway** (HMAC, rate limiting, backpressure, forward do Ingest).
- Narzędzia HMAC (`tools/sign_hmac.py`, `tools/hmac_curl.sh`) oraz orchestrator scenariuszy (`tools/run_scenario.py`).
- Rozszerzone metryki i reguły alertów (w tym SLO i p95).

---

## C1: System Context

Najważniejsi aktorzy i systemy zewnętrzne.  
Deweloper uruchamia emitery i scenariusze; użytkownik ogląda logi i metryki w Grafanie; monitoring zapewniają Prometheus + Alertmanager.

**Diagram C1:**  
![C1 System Context](architecture/C1.png)

---

## C2: Containers

Widok kontenerów w LogOps (v0.4):

- **Emitters & Scenario Orchestrator** – generują ruch/logi zgodnie z profilami EPS (rampy, bursty), zapisują telemetrię scenariuszy do JSONL.
- **Auth Gateway** – weryfikacja HMAC/API key, rate limiting per emitter (token bucket), backpressure (413), forward do Ingest, `/metrics`.
- **Ingest Gateway** – parsowanie i normalizacja, PII mask/enc, opcjonalny **File Sink** (NDJSON), `/metrics`, **housekeeping autorun**.
- **Promtail → Loki** – zbieranie i przechowywanie logów.
- **Prometheus → Alertmanager** – metryki i alerty (w tym SLO/p95).
- **Grafana** – dashboardy + Explore.

**Diagram C2:**  
![C2 Containers](architecture/C2.png)

---

## C3: Auth Gateway – Components

Wewnątrz **AuthGW**:
- `HmacAuthMiddleware` – weryfikacja `X-Api-Key`, `X-Timestamp`, `X-Content-SHA256`, `X-Signature`, anty-replay (`X-Nonce`), tolerancja zegara.
- `TokenBucketRL` – rate limit per-emitter (capacity/refill).
- `Backpressure Filter` – kontrola rozmiaru/ilości elementów (413 + `x-backpressure-reason`).
- `Downstream Forwarder` – forward do Ingest (retry + exponential backoff + circuit breaker).
- `Metrics Exporter` – metryki Prometheus (w tym rejected).

**Diagram C3 (AuthGW):**  
![C3 Auth Gateway](architecture/C3_auth.png)

---

## C3: Ingest Gateway – Components

Wewnątrz **Ingest**:
- `API (/v1/logs, /metrics, /healthz)` – wejście ruchu z AuthGW / testów lokalnych.
- `Parsers` – JSON / CSV / plain (syslog-like).
- `Normalizer + PII` – mapowanie level, maskowanie/szyfrowanie PII (Fernet), walidacja.
- `File Sink` – zapis do plików NDJSON (dziennie).
- `Metrics Exporter` – metryki (`ingested_total`, `missing_ts/level`, `parse_errors`, `inflight`, histogramy batch latency).
- `Housekeeping Trigger` – autorun + interval → `tools.housekeeping.run_once()`.

**Diagram C3 (Ingest):**  
![C3 Ingest Gateway](architecture/C3_ingest.png)

---

