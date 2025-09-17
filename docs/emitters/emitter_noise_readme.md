# emitter_noise

Generator **„chaotycznych”** rekordów JSON do testowania odporności normalizacji (aliasy pól, nietypowe typy, braki, dodatkowe atrybuty).

- **Kod:** `emitters/noise.py`
- **Domyślny endpoint:** `http://127.0.0.1:8081/ingest` (AuthGW, HMAC)
- **Content-Type:** `application/json`

> Uwaga: domyślnie wysyłamy przez **AuthGW** (HMAC). Aby ominąć HMAC i trafić bezpośrednio do IngestGW, użyj `--ingest-url http://127.0.0.1:8080/v1/logs`.

---

## Wymagania

- Działające usługi (np. `make stack-start` albo po prostu `make demo`).
- Dla trybu przez AuthGW ustaw klucze klienta (zgodne z `make authgw-config`):
  ```bash
  export LOGOPS_API_KEY=demo-pub-4
  export LOGOPS_SECRET=demo-priv-4
  ```

---

## Uruchomienie

### Najprościej (modułowo)
```bash
python -m emitters.noise \
  --scenario-id "sc-noise-$(date +%s)" \
  --duration 8 --eps 12 --batch-size 8 \
  --chaos 0.5 --seed 123
```

### Bezpośrednio (skrypt)
```bash
./emitters/noise.py \
  --scenario-id "sc-noise-$(date +%s)" \
  --duration 8 --eps 12 --batch-size 8 \
  --chaos 0.5 --seed 123
```

**Parametry**

- `--ingest-url` – endpoint wejściowy (domyślnie **AuthGW** `http://127.0.0.1:8081/ingest`)
- `--scenario-id` *(wymagane)* – identyfikator scenariusza (do etykiet/logów)
- `--emitter` – nazwa emitera (domyślnie: `noise`)
- `--eps` – średnia liczba rekordów/sek (domyślnie: `10`)
- `--duration` – czas trwania w sekundach (domyślnie: `60`)
- `--batch-size` – ile rekordów w jednym żądaniu (domyślnie: `10`)
- `--jitter-ms` – losowy jitter (ms) między batchami (domyślnie: `0`)
- `--chaos` – poziom chaosu `0.0–1.0` (im wyżej, tym więcej braków i „dziwnych” typów; domyślnie `0.5`)
- `--seed` – ziarno RNG dla powtarzalności (opcjonalnie)

Na końcu program wypisze statystykę:
```
SC_STAT {"sent": <liczba_wysłanych_rekordów>}
```

---

## Co generuje „noise”

- **Aliasowane klucze** (losowo wybierane):
  - wiadomość: `message | msg | log | text`
  - poziom: `level | lvl | severity`
  - czas: `timestamp | ts | time`
- **Różne typy**: `level` bywa liczbą/bool, `msg` może być obiektem/listą.
- **Dodatkowe pola** (losowa podgrupa): `user_email`, `client_ip`, `path`, `method`, `durationMs`, `env`, `service`, `meta`, `userId`, …
- **Formaty czasu**: poprawne ISO8601 i celowo „śmieciowe” wartości.

Regulator **`--chaos`** zwiększa prawdopodobieństwo braków i niepoprawnych typów.

---

## Co zrobi gateway

Po stronie **IngestGW**:

- spróbuje wyciągnąć `ts/level/msg` po **aliasach**; uzupełni braki,
- zmapuje `level`, zmaskuje/zaszyfruje PII (jeśli włączone),
- policzy metryki Prometheus (m.in. `logops_ingested_total`, `logops_parse_errors_total`, histogram p95),
- doda/ustali etykiety `app="logops"`, `source="ingest"`, `emitter`, `scenario_id`,
- *(opcjonalnie)* zapisze NDJSON do `./data/ingest/YYYYMMDD.ndjson` (`LOGOPS_SINK_FILE=true`).

To świetny generator do testowania **stabilności** pipeline’u i **jakości** normalizacji.

---

## Loki / Grafana (Explore)

Z nagłówkami `X-Emitter: noise`, `X-Scenario-Id: sc-…` łatwo filtrujesz:

```logql
{job="logops-ndjson", app="logops", source="ingest", emitter="noise", scenario_id="sc-..."}
```

Albo szerzej:
```logql
{job="logops-ndjson", app="logops", source="ingest"}
```

---

## Flow

JSON „noisy” → `POST /ingest` (AuthGW, HMAC) → IngestGW (`/v1/logs`) → normalizacja + metryki → *(opcjonalnie)* NDJSON → Promtail → Loki → Grafana

*(Alternatywa bez HMAC: JSON → `POST /v1/logs` bezpośrednio do IngestGW przy `--ingest-url http://127.0.0.1:8080/v1/logs`.)*
