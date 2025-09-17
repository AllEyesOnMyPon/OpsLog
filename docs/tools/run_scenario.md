# Scenarios — generator ruchu do LogOps (`tools/run_scenario.py`)

Ten moduł uruchamia **scenariusze ruchu** (YAML), które odpalają emitery w krótkich „tickach” z wyliczonym **efektywnym EPS**.
Scenariusze kierują ruch do Ingest (bezpośrednio) lub do AuthGW (jeśli wskażesz jego URL), dzięki czemu łatwo ćwiczyć **SLO/p95**, alerty i dashboardy.

- **Runner:** `tools/run_scenario.py`
- **Scenariusze (YAML):** `scenarios/*.yaml`
- **Logi scenariusza (JSONL, opcjonalnie):** np. `data/scenario_runs/*.jsonl`

---

## Co robi runner (high-level)

W pętli co `tick_sec` runner:
1. Dla każdego emitera oblicza **efektywny EPS** (`base_eps` z uwzględnieniem okna `start/stop`, ramp-up/ramp-down i `jitter_pct`).
2. Uruchamia proces emitera **na czas jednego ticka** z parametrami:
   - `--eps <INT>` — zaokrąglony `eff_eps`,
   - `--duration <INT>` — równy `tick_sec` (zaokrąglone),
   - `--scenario-id <ID>` — z ENV `LOGOPS_SCENARIO` (albo `na`),
   - `--ingest-url` — z `args.ingest_url` w YAML **lub** `LOGOPS_URL` **lub** `http://127.0.0.1:8081/ingest`.
3. Zbiera statystyki z linii `SC_STAT { ... }` wypisywanej przez emitery (np. rozkład `level`), a na końcu drukuje **podsumowanie**.

> Zatrzymanie `CTRL+C` jest **graceful** — dokończy bieżący tick i zakończy scenariusz.

---

## Wbudowane emitery (domyślne)

Runner uruchamia emitery jako moduły Pythona: `python -m emitters.<name>`.

| Nazwa w YAML | Moduł                | Opis skrótowy |
|--------------|----------------------|---------------|
| `csv`        | `emitters.csv`       | CSV (`ts,level,msg`), opcj. `partial_ratio` |
| `json`       | `emitters.json`      | Batch JSON (strukturalne logi), `partial_ratio` |
| `minimal`    | `emitters.minimal`   | Tylko `{"msg": ...}` w batchu JSON |
| `noise`      | `emitters.noise`     | Chaotyczne rekordy (aliasy pól/typy), `chaos` |
| `syslog`     | `emitters.syslog`    | Linie syslog-like `text/plain`, `partial_ratio` |

Możesz też podać **własny skrypt** emitera (pole `script` w YAML).

---

## Szybki start

```bash
# Sanity check scenariusza z logiem do JSONL (polecam)
python tools/run_scenario.py -s scenarios/default.yaml --log-file data/scenario_runs/default.jsonl

# Tryb głośny + deterministyczny jitter (seed)
python tools/run_scenario.py -s scenarios/burst-then-ramp.yaml --debug --seed 1337

# Twarde „fail fast”, jeśli którykolwiek emiter zwróci RC≠0 (poza timeoutem 124)
python tools/run_scenario.py -s scenarios/high_errors.yaml --strict

# Plan bez wysyłania (dry-run)
python tools/run_scenario.py -s scenarios/spike.yaml --dry-run
```

> Jeśli chcesz wysyłać przez AuthGW, ustaw:
> ```bash
> export LOGOPS_URL="http://127.0.0.1:8081/ingest"
> export LOGOPS_SCENARIO="my-scenario-123"   # trafi do nagłówków emitterów
> ```

---

## Opcje `tools/run_scenario.py`

```
-s, --scenario PATH     Ścieżka do pliku YAML (wymagane)
--py PATH               Interpreter Pythona dla emitterów (domyślnie: bieżący)
--strict                Zakończ cały scenariusz, jeśli krok emitera rc≠0 (poza timeoutem 124)
--step-timeout SEC      Timeout pojedynczego wywołania emitera (domyślnie 20.0)
--dry-run               Nie uruchamiaj emitterów — tylko plan i logi ticków
--debug                 Więcej informacji (EPS, wywołania, komendy)
--log-file PATH         Zapisuj ticki/podsumowanie do JSONL
--seed INT              Ziarno RNG (np. do jittera)
```

---

## Schemat pliku scenariusza (YAML)

```yaml
name: <nazwa>            # opcjonalnie; domyślnie nazwa pliku
duration_sec: <float>    # czas trwania
tick_sec: <float>        # długość ticka (runner uruchamia emiter na ten czas)

emitters:
  - name: <csv|json|minimal|noise|syslog>  # lub własny skrypt przez 'script'
    eps: <float>             # docelowy EPS na plateau
    args:                    # parametry przekazywane do emitera
      partial_ratio: 0.2     # csv/json/syslog: udział „ubogich” rekordów
      chaos: 0.5             # noise: poziom chaosu
      seed: 123              # seed lokalny emitera
      batch_size: 10         # (jeśli emiter wspiera)
      jitter_ms: 0           # (jeśli emiter wspiera)
      ingest_url: "http://127.0.0.1:8081/ingest"  # override per-emitter
    script: custom_emiters/my_emitter.py  # zamiast modułu 'emitters.<name>'
    schedule:
      start_after_sec: 0
      stop_after_sec:  30
      ramp_up_sec:     5
      ramp_down_sec:   5
      jitter_pct:      0.10   # losowa fluktuacja EPS ±10% per tick
```

