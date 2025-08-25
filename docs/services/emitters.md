# Emitery

Emitery to małe programy symulujące różne style logów. Wysyłają dane **HTTP** do gatewaya:
- URL: `http://127.0.0.1:8080/v1/logs`
- Nagłówek (ustawiany automatycznie w kodzie emitera lub domyślnie przez typ Content-Type):
  - JSON: `Content-Type: application/json`
  - CSV: `Content-Type: text/csv`
  - Syslog-like (text): `Content-Type: text/plain`
- Opcjonalnie możesz dodać nagłówek `X-Emitter: <nazwa>` — gateway wstawi go do pola `emitter`, jeśli payload go nie zawiera.

**Powiązania i przepływ:**  
Emitter → `/v1/logs` (gateway) → (opcjonalny) NDJSON (`./data/ingest/*.ndjson`) → Promtail → Loki → Grafana  
W Grafanie (Explore / Loki) użyjesz zapytania:
```
{job="logops-ndjson", app="logops", emitter="<nazwa>"}
```
---

## Zasady wspólne

- **Minimalny schemat po normalizacji:** `ts`, `level`, `msg`, `emitter`
- **Mapowanie leveli:** `debug→DEBUG`, `warn/warning→WARN`, `fatal→ERROR`, brak→`INFO`
- **PII:** e-maile/IP w `msg` maskowane; przy `LOGOPS_ENCRYPT_PII=true` dodawane pola `*_enc` (Fernet)
- **Sink plikowy (opcjonalnie):** `LOGOPS_SINK_FILE=true` → zapis `./data/ingest/YYYYMMDD.ndjson`

---

## Lista emiterów

### 1. CSV — generator zdarzeń CSV
Plik: [`emitters/emitter_csv/emit_csv.py`](../../emitters/emitter_csv/emit_csv.py)  
Szczegóły: [docs/emitters/emitter_csv/README.md](../emitters/emitter_csv/README.md)

- **Co robi:** tworzy CSV (`ts,level,msg`) z losowymi poziomami i wysyła jako `text/csv`.
- **Komenda:**
```bash
  python emitters/emitter_csv/emit_csv.py -n 10 --partial-ratio 0.3
```
- **Parametry**:

    - `-n, --num` — liczba wierszy (domyślnie 10)

    - `--partial-ratio` — udział „uboższych” wierszy bez `ts/level` (0.0–1.0; domyślnie 0.3)

- **Uwagi**: Brakujące `ts/level` zostaną uzupełnione/znormalizowane przez gateway.

### 2. JSON — ustrukturyzowane logi aplikacyjne
Plik: [`emitters/emitter_json/emit_json.py`](../../emitters/emitter_json/emit_json.py)  
Szczegóły: [docs/emitters/emitter_json/README.md](../emitters/emitter_json/README.md)

- **Co robi**: generuje batch JSON (tablica obiektów) w stylu logów serwerowych; pola m.in. `timestamp`, `level`, `message`, `service`, `env`, `host`, `request_id`, `user_email`, `client_ip`, `attrs`.

- **Komenda**:
```bash
python emitters/emitter_json/emit_json.py -n 10 --partial-ratio 0.3
```
- **Parametry**:

    - `-n, --num` — liczba rekordów w batchu (domyślnie 10)

    - `--partial-ratio` — udział rekordów z brakującym `timestamp/level` (0.0–1.0; domyślnie 0.3)

- **Uwagi**: Gateway:

    - użyje `timestamp` jako ts (lub doda `now()` jeśli brakuje),

    - zmapuje `level`,

    - zamaskuje PII w `message`, a przy włączonym szyfrowaniu doda `msg_enc`, `user_email_enc`, `client_ip_enc`.

### 3. Minimal — najprostszy smoke test
Plik: [`emitters/emitter_minimal/emit_minimal.py`](../../emitters/emitter_minimal/emit_minimal.py)  
Szczegóły: [docs/emitters/emitter_minimal/README.md](../emitters/emitter_minimal/README.md)

- **Co robi**: wysyła batch JSON zawierający wyłącznie pole msg (np. {"msg":"minimal #1"}).

- **Komenda**:
```bash
python emitters/emitter_minimal/emit_minimal.py -n 10
```
- **Parametry**:

    - `-n, --num` — liczba rekordów (domyślnie 10)

- **Uwagi**: Gateway uzupełni brakujące `ts` i `level` (przyjmie `INFO`).
### 4. Noise — „chaotyczne” rekordy testujące odporność
Plik: [`emitters/emitter_noise/emit_noise.py`](../../emitters/emitter_noise/emit_noise.py)  
Szczegóły: [docs/emitters/emitter_noise/README.md](../emitters/emitter_noise/README.md)

- **Co robi**: generuje różnorodne, czasem „wadliwe” rekordy: aliasy kluczy (`message/msg/log`), różne typy wartości (`level` jako liczba/bool), dziwne timestampy, dodatkowe pola (`user_email`, `client_ip`, `attrs`, itp.).

- **Komenda**:
```bash
python emitters/emitter_noise/emit_noise.py -n 20 --chaos 0.5 --seed 123
```
- **Parametry**:

    - `-n, --num` — liczba rekordów (domyślnie 20)

    - `--chaos` — poziom chaosu 0.0–1.0 (więcej braków i nietypów → trudniejsza normalizacja)

    - `--seed` — ziarno RNG dla powtarzalności (opcjonalnie)

- **Uwagi**: Idealny do sprawdzania liczników braków (`missing_ts`, `missing_level`) i maskowania PII w złożonych `msg`.
### 5. Syslog — linie tekstowe jak w syslogu
Plik: [`emitters/emitter_syslog/emit_syslog.py`](../../emitters/emitter_syslog/emit_syslog.py)  
Szczegóły: [docs/emitters/emitter_syslog/README.md](../emitters/emitter_syslog/README.md)

Co robi: buduje linie tekstowe w formacie `YYYY-mm-dd HH:MM:SS [LEVEL] host app[pid]: message ...` i wysyła jako `text/plain`. Każda linia to jeden rekord.

**Komenda**:
```bash
python emitters/emitter_syslog/emit_syslog.py -n 10 --partial-ratio 0.3
```
- **Parametry**:

    - `-n, --num` — liczba linii (domyślnie 10)

    - `--partial-ratio` — udział „uboższych” linii (np. bez level/host) (0.0–1.0; domyślnie 0.3)

- **Uwagi**: Gateway parsuje linie regexem (timestamp + opcjonalny level + reszta), maskuje PII w treści.

### Szybkie sprawdzenie w Lokim (po uruchomieniu stacka i gatewaya)

**Linux/macOS (curl):**
```bash
curl -G "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query={job="logops-ndjson",app="logops",emitter="emitter_csv"}'
```
**Windows PowerShell (irm):**
```powershell
irm "http://localhost:3100/loki/api/v1/query?query={job='logops-ndjson',app='logops',emitter='emitter_csv'}"
```
Zmień `emitter="emitter_csv"` na odpowiednie źródło (`emitter_json`, `emitter_minimal`, `emitter_noise`, emitter_syslog), jeśli dodajesz nagłówek `X-Emitter` w testach lub gateway dokleja `emitter` z payloadu.
