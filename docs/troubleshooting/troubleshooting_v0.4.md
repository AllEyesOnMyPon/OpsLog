# Troubleshooting — v0.4 (AuthGW + Tools + Makefile)

---

## PROBLEM 1 — `*** missing separator` (CRLF + spacje vs TAB)

**Objawy**
- `make: *** missing separator` w wielu miejscach.

**Przyczyna**
- Plik w CRLF, a przepisy Make wymagają TAB.
- Edytor zamienił TAB na spacje.

**Naprawa**
1. Konwersja na LF:
   ```bash
   dos2unix Makefile
   ```
2. Dodanie prostego separatora:
   ```make
   .RECIPEPREFIX := >
   ```
3. Każdy przepis zaczyna się od `>`.

**Testy**
```bash
make -n help
```

**Prewencja**
- `.gitattributes` → `* text=auto eol=lf`
- VS Code: `files.eol=LF`
- Pre-commit: sprawdzanie CRLF/TAB.

---

## PROBLEM 2 — `nohup: unrecognized option '--host'`

**Objawy**
- Ingest nie startował, log: `nohup: unrecognized option '--host'`.

**Przyczyna**
- Zła kolejność: argumenty `--host`/`--port` trafiły do `nohup`, nie do `uvicorn`.

**Naprawa**
Poprawny wzorzec (już w Makefile):
```make
@nohup $(UVICORN) $(GATEWAY_APP) --host $(HOST) --port $(PORT) --reload \
  >"$(INGEST_LOG)" 2>&1 & echo $$! >"$(INGEST_PID)"
```

**Testy**
- `tail -f logs/ingest.out` — brak błędu nohupa.
- `curl :8080/healthz` → 200.

**Prewencja**
- Trzymać się sprawdzonego szablonu w Makefile.

---

## PROBLEM 3 — `smoke-authgw` dawał uparte 429 (RL ignorował override)

**Objawy**
- Po `make RL_CAP=3 RL_REFILL=5 authgw-restart` dalej 429 jak dla capacity=1.

**Przyczyna**
- YAML nie czytał zmiennych albo startował bez bufora (token bucket pusty).

**Naprawa**
- Generowanie configu ze zmiennych (już poprawione).
- Dodanie `authgw-wait`/krótkiego `sleep` przed smoke.

**Testy**
```bash
sed -n '1,120p' services/authgw/config.rltest.yaml | grep -A2 per_emitter
make smoke-authgw   # oczekiwane: A:200, B:413, C:413
```

**Prewencja**
- W `all-authgw` najpierw `authgw-wait`, potem smoke.
- Testy RL po restarcie i refill’u.

---

## PROBLEM 4 — 413 z backpressure w smoke (za duże body / zbyt wiele elementów)

**Objawy**
- `HTTP/1.1 413 Request Entity Too Large` z `x-backpressure-reason`.

**Przyczyna**
- `big.json` (250kB) i `many.json` (1200 rekordów) **celowo** wywołują 413.

**Naprawa**
- To jest zamierzony rezultat; tylko **A** ma dać `200`.

**Testy**
```bash
make smoke-authgw
# Oczekiwane: A:200, B:413, C:413
```

**Prewencja**
- Komentarz w Makefile wyjaśniający „expected”.

---

## PROBLEM 5 — Grafana: brak zakładki Explore / brak logów

**Objawy**
- Brak zakładki Explore albo pusto mimo generowania ruchu.

**Przyczyna**
- Datasource’y nie były dodane/provisionowane (Prometheus, Loki).
- Dashboard importowany wcześniej niż konfiguracja datasource.

**Naprawa**
1. Grafana → *Configuration → Data sources*:
   - Prometheus: `http://prometheus:9090`
   - Loki: `http://loki:3100`
2. Dopiero potem import dashboardu z `docs/grafena_dashboard.json`.

**Testy**
```logql
{job="logops-ndjson", app="logops"}
```
w Explore zwraca logi.

**Prewencja**
- Provisioning datasource w `infra/docker/grafana/provisioning/datasources/datasources.yml`.

---

## PROBLEM 6 — Alerty SLO/p95: „same zera” i puste wyniki

**Objawy**
- `logops_batch_latency_seconds_bucket` pokazywał same zera.
- Alerty p95 dla `logops_request_latency_seconds_bucket` → `Empty query result`.

**Przyczyna**
- Brak wygenerowanego ruchu (histogram pusty).
- Alerty p95 dla requestów odnosiły się do nieistniejącej metryki.

**Naprawa**
- Uruchomienie scenariusza:
  ```bash
  make scenario-default
  ```
- Usunięcie dodatkowych alertów p95 dla requestów w v0.4.

**Testy**
```promql
sum(rate(logops_batch_latency_seconds_bucket[5m]))
histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
```

**Prewencja**
- Trzymamy alerty tylko dla eksportowanych metryk.

---

## PROBLEM 7 — Literówka `.py` zamiast `.yml` w Compose

**Objawy**
- `docker compose` krzyczał, że plik nie jest poprawnym YAML.

**Przyczyna**
- Dokumentacja wskazywała `docker-compose.observability.py` zamiast `.yml`.

**Naprawa**
Poprawne uruchomienie:
```bash
docker compose -f infra/docker/docker-compose.observability.yml up -d
```

**Testy**
- `docker compose ps` pokazuje loki/promtail/prometheus/grafana.

**Prewencja**
- Dokumentacja Quickstart/README poprawiona na `.yml`.

---
