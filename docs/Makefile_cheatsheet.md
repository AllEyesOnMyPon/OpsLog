# Makefile Cheatsheet (v0.3+)

Szybkie komendy zgodne z aktualnym `Makefile`. Wykonuj z katalogu głównego repo.

---

## Observability stack (Loki/Promtail/Prometheus/Grafana)

```bash
# start (detached)
make up

# podgląd usług / logów
make ps
make logs

# przeładuj Prometheusa po zmianie reguł
make prom-reload

# stop & cleanup
make down
```

---

## Ingest Gateway (FastAPI)

```bash
# uruchom w trybie dev (uvicorn --reload) na :8080
make gateway
```

---

## Emitery – szybkie sample

```bash
# CSV (50 rekordów, mniej braków)
make emit-csv N=50 PARTIAL=0.1

# JSON
make emit-json N=30 JSON_PARTIAL=0.2

# Noise (chaotyczne rekordy)
make emit-noise N=40 CHAOS=0.6 SEED=123

# Syslog-like
make emit-syslog N=20 PARTIAL=0.2

# Minimal
make emit-minimal N=10
```

---

## Scenariusze ruchu (orchestrator)

```bash
# lista dostępnych scenariuszy (z katalogu scenarios/)
make scenario-list

# uruchom domyślny scenariusz
make scenario-default

# inne gotowe:
make scenario-quiet
make scenario-spike
make scenario-burst-high-error
make scenario-high-errors

# sekwencja: quiet → spike
make scenario-quiet-then-spike

# dowolny plik: scenarios/MOJ.yaml
make scenario-run SCEN=scenarios/MOJ.yaml
```

---

## Auth Gateway (HMAC, RL, backpressure)

```bash
# szybkie testy: 200, 413(too_large_hdr), 413(too_many_items)
make smoke-authgw

# pokaż nagłówki 413 dla zbyt dużego body / zbyt wielu elementów
make bp-big
make bp-many

# wypisz nagłówki HMAC dla przykładowego body
make headers

# metryki / tylko liczniki odrzuceń
make metrics
make metrics-rejected

# negatywne testy HMAC
make hmac-old-ts       # stary timestamp → 401 skew
make hmac-bad-secret   # zły sekret → 401 bad signature
```

### All-in-one (Ingest + AuthGW)

```bash
# start Ingest (bg), potem AuthGW (bg), czekaj na healthz i zrób szybkie testy
make all-authgw

# tylko Ingest + próbki
make all-ingest

# kontrola procesów w tle (logi/PID w ./logs i ./run)
make authgw-logs
make ingest-logs
```

> Konfig RL-test dla AuthGW generuje się automatycznie do: `services/authgw/config.rltest.yaml`.

---

## Housekeeping

```bash
# pojedynczy przebieg sprzątania plików NDJSON (retencja/archiwizacja wg ENV)
make hk-once
```

---

## Loki – szybkie zapytanie

```bash
make loki-query
# alias na:
# curl -G "http://localhost:3100/loki/api/v1/query" \
#   --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```

---

## Alertmanager (opcjonalnie)

```bash
# wyrenderuj alertmanager.yml z template (wymaga env: ALERTMANAGER_SLACK_WEBHOOK, ALERTMANAGER_SLACK_WEBHOOK_LOGOPS)
make am-render

# uruchom/odśwież sam Alertmanager (docker compose target)
make am-up

# /-/reload
make am-reload

# syntetyczny alert (E2E do Slacka)
make am-synthetic

# health/status i integracja z Prometheusem
make am-health

# szybki smoke bezpośrednio do webhooka (bez AM)
make slack-smoke
```

---

## Utility

```bash
# utwórz .env z .env.example (jeśli brak)
make env
```

> Wskazówka: wszystkie cele mają opisy — użyj `make help`.
