from prometheus_client import Counter, Gauge

# 1 gdy scenariusz RUNNING, 0 gdy finished/stopped/error.
# Labelujemy po scenario_id i (opcjonalnie) name.
ORCH_RUNNING = Gauge(
    "logops_orch_running",
    "Scenario running state (1=running, 0=not running).",
    labelnames=("scenario_id", "name"),
)

# Zliczamy ile *z grubsza* eventów emiterów wypuścił runner scenariusza.
# Labelujemy po scenario_id i emitter.
ORCH_EMITTED_TOTAL = Counter(
    "logops_orch_emitted_total",
    "Approx events emitted by orchestrated emitters.",
    labelnames=("scenario_id", "emitter"),
)

# Błędy w trakcie scenariusza (np. rc emitera != 0/124, parse, itp.).
# Labelujemy po scenario_id i reason.
ORCH_ERRORS_TOTAL = Counter(
    "logops_orch_errors_total",
    "Errors observed by orchestrator while running scenarios.",
    labelnames=("scenario_id", "reason"),
)
