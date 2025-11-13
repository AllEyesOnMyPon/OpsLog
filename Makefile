# ===================== MAKEFILE (LF only) =====================
.RECIPEPREFIX := >
.ONESHELL:
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# (opcjonalnie ładuj zmienne z .env jeśli plik istnieje)
-include .env

# ====== Narzędzia / binaria ======
PY        ?= $(shell command -v python || command -v python3 || echo $(PWD)/.venv/bin/python)
UVICORN   ?= uvicorn
CURL      ?= curl
JQ        ?= jq

# ====== Globalne ENV (S13/S14) ======
ENTRYPOINT_URL  ?= http://127.0.0.1:8081/ingest
CORE_URL        ?= http://127.0.0.1:8095/v1/logs
LOGOPS_SINK_DIR ?= ./data/ingest
# (opcjonalnie demo-klucze do AuthGW)
LOGOPS_API_KEY  ?=
LOGOPS_SECRET   ?=

# (opcjonalnie: file-sink Core – przydatne do testów)
CORE_SINK_FILE  ?=
CORE_SINK_DIR   ?=

export ENTRYPOINT_URL
export CORE_URL
export LOGOPS_SINK_DIR
export LOGOPS_API_KEY
export LOGOPS_SECRET
export CORE_SINK_FILE
export CORE_SINK_DIR

# ====== Ścieżki i katalogi pomocnicze ======
RUN_DIR   ?= run
LOG_DIR   ?= logs

# ====== Adresy usług lokalnych ======
PROM_HOST ?= 127.0.0.1
PROM_PORT ?= 9090
PROM_URL  := http://$(PROM_HOST):$(PROM_PORT)
export PROM_URL

LOKI_HOST ?= 127.0.0.1
LOKI_PORT ?= 3100
LOKI_URL  := http://$(LOKI_HOST):$(LOKI_PORT)
export LOKI_URL

CORE_HOST ?= 127.0.0.1
CORE_PORT ?= 8095
CORE_APP  := services.core.app:app
CORE_URL_HINT := http://$(CORE_HOST):$(CORE_PORT)/v1/logs

INGEST_HOST ?= 127.0.0.1
INGEST_PORT ?= 8080
INGEST_APP  := services.ingestgw.app:app
INGEST_URL  := http://$(INGEST_HOST):$(INGEST_PORT)

AUTHGW_HOST ?= 127.0.0.1
AUTHGW_PORT ?= 8081
AUTHGW_APP  := services.authgw.app:app
AUTHGW_URL  := http://$(AUTHGW_HOST):$(AUTHGW_PORT)

ORCH_HOST ?= 127.0.0.1
ORCH_PORT ?= 8070
ORCH_APP  := services.orchestrator.app:app
ORCH_URL  := http://$(ORCH_HOST):$(ORCH_PORT)

# ====== Docker Compose (observability stack) ======
COMPOSE_FILE ?=
ifeq ($(COMPOSE_FILE),)
  _CAND := infra/docker/observability/docker-compose.yml \
           infra/docker/docker-compose.observability.yml \
           docker-compose.observability.yml \
           docker-compose.yml
  FOUND_COMPOSE := $(firstword $(wildcard $(_CAND)))
else
  FOUND_COMPOSE := $(COMPOSE_FILE)
endif
ifeq ($(FOUND_COMPOSE),)
  DC := docker compose
  $(warning [Make] Nie znaleziono pliku compose; użyję 'docker compose' bez -f. Podaj COMPOSE_FILE=...)
else
  DC := docker compose -f $(FOUND_COMPOSE)
endif

# ====== PID/LOG pliki ======
CORE_PID   := $(RUN_DIR)/core.pid
CORE_LOG   := $(LOG_DIR)/core.out
INGEST_PID := $(RUN_DIR)/ingest.pid
INGEST_LOG := $(LOG_DIR)/ingest.out
AUTHGW_PID := $(RUN_DIR)/authgw.pid
AUTHGW_LOG := $(LOG_DIR)/authgw.out
ORCH_PID   := $(RUN_DIR)/orch.pid
ORCH_LOG   := $(LOG_DIR)/orch.out
ORCH_LAST  := $(RUN_DIR)/orch.last

