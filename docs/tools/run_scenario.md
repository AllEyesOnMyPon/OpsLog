# Scenarios — generator ruchu do LogOps

Ten katalog zawiera predefiniowane **profile ruchu** (YAML) oraz narzędzie do ich uruchamiania. Scenariusze produkują żądania z emiterów do Ingest (bezpośrednio lub przez AuthGW), co pozwala ćwiczyć **SLO/p95**, alerty i dashboardy.

- Pliki scenariuszy: `scenarios/*.yaml`
- Runner: `tools/run_scenario.py`
- Wyniki (opcjonalne logi JSONL): `data/scenario_runs/*.jsonl`

---

## 1) Jak działa runner (`tools/run_scenario.py`)

Runner w pętli „ticków” (co `tick_sec`) uruchamia emitery z wyliczonym **EPS efektywnym** wg harmonogramu.

**Obsługiwane emitery (domyślne skrypty):**
```
emitter_csv     → emitters/emitter_csv/emit_csv.py
emitter_json    → emitters/emitter_json/emit_json.py
emitter_minimal → emitters/emitter_minimal/emit_minimal.py
emitter_noise   → emitters/emitter_noise/emit_noise.py
emitter_syslog  → emitters/emitter_syslog/emit_syslog.py
```
Możesz podmienić skrypt emitera per-scenario:
```yaml
emitters:
  - name: emitter_json
    script: custom_emitters/my_special.py
    eps: 42
```

**Parametry runnera:**
```
-s, --scenario PATH   ścieżka do pliku YAML (wymagane)
--py PATH             interpreter Pythona (domyślnie: bieżący)
--strict              przerwij cały scenariusz, jeśli którykolwiek emiter zakończy się ≠0 (poza timeoutem 124)
--step-timeout SEC    timeout pojedynczego kroku emitera (domyślnie 20.0)
--dry-run             nie uruchamiaj emiterów, tylko loguj plan
--debug               wypisz szczegóły obliczeń EPS/schedule i poleceń
--log-file PATH       zapisuj ticki i podsumowanie do JSONL
--seed INT            globalny seed do losowości (np. jitter)
```

**Format logów JSONL (opcjonalny):**
- rekordy `scenario.start` / `scenario.end`
- per tick: `type: "tick"`, w tym `emitter`, `n` (planowana liczba eventów w ticku), `base_eps`, `eff_eps`, `schedule`, `jitter_scale`, ew. `levels` (z ostatniej linii `SC_STAT { ... }` wyemitowanej przez emiter).

---

## 2) Schemat pliku scenariusza (YAML)

```yaml
name: <nazwa>
duration_sec: <czas trwania>
tick_sec: <krok planowania w sekundach>

emitters:
  - name: <emitter_csv|emitter_json|...>
    eps: <docelowy EPS na plateau>
    args:
      partial_ratio: <0..1>   # dla csv/json/syslog — udział „ubogich” rekordów
      chaos: <0..1>           # dla noise — losowe typy/braki
      seed: <int>             # seed lokalny emitera
    schedule:                 # (opcjonalnie) sterowanie w czasie
      start_after_sec: <0..>  # cisza przed startem
      ramp_up_sec: <0..>      # liniowy wzrost do eps
      stop_after_sec: <0..>   # moment stopu emitera
      ramp_down_sec: <0..>    # liniowy spadek do 0 przed stopem
      jitter_pct: <0..1>      # +/- losowy % na EPS (per tick)
```

**Uwaga:** Efektywny EPS na ticku = `base_eps` * (ramp) * (jitter). Liczba eventów w ticku: `round(eff_eps * tick_sec)`.

---

## 3) Scenariusze w repo (opis)

### `default.yaml` (20s)
Umiarkowany, równy ruch wszystkich emiterów. Dobre do sanity check.
- CSV/JSON/Minimal/Noise/Syslog po 5 EPS (noise: `chaos: 0.3`, część CSV/JSON/Syslog ma `partial_ratio: 0.1–0.2`).