**Uwaga:** emitery przyjmują `--eps` jako **int** — runner zaokrągla `eff_eps`, a `--duration` ustawia na `tick_sec` (też int, zaokrąglony w górę do ≥1s).

---

## EPS i harmonogram (jak liczymy)

Dla danego ticka:
1. Sprawdź okno aktywności: `start_after_sec ≤ t < stop_after_sec` → inaczej `eff_eps=0`.
2. Zastosuj ramp-up / ramp-down (liniowo).
3. Zastosuj `jitter_pct` (np. 0.10 ⇒ mnożnik z przedziału `[0.9, 1.1]`).
4. `events_in_tick = round(eff_eps * tick_sec)`.

Runner drukuje (w `--debug`) m.in. `base_eps`, `eff_eps`, `n`.

---

## Nagłówki i identyfikacja scenariusza

- Runner przekazuje emiterom `--scenario-id` z ENV **`LOGOPS_SCENARIO`** (gdy brak: `"na"`).
- Emitery dodają nagłówki `X-Emitter` (swoja nazwa) i `X-Scenario-Id` do żądań HTTP.
- W lokach/metrykach można filtrować po `emitter`/`scenario_id`.

---

## Logi JSONL z przebiegu (`--log-file`)

Do pliku trafiają rekordy:
- `{"type":"scenario.start", ...}`
- per tick: `{"type":"tick", "emitter":..., "n":..., "eff_eps":..., "schedule":{...}, "levels":{...}, "rc":<exitcode>}`
  - `levels` pochodzi z `SC_STAT {...}` wypisywanego przez dany emiter (jeśli jest).
- `{"type":"scenario.end", "sent_approx":{...}, "levels_total":{...}, "errors_total":{...}}`

To pomaga później korelować plan z metrykami Prometheus/Grafana.

---

## Integracja z observability

**Loki (Explore / LogQL):**
```logql
{job="logops-ndjson", app="logops", emitter="json"}
```

**Prometheus (przykłady):**
- p95 (5m):
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
  ```
- throughput:
  ```promql
  sum(rate(logops_ingested_total[1m]))
  ```
- jakość / braki:
  ```promql
  increase(logops_missing_ts_total[5m])
  increase(logops_missing_level_total[5m])
  increase(logops_parse_errors_total[5m])
  ```

**AuthGW (jeśli w torze):**
```promql
sum by (reason) (increase(logops_rejected_total[5m]))
```
Spodziewane `reason`: `too_large_hdr`, `too_large`, `too_many_items`, itp.

---

## Przykładowe scenariusze (z repo)

- **default.yaml (20s)** — umiarkowany, równy ruch (wszystkie emitery ~5 EPS).
- **quiet.yaml (30s)** — niski, stabilny ruch (np. JSON 2 EPS, Syslog 1 EPS).
- **spike.yaml (10s)** — krótki, intensywny skok (JSON 120 EPS, itd.).
- **high_errors.yaml (20s)** — celowo dużo braków (wysoki `partial_ratio`/`chaos`).
- **burst-then-ramp.yaml (40s)** — płynne rampy + przesunięte starty.

Uruchom:
```bash
make scenario-default
make scenario-quiet
make scenario-spike
make scenario-high-errors
make scenario-run SCEN=scenarios/burst-then-ramp.yaml
```

---

## Najczęstsze problemy

- **Brak logów w Loki**: sprawdź, czy powstają pliki NDJSON w `data/ingest/`. Jeśli tak — zerknij w konfigurację Promtail (ścieżki / positions).
- **RC≠0 z emitera**: włącz `--debug`, sprawdź komendę wywołania i endpoint (`ingest_url`). Z `--strict` runner zakończy całość na pierwszym błędzie.
- **Za mały wolumen**: zwiększ `eps` albo wydłuż `duration_sec`, pamiętaj o oknie `[5m]` w promql dla p95.
- **AuthGW 413/429**: to oczekiwane podczas testów backpressure/RL. Obserwuj `logops_rejected_total{reason}`.

---

## Dobre praktyki

- Ustaw `LOGOPS_SCENARIO` przed testem (łatwiej filtrować w metrykach/logach).
- Zawsze podpinaj `--log-file data/scenario_runs/<nazwa>.jsonl`.
- Do testów p95 używaj scenariuszy z **rampami** lub **spike** (wyraźne kształty w histogramach).
- Gdy testujesz AuthGW, zacznij od małego `eps` i włącz `jitter_pct`, by uniknąć synchronicznych pików.

---

## Przykłady YAML

**Rampy + jitter na `syslog`:**
```yaml
name: "ramped-syslog"
duration_sec: 50
tick_sec: 1
emitters:
  - name: syslog
    eps: 50
    args: { partial_ratio: 0.2 }
    schedule:
      start_after_sec: 3
      ramp_up_sec: 10
      stop_after_sec: 45
      ramp_down_sec: 8
      jitter_pct: 0.15
```

**Własny skrypt emitera:**
```yaml
name: "custom"
duration_sec: 20
tick_sec: 1
emitters:
  - name: json
    script: custom_emitters/json_heavy.py
    eps: 100
    args:
      partial_ratio: 0.05
      seed: 9001
```

---

## Notatki implementacyjne

- Runner traktuje `--eps` jako **int** (emitery mają `argparse type=int`), dlatego zaokrągla `eff_eps`.
- Timeout kroku to kod 124 (nie traktowany jako błąd w `--strict`).
- `SC_STAT {...}` z emiterów może zawierać np. `{"sent": N, "level_counts": {...}}`.

---
