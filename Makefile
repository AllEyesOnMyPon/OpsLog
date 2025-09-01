# ===================== MAKEFILE (LF only) =====================
# Używamy '>' zamiast TAB w przepisach:
.RECIPEPREFIX := >

# ====== Config ======
PY        ?= $(shell command -v python || command -v python3 || echo $(PWD)/.venv/bin/python)
UVICORN   ?= uvicorn

COMPOSE_FILE := infra/docker/docker-compose.observability.yml
DC          := docker compose -f $(COMPOSE_FILE)

# Ingest Gateway (dev)
GATEWAY_APP := services.ingest_gateway.gateway:app
HOST        ?= 0.0.0.0
PORT        ?= 8080

# Emitters defaults
N            ?= 20
PARTIAL      ?= 0.3
CHAOS        ?= 0.5
JSON_PARTIAL ?= 0.3
SEED         ?=

# Domyślny cel
.DEFAULT_GOAL := help

# ====== Help ======
help: ## Pokaż listę komend
> echo "LogOps Makefile — skróty komend:"
> grep -E '^[a-zA-Z0-9_.%-]+:.*?## .*$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ====== Observability stack (Compose) ======
up: ## Uruchom Loki/Promtail/Prometheus/Grafana (detached)
> $(DC) up -d

down: ## Zatrzymaj i usuń kontenery observability
> $(DC) down

ps: ## Lista działających usług (compose)
> $(DC) ps

logs: ## Podgląd logów usług (compose)
> $(DC) logs -f

prom-reload: ## Przeładuj Prometheusa (po zmianie reguł)
> docker exec -it logops-prometheus kill -HUP 1

# ====== Ingest Gateway (dev, foreground) ======
gateway: ## Uruchom Ingest Gateway w trybie dev (uvicorn --reload)
> $(UVICORN) $(GATEWAY_APP) --host $(HOST) --port $(PORT) --reload

# ====== Emitery ======
emit-csv: ## Wyślij sample z emitter_csv (N, PARTIAL)
> $(PY) emitters/emitter_csv/emit_csv.py -n $(N) --partial-ratio $(PARTIAL)

emit-json: ## Wyślij sample z emitter_json (N, JSON_PARTIAL)
> $(PY) emitters/emitter_json/emit_json.py -n $(N) --partial-ratio $(JSON_PARTIAL)

emit-minimal: ## Wyślij sample z emitter_minimal (N)
> $(PY) emitters/emitter_minimal/emit_minimal.py -n $(N)

emit-noise: ## Wyślij sample z emitter_noise (N, CHAOS, [SEED])
> $(PY) emitters/emitter_noise/emit_noise.py -n $(N) --chaos $(CHAOS) $(if $(SEED),--seed $(SEED),)

emit-syslog: ## Wyślij sample z emitter_syslog (N, PARTIAL)
> $(PY) emitters/emitter_syslog/emit_syslog.py -n $(N) --partial-ratio $(PARTIAL)

# ====== Housekeeping ======
hk-once: ## Uruchom housekeeping jednorazowo
> $(PY) tools/housekeeping.py

# ====== Structurizr (opcjonalnie) ======
structurizr: ## Otwórz Structurizr Lite (UI: http://localhost:8081)
> docker run --rm -p 8081:8080 -v "$(PWD)/docs/architecture:/usr/local/structurizr" structurizr/lite

structurizr-export: ## Eksportuj C1–C3 do PNG (wymaga skonfigurowanych 'key' w DSL)
> docker run --rm -v "$(PWD)/docs/architecture:/usr/local/structurizr" structurizr/cli export -workspace /usr/local/structurizr/workspace.dsl -format png -output /usr/local/structurizr

# ====== Loki (przykładowe query) ======
loki-query: ## Szybkie zapytanie do Loki (emitter_csv)
> curl -G "http://localhost:3100/loki/api/v1/query" --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'

# ====== Utilities ======
env: ## Stwórz .env z .env.example jeśli nie istnieje
> test -f .env || cp .env.example .env


# ====== Scenarios ======
scenario-run: ## Uruchom scenariusz: make scenario-run SCEN=scenarios/default.yaml
> $(PY) tools/run_scenario.py --scenario $(SCEN)

