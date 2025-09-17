# Emitery

Emitery to małe programy symulujące różne style logów. Wysyłają dane **HTTP** do bramki (domyślnie przez **AuthGW** z HMAC).

**Domyślny przepływ:**
```
Emitter  →  AuthGW (HMAC)  →  IngestGW (/v1/logs)  →  (opcjonalnie) NDJSON  →  Promtail  →  Loki  →  Grafana
```

> Chcesz ominąć HMAC? Podaj `--ingest-url http://127.0.0.1:8080/v1/logs` i wyślij **bezpośrednio** do IngestGW.

---

## Wymagania

- Uruchomiony stack obserwowalności i serwisy (`make demo` lub `make stack-start`).
- Jeśli używasz domyślnego **AuthGW**, ustaw klucze (zgodne z `make authgw-config`):
  ```bash
  # przykładowi klienci z configu dev:
  export LOGOPS_API_KEY=demo-pub-1
  export LOGOPS_SECRET=demo-priv-1
  ```
  Mapa przykładowych kluczy → domyślny `--emitter`:
  | api key     | secret       | sugerowany emitter |
  |-------------|--------------|--------------------|
  | demo-pub-1  | demo-priv-1  | `json`             |
  | demo-pub-2  | demo-priv-2  | `minimal`          |
  | demo-pub-3  | demo-priv-3  | `csv`              |
  | demo-pub-4  | demo-priv-4  | `noise`            |
  | demo-pub-5  | demo-priv-5  | `syslog`           |

---

## Wspólne uruchamianie i parametry

Każdy emiter działa jako moduł Pythona:

```bash
python -m emitters.<nazwa> --scenario-id "sc-$(date +%s)" [opcje…]
```

