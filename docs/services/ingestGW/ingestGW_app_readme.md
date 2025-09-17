# Ingest Gateway (FastAPI)

Warstwa **wejściowa i normalizująca**. Przyjmuje logi w kilku formatach (JSON / CSV / syslog-like),
**normalizuje** je do wspólnego schematu (`ts`, `level`, `msg`, …), **dokleja etykiety transportowe**
(`emitter`, `scenario_id`, `app="logops"`, `source="ingest"`), opcjonalnie **zapisuje NDJSON** i
**forwarduje** przetworzony batch do **Core**.

Pliki źródłowe:
- Aplikacja: `services/ingestgw/app.py`
- Normalizacja: `services/ingestgw/normalize.py`
- Parsowanie CSV/syslog: `services/ingestgw/parsers.py`
- Metryki i flaki konfiguracyjne: `services/ingestgw/metrics.py`

---

## Endpointy

- `GET /metrics` — metryki Prometheus (exposition format).
- `POST /v1/logs` — ingest logów w jednym z obsługiwanych formatów, normalizacja i **forward** do Core.
  - Zwraca **dokładnie** to, co zwróci Core (status + body).

> Uwaga: Ingest **nie wystawia** `GET /healthz` (stan na tę wersję).

---

## `/v1/logs` — wejście i nagłówki

**Nagłówki transportowe (opcjonalne, ale zalecane):**
- `X-Emitter: <nazwa>` — identyfikator źródła; ma **pierwszeństwo** nad polem w rekordzie.
- `X-Scenario-Id: <id>` *(lub starszy `X-Scenario`)* — id scenariusza/testu; dołączane do rekordów.

**Obsługiwane Content-Type:**
1. `application/json`
   - Pojedynczy **obiekt** lub **tablica obiektów**.
   - Jeśli w tablicy znajdują się elementy nie-będące obiektami, są one odfiltrowywane.
     Gdy **wszystkie** elementy są niepoprawne → `422` z listą indeksów.

2. `text/csv`
   - Wymagany nagłówek kolumn: `ts,level,msg`
   - Dopuszczalne dodatkowe kolumny (np. `user_email`, `client_ip`, …)
   - Każdy wiersz → jeden rekord.

3. `text/plain`
   - Syslog-like, **1 linia = 1 rekord**.
   - Parser wyciąga `ts` (`YYYY-MM-DD HH:MM:SS`), opcjonalny `LEVEL` i resztę jako `msg`.

**Błędy wejścia:**
- Niepoprawny JSON → `400` (`Invalid JSON body`).
- JSON nie będący obiektem/arrayem → `400`.
- JSON array z wyłącznie wadliwymi elementami → `422` + `invalid_indices`.

---

## Normalizacja (co robi Ingest)

- **Timestamp (`ts`)**
  Rozpoznaje pola-aliasy (`ts` / `timestamp` / `time`).
  Brak / niepoprawny → wstawia bieżący **UTC** (ISO8601).

- **Poziom (`level`)**
  Mapowanie: `debug→DEBUG`, `warn|warning→WARN`, `fatal→ERROR`, brak→`INFO`.
  Nietypowe typy (np. liczba/bool) → mapowane zachowawczo do stringów/INFO.

- **Wiadomość (`msg`)**
  Źródła: `message` / `msg` / `log` / treść linii (dla syslog).
  Maskowanie PII (email/IP) wykonywane w trakcie normalizacji.

- **PII encryption (opcjonalnie)**
  Jeżeli włączone w `metrics.py` poprzez ENV (np. `LOGOPS_ENCRYPT_PII=true` i poprawny klucz Fernet):
  dodawane są pola `*_enc` (np. `msg_enc`, `user_email_enc`, `client_ip_enc`) obok **zamaskowanych**
  wartości jawnych.

- **Etykiety transportowe i źródłowe**
  `app="logops"`, `source="ingest"`, a także:
  - `emitter` — z **nagłówka** (ma pierwszeństwo) lub z rekordu,
  - `scenario_id` — z nagłówka `X-Scenario-Id`/`X-Scenario`.

---

## Forward do Core

Po normalizacji batch jest forwardowany do **Core** (`CORE_URL`) z nagłówkami:
- `Content-Type: application/json`
- `X-Emitter: <…>`
- `X-Scenario-Id: <…>`

Wysyłka używa `_post_with_retry(...)` (timeouty, exponential backoff, kilka prób).
Odpowiedź z Core jest zwracana 1:1.

---

## NDJSON (opcjonalnie)

Jeśli włączone w `metrics.py` (`SINK_FILE=true`), Ingest dopisuje **każdy znormalizowany rekord**
do dziennego pliku NDJSON:
```
<DIR>/<YYYYMMDD>.ndjson
```
gdzie `<DIR>` to `LOGOPS_SINK_DIR` (jeśli ustawione) albo `SINK_DIR_PATH` (domyślne w metrics.py, zazwyczaj `./data/ingest`).

Do pliku **nie trafiają** pola techniczne zaczynające się od `_`.

---

## Metryki Prometheus

Zdefiniowane w `metrics.py` i używane w `app.py`:

- **Przepływ żądania**
  - `logops_inflight` *(Gauge)* — równolegle obsługiwane żądania.

- **Batch**
  - `logops_batch_size` *(Histogram)* — liczebność batcha.
  - `logops_batch_latency_seconds{emitter,scenario_id}` *(Histogram)* — latencja przetwarzania.

- **Akceptacje / poziomy / braki**
  - `logops_accepted_total{emitter,scenario_id}` *(Counter)* — liczba rekordów po normalizacji.
  - `logops_ingested_total{emitter,level}` *(Counter)* — rozkład leveli po normalizacji.
  - `logops_missing_ts_total{emitter,scenario_id}` *(Counter)*
  - `logops_missing_level_total{emitter,scenario_id}` *(Counter)*

- **Walidacja**
  - `logops_parse_errors_total{emitter,scenario_id}` *(Counter)* — błędne elementy w JSON array.

---

## ENV (kluczowe)

Z `app.py` i `metrics.py`:

- **Forward**
  - `CORE_URL` — URL endpointu Core (domyślnie `http://127.0.0.1:8095/v1/logs`)

- **Sink / ścieżki**
  - `LOGOPS_SINK_DIR` — katalog NDJSON (nadpisuje domyślny z `metrics.py`)
  - (w `metrics.py`) `SINK_FILE` *(bool)*, `SINK_DIR_PATH`

- **Debug (w `metrics.py`)**
  - `DEBUG_SAMPLE` *(bool)* — wewnętrzny sampling znormalizowanych rekordów
  - `DEBUG_SAMPLE_SIZE` *(int)* — rozmiar próbki

- **PII encryption (w `metrics.py`/`normalize.py`)**
  - `LOGOPS_ENCRYPT_PII` *(bool)*
  - `LOGOPS_SECRET_KEY` *(Fernet 32B base64)*
  - `LOGOPS_ENCRYPT_FIELDS` *(CSV pól do szyfrowania; np. `user_email,client_ip`)*

> W tej wersji Ingest **nie zwraca** żadnych debugowych pól w odpowiedzi — zwraca odpowiedź z Core.

---

## Flow i zapytania w Loki

**Przepływ:**
```
Emitery → (AuthGW) → IngestGW → Core → (opcjonalnie) NDJSON → Promtail → Loki → Grafana
```

**Zapytanie Explore (Loki):**
```logql
{job="logops-ndjson", app="logops", emitter="json"}
```
Zmieniaj `emitter` na `csv`, `syslog`, `noise`, `minimal` zgodnie ze źródłem.

---

## Przykłady

### JSON (tablica)
```bash
curl -s http://127.0.0.1:8080/v1/logs \
  -H "Content-Type: application/json" \
  -H "X-Emitter: json" \
  -H "X-Scenario-Id: sc-local" \
  -d '[{"timestamp":"2025-09-09T10:00:00Z","level":"warning","message":"user a@b.com from 10.1.2.3"}]'
```

### CSV
```bash
curl -s http://127.0.0.1:8080/v1/logs \
  -H "Content-Type: text/csv" \
  -H "X-Emitter: csv" \
  --data-binary $'ts,level,msg\n2025-09-09T10:00:00+0000,INFO,"csv event #1"\n,,"csv event #2"\n'
```

### Syslog-like (text/plain)
```bash
curl -s http://127.0.0.1:8080/v1/logs \
  -H "Content-Type: text/plain" \
  -H "X-Emitter: syslog" \
  --data-binary $'2025-09-09 10:00:00 INFO host web[1234]: served #1 user=u@ex.com ip=192.168.1.5\n'
```

> W praktyce skorzystasz z gotowych emiterów: `emitters/json.py`, `csv.py`, `syslog.py`, `noise.py`, `minimal.py`
> (ustawiają nagłówki i `Content-Type` poprawnie).

---

## Uwagi operacyjne

- **Gdzie normalizować?** CSV/syslog-like zawsze kieruj do **Ingest**, nie do Core.
- **Kardynalność etykiet**: staraj się mieć stabilne `emitter` i sensowne `scenario_id`, by nie wysadzić metryk.
- **NDJSON**: unikaj podwójnego zapisu (Ingest i Core jednocześnie), chyba że wiesz co robisz — wybierz jeden punkt „prawdy” dla Promtail.
- **Timeouty/retry**: `_post_with_retry` zapewnia podstawowy backoff — dopasuj `CORE_URL` oraz zachowanie Core do wolumenów, które wysyłasz.

---

## Checklist

- [ ] Ingest działa (`/metrics` odpowiada).
- [ ] `CORE_URL` wskazuje na działające `/v1/logs` w Core.
- [ ] Emiter wysyła z `X-Emitter` i (opcjonalnie) `X-Scenario-Id`.
- [ ] (Opcjonalnie) `SINK_FILE=true` + `LOGOPS_SINK_DIR` tam, gdzie zbiera Promtail.
- [ ] Monitorujesz: `logops_batch_latency_seconds`, `logops_ingested_total`, `logops_missing_*`, `logops_parse_errors_total`.

---