scenario-default: ## Szybki scenariusz domyślny
> $(PY) tools/run_scenario.py --scenario scenarios/default.yaml

scenario-burst-high-error: ## Scenariusz burst_high_error
> $(PY) tools/run_scenario.py --scenario scenarios/burst_high_error.yaml

scenario-quiet: ## Scenariusz quiet (niski EPS)
> $(PY) tools/run_scenario.py --scenario scenarios/quiet.yaml

scenario-spike: ## Scenariusz spike (nagły wzrost EPS)
> $(PY) tools/run_scenario.py --scenario scenarios/spike.yaml

scenario-quiet-then-spike: ## Scenariusz: najpierw cisza, potem spike
> $(MAKE) scenario-quiet
> $(MAKE) scenario-spike

scenario-high-errors: ## Scenariusz z dużą ilością ERROR
> $(PY) tools/run_scenario.py --scenario scenarios/high_errors.yaml

scenario-list: ## Wypisz dostępne scenariusze
> ls -1 scenarios | sed 's/^/  - /'

scenario-%: ## Uruchom dowolny scenariusz: make scenario-NAZWA (bez .yaml)
> $(PY) tools/run_scenario.py --scenario scenarios/$*.yaml


# ====== AuthGW quick targets (curl HMAC wrapper) ======
LOGOPS_URL      ?= http://127.0.0.1:8090/ingest
METRICS_URL     ?= http://127.0.0.1:8090/metrics
LOGOPS_API_KEY  ?= demo-pub-1
LOGOPS_SECRET   ?= demo-priv-1
CURL_WRAP       ?= tools/hmac_curl.sh

help-authgw:
> echo "AuthGW targets:"
> echo "  make smoke-authgw      # A=200, B=413(too_large_hdr), C=413(too_many_items)"
> echo "  make bp-big            # pokaż nagłówki 413 dla dużego body"
> echo "  make bp-many           # pokaż nagłówki 413 dla zbyt wielu elementów"
> echo "  make headers           # wypisz nagłówki HMAC dla przykładowego body"
> echo "  make metrics           # zrzut /metrics (pierwsze linie)"
> echo "  make metrics-rejected  # same liczniki logops_rejected_total"
> echo "  make clean-bp          # kasuje pliki big.json/many.json"
> echo "  make hmac-old-ts       # negatywny test: stary timestamp → 401 skew"
> echo "  make hmac-bad-secret   # negatywny test: zły sekret → 401 bad signature"

smoke-authgw: bp-big bp-many
> $(CURL_WRAP) --nonce -d '{"msg":"hello"}' -- -s -o /dev/null -w 'A:%{http_code}\n' || true
> $(PY) -c 'import json; open("big.json","w").write(json.dumps({"msg":"x"*250000}))'
> $(CURL_WRAP) --nonce -f big.json -- -s -o /dev/null -w 'B:%{http_code}\n' -D - || true
> $(PY) -c 'import json; open("many.json","w").write(json.dumps([{"msg":"x"}]*1200))'
> $(CURL_WRAP) --nonce -f many.json -- -s -o /dev/null -w 'C:%{http_code}\n' -D - || true

bp-big:
> $(PY) -c 'import json; open("big.json","w").write(json.dumps({"msg":"x"*250000}))'
> $(CURL_WRAP) --nonce -f big.json -- --dump-header - -s -o /dev/null | sed -n '1,20p'

bp-many:
> $(PY) -c 'import json; open("many.json","w").write(json.dumps([{"msg":"x"}]*1200))'
> $(CURL_WRAP) --nonce -f many.json -- --dump-header - -s -o /dev/null | sed -n '1,20p'

headers:
> LOGOPS_API_KEY=$(LOGOPS_API_KEY) LOGOPS_SECRET=$(LOGOPS_SECRET) $(CURL_WRAP) --nonce -d '{"msg":"hello"}' --echo-headers

metrics:
> curl -s $(METRICS_URL) | sed -n '1,80p'

metrics-rejected:
> curl -s $(METRICS_URL) | grep '^logops_rejected_total' || true

clean-bp:
> rm -f big.json many.json

hmac-old-ts:
> $(CURL_WRAP) --nonce --ts-offset -3600 -d '{"msg":"old"}' -- -i -s -o /dev/null -w "old-ts:%{http_code}\n" -D -