**Wspólne opcje:**
- `--ingest-url` – endpoint wejściowy (domyślnie **AuthGW**: `http://127.0.0.1:8081/ingest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (etykieta w logach/metrykach)
- `--emitter` – nazwa emitera (domyślnie: nazwa modułu: `json|csv|minimal|noise|syslog`)
- `--eps` – średnia liczba rekordów/s (domyślnie `10`)
- `--duration` – czas trwania w sekundach (domyślnie `60`)
- `--batch-size` – ile rekordów/wierszy w jednym żądaniu (domyślnie `10`)
- `--jitter-ms` – losowy jitter (ms) między batchami (domyślnie `0`)
- `--seed` – ziarno RNG (opcjonalne)

**Zwracana statystyka (STDOUT):**
```
SC_STAT {"sent": <liczba_wysłanych_rekordów>}
```

---

## Zasady wspólne po stronie IngestGW

- **Minimalny schemat po normalizacji:** `ts`, `level`, `msg`, `emitter`, `scenario_id`, `app="logops"`, `source="ingest"`.
- **Mapowanie leveli:** `debug→DEBUG`, `warn/warning→WARN`, `fatal→ERROR`, brak→`INFO`.
- **PII:** e-maile/IP maskowane; przy `LOGOPS_ENCRYPT_PII=true` dodawane pola `*_enc` (Fernet).
- **NDJSON (opcjonalnie):** `LOGOPS_SINK_FILE=true` → zapis `./data/ingest/YYYYMMDD.ndjson`.
- **Metryki Prometheus:** m.in. `logops_ingested_total`, `logops_accepted_total`, `logops_parse_errors_total`, histogram `logops_batch_latency_seconds_*`.

---

## Szybkie sprawdzenie w Lokim / Grafanie

Filtr z etykietami dodanymi przez IngestGW:
```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="json", scenario_id="sc-..."}
```

Nie znasz `scenario_id`? Użyj tylko `emitter`:
```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="csv"}
```

---

## Lista emiterów

### 1) JSON — ustrukturyzowane logi aplikacyjne
Plik: `emitters/json.py`
Content-Type: `application/json`

- Generuje batch obiektów z polami m.in. `timestamp`, `level`, `message`, `service`, `env`, `host`, `request_id`, `user_email`, `client_ip`, `attrs`.
- Przykład:
  ```bash
  python -m emitters.json \
    --scenario-id "sc-json-$(date +%s)" \
    --duration 8 --eps 12 --batch-size 8 \
    --partial-ratio 0.3 --seed 123
  ```
- Dodatkowe opcje: `--partial-ratio` (udział rekordów bez `timestamp/level`).

### 2) CSV — proste zdarzenia w CSV
Plik: `emitters/csv.py`
Content-Type: `text/csv`

- Tworzy CSV `ts,level,msg` z losowymi poziomami; część wierszy może być „uboga”.
- Przykład:
  ```bash
  python -m emitters.csv \
    --scenario-id "sc-csv-$(date +%s)" \
    --duration 8 --eps 12 --batch-size 8 \
    --partial-ratio 0.3 --seed 123
  ```
- Dodatkowe opcje: `--partial-ratio`.

### 3) Minimal — najprostszy smoke test
Plik: `emitters/minimal.py`
Content-Type: `application/json`

- Wysyła batch JSON zawierający **tylko** `{"msg": "…"}` — resztę (`ts`, `level`) uzupełni gateway.
- Przykład:
  ```bash
  python -m emitters.minimal \
    --scenario-id "sc-min-$(date +%s)" \
    --duration 6 --eps 10 --batch-size 10
  ```

### 4) Noise — „chaotyczne” rekordy do testów odporności
Plik: `emitters/noise.py`
Content-Type: `application/json`

- Miesza aliasy kluczy (`message|msg|log`, `level|lvl|severity`, `timestamp|ts|time`), typy wartości (`level` jako liczba/bool), dziwne timestampy, dodatkowe pola (`user_email`, `client_ip`, `env`, `meta`).
- Przykład:
  ```bash
  python -m emitters.noise \
    --scenario-id "sc-noise-$(date +%s)" \
    --duration 10 --eps 15 --batch-size 10 \
    --chaos 0.5 --seed 42
  ```
- Dodatkowe opcje: `--chaos` (0.0–1.0).

### 5) Syslog — linie tekstowe w stylu sysloga
Plik: `emitters/syslog.py`
Content-Type: `text/plain`

- Wysyła linie `YYYY-mm-dd HH:MM:SS LEVEL host app[pid]: message …`; przy `--partial-ratio` część linii bez `LEVEL/host`.
- Przykład:
  ```bash
  python -m emitters.syslog \
    --scenario-id "sc-syslog-$(date +%s)" \
    --duration 8 --eps 12 --batch-size 8 \
    --partial-ratio 0.3 --seed 7
  ```

---

## Wskazówki

- **AuthGW vs IngestGW:** domyślnie emitery mówią do AuthGW (`/ingest`, HMAC). Aby wysłać bez HMAC, podaj:
  ```
  --ingest-url http://127.0.0.1:8080/v1/logs
  ```
- **Spójność etykiet:** używaj sensownego `--scenario-id` (np. `sc-<data>-<cel>`), ułatwi to filtrowanie w Lokim i łączenie metryk z logami.
- **Szybki start całego demo:** `make demo` — odpala stack, krótki ruch i otwiera dashboard Grafany.
- **Diagnostyka HMAC:** `tools/hmac_curl.sh` i `tools/verify_hmac_against_signer.py` pomogą sprawdzić nagłówki i podpis.

---

## Przykładowe zapytania PromQL (pod **Prometheus** → **Graph**)

- Wzrost przyjętych rekordów wg emitera:
  ```promql
  sum by (emitter) (increase(logops_accepted_total[5m]))
  ```
- p95 latencji batcha:
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(logops_batch_latency_seconds_bucket[5m])))
  ```
- Błędy parsowania wg scenariusza:
  ```promql
  sum by (emitter, scenario_id) (increase(logops_parse_errors_total[10m]))
  ```