# ====== Domyślny cel ======
.DEFAULT_GOAL := help

.PHONY: help dirs up down ps logs prom-reload \
        core-start core-stop core-logs core-restart core-kill-port core-env \
        ingest-start ingest-stop ingest-logs ingest-restart \
        authgw-config authgw-start authgw-stop authgw-logs \
        orch-run orch-dev orch-stop orch-logs \
        orch-start orch-stop-id orch-stop-last orch-list orch-metrics \
        scenario-run scenario-list stack-start stack-stop \
        chaos-on chaos-off chaos-status env \
        prom-orch-running prom-orch-eps \
        e2e report \
        precommit-install precommit-run \
        demo prune-data

# ====== Help ======
help: ## Pokaż listę komend
> @echo "LogOps - skróty komend:"
> @grep -h -E '^[A-Za-z0-9_.%/-]+:.*?## ' $(MAKEFILE_LIST) | \
> awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ====== Katalogi ======
dirs: ## Utwórz katalogi RUN/LOG
> mkdir -p "$(RUN_DIR)" "$(LOG_DIR)"

# =====================================================================
#  Observability stack (Loki/Promtail/Prometheus/Grafana)
# =====================================================================
up: ## Uruchom observability (detached)
> echo ">> compose file: $(FOUND_COMPOSE)"
> $(DC) up -d

down: ## Zatrzymaj observability
> $(DC) down

ps: ## Lista usług (compose)
> $(DC) ps

logs: ## Podgląd logów (compose)
> $(DC) logs -f

prom-reload: ## Przeładuj Prometheusa (HUP + HTTP)
> docker kill --signal=HUP logops-prometheus 2>/dev/null || docker exec logops-prometheus kill -HUP 1 || true
> curl -fsS -X POST $(PROM_URL)/-/reload >/dev/null || true
> echo ">> Prometheus reload triggered"

# =====================================================================
#  Core (8095)
# =====================================================================
core-start: dirs ## Start Core (background)
> if [[ -f "$(CORE_PID)" ]] && kill -0 $$(cat "$(CORE_PID)") 2>/dev/null; then
>   echo "Core already running (PID $$(cat $(CORE_PID)))"; exit 0; fi
> echo ">> starting Core on $(CORE_HOST):$(CORE_PORT)"
> if [[ "$(CORE_SINK_FILE)" == "true" && -n "$(CORE_SINK_DIR)" ]]; then mkdir -p "$(CORE_SINK_DIR)"; fi
> nohup env CORE_SINK_FILE="$(CORE_SINK_FILE)" CORE_SINK_DIR="$(CORE_SINK_DIR)" \
>   $(UVICORN) $(CORE_APP) --host $(CORE_HOST) --port $(CORE_PORT) \
>   >"$(CORE_LOG)" 2>&1 & echo $$! >"$(CORE_PID)"
> sleep 0.3; echo "PID: $$(cat $(CORE_PID))  | logs: $(CORE_LOG)"

core-stop: ## Stop Core
> if [[ -f "$(CORE_PID)" ]]; then
>   PID=$$(cat "$(CORE_PID)")
>   if kill -0 $$PID 2>/dev/null; then echo "stopping Core $$PID" && kill $$PID; fi
>   rm -f "$(CORE_PID)"
> else echo "Core not running"; fi

core-kill-port: ## Awaryjnie zabij proces na :8095 (gdy brak PIDa)
> PID=$$(ss -ltnp | awk '/:$(CORE_PORT)/{match($$0,/pid=([0-9]+)/,m); if (m[1]) print m[1]}'); \
> if [[ -n "$$PID" ]]; then echo "Killing PID $$PID on :$(CORE_PORT)"; kill $$PID || true; else echo "No process on :$(CORE_PORT)"; fi

core-restart: core-stop core-start ## Restart Core

core-logs: ## Tail logów Core
> tail -n 100 -f "$(CORE_LOG)"

core-env: ## Pokaż konfigurację Core z /_debug/hdrs
> curl -s http://$(CORE_HOST):$(CORE_PORT)/_debug/hdrs | $(JQ) '.config'