hmac-bad-secret:
> LOGOPS_SECRET="wrong-secret" $(CURL_WRAP) --nonce -d '{"msg":"bad"}' -- -i -s -o /dev/null -w "bad-secret:%{http_code}\n" -D -


# ====== All-in-one runners (AuthGW & Ingest) ======
RUN_DIR   ?= run
LOG_DIR   ?= logs
SHELL     := /bin/bash

# --- AuthGW (RL-test) ---
AUTHGW_APP   := services.authgw.app:app
AUTHGW_HOST  ?= 0.0.0.0
AUTHGW_PORT  ?= 8090
RLTEST_CFG   := services/authgw/config.rltest.yaml
AUTHGW_PID   := $(RUN_DIR)/authgw.pid
AUTHGW_LOG   := $(LOG_DIR)/authgw.out

# --- Ingest Gateway (background) ---
INGEST_PID   := $(RUN_DIR)/ingest.pid
INGEST_LOG   := $(LOG_DIR)/ingest.out

dirs: ## Utwórz katalogi pomocnicze
> mkdir -p "$(RUN_DIR)" "$(LOG_DIR)" services/authgw

# ---------- AuthGW: config + start/stop ----------
authgw-rltest-config: dirs ## Zbuduj RL-test config dla AuthGW
>	@printf '%s\n' \
>	 'auth:' \
>	 '  mode: "hmac"' \
>	 '  hmac:' \
>	 '    clock_skew_sec: 300' \
>	 '    require_nonce: true' \
>	 '' \
>	 'forward:' \
>	 '  url: "http://127.0.0.1:8080/v1/logs"' \
>	 '  timeout_sec: 5' \
>	 '' \
>	 'ratelimit:' \
>	 '  per_emitter:' \
>	 '    capacity: 100' \
>	 '    refill_per_sec: 100' \
>	 '' \
>	 'secrets:' \
>	 '  clients:' \
>	 '    demo-pub-1:' \
>	 '      secret: "demo-priv-1"' \
>	 '      emitter: "emitter_json"' \
>	 '' \
>	 'backpressure:' \
>	 '  enabled: true' \
>	 '  max_body_bytes: 200000' \
>	 '  max_items: 1000' \
>	 > "$(RLTEST_CFG)"
>	@echo ">> wrote $(RLTEST_CFG)"

# ===== Rate-limit (parametryzowalne) =====
RL_CAP    ?= 1
RL_REFILL ?= 0

authgw-start: authgw-rltest-config ## Start AuthGW (background)
>	@if [[ -f "$(AUTHGW_PID)" ]] && kill -0 $$(cat "$(AUTHGW_PID)") 2>/dev/null; then \
>	  echo "AuthGW already running (PID $$(cat $(AUTHGW_PID)))"; exit 0; fi
>	@echo ">> starting AuthGW on $(AUTHGW_HOST):$(AUTHGW_PORT)"
>	@AUTHGW_CONFIG="$(RLTEST_CFG)" nohup $(UVICORN) $(AUTHGW_APP) \
>	  --host $(AUTHGW_HOST) --port $(AUTHGW_PORT) --reload \
>	  >"$(AUTHGW_LOG)" 2>&1 & echo $$! >"$(AUTHGW_PID)"
>	@sleep 0.3
>	@echo "PID: $$(cat $(AUTHGW_PID))  | logs: $(AUTHGW_LOG)"

authgw-stop: ## Stop AuthGW (z PID-file)
>	@if [[ -f "$(AUTHGW_PID)" ]]; then \
>	  PID=$$(cat "$(AUTHGW_PID)"); \
>	  if kill -0 $$PID 2>/dev/null; then echo "stopping AuthGW $$PID" && kill $$PID; fi; \
>	  rm -f "$(AUTHGW_PID)"; \
>	else echo "AuthGW not running"; fi

authgw-restart: authgw-stop authgw-start ## Restart AuthGW

authgw-wait: ## Czekaj aż /healthz zacznie odpowiadać
>	@echo ">> waiting for http://$(AUTHGW_HOST):$(AUTHGW_PORT)/healthz ..."
>	@for i in $$(seq 1 100); do \
>	  curl -fsS "http://$(AUTHGW_HOST):$(AUTHGW_PORT)/healthz" >/dev/null 2>&1 && exit 0; \
>	  sleep 0.1; \
>	done; \
>	echo "!! timeout waiting for AuthGW" >&2; exit 1

