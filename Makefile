# ====== Config ======
PY ?= $(shell command -v python || command -v python3 || echo $(PWD)/.venv/bin/python)
UVICORN   ?= uvicorn

COMPOSE_FILE := infra/docker/docker-compose.observability.yml
DC          := docker compose -f $(COMPOSE_FILE)

GATEWAY_APP := services.ingest_gateway.gateway:app
HOST        ?= 0.0.0.0
PORT        ?= 8080

# domyślne parametry emiterów (możesz nadpisywać: make emit-csv N=50 PARTIAL=0.1)
N        ?= 20
PARTIAL  ?= 0.3
CHAOS    ?= 0.5
JSON_PARTIAL ?= 0.3
SEED     ?=

# ====== Help (domyślny cel) ======
.DEFAULT_GOAL := help
help: ## Pokaż listę komend
	@echo "LogOps Makefile — skróty komend:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ====== Observability stack (Compose) ======
up: ## Uruchom Loki/Promtail/Prometheus/Grafana (detached)
	$(DC) up -d

down: ## Zatrzymaj i usuń kontenery observability
	$(DC) down

ps: ## Lista działających usług (compose)
	$(DC) ps

logs: ## Podgląd logów usług (compose)
	$(DC) logs -f

prom-reload: ## Przeładuj Prometheusa (po zmianie reguł)
	docker exec -it logops-prometheus kill -HUP 1

# ====== Gateway ======
gateway: ## Uruchom Ingest Gateway (uvicorn, foreground)
	$(UVICORN) $(GATEWAY_APP) --host $(HOST) --port $(PORT) --reload

# ====== Emitery ======
emit-csv: ## Wyślij sample z emitter_csv (N, PARTIAL)
	$(PY) emitters/emitter_csv/emit_csv.py -n $(N) --partial-ratio $(PARTIAL)

emit-json: ## Wyślij sample z emitter_json (N, JSON_PARTIAL)
	$(PY) emitters/emitter_json/emit_json.py -n $(N) --partial-ratio $(JSON_PARTIAL)

emit-minimal: ## Wyślij sample z emitter_minimal (N)
	$(PY) emitters/emitter_minimal/emit_minimal.py -n $(N)

emit-noise: ## Wyślij sample z emitter_noise (N, CHAOS, SEED)
	$(PY) emitters/emitter_noise/emit_noise.py -n $(N) --chaos $(CHAOS) $(if $(SEED),--seed $(SEED),)

emit-syslog: ## Wyślij sample z emitter_syslog (N, PARTIAL)
	$(PY) emitters/emitter_syslog/emit_syslog.py -n $(N) --partial-ratio $(PARTIAL)

# ====== Housekeeping ======
hk-once: ## Uruchom housekeeping jednorazowo (tools/housekeeping.py)
	$(PY) tools/housekeeping.py

# ====== Structurizr (opcjonalnie) ======
structurizr: ## Otwórz Structurizr Lite (UI na http://localhost:8081)
	docker run --rm -p 8081:8080 -v "$(PWD)/docs/architecture:/usr/local/structurizr" structurizr/lite

structurizr-export: ## Eksportuj C1–C3 do PNG (wymaga ustawionych 'key' w views)
	docker run --rm -v "$(PWD)/docs/architecture:/usr/local/structurizr" structurizr/cli export -workspace /usr/local/structurizr/workspace.dsl -format png -output /usr/local/structurizr

# ====== Loki (przykładowe query) ======
loki-query: ## Szybkie zapytanie do Loki (emitter_csv)
	curl -G "http://localhost:3100/loki/api/v1/query" --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'

# ====== Utilities ======
env: ## Stwórz .env z .env.example jeśli nie istnieje
	test -f .env || cp .env.example .env

.PHONY: help up down ps logs prom-reload gateway \
        emit-csv emit-json emit-minimal emit-noise emit-syslog \
        hk-once structurizr structurizr-export loki-query env

# ====== Scenarios ======
scenario-run: ## Uruchom scenariusz: make scenario-run SCEN=scenarios/default.yaml
	$(PY) tools/run_scenario.py --scenario $(SCEN)

scenario-default: ## Szybki scenariusz domyślny
	$(PY) tools/run_scenario.py --scenario scenarios/default.yaml

scenario-burst-high-error: ## Scenariusz burst_high_error
	$(PY) tools/run_scenario.py --scenario scenarios/burst_high_error.yaml

scenario-quiet: ## Scenariusz quiet (niski EPS)
	$(PY) tools/run_scenario.py --scenario scenarios/quiet.yaml

scenario-spike: ## Scenariusz spike (nagły wzrost EPS)
	$(PY) tools/run_scenario.py --scenario scenarios/spike.yaml

scenario-quiet-then-spike: ## Scenariusz: najpierw cisza, potem spike
	$(MAKE) scenario-quiet
	$(MAKE) scenario-spike

scenario-high-errors: ## Scenariusz z dużą ilością ERROR
	$(PY) tools/run_scenario.py --scenario scenarios/high_errors.yaml

scenario-list: ## Wypisz dostępne scenariusze
	@ls -1 scenarios | sed 's/^/  - /'

scenario-%: ## Uruchom dowolny scenariusz: make scenario-NAZWA (bez .yaml)
	$(PY) tools/run_scenario.py --scenario scenarios/$*.yaml
