workspace "LogOps" "Dev logs playground (v0.4)" {

  !identifiers hierarchical

  model {

    user   = person "Developer" "Uruchamia emitery/scenariusze, testuje HMAC, sprawdza metryki."
    viewer = person "Grafana User" "Przegląda logi i metryki, reaguje na alerty."

    sys = softwareSystem "LogOps" "Emitery → AuthGW → Ingest → Promtail/Loki → Grafana/Prometheus (+ Alertmanager)" {

      # --- Tooling (CLI) ---
      orchestrator = container "Scenario Orchestrator" "Steruje ruchem: profile EPS, rampy, JSONL telemetry (scenario.start/tick/end)." "Python CLI (tools/run_scenario.py)"
      emitters     = container "Emitters" "Symulatory: CSV / JSON / Minimal / Noise / Syslog" "Python CLI"
      hmacTools    = container "HMAC Tools" "Generacja podpisów HMAC i wrapper nad curl." "Python & Bash (tools/sign_hmac.py, tools/hmac_curl.sh)"

      # --- Gateways ---
      authgw = container "Auth Gateway" "Weryfikuje HMAC/API key, rate-limit per emitter, backpressure, forward do Ingest; /metrics." "FastAPI (Python) :8090" {
        apiAuth    = component "API (/ingest, /healthz, /metrics)" "Wejście ruchu od emiterów." "FastAPI"
        hmacMw     = component "HmacAuthMiddleware" "Weryfikacja X-Api-Key, X-Timestamp, X-Content-SHA256, X-Signature; replay/X-Nonce; clock skew."
        rlMw       = component "TokenBucketRL" "Rate limiting per-emitter (capacity/refill)."
        bpFilter   = component "Backpressure Filter" "Limit rozmiaru batcha/elementów → 413 + x-backpressure-reason."
        downstream = component "Downstream Forwarder" "Forward do Ingest: retry + exponential backoff + circuit breaker."
        metricsA   = component "Metrics Exporter" "Eksport metryk Prometheus (np. rejected_total)."

        apiAuth  -> hmacMw     "weryfikuje HMAC"
        apiAuth  -> rlMw       "sprawdza limity"
        apiAuth  -> bpFilter   "egzekwuje limity payloadu"
        apiAuth  -> downstream "forward ok trafia do Ingest"
        rlMw     -> metricsA   "aktualizuje liczniki"
        bpFilter -> metricsA   "aktualizuje liczniki (rejected)"
      }

      ingest = container "Ingest Gateway" "Przyjmuje/normalizuje logi, opcjonalny file sink, /metrics, housekeeping autorun." "FastAPI (Python) :8080" {
        apiIngest  = component "API (/v1/logs, /metrics, /healthz)" "Wejście z AuthGW i testów lokalnych." "FastAPI"
        parsers    = component "Parsers" "JSON / CSV / plain (syslog-like)."
        normalizer = component "Normalizer + PII" "Mapowanie level, maskowanie/szyfrowanie PII (Fernet), walidacja."
        sink       = component "File Sink" "NDJSON writer (daily files)."
        metricsI   = component "Metrics Exporter" "Prometheus (ingested_total, missing_ts/level, parse_errors, inflight, batch histogramy)."
        hkTrigger  = component "Housekeeping Trigger" "Autorun + interval → tools.housekeeping.run_once()."

        apiIngest  -> parsers     "Parsuje payload"
        parsers    -> normalizer  "Rekordy do normalizacji"
        normalizer -> sink        "Opcjonalny zapis NDJSON"
        normalizer -> metricsI    "Aktualizuje metryki"
        normalizer -> hkTrigger   "Trigger wg ENV (opcjonalnie)"
      }

      # --- Observability / storage ---
      fileSink   = container "File Sink" "Pliki NDJSON (YYYYMMDD.ndjson)." "Filesystem: data/ingest"
      promtail   = container "Promtail" "Czyta NDJSON, dodaje etykiety i push do Loki." "Grafana Promtail :9080"
      loki       = container "Loki" "Składowanie logów + zapytania (LogQL)." "Grafana Loki :3100"
      prometheus = container "Prometheus" "Scrape /metrics (AuthGW, Ingest, Promtail); reguły alertów (w tym SLO/p95)." "Prometheus :9090"
      alertm     = container "Alertmanager" "Router alertów (Slack)." "Alertmanager :9093"
      grafana    = container "Grafana" "Dashboardy + Explore (Loki/Prometheus)." "Grafana :3000"
      hk         = container "Housekeeping" "Cleanup/archiwizacja starych NDJSON wg retencji." "Python script (tools/housekeeping.py)"

      # --- Relacje C1–C2 ---
      orchestrator -> emitters     "Uruchamia wg scenariusza (EPS/ramp)"
      user         -> orchestrator "CLI: make scenario-*, run_scenario.py"
      user         -> emitters     "Uruchamia bezpośrednio (make emit-*)"
      user         -> hmacTools    "Generuje podpisy i testy HMAC"

      emitters   -> authgw.apiAuth "POST /ingest (HMAC) + nagłówki" "HTTPS/JSON"
      hmacTools  -> authgw.apiAuth "curl z podpisem HMAC" "HTTPS/JSON"

      authgw.downstream -> ingest.apiIngest "Forward OK do /v1/logs" "HTTP/JSON"
      ingest.sink       -> fileSink         "Zapis NDJSON (opcjonalny)"

      promtail -> fileSink   "Scrape *.ndjson (bind-mount)" "read-only"
      promtail -> loki       "Push logów"

      prometheus -> authgw   "GET /metrics"
      prometheus -> ingest   "GET /metrics"
      prometheus -> promtail "GET /metrics"
      prometheus -> loki     "Health/status (opcjonalnie)"
      prometheus -> alertm   "Wysyła aktywacje alertów"

      grafana -> prometheus  "Dashboardy / Alerting"
      grafana -> loki        "Explore / LogQL"

      viewer  -> grafana     "Przegląda dashboardy/logi"

      hk      -> fileSink    "Usuwa/archiwizuje wg retencji"
      ingest  -> hk          "run_once()/loop (ENV)"
    }
  }

  views {

    systemContext sys {
      include *
      autolayout lr
      title "C1: LogOps – System Context (v0.4)"
    }

    container sys {
      include *
      autolayout lr
      title "C2: LogOps – Containers (v0.4)"
    }

    component sys.authgw {
      include *
      autolayout lr
      title "C3: Auth Gateway – Components (v0.4)"
    }

    component sys.ingest {
      include *
      autolayout lr
      title "C3: Ingest Gateway – Components (v0.4)"
    }
  }
}