authgw-logs: ## Tail logów AuthGW
> tail -n 100 -f "$(AUTHGW_LOG)"

# ---------- Ingest: start/stop ----------
ingest-start: dirs ## Start Ingest Gateway (background, port $(PORT))
>	@if [[ -f "$(INGEST_PID)" ]] && kill -0 $$(cat "$(INGEST_PID)") 2>/dev/null; then \
>	  echo "Ingest already running (PID $$(cat $(INGEST_PID)))"; exit 0; fi
>	@echo ">> starting Ingest on $(HOST):$(PORT)"
>	@nohup $(UVICORN) $(GATEWAY_APP) \
>	  --host $(HOST) --port $(PORT) --reload \
>	  >"$(INGEST_LOG)" 2>&1 & echo $$! >"$(INGEST_PID)"
>	@sleep 0.3
>	@echo "PID: $$(cat $(INGEST_PID))  | logs: $(INGEST_LOG)"

ingest-stop: ## Stop Ingest Gateway (z PID-file)
>	@if [[ -f "$(INGEST_PID)" ]]; then \
>	  PID=$$(cat "$(INGEST_PID)"); \
>	  if kill -0 $$PID 2>/dev/null; then echo "stopping Ingest $$PID" && kill $$PID; fi; \
>	  rm -f "$(INGEST_PID)"; \
>	else echo "Ingest not running"; fi

ingest-restart: ingest-stop ingest-start ## Restart Ingest

ingest-wait: ## Czekaj aż /healthz zacznie odpowiadać
>	@echo ">> waiting for http://127.0.0.1:$(PORT)/healthz ..."
>	@for i in $$(seq 1 100); do \
>	  curl -fsS "http://127.0.0.1:$(PORT)/healthz" >/dev/null 2>&1 && exit 0; \
>	  sleep 0.1; \
>	done; \
>	echo "!! timeout waiting for Ingest" >&2; exit 1

ingest-logs: ## Tail logów Ingest
> tail -n 100 -f "$(INGEST_LOG)"

# ---------- „All” sekwencje ----------
all-authgw: ingest-start ingest-wait authgw-start authgw-wait ## Odpal Ingest + AuthGW i szybkie testy
> echo ">> smoke tests (AuthGW)"
> $(MAKE) smoke-authgw
> $(MAKE) rl-hit
> $(MAKE) rl-test
> $(MAKE) metrics-rejected

all-ingest: ingest-start ingest-wait ## Odpal sam Ingest i wyślij próbki
> echo ">> sending sample traffic to Ingest"
> $(MAKE) emit-json N=10 JSON_PARTIAL=0.2
> $(MAKE) emit-minimal N=10

# ====== RL quick tests (wymagają AuthGW) ======
rl-hit: ## 2 szybkie requesty: 200, potem 429 (rate limit)
> tools/hmac_curl.sh --nonce -d '{"msg":"one"}' -- -s -o /dev/null -w "one:%{http_code}\n"
> sleep 0.1
> tools/hmac_curl.sh --nonce -d '{"msg":"two"}' -- -s -o /dev/null -w "two:%{http_code}\n" -D - | sed -n '1,20p'

rl-test: ## 5 requestów z rzędu — powinny wpaść 429
>	@for i in 1 2 3 4 5; do \
>	  tools/hmac_curl.sh --nonce -d '{"msg":"burst"}' -- -s -o /dev/null -w "$$i:%{http_code}\n"; \
>	  sleep 0.05; \
>	done

rl-test-headers: ## Pokaż nagłówki X-RateLimit-* (jeden request)
> tools/hmac_curl.sh --nonce -d '{"msg":"hdr"}' -- -s -o /dev/null -D - | sed -n '1,40p'

