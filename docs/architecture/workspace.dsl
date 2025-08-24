workspace "LogOps" "Dev logs playground" {

  !identifiers hierarchical

  model {

    user   = person "Developer" "Uruchamia emitery, sprawdza wyniki w Grafanie."
    viewer = person "Grafana User" "Przegląda logi i metryki."

    sys = softwareSystem "LogOps" "Emitery → Gateway → Promtail/Loki → Grafana/Prometheus" {

      emitters    = container "Emitters" "Symulatory: CSV/JSON/Minimal/Noise/Syslog" "Python CLI"

      gateway = container "Ingest Gateway" "Przyjmuje/normalizuje logi, PII mask/enc, /metrics" "FastAPI (Python) :8080" {
        api        = component "API" "Endpoints: /v1/logs, /metrics, /healthz" "FastAPI"
        parsers    = component "Parsers" "JSON/CSV/plain (syslog regex)"
        normalizer = component "Normalizer + PII" "map level, mask e-mail/IP, enc fields"
        sink       = component "File Sink" "NDJSON writer"
        metrics    = component "Metrics Exporter" "Prometheus exposition"
        hkTrigger  = component "Housekeeping Trigger" "autorun/interval → tools.housekeeping.run_once()"

        # Relacje C3 wewnątrz gatewaya
        api        -> parsers    "Odbiera payload i przekazuje do parserów"
        parsers    -> normalizer "Parsuje dane i przekazuje do normalizatora"
        normalizer -> sink       "Zapisuje rekordy do NDJSON (opcjonalnie)"
        normalizer -> metrics    "Aktualizuje liczniki/metryki Prometheus"
        normalizer -> hkTrigger  "Trigger housekeeping wg ENV (opcjonalnie)"
      }

      fileSink    = container "File Sink" "Pliki NDJSON (YYYYMMDD.ndjson)" "Filesystem: data/ingest"
      promtail    = container "Promtail" "Czyta NDJSON, etykiety i push do Loki" "Grafana Promtail :9080"
      loki        = container "Loki" "Składowanie i query logów" "Grafana Loki :3100"
      prometheus  = container "Prometheus" "Scrape /metrics, alerty" "Prometheus :9090"
      grafana     = container "Grafana" "Dashboardy / Explore (Loki + Prometheus)" "Grafana :3000"
      hk          = container "Housekeeping" "Cleanup/archiwizacja starych NDJSON" "Python script (tools/housekeeping.py)"
    }

    # Relacje C1–C2
    user               -> sys.emitters     "Uruchamia (CLI)"
    sys.emitters       -> sys.gateway      "POST /v1/logs (CSV/JSON/plain)"
    sys.gateway        -> sys.fileSink     "Opcjonalny zapis NDJSON" "LOGOPS_SINK_FILE=true"
    sys.promtail       -> sys.fileSink     "Scrape *.ndjson (bind-mount)" "read-only"
    sys.promtail       -> sys.loki         "Push logów"
    sys.prometheus     -> sys.gateway      "GET /metrics"
    sys.prometheus     -> sys.loki         "Scrape status"
    sys.prometheus     -> sys.promtail     "Scrape :9080"
    sys.grafana        -> sys.loki         "Explore / Query"
    sys.grafana        -> sys.prometheus   "Dashboardy / Alerting"
    viewer             -> sys.grafana      "Przegląda"

    sys.hk             -> sys.fileSink     "Usuwa/archiwizuje wg retention"
    sys.gateway        -> sys.hk           "run_once()/loop (ENV)" "autorun + interval (opcjonalnie)"
  }

  views {

    systemContext sys {
      key "c1"
      include *
      autolayout lr
      title "C1: LogOps – System Context"
    }

    container sys {
      key "c2"
      include *
      autolayout lr
      title "C2: LogOps – Containers"
    }

    component sys.gateway {
      key "c3"
      include *
      autolayout lr
      title "C3: Ingest Gateway – Components"
    }
  }
}