# =====================================================================
#  Ingest Gateway (8080)
# =====================================================================
ingest-start: dirs ## Start IngestGW (background)
> if [[ -f "$(INGEST_PID)" ]] && kill -0 $$(cat "$(INGEST_PID)") 2>/dev/null; then
>   echo "IngestGW already running (PID $$(cat $(INGEST_PID)))"; exit 0; fi
> echo ">> starting IngestGW on $(INGEST_HOST):$(INGEST_PORT)"
> nohup $(UVICORN) $(INGEST_APP) --host $(INGEST_HOST) --port $(INGEST_PORT) \
>   >"$(INGEST_LOG)" 2>&1 & echo $$! >"$(INGEST_PID)"
> sleep 0.3; echo "PID: $$(cat $(INGEST_PID))  | logs: $(INGEST_LOG)"

ingest-stop: ## Stop IngestGW
> if [[ -f "$(INGEST_PID)" ]]; then
>   PID=$$(cat "$(INGEST_PID)")
>   if kill -0 $$PID 2>/dev/null; then echo "stopping IngestGW $$PID" && kill $$PID; fi
>   rm -f "$(INGEST_PID)"
> else echo "IngestGW not running"; fi

ingest-restart: ingest-stop ingest-start ## Restart IngestGW

ingest-logs: ## Tail logów IngestGW
> tail -n 100 -f "$(INGEST_LOG)"

# =====================================================================
#  Auth & RL Gateway (8081)
# =====================================================================
AUTHGW_CFG := services/authgw/config.rltest.yaml

authgw-config: ## Zbuduj przykładowy config (forward do IngestGW)
> printf '%s\n' \
> 'auth:' \
> '  mode: "hmac"' \
> '  hmac:' \
> '    clock_skew_sec: 300' \
> '    require_nonce: true' \
> '' \
> 'forward:' \
> '  url: "$(INGEST_URL)/v1/logs"' \
> '  timeout_sec: 5' \
> '' \
> 'ratelimit:' \
> '  per_emitter:' \
> '    capacity: 100' \
> '    refill_per_sec: 100' \
> '' \
> 'secrets:' \
> '  clients:' \
> '    demo-pub-1: { secret: "demo-priv-1", emitter: "json" }' \
> '    demo-pub-2: { secret: "demo-priv-2", emitter: "minimal" }' \
> '    demo-pub-3: { secret: "demo-priv-3", emitter: "csv" }' \
> '    demo-pub-4: { secret: "demo-priv-4", emitter: "noise" }' \
> '    demo-pub-5: { secret: "demo-priv-5", emitter: "syslog" }' \
> '' \
> 'backpressure:' \
> '  enabled: true' \
> '  max_body_bytes: 200000' \
> > "$(AUTHGW_CFG)"
> echo ">> wrote $(AUTHGW_CFG)"

authgw-start: dirs authgw-config ## Start AuthGW (background)
> if [[ -f "$(AUTHGW_PID)" ]] && kill -0 $$(cat "$(AUTHGW_PID)") 2>/dev/null; then
>   echo "AuthGW already running (PID $$(cat $(AUTHGW_PID)))"; exit 0; fi
> echo ">> starting AuthGW on $(AUTHGW_HOST):$(AUTHGW_PORT)"
> AUTHGW_CONFIG="$(AUTHGW_CFG)" \
>   nohup $(UVICORN) $(AUTHGW_APP) --host $(AUTHGW_HOST) --port $(AUTHGW_PORT) \
>   >"$(AUTHGW_LOG)" 2>&1 & echo $$! >"$(AUTHGW_PID)"
> sleep 0.3; echo "PID: $$(cat $(AUTHGW_PID))  | logs: $(AUTHGW_LOG)"

authgw-stop: ## Stop AuthGW
> if [[ -f "$(AUTHGW_PID)" ]]; then
>   PID=$$(cat "$(AUTHGW_PID)")
>   if kill -0 $$PID 2>/div/null; then echo "stopping AuthGW $$PID" && kill $$PID; fi
>   rm -f "$(AUTHGW_PID)"
> else echo "AuthGW not running"; fi