### `quiet.yaml` (30s)
Niski EPS i stabilnie — przydatne do sprawdzania podstawowej ścieżki i dashboardów.
- JSON 2 EPS (`partial_ratio: 0.1`), Syslog 1 EPS.

### `spike.yaml` (10s)
Krótki, intensywny skok: JSON 120 EPS + Syslog 80 EPS + Minimal 40 + Noise 40 i drugi Syslog 40.
- Szybko wyzwala **burst** i pomaga zobaczyć reakcję SLO/p95 i alertów.

### `high_errors.yaml` (20s)
Celowo dużo braków i dziwnych typów:
- JSON 30 EPS (`partial_ratio: 0.6`)
- Noise 40 EPS (`chaos: 0.8`)
- CSV 15 EPS (`partial_ratio: 0.7`)
Świetny do walidacji metryk `logops_missing_*`, `logops_parse_errors_total`.

### `burst_high_error.yaml` (30s)
Mieszanka burstu i podwyższonego błędu:
- JSON 30 EPS (`partial_ratio: 0.15`)
- Noise 20 EPS (`chaos: 0.6`, `seed: 42`)
Pozwala obserwować jednocześnie throughput i utratę jakości.

### `burst-then-ramp.yaml` (40s)
Scenariusz z **płynnymi rampami** i przesuniętym startem drugiego emitera:
- JSON: start od 0s, ramp-up 5s do 20 EPS, stop w 30s z ramp-down 5s, `jitter_pct: 0.10`.
- Minimal: start po 10s, 5 EPS, stop po 35s (ramp-down 3s).
Doskonały do testów SLO i paneli p95 — widać wpływ ramp na histogramy.

---

## 4) Jak uruchamiać

### Przez Makefile
```bash
make scenario-default
make scenario-quiet
make scenario-spike
make scenario-high-errors
make scenario-burst-high-error
make scenario-run SCEN=scenarios/burst-then-ramp.yaml
```

### Bezpośrednio runnerem
```bash
python tools/run_scenario.py --scenario scenarios/default.yaml --debug
python tools/run_scenario.py -s scenarios/spike.yaml --log-file data/scenario_runs/spike.jsonl
python tools/run_scenario.py -s scenarios/high_errors.yaml --strict --step-timeout 30
python tools/run_scenario.py -s scenarios/burst-then-ramp.yaml --seed 1337
```

**Tipy:**
- `--dry-run` sprawdza plan (EPS/ticki) bez realnego wysyłania.
- `--strict` zatrzyma scenariusz gdy którykolwiek emiter zwróci RC≠0 (poza timeoutem 124).
- `--log-file` zapisuje ticki i podsumowanie (łatwo później korelować z metrykami).
- `CTRL+C` zatrzymuje **po bieżącym ticku** (graceful).

---

## 5) Co zobaczysz w observability

**Loki (Explore/Logs):**
- zapytanie podstawowe:  
  ```logql
  {job="logops-ndjson", app="logops", emitter="emitter_json"}
  ```

