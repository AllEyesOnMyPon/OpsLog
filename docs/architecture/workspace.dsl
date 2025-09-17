workspace "LogOps" "Dev logs playground (v0.5)" {

  !identifiers flat

  model {

    dev    = person "Developer" "Uruchamia emitery/scenariusze, testuje HMAC, sprawdza metryki."
    viewer = person "Grafana User" "Przegląda logi i metryki, reaguje na alerty."

    sys = softwareSystem "LogOps" "Emitery -> AuthGW -> Ingest -> Promtail/Loki -> Grafana/Prometheus (+ Alertmanager)" {

      # --- Tooling / Control-plane (proste kontenery; tag jako 4. argument) ---
      orch_c  = container "Scenario Orchestrator API" "HTTP API: /scenario/start|stop|list; uruchamia runner." "FastAPI (Python) :8070" "Orchestrator"
      emit_c  = container "Emitters" "Symulatory ruchu: CSV / JSON / Minimal / Noise / Syslog." "Python CLI" "Emitters"
      tools_c = container "HMAC Tools" "sign_hmac.py, hmac_curl.sh, verify_hmac_against_signer.py." "Python & Bash" "DevTools"

      # --- Auth Gateway (kontener z komponentami) ---
      authgw_c = container "Auth Gateway" "HMAC/API key, rate-limit per-emitter, backpressure, retry+CB forward; /metrics." "FastAPI (Python) :8090" "AuthGW" {

        api_auth     = component "API" "(/ingest, /healthz, /metrics) - wejście ruchu." "FastAPI" "Component"
        hmac_mw      = component "HmacAuthMiddleware" "Weryfikacja X-Api-Key, X-Timestamp, X-Content-SHA256, X-Signature; anti-replay X-Nonce; clock skew." "" "Component"
        rl_mw        = component "TokenBucketRL" "Rate limiting per-emitter (capacity/refill)." "" "Component"
        bp_filter    = component "Backpressure Filter" "Limity payloadu (rozmiar) -> 413 + X-Backpressure-Reason." "" "Component"
        ds_forwarder = component "Downstream Forwarder" "httpx POST z retry (exponential backoff) + circuit breaker -> Ingest." "" "Component"
        metrics_a    = component "Metrics Exporter" "Prometheus: auth_requests_total, auth_request_latency_seconds, logops_rejected_total." "" "Component"

        api_auth  -> hmac_mw      "weryfikuje HMAC/API key"
        api_auth  -> rl_mw        "sprawdza limity"
        api_auth  -> bp_filter    "egzekwuje limity payloadu"
        api_auth  -> ds_forwarder "forward OK -> Ingest"
        rl_mw     -> metrics_a    "aktualizuje liczniki"
        bp_filter -> metrics_a    "aktualizuje liczniki (rejected)"
      }

      # --- Ingest Gateway (kontener z komponentami) ---
      ingest_c = container "Ingest Gateway" "Przyjmuje/normalizuje logi, opcjonalny file sink, /metrics, housekeeping autorun." "FastAPI (Python) :8080" "IngestGW" {

        api_ing     = component "API" "(/v1/logs, /healthz, /metrics) - wejście z AuthGW i testów lokalnych." "FastAPI" "Component"
        parsers_c   = component "Parsers" "JSON / CSV / plain (syslog-like)." "" "Component"
        normalizer  = component "Normalizer + PII" "Mapowanie poziomów, walidacja; maskowanie/szyfrowanie PII (Fernet)." "" "Component"
        sink_comp   = component "File Sink" "Zapis NDJSON (pliki dzienne)." "" "Component"
        metrics_i   = component "Metrics Exporter" "Prometheus: ingested_total, missing_ts/level, parse_errors, inflight, batch histogramy." "" "Component"
        hk_trigger  = component "Housekeeping Trigger" "Autorun/interval -> tools.housekeeping.run_once()." "" "Component"

        api_ing    -> parsers_c  "parsuje payload"
        parsers_c  -> normalizer "normalizuje rekordy"
        normalizer -> sink_comp  "opcjonalny zapis NDJSON"
        normalizer -> metrics_i  "aktualizuje metryki"
        normalizer -> hk_trigger "opcjonalny trigger housekeeping"
      }

      # --- (opcjonalny) Core ---
      core_c = container "Core" "Dalsze przetwarzanie/analiza (jeśli włączony)." "FastAPI (Python)" "Core"

      # --- Storage/observability (proste kontenery) ---
      sink_c     = container "NDJSON sink" "Pliki dzienne *.ndjson - źródło dla Promtail." "Filesystem (data/ingest)" "NDJSONSink"
      promtail_c = container "Promtail" "Czyta NDJSON, etykietuje i push do Loki." "Grafana Promtail :9080" "Promtail"
      loki_c     = container "Loki" "Składowanie i zapytania (LogQL)." "Grafana Loki :3100" "Loki"
      prom_c     = container "Prometheus" "Scrape /metrics (AuthGW, Ingest, Promtail, Loki); reguły alertów (SLO/p95)." "Prometheus :9090" "Prometheus"
      am_c       = container "Alertmanager" "Routing alertów (Slack)." "Alertmanager :9093" "Alertmanager"
      grafana_c  = container "Grafana" "Dashboardy + Explore (Loki/Prometheus)." "Grafana :3000" "Grafana"
      hk_c       = container "Housekeeping" "Cleanup/archiwizacja starych NDJSON wg retencji." "Python script (tools/housekeeping.py)" "Housekeeping"

      # --- Relacje cross-container ---
      dev        -> orch_c      "Start/stop/list scenariusze (CLI/HTTP)"
      dev        -> emit_c      "Uruchamia ręcznie (make emit-*)"
      dev        -> tools_c     "Generuje podpisy i testy HMAC"
      viewer     -> grafana_c   "Przegląda dashboardy/logi"

      orch_c     -> emit_c      "Orkiestruje EPS/ramp (subprocess)"
      emit_c     -> authgw_c    "POST /ingest (HMAC/API key)" "HTTP/JSON"
      tools_c    -> authgw_c    "curl z podpisem HMAC" "HTTP/JSON"

      authgw_c   -> ingest_c    "Forward OK: POST /v1/logs"
      ingest_c   -> sink_c      "Zapis NDJSON (opcjonalny)"
      promtail_c -> sink_c      "Odczyt *.ndjson (bind-mount)" "read-only"
      promtail_c -> loki_c      "Push logów"

      grafana_c  -> loki_c      "Explore / LogQL"
      grafana_c  -> prom_c      "Dashboardy / Alerting"

      prom_c     -> authgw_c    "GET /metrics"
      prom_c     -> ingest_c    "GET /metrics"
      prom_c     -> promtail_c  "GET /metrics"
      prom_c     -> loki_c      "Health/metrics (opcjonalnie)"
      prom_c     -> am_c        "Wysyła aktywacje alertów"

      ingest_c   -> hk_c        "Trigger run_once()/loop (ENV)"
      hk_c       -> sink_c      "Usuwa/archiwizuje wg retencji"
    }
  }

  views {

    systemContext sys c1 {
      title "C1: LogOps - System Context (v0.5)"
      include *
      autolayout lr
    }

    container sys c2 {
      title "C2: LogOps - Containers (v0.5)"
      include *
      autolayout lr
    }

    component authgw_c c3_auth {
      title "C3: Auth Gateway - Components (v0.5)"
      include *
      autolayout lr
    }

    component ingest_c c3_ingest {
      title "C3: Ingest Gateway - Components (v0.5)"
      include *
      autolayout lr
    }

    styles {
      element "Person" {
        shape Person
        background #003f5c
        color #ffffff
      }
      element "Software System" {
        shape RoundedBox
        background #7a5195
        color #ffffff
      }
      element "Container" {
        shape RoundedBox
        background #ef5675
        color #ffffff
      }
      element "Component" {
        shape RoundedBox
        background #ffa600
        color #000000
      }
    }
  }
}
