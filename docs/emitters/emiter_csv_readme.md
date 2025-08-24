# emitter_csv

Generator logów w formacie **CSV** i wysyłka do gatewaya jako `text/csv`.

- **Kod:** `emitters/emitter_csv/emit_csv.py`
- **Endpoint:** `http://127.0.0.1:8080/v1/logs`
- **Content-Type:** `text/csv`

## Uruchomienie
```bash
python emitters/emitter_csv/emit_csv.py -n 10 --partial-ratio 0.3
```
**Parametry**

- `-n, --num` – liczba wierszy (domyślnie: 10)

- `--partial-ratio` – odsetek niepełnych wierszy (bez ts/level) w zakresie 0.0–1.0 (domyślnie: 0.3)

## Format danych

Nagłówek: `ts`,`level`,`msg`

Przykład (częściowo ubożone wiersze):
```pgsql
ts,level,msg
2025-08-24T15:22:10+0200,INFO,"csv event #1"
,,"csv event #2"
```
## Co zrobi gateway

- Uzupełni brakujące `ts` (UTC now) i zmapuje `level` (warn→WARN, itp.)

- Zmaskuje PII w `msg` (email/IP). Przy włączonym szyfrowaniu doda pola `*_enc`.

- Opcjonalnie zapisze NDJSON do `./data/ingest/YYYYMMDD.ndjson` (jeśli `LOGOPS_SINK_FILE=true`)

## Loki / Grafana (Explore)

Jeśli **dodałeś etykietę** `emitter` (np. przez nagłówek `X-Emitter`: `emitter_csv`):
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_csv"}
```
W przeciwnym razie filtruj po:
```arduion
{job="logops-ndjson", app="logops"}
```
## Flow
CSV → `POST /v1/logs` → normalizacja → (opcjonalnie) NDJSON → Promtail → Loki → Grafana