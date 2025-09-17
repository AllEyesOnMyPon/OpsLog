# Konfiguracja środowiska LogOps (`.env`)

Plik `.env` steruje zachowaniem usług **LogOps** (Auth Gateway, Ingest Gateway, Core), narzędzi (`tools/*`), housekeepingiem oraz integracjami z Prometheusem/Alertmanagerem/Slackiem.
W repozytorium znajdziesz szablon: **`.env.example`** — skopiuj go do `.env` i dopasuj wartości.

---

## Endpoints / integracje (dev lokalny)

| Zmienna         | Domyślna                           | Użycie |
|-----------------|------------------------------------|-------|
| `ENTRYPOINT_URL`| `http://127.0.0.1:8081/ingest`     | Adres wejściowy (zwykle **AuthGW** `/ingest`) używany przez emitery i skrypty (np. `tools/hmac_curl.sh`). |
| `INGEST_URL`    | `http://127.0.0.1:8080`            | Adres **Ingest Gateway** (bez ścieżki). |
| `CORE_URL`      | `http://127.0.0.1:8095/v1/logs`    | Endpoint **Core**; Ingest forwarduje tu znormalizowane rekordy. |
| `PROM_URL`      | `http://127.0.0.1:9090`            | Adres **Prometheus** (używany w skryptach/demo). |
| `LOKI_URL`      | `http://127.0.0.1:3100`            | Adres **Loki** (Explore/Grafana, skrypty/demo). |

---

## HMAC (klucze demo dla klienta/emitera)

> **Uwaga:** wartości tylko do lokalnych testów. Sekretów nie commituj do Gita.

| Zmienna          | Domyślna        | Opis |
|------------------|-----------------|------|
| `LOGOPS_API_KEY` | `demo-pub-1`    | Publiczny identyfikator klienta (nagłówek `X-Api-Key`). |
| `LOGOPS_SECRET`  | `demo-priv-1`   | Sekret HMAC klienta; wykorzystywany przez narzędzia (`tools/sign_hmac.py`, `tools/hmac_curl.sh`) oraz weryfikatory. |

---

## Encryption settings

| Zmienna                | Typ       | Domyślna                    | Opis |
|------------------------|-----------|-----------------------------|------|
| `LOGOPS_SECRET_KEY`    | string    | *(brak)*                    | Klucz **Fernet** (32 bajty Base64) do szyfrowania PII. |
| `LOGOPS_ENCRYPT_PII`   | bool      | `false`                     | Włącza szyfrowanie pól wrażliwych. |
| `LOGOPS_ENCRYPT_FIELDS`| csv list  | `user_email,client_ip`      | Lista dodatkowych pól do szyfrowania (wraz z `msg_enc` dla pełnego tekstu, jeśli włączone po stronie serwisu). |

---

## Debugging & sampling

| Zmienna                   | Typ  | Domyślna | Opis |
|---------------------------|------|----------|------|
| `LOGOPS_DEBUG_SAMPLE`     | bool | `false`  | Jeśli `true`, API może zwracać próbkę znormalizowanych rekordów w odpowiedzi (pomocne w dev). |
| `LOGOPS_DEBUG_SAMPLE_SIZE`| int  | `2`      | Maksymalna liczba rekordów w próbce debugowej. |

---

## File sink (NDJSON → Promtail → Loki)

| Zmienna          | Typ  | Domyślna        | Opis |
|------------------|------|-----------------|------|
| `LOGOPS_SINK_FILE`| bool| `false`         | Gdy `true`, zapisuje przyjęte rekordy do **NDJSON** (źródło dla Promtail). |
| `LOGOPS_SINK_DIR` | path| `./data/ingest` | Katalog z plikami `YYYYMMDD.ndjson`. <br>**Uwaga (Core):** Core honoruje `LOGOPS_SINK_DIR` jako priorytet (nad `CORE_SINK_DIR`). |

---

## Housekeeping (retencja / archiwizacja)

| Zmienna                  | Typ  | Domyślna | Opis |
|--------------------------|------|----------|------|
| `LOGOPS_RETENTION_DAYS`  | int  | `7`      | Ile dni trzymać pliki NDJSON w `LOGOPS_SINK_DIR`. |
| `LOGOPS_ARCHIVE_MODE`    | enum | `delete` | Co robić z plikami po terminie: `delete` — usuń, `zip` — spakuj do `./data/archive/`. |

