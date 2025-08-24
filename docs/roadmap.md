# Roadmap — LogOps

Krótka, żywa roadmapa rozwoju LogOps. Cele są zgrupowane na krótkie / średnie / długie terminy.  
`[ ]` → `[x]`

---

## Baseline (zrobione)

- [x] Emitery: CSV, JSON, Minimal, Noise, Syslog — `/emitters/*`
- [x] Ingest Gateway (FastAPI): `/v1/logs`, `/metrics`, `/healthz` — `services/ingest_gateway/gateway.py`
- [x] Normalizacja + PII (mask/enc), zapis NDJSON (opcjonalny)
- [x] Housekeeping: retention + archiwizacja zip — `tools/housekeeping.py`
- [x] Observability stack (Loki, Promtail, Prometheus, Grafana)
- [x] Alerty Prometheusa (10 reguł) — `infra/docker/prometheus/alert_rules.yml`
- [x] Dokumentacja modułowa + C4 (C1–C3) — `docs/*`, `docs/architecture/workspace.dsl` + `docs/architecture/c1.png,c2.png,c3.png`

---

## Short term (najbliższe tygodnie)

**Emitery i scenariusze**
- [ ] Dodać katalog `scenarios/` z profilami ruchu (`default.yaml`, `burst.yaml`, `quiet-then-spike.yaml`, `high-errors.yaml`)
- [ ] (Opcjonalnie) dopisać do emiterów nagłówek `X-Emitter` zawsze (jeśli gdzieś brakuje), by `emitter=` był w Lokim przewidywalny

**Orchestracja „CLI first”**
- [ ] `tools/run_scenario.py`: CLI, które odpala emitery wg scenariusza (czas trwania, EPS, rozkład leveli)
- [ ] Wypisywać krótkie statystyki na koniec (ile wysłano per emitter/level)
- [ ] Dodać targety do `Makefile`: `scenario:run`, `emit:*` (opcjonalnie)

**Gateway**
- [ ] Walidacja wejścia (proste `pydantic` modele; 400/422 dla złych danych)
- [ ] Drobne metryki dodatkowe (np. `logops_parse_errors_total`)

**Observability i alerty**
- [ ] Dashboard Grafany: panele pod orchestrację/scenariusze (EPS, udział poziomów, missing ts/level)
- [ ] Dopracować alerty progowe po testach scenariuszy (progi, `for`, opisy)

**Dokumentacja**
- [ ] Uzupełnić `docs/services/orchestrator.md` (jeśli ruszy CLI)
- [ ] Dodać `.env.example` z flagami: `LOGOPS_SINK_FILE`, `LOGOPS_ENCRYPT_PII`, `LOGOPS_RETENTION_DAYS`, `LOGOPS_ARCHIVE_MODE`, `LOGOPS_HOUSEKEEP_*`
- [ ] Uporządkować nazewnictwo README emiterów (docelowo `docs/emitters/emitter_xxx.md` lub `docs/emitters/emitter_xxx/README.md`)

---

## Medium term (1–2 mies.)

**Orchestrator (lekki serwis + GUI)**
- [ ] `services/orchestrator/` (FastAPI + HTMX/Alpine): endpointy `start/stop/status`, proste GUI
- [ ] Sterowanie EPS: throttling (token bucket), scenariusze z YAML
- [ ] Metryki orchestratora: `logops_orch_emitted_total`, `logops_orch_running`, `logops_orch_errors_total`
- [ ] WebSocket do live-podglądu (liczniki) — opcjonalnie

**Konteneryzacja i Compose**
- [ ] `Dockerfile` dla gatewaya
- [ ] Nowy `docker-compose` spinający **gateway + observability** (osobny od `observability`)

**Testy i jakość**
- [ ] Test E2E: uruchom mini-scenario → sprawdź query do Lokiego i metryki Prometheusa (asercje)
- [ ] Linting i format: `ruff/black/isort` + `pre-commit` hooki
- [ ] CI (GitHub Actions): lint + testy + budowa obrazów Docker (opcjonalnie publikacja do GHCR)

**Housekeeping/retencja**
- [ ] Dokumentacja edge-case: wpływ retencji NDJSON vs. retencja Loki (48h) — `docs/observability.md` update
- [ ] (Opcjonalnie) Rotacja plików NDJSON co `HH` zamiast dobowo — jeśli pojawią się duże wolumeny

---

## Long term (3+ mies.)

**Źródła i sinki**
- [ ] Emiter „access-log” (Nginx/Apache), emiter „kafka” (symulacja konsumenta)
- [ ] Alternatywny sink: S3/Azure Blob (przykład integracji chmurowej)

**Kubernetes**
- [ ] Manifests/Helm/kustomize dla pełnego stacku (gateway + observability + orchestrator)
- [ ] Kind/Minikube jako środowisko lokalne do demonstracji

**Multi-tenant ingest**
- [ ] Obsługa `tenant_id` (etykieta, separacja scenariuszy / filtrowanie w Lokim)
- [ ] (Opcjonalnie) proste limitowanie per tenant (token bucket na wejściu gatewaya)

**Analityka**
- [ ] Proste wykrywanie anomalii na metrykach ingestu (np. regresje/bursty)
- [ ] Klasyfikacja logów / clustering — proof-of-concept (off-line, raport do Grafany)

---

## Odnośniki

- Przegląd: `docs/overview.md`  
- Quickstart: `docs/quickstart.md`  
- Observability: `docs/observability.md`  
- Infrastruktura (Docker): `docs/infra.md`  
- Ingest Gateway (API): `docs/services/ingest_gateway.md`  
- Emitery: `docs/services/emitters.md` + `docs/emitters/*`  
- Housekeeping: `docs/tools/housekeeping.md`  
- Architektura (C4): `docs/architecture.md` + `docs/architecture/workspace.dsl`

---

## Zasady aktualizacji roadmapy

- Krótkie PR-y, każda pozycja z listy → osobny commit/PR z prefiksem `feat:` / `chore:` / `docs:`.  
- Po wdrożeniu: oznacz `[x]`, dopisz link do PR/commita i ewentualnie datę.  
- Co sprint/przegląd: przesuń elementy między sekcjami (short → medium → done).