authgw-logs: ## Tail logów AuthGW
> tail -n 100 -f "$(AUTHGW_LOG)"

# =====================================================================
#  Orchestrator (8070)
# =====================================================================
orch-run: dirs ## Start Orchestratora (background)
> if [[ -f "$(ORCH_PID)" ]] && kill -0 $$(cat "$(ORCH_PID)") 2>/dev/null; then
>   echo "Orchestrator already running (PID $$(cat $(ORCH_PID)))"; exit 0; fi
> echo ">> starting Orchestrator on $(ORCH_HOST):$(ORCH_PORT)"
> nohup $(UVICORN) $(ORCH_APP) --host $(ORCH_HOST) --port $(ORCH_PORT) \
>   >"$(ORCH_LOG)" 2>&1 & echo $$! >"$(ORCH_PID)"
> sleep 0.3; echo "PID: $$(cat $(ORCH_PID))  | logs: $(ORCH_LOG)"

orch-dev: ## Start Orchestratora z hot-reload (StatReload po odinstalowaniu watchfiles)
> $(UVICORN) $(ORCH_APP) --host $(ORCH_HOST) --port $(ORCH_PORT) --reload \
>  --reload-dir services/orchestrator --reload-dir tools \
>  --reload-include '*.py' \
>  --reload-exclude 'infra/**' --reload-exclude 'data/**' \
>  --reload-exclude '.venv/**' --reload-exclude '.git/**'

orch-stop: ## Stop Orchestratora
> if [[ -f "$(ORCH_PID)" ]]; then
>   PID=$$(cat "$(ORCH_PID)")
>   if kill -0 $$PID 2>/dev/null; then echo "stopping Orchestrator $$PID" && kill $$PID; fi
>   rm -f "$(ORCH_PID)"
> else echo "Orchestrator not running"; fi

orch-logs: ## Tail logów Orchestratora
> tail -n 100 -f "$(ORCH_LOG)"

# ===== Orchestrator API skróty =====
SCEN ?= default

orch-start: ## Start scenariusza: make orch-start SCEN=name | SCEN=scenarios/foo.yaml
> if [[ "$(SCEN)" == *.yaml || "$(SCEN)" == *.yml ]]; then
>   BODY=$$(printf '{"yaml_path":"%s"}' "$(SCEN)")
> else
>   BODY=$$(printf '{"name":"%s"}' "$(SCEN)")
> fi
> echo ">> POST $(ORCH_URL)/scenario/start  $$BODY"
> RESP=$$($(CURL) -s "$(ORCH_URL)/scenario/start" -H 'Content-Type: application/json' -d "$$BODY")
> echo "$$RESP" | $(JQ) . 2>/dev/null || echo "$$RESP"
> ID=$$(echo "$$RESP" | $(JQ) -r '.scenario_id // empty')
> if [[ -n "$$ID" ]]; then echo "$$ID" > "$(ORCH_LAST)"; echo "scenario_id: $$ID"; else echo "WARN: no scenario_id"; fi

ID ?=
orch-stop-id: ## Stop scenariusza po ID: make orch-stop-id ID=sc-xxxx
> test -n "$(ID)" || { echo "ERR: provide ID=sc-..."; exit 2; }
> RESP=$$($(CURL) -s "$(ORCH_URL)/scenario/stop" -H 'Content-Type: application/json' -d "$$(printf '{"scenario_id":"%s"}' "$(ID)")")
> echo "$$RESP" | $(JQ) . 2>/dev/null || echo "$$RESP"

orch-stop-last: ## Stop ostatniego scenariusza (ID z run/orch.last)
> test -f "$(ORCH_LAST)" || { echo "No $(ORCH_LAST) found"; exit 2; }
> ID=$$(cat "$(ORCH_LAST)")
> $(MAKE) orch-stop-id ID=$$ID

orch-list: ## Lista scenariuszy (Orchestrator)
> $(CURL) -s "$(ORCH_URL)/scenario/list" | $(JQ) .