### Autorun housekeeping (jeśli serwis wspiera)
| Zmienna                         | Typ  | Domyślna | Opis |
|---------------------------------|------|----------|------|
| `LOGOPS_HOUSEKEEP_AUTORUN`      | bool | `false`  | Uruchom housekeeping automatycznie na starcie. |
| `LOGOPS_HOUSEKEEP_INTERVAL_SEC` | int  | `0`      | Interwał uruchomień w sekundach (0 = tylko jednorazowo na starcie). |

> Ręczne uruchomienie: `python tools/housekeeping.py`

---

## Alertmanager / Slack

| Zmienna                           | Typ     | Domyślna | Opis |
|-----------------------------------|---------|----------|------|
| `ALERTMANAGER_SLACK_WEBHOOK`      | string  | *(brak)* | Webhook Slack dla Alertmanagera (globalny). |
| `ALERTMANAGER_SLACK_WEBHOOK_LOGOPS`| string | *(brak)* | Webhook Slack dla alertów LogOps (może być taki sam jak globalny). |

---

## Parametry demo (Makefile)

| Zmienna          | Domyślna                        | Opis |
|------------------|---------------------------------|------|
| `DEMO_SCENARIO`  | `default`                       | Domyślny scenariusz ruchu (z `scenarios/*.yaml`). |
| `DEMO_DASH_UID`  | `logops-observability-slo`      | UID importowanego dashboardu w Grafanie. |

---

## Przykład (`.env`)

```env
# === Endpoints (lokalnie) ===
ENTRYPOINT_URL=http://127.0.0.1:8081/ingest
INGEST_URL=http://127.0.0.1:8080
CORE_URL=http://127.0.0.1:8095/v1/logs
PROM_URL=http://127.0.0.1:9090
LOKI_URL=http://127.0.0.1:3100

# === HMAC (demo) ===
LOGOPS_API_KEY=demo-pub-1
LOGOPS_SECRET=demo-priv-1

# === Szyfrowanie PII ===
LOGOPS_SECRET_KEY=H0JFlLBAZirMvzzQD-lQziWhRGesRXWQMK1nA1u5b5k=
LOGOPS_ENCRYPT_PII=true
LOGOPS_ENCRYPT_FIELDS=user_email,client_ip

# === Debug sample ===
LOGOPS_DEBUG_SAMPLE=true
LOGOPS_DEBUG_SAMPLE_SIZE=3

# === File sink (NDJSON) ===
LOGOPS_SINK_FILE=true
LOGOPS_SINK_DIR=./data/ingest

# === Housekeeping ===
LOGOPS_RETENTION_DAYS=2
LOGOPS_ARCHIVE_MODE=delete
LOGOPS_HOUSEKEEP_AUTORUN=true
LOGOPS_HOUSEKEEP_INTERVAL_SEC=0

# === Alertmanager / Slack ===
ALERTMANAGER_SLACK_WEBHOOK=https://hooks.slack.com/services/XXX/YYY/ZZZ
ALERTMANAGER_SLACK_WEBHOOK_LOGOPS=https://hooks.slack.com/services/XXX/YYY/ZZZ

# === Demo (Makefile) ===
DEMO_SCENARIO=default
DEMO_DASH_UID=logops-observability-slo
```

---

## Notatki i dobre praktyki

- **Sekrety** (`LOGOPS_SECRET`, `LOGOPS_SECRET_KEY`, webhooki) trzymaj poza repo — w `.env` lokalnym, menedżerze sekretów lub zmiennych CI.
- `ENTRYPOINT_URL` wskazuje zwykle **AuthGW** (`/ingest`) — emitery i skrypty testowe (np. `hmac_curl.sh`) wyślą tam ruch, a AuthGW prześle go do **Ingest** (`INGEST_URL`).
- **Ingest → Core**: Ingest forwarduje już znormalizowane rekordy do `CORE_URL`.
- **Promtail/Loki**: włącz `LOGOPS_SINK_FILE=true`, aby powstawały pliki NDJSON śledzone przez Promtail; logi zobaczysz w Grafanie (Explore/Loki).
