# Roadmap — LogOps (po v0.4)

Krótka, żywa roadmapa. Elementy pogrupowane per wersję i horyzont.
`[ ]` → `[x]`

---

## 🕰️ Historia wersji

- **v0.1 — Sterylny Ingest**
  - [x] Ingest Gateway (FastAPI) z prostym przyjęciem logów (bez pełnego tagowania)
- **v0.2 — Housekeeping + Observability**
  - [x] Retencja + archiwizacja NDJSON
  - [x] Stack: Loki/Promtail, Prometheus, Grafana
- **v0.3 — CLI-first orchestration + validation + dashboard & alerts**
  - [x] `tools/run_scenario.py` (CLI), scenariusze YAML
  - [x] Walidacja wejścia, pierwsze dashboardy i alerty
- **v0.4 — Auth + run_scenario + SLO/p95**
  - [x] Auth Gateway (HMAC/API key, RL, backpressure, forward)
  - [x] Rozszerzone metryki i reguły (SLO + p95)
  - [x] Narzędzia HMAC i scenariusze (run_scenario)

---

## 🎯 v0.5 — Operacyjność E2E + pierwszy krok w skalowanie
> Cel: **single pane of glass** w Grafanie + **control-plane do uruchamiania ruchu**, test E2E z alertem, oraz **pierwszy kontakt z K8s/CI/CD/GUI**.

### CORE (~70%)
- **Orchestrator (control-plane API)**
  - [x] `services/orchestrator/` (FastAPI): `POST /scenario/start|stop`, `GET /scenario/list`
  - [x] Generowanie `scenario_id` + metryki: `logops_orch_running`, `logops_orch_emitted_total`, `logops_orch_errors_total`
  - [x] Emitery: honorują profil z orchestratora, **tagują logi `scenario_id`**
- **Dashboard “LogOps: E2E” (provisioning jako kod)**
  - [x] Datasources (Prometheus, Loki) + `dashboards/` (JSON)
  - [x] Panele: **Error rate (SLO)**, **p95 ingest latency**, **AuthGW 429/413**, **parse_errors**, **Live Logs** po `scenario_id`
  - [x] Zmienne: `env`, `service`, `scenario_id`; panel „Alert list” (Unified Alerting)
- **Alert rules — pokrycie wszystkich emiterów**
  - [x] Reguły w PromQL z wymiarem `emitter` (i agregat bez `emitter`)
  - [x] Progi i `for:` urealnione po testach scenariuszy (happy/burst/rl/bp)
- **Test E2E + report**
  - [x] `make e2e`: start scenariuszy → weryfikacja logów w Lokim i stanu alertów (AM/Grafana)
  - [x] `make report`: raport `.md` z Prometheus/Loki API (headless)
- **Higiena repo / bezpieczeństwo**
  - [x] `.env.example` + `.env.local` w `.gitignore`
  - [x] Pre-commit (ruff/black, git-secrets) — brak sekretów w diffach
- **Dokumentacja operacyjna**
  - [x] Quickstart (90s) — `make demo`
  - [x] Playbook: „Jak uruchomić scenariusz i zobaczyć alert”
  - [x] Runbook: „Co zrobić, gdy p95/SLO się odpali”

### EXPLORATION (~30%)
- **K8s (spike)**
  - [ ] Uruchom **Auth+Ingest** w Kind/Minikube jako `Deployment + Service`
  - [ ] ConfigMap/Secret na env/secrety; **bez** Helm — tylko „działa w K8s”
- **CI/CD (spike)**
  - [ ] GitHub Actions: lint (ruff/black) + pytest (services/tools)
  - [ ] Badge w README
- **GUI (spike)**
  - [ ] Prosta strona (FastAPI + HTMX) w orchestratorze: **przycisk „Start scenario (burst)”**
  - [ ] Wyświetl `scenario_id` i link do Explore (Grafana) z presetem filtra

---

## 🔧 Zmiany w alertach (multi-emitter & scenario-aware)
- [ ] Zmień liczniki na **wymiarowane po `emitter`**:
  - `sum by (emitter)(rate(logops_errors_total[5m]))`
  - `sum without (emitter)(...)` dla agregatów globalnych
- [ ] Dodaj wymiar **`scenario_id`** do części zapytań (diagnoza demo)
- [ ] Osobne reguły na **AuthGW 429/413**, **Ingest parse_errors**, **Latency p95**

---

## 🛣️ v0.6 — „Pierwsze skalowanie”
- [ ] **Horizontal scaling**: 2 repliki Ingest (lokalnie/docker-compose lub K8s)
- [ ] **CI/CD+containers**: build/push obrazów do GHCR, deploy do Kind (kubectl apply)
- [ ] **GUI+control**: panel orchestratora z wyborem profilu, duration, RPS; log działań
- [ ] **Alerting jako code**: pełne provisioning reguł i kontakt pointów (Slack/webhook)

## 🛰️ v0.7 — „Twardsza platforma”
- [ ] Helm Chart (Ingest/Auth/Orch) + values dla lokal/ci
- [ ] Multi-tenant (`tenant_id` label), limity per tenant
- [ ] Sink S3/GCS (rotacja dzienna) + narzędzie offline do odszyfr. PII
- [ ] Testy E2E w CI (uruchom stack, odpal scenario, asercje Prom/Loki)

---

## 📐 Definition of Done (v0.5)
- [ ] `make demo` podnosi stack i uruchamia „happy path”; dashboard pokazuje ruch
- [ ] `make e2e` wyzwala **co najmniej 1 alert** i zapisuje `artefacts/run/.../report.md`
- [ ] Grafana provisioning, alert rules i dashboardy są w repo jako kod
- [ ] Reguły obejmują **wszystkie emitery** (wymiar `emitter`) + agregaty
- [ ] Orchestrator nadaje `scenario_id` i eksponuje metryki
- [ ] Brak sekretów w repo (pre-commit przechodzi)

---

## 📝 Zasady aktualizacji roadmapy
- Short (aktywny milestone) ≤ **7 pozycji** — jeśli coś dochodzi, coś spada do v0.6
- Każdy release = **2–4 zadania core + 1–2 zadania exploration**
- Każdy PR: prefiks `feat:` / `chore:` / `docs:` + link w roadmapzie po domknięciu
