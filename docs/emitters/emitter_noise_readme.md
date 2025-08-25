# emitter_noise

Generuje **chaotyczne** rekordy JSON, by testować odporność normalizacji (różne aliasy pól, typy wartości, brakujące pola, dodatkowe atrybuty).

- **Kod:** `emitters/emitter_noise/emit_noise.py`
- **Endpoint:** `http://127.0.0.1:8080/v1/logs`
- **Content-Type:** `application/json`

## Uruchomienie
```bash
python emitters/emitter_noise/emit_noise.py -n 20 --chaos 0.5 --seed 123
```
**Parametry**

- `-n, --num` – liczba rekordów (domyślnie: 20)

- `--chaos` – poziom chaosu `0.0–1.0` (im wyżej, tym więcej braków i „dziwnych” typów)

- `--seed` – ziarno RNG dla powtarzalności (opcjonalnie)

## Co generuje

Aliasy kluczy: np. `message|msg|log|text`, `level|lvl|severity`, `timestamp|ts|time`

Różne typy: `level` bywa liczbą/bool, msg może być obiektem/listą

Dodatkowe pola: `user_email`, `client_ip`, `path`, `method`, `durationMs`, `env`, `service`, `meta`

## Co zrobi gateway

- spróbuje wyciągnąć `ts/level/msg` po aliasach; uzupełni braki

- zmapuje `level`, zmaskuje PII; liczniki braków zobaczysz w odpowiedzi (`missing_ts`, `missing_level`)

- świetne do testowania metryk i stabilności pipeline’u

## Loki / Grafana (Explore)

Z nagłówkiem `X-Emitter`: `emitter_noise`:
```arduino
{job="logops-ndjson", app="logops", emitter="emitter_noise"}
```
Bez nagłówka:
```arduino
{job="logops-ndjson", app="logops"}
```
## Flow

JSON „noisy” → `POST /v1/logs` → normalizacja → (opcjonalnie) NDJSON → Promtail → Loki → Grafana