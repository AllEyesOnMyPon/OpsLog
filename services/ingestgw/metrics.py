from prometheus_client import Counter, Gauge, Histogram

# inflight – liczba równoległych żądań
METRIC_INFLIGHT = Gauge(
    "logops_inflight",
    "Number of in-flight ingest requests.",
)

# wielkość batcha
BATCH_SIZE = Histogram(
    "logops_batch_size",
    "Number of records per batch.",
    buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, float("inf")),
)

# latency batcha
BATCH_LATENCY = Histogram(
    "logops_batch_latency_seconds",
    "Batch processing latency (ingest).",
    labelnames=("emitter", "scenario_id"),
    buckets=(0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, float("inf")),
)

# accepted (całkowity licznik zaakceptowanych rekordów)
ACCEPTED_TOTAL = Counter(
    "logops_accepted_total",
    "Accepted records total (post-normalization).",
    labelnames=("emitter", "scenario_id"),
)

# rozkład leveli
INGESTED_TOTAL = Counter(
    "logops_ingested_total",
    "Ingested records by level and emitter.",
    labelnames=("emitter", "level"),
)

# braki pól
MISSING_TS_TOTAL = Counter(
    "logops_missing_ts_total",
    "Records missing timestamp.",
    labelnames=("emitter", "scenario_id"),
)
MISSING_LEVEL_TOTAL = Counter(
    "logops_missing_level_total",
    "Records missing level.",
    labelnames=("emitter", "scenario_id"),
)

# błędy parsowania — dodano scenario_id (żeby dało się filtrować po scenariuszu)
PARSE_ERRORS = Counter(
    "logops_parse_errors_total",
    "Pydantic/parse errors in JSON payload.",
    labelnames=("emitter", "scenario_id"),
)

# flaga/sample do odpowiedzi debug
DEBUG_SAMPLE = True
DEBUG_SAMPLE_SIZE = 10

# --- zapis NDJSON (kontrolowany flagą) ---
# Utrzymujemy domyślnie WŁĄCZONE (promtail w smoke testach).
SINK_FILE = True
# Domyślny katalog (może być nadpisany przez env LOGOPS_SINK_DIR)
SINK_DIR_PATH = "./data/ingest"
ENCRYPT_PII = False