**Prometheus (metryki runnera/ingestu):**
- throughput: `sum(rate(logops_ingested_total[1m]))`
- jakość: `increase(logops_missing_ts_total[5m])`, `increase(logops_missing_level_total[5m])`, `increase(logops_parse_errors_total[5m])`
- p95 (5m):  
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
  ```
- SLO % batchy < 500ms (5m):  
  ```promql
  100 * (sum(rate(logops_batch_latency_seconds_bucket{le="0.5"}[5m]))
         / sum(rate(logops_batch_latency_seconds_count[5m])))
  ```

**AuthGW (jeśli w torze):**
- odrzucenia backpressure: `increase(logops_rejected_total[5m])` oraz rozbicie wg `reason`:
  ```promql
  sum by (reason) (increase(logops_rejected_total[5m]))
  ```
  oczekiwane powody: `too_large_hdr`, `too_large`, `too_many_items`.

---

## 6) Najczęstsze problemy i diagnostyka

- **Brak logów w Loki**: sprawdź, czy powstają pliki w `data/ingest/*.ndjson`. Jeśli tak – rzuć okiem na **Promtail** (positions + ścieżki w `promtail-config.yml`).
- **Alerty nie lecą**: `make am-render`, `make am-up`, sprawdź `/etc/prometheus/alert_rules.yml` i `make prom-reload`. Upewnij się, że `ALERTMANAGER_SLACK_WEBHOOK*` są w `.env`.
- **P95 nie zmienia się**: upewnij się, że scenariusz generuje wystarczający ruch (np. `spike`), a okna rate/`[5m]` nie są za krótkie.
- **429/413 z AuthGW**: to normalne przy testach limitów/backpressure. W dashboardzie panel *AuthGW rejected by reason (5m)* powinien rosnąć.
- **Emiter nieznany**: runner zgłosi błąd „Unknown emitter …” — dodaj `script:` do YAML lub uzupełnij mapę `EMITTERS` w `run_scenario.py`.

---

## 7) Dobre praktyki

- Używaj `--log-file data/scenario_runs/<nazwa>.jsonl` — później łatwo porównać plan z metrykami.
- Testy SLO/p95 rób na scenariuszach **spike** i **burst-then-ramp** (widoczne zmiany w histogramach).
- Testy jakości/normalizacji rób na **high_errors** i **burst_high_error** (spodziewany wzrost `missing_*` i `parse_errors_total`).
- Gdy drzemią limity AuthGW, zacznij od małego `eps` i zwiększaj stopniowo albo włącz `jitter_pct`, aby uniknąć synchronicznych pików.

---

## 8) Przykładowe modyfikacje

**Podwój rampę i dodaj jitter do sysloga:**
```yaml
emitters:
  - name: emitter_syslog
    eps: 50
    args: { partial_ratio: 0.2 }
    schedule:
      start_after_sec: 3
      ramp_up_sec: 10
      stop_after_sec: 50
      ramp_down_sec: 8
      jitter_pct: 0.15
```

**Własny plugin emitera:**
```yaml
emitters:
  - name: emitter_json
    script: custom_emitters/json_heavy.py
    eps: 100
    args:
      partial_ratio: 0.05
      seed: 9001
```

---

## 9) Konwencje i ścieżki

- Scenariusze trzymamy w `scenarios/`.
- Logi scenariuszy (jeśli używasz `--log-file`) trafią do `data/scenario_runs/` (utwórz katalog).
- W trybie standardowym emitery wysyłają na **Ingest** (`/v1/logs`). Jeśli masz w torze **AuthGW**, użyj jego wrappera `tools/hmac_curl.sh` w emiterach lub ustaw zmienne środowiskowe wg dokumentacji AuthGW (patrz `docs/services/auth_gateway.md`).

---

## 10) Szybki start

```bash
# 1) Odpal observability stack
make up

# 2) Odpal Ingest (i opcjonalnie AuthGW) – patrz Makefile cele all-ingest / all-authgw
make all-ingest             # tylko Ingest + sample ruch
# lub
make all-authgw             # Ingest + AuthGW + smoke/backpressure/RL

# 3) Uruchom scenariusz
make scenario-spike
# albo
python tools/run_scenario.py -s scenarios/burst-then-ramp.yaml --log-file data/scenario_runs/ramp.jsonl

# 4) Grafana → import docs/grafana_dashboard.json i obserwuj panele
# 5) (opcjonalnie) sprawdź alerty: make am-render && make am-up && make am-synthetic
```

---

**Powiązane dokumenty:**
- `docs/services/ingest_gateway.md` — normalizacja/PII/NDJSON/metryki.  
- `docs/services/auth_gateway.md` — auth (HMAC/API Key), rate limit, backpressure, retry + circuit breaker.  
- `docs/observability.md` — Loki/Promtail/Prometheus/Grafana, alerty i SLO/p95.

```