# ====== Phony ======
.PHONY: help up down ps logs prom-reload gateway
.PHONY: emit-csv emit-json emit-minimal emit-noise emit-syslog hk-once
.PHONY: structurizr structurizr-export loki-query env
.PHONY: scenario-run scenario-default scenario-burst-high-error scenario-quiet
.PHONY: scenario-spike scenario-quiet-then-spike scenario-high-errors scenario-list scenario-%
.PHONY: help-authgw smoke-authgw bp-big bp-many headers metrics metrics-rejected clean-bp
.PHONY: hmac-old-ts hmac-bad-secret
.PHONY: dirs authgw-rltest-config authgw-start authgw-stop authgw-restart authgw-wait authgw-logs
.PHONY: ingest-start ingest-stop ingest-restart ingest-wait ingest-logs
.PHONY: all-authgw all-ingest rl-hit rl-test rl-test-headers

# ====== Alertmanager (render, reload, synthetic, health) ======
AM_TMPL         := infra/docker/alertmanager/alertmanager.tmpl.yml
AM_RENDERED_DIR := infra/docker/alertmanager/rendered
AM_RENDERED     := $(AM_RENDERED_DIR)/alertmanager.yml

AM_RELOAD_URL   ?= http://localhost:9093/-/reload
AM_ALERTS_URL   ?= http://localhost:9093/api/v2/alerts
AM_READY_URL    ?= http://localhost:9093/-/ready
AM_STATUS_URL   ?= http://localhost:9093/api/v2/status
PROM_AMS_URL    ?= http://localhost:9090/api/v1/alertmanagers
PROM_RULES_URL  ?= http://localhost:9090/api/v1/rules

am-render: ## Renderuj alertmanager.yml z template (envsubst)
> @test -n "$(ALERTMANAGER_SLACK_WEBHOOK)" || (echo "ERR: brak ALERTMANAGER_SLACK_WEBHOOK w .env"; exit 1)
> @test -n "$(ALERTMANAGER_SLACK_WEBHOOK_LOGOPS)" || (echo "ERR: brak ALERTMANAGER_SLACK_WEBHOOK_LOGOPS w .env"; exit 1)
> @mkdir -p $(AM_RENDERED_DIR)
> @envsubst < $(AM_TMPL) > $(AM_RENDERED)
> @echo "Rendered -> $(AM_RENDERED)"
> @grep -nE 'api_url' $(AM_RENDERED) || true

am-up: ## Uruchom/odśwież sam Alertmanager (compose)
> $(DC) up -d alertmanager

am-reload: ## /-/reload Alertmanager
> curl -s -X POST "$(AM_RELOAD_URL)" && echo "AM reloaded"

am-synthetic: ## Wyślij syntetyczny alert do AM -> Slack
> START_TS=$$(date -u +%Y-%m-%dT%H:%M:%SZ); \
> END_TS=$$(date -u -d '+5 minutes' +%Y-%m-%dT%H:%M:%SZ); \
> curl -s -X POST "$(AM_ALERTS_URL)" -H 'Content-Type: application/json' \
>   -d "[{\"labels\":{\"alertname\":\"LogOpsSyntheticTest\",\"service\":\"logops\",\"severity\":\"warning\"},\"annotations\":{\"summary\":\"routing check\",\"description\":\"E2E AM→Slack\"},\"startsAt\":\"$${START_TS}\",\"endsAt\":\"$${END_TS}\"}]" \
>   && echo "synthetic alert posted"

am-health: ## Sprawdź ready/status AM i czy Prom widzi AM + listę grup reguł
> echo "== AM ready ==" && curl -s "$(AM_READY_URL)" && echo
> echo "== AM status ==" && curl -s "$(AM_STATUS_URL)" | jq '.cluster,.versionInfo' || true
> echo "== Prom → AM ==" && curl -s "$(PROM_AMS_URL)" | jq || true
> echo "== Prom rule groups ==" && curl -s "$(PROM_RULES_URL)" | jq '.data.groups[].name' || true

slack-smoke: ## Bezpośredni POST do webhooka (z hosta; omija AM)
> @test -n "$(ALERTMANAGER_SLACK_WEBHOOK)" || (echo "ERR: brak ALERTMANAGER_SLACK_WEBHOOK w .env"; exit 1)
> curl -sS -H 'Content-Type: application/json' \
>   --data '{"text":"Smoke from host via webhook"}' \
>   "$(ALERTMANAGER_SLACK_WEBHOOK)" >/dev/null && echo "Slack smoke OK"