orch-metrics: ## Metryki Orchestratora (grep na orch_* )
> $(CURL) -s "$(ORCH_URL)/metrics" | egrep 'logops_orch_(running|emitted_total|errors_total)' || true

# =====================================================================
#  Scenariusze: runner bezpośrednio
# =====================================================================
scenario-run: ## Uruchom runner (bez Orchestratora) - make scenario-run SCEN=scenarios/default.yaml
> test -n "$(SCEN)" || { echo "ERR: provide SCEN=scenarios/....yaml"; exit 2; }
> $(PY) tools/run_scenario.py --scenario $(SCEN)

scenario-list: ## Wypisz dostępne scenariusze
> ls -1 scenarios | sed 's/^/  - /'

# =====================================================================
#  All-in-one start/stop
# =====================================================================
stack-start: core-start ingest-start authgw-start orch-run ## Odpal cały pipeline + Orchestrator
stack-stop:  orch-stop core-stop ingest-stop authgw-stop   ## Stop wszystkiego

# =====================================================================
#  CHAOS MODE — długi hałas aż go wyłączysz
# =====================================================================
DURATION        ?= 7200
CHAOS_EPS       ?= 80
CHAOS_LVL       ?= 0.7
JSON_EPS        ?= 30
JSON_PARTIAL    ?= 0.5
SYSLOG_EPS      ?= 30
SYSLOG_PARTIAL  ?= 0.4

chaos-on: ## Start "chaos mode"
> mkdir -p "$(RUN_DIR)"
> BODY=$$($(PY) - <<'PY'
> import os, json
> payload = {
>   "inline": {
>     "name": "chaos",
>     "duration_sec": float(os.getenv("DURATION", "7200")),   # steruje scenariuszem
>     "tick_sec": 1.0,
>     "emitters": [
>       {
>         "name": "noise",
>         "eps": float(os.getenv("CHAOS_EPS", "80")),
>         "duration_sec": float(os.getenv("DURATION", "7200")),   # ← per-emitter
>         "args": {"chaos": float(os.getenv("CHAOS_LVL", "0.7")), "seed": 9001}
>       },
>       {
>         "name": "json",
>         "eps": float(os.getenv("JSON_EPS", "30")),
>         "duration_sec": float(os.getenv("DURATION", "7200")),   # ← per-emitter
>         "args": {"partial_ratio": float(os.getenv("JSON_PARTIAL", "0.5")), "seed": 9002}
>       },
>       {
>         "name": "syslog",
>         "eps": float(os.getenv("SYSLOG_EPS", "30")),
>         "duration_sec": float(os.getenv("DURATION", "7200")),   # ← per-emitter
>         "args": {"partial_ratio": float(os.getenv("SYSLOG_PARTIAL", "0.4")), "seed": 9003}
>       },
>     ]
>   },
>   "debug": False
> }
> print(json.dumps(payload))
> PY
> )
> echo ">> POST $(ORCH_URL)/scenario/start"
> echo "$$BODY" | $(JQ) .
> RESP=$$($(CURL) -fsS "$(ORCH_URL)/scenario/start" -H 'Content-Type: application/json' -d "$$BODY")
> echo "$$RESP" | $(JQ) . 2>/dev/null || echo "$$RESP"
> ID=$$(echo "$$RESP" | $(JQ) -r '.scenario_id // empty')
> test -n "$$ID"
> echo "$$ID" > "$(ORCH_LAST)"
> echo "chaos scenario_id: $$ID"

chaos-off: ## Stop ostatniego chaosu (lub podaj ID=...)
> if [[ -n "$(ID)" ]]; then $(MAKE) orch-stop-id ID=$(ID); else $(MAKE) orch-stop-last; fi

chaos-status: ## Lista scenariuszy + metryki orch_*
> echo ">> Orchestrator scenarios:"; $(CURL) -s "$(ORCH_URL)/scenario/list" | $(JQ) '.items'
> echo ">> Orchestrator metrics:";   $(CURL) -s "$(ORCH_URL)/metrics" | grep -E 'logops_orch_(running|emitted_total|errors_total)' || true

# =====================================================================
#  Prometheus szybkie zapytania
# =====================================================================
prom-orch-running: ## sum(logops_orch_running)
> $(CURL) -s '$(PROM_URL)/api/v1/query?query=sum(logops_orch_running)' | $(JQ) .

prom-orch-eps: ## rate(logops_orch_emitted_total[1m]) by (emitter)
> $(CURL) -s '$(PROM_URL)/api/v1/query?query=sum%20by%20(emitter)(rate(logops_orch_emitted_total%5B1m%5D))' | $(JQ) .

# =====================================================================
#  E2E smoke + raport
# =====================================================================
e2e: ## Uruchom E2E smoke (scripts/obs_smoke_e2e.sh). Użyj env: DURATION, EPS, BATCH, SCENARIO_ID
> chmod +x scripts/obs_smoke_e2e.sh
> ./scripts/obs_smoke_e2e.sh

report: ## Wygeneruj raport Markdown z ostatniego scenariusza (scripts/obs_report.sh). Użyj env: SCENARIO_ID, WINDOW
> chmod +x scripts/obs_report.sh
> ./scripts/obs_report.sh

# =====================================================================
#  Pre-commit / git-secrets
# =====================================================================
precommit-install: ## Zainstaluj pre-commit i skonfiguruj git-secrets (jeśli dostępny)
> pip install -r requirements-dev.txt || pip install pre-commit black ruff
> pre-commit install
> if command -v git-secrets >/dev/null 2>&1; then \
>   git secrets --install || true; \
>   git secrets --register-aws || true; \
>   git secrets --add 'LOGOPS_SECRET' || true; \
>   git secrets --add 'demo-priv-[0-9]+' --allowed || true; \
>   echo "git-secrets: skonfigurowane"; \
> else \
>   echo "git-secrets: nie znaleziono w PATH (pomijam)"; \
> fi
> echo "pre-commit: zainstalowane"

precommit-run: ## Uruchom wszystkie hooki na całym repo
> pre-commit run --all-files || true

# =====================================================================
#  Demo: boot stack + krótki scenariusz + otwarcie dashboardu
# =====================================================================
GRAFANA_HOST ?= 127.0.0.1
GRAFANA_PORT ?= 3000
DASH_UID     ?= logops-observability-slo

demo: ## Uruchom demo (stack + krótki ruch + otwarcie dashboardu)
> $(MAKE) up
> $(MAKE) stack-start
> DURATION=8 EPS=6 BATCH=1 ./scripts/obs_smoke_e2e.sh --quiet || true
> SCEN_ID=$$(test -f $(ORCH_LAST) && cat $(ORCH_LAST) || echo ".*")
> echo "scenario_id: $$SCEN_ID"
> URL="http://$(GRAFANA_HOST):$(GRAFANA_PORT)/d/$(DASH_UID)?from=now-30m&to=now&var_level=%24__all&var_emitter=%24__all&var_scenario=$$SCEN_ID&var_p_emitter=%24__all"
> echo "Opening: $$URL"
> if command -v xdg-open >/dev/null 2>&1; then xdg-open "$$URL" >/dev/null 2>&1 || true; \
> elif command -v open >/dev/null 2>&1; then open "$$URL" || true; \
> else echo "Open this URL in your browser: $$URL"; fi

# =====================================================================
#  Retencja danych (NDJSON + ślady scenariuszy)
# =====================================================================
RETENTION_DAYS ?= 7
prune-data: ## Usuń dane starsze niż RETENTION_DAYS (domyślnie 7)
> echo "Pruning data older than $(RETENTION_DAYS) days…"
> find data/ingest -type f -mtime +$(RETENTION_DAYS) -name '*.ndjson' -print -delete 2>/dev/null || true
> find data/orch/scenarios -type f -mtime +$(RETENTION_DAYS) -name '*.jsonl' -print -delete 2>/dev/null || true
> find data/orch/tmp_scenarios -type f -mtime +1 -name '*.yaml' -print -delete 2>/dev/null || true
> echo "Done."

# =====================================================================
#  Drobiazgi
# =====================================================================
env: ## Stwórz .env z .env.example jeśli nie istnieje
> test -f .env || cp .env.example .env
