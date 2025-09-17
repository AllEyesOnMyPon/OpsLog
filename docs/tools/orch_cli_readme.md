# Orchestrator CLI (`tools/orch_cli.py`)

Lekki klient wiersza poleceń do **Orchestratora** (`services/orchestrator/app.py`).
Pozwala listować aktywne scenariusze, uruchamiać nowe (z pliku YAML lub inline JSON) oraz zatrzymywać działające.

**Plik:** `tools/orch_cli.py`
**Wymaga:** Python 3.10+
**Domyślny Orchestrator URL:** `http://127.0.0.1:8070` (stała `BASE` w pliku)

---

## Co robi

- `list` — pobiera i wyświetla listę scenariuszy (`/scenario/list`)
- `start` — uruchamia scenariusz (`/scenario/start`)
- `stop` — zatrzymuje scenariusz (`/scenario/stop`)

Wszystkie odpowiedzi są drukowane jako sformatowany JSON (UTF-8).

---

## Szybki start

```bash
# Listuj scenariusze
python tools/orch_cli.py list

# Start scenariusza z pliku YAML
python tools/orch_cli.py start --yaml-path path/to/scenario.yaml

# Start scenariusza z inline JSON
python tools/orch_cli.py start --inline '{"steps":[{"run":"echo hi"}]}'

# Stop scenariusza po ID
python tools/orch_cli.py stop <SCENARIO_ID>
```

> Jeśli Orchestrator działa pod innym adresem/portem, **zmień stałą `BASE`** u góry pliku
> (np. na `http://127.0.0.1:18070`).

---

## Składnia

```bash
python tools/orch_cli.py <komenda> [opcje]
```

### Komendy

#### `list`
Bez opcji. Zwraca listę scenariuszy w formacie odpowiedzi API.

```bash
python tools/orch_cli.py list
```

#### `start`
Opcje:

- `--name <str>` — nazwa scenariusza (opcjonalnie)
- `--yaml-path <path>` — ścieżka do pliku YAML z definicją scenariusza
- `--inline <json>` — treść scenariusza w JSON (jako **string**)
- `--seed <int>` — ziarno RNG (jeśli runner wspiera deterministykę)
- `--dry-run` — uruchom w trybie „na sucho”
- `--debug` — więcej szczegółów w logach
- `--strict` — tryb restrykcyjny walidacji
- `--step-timeout <float>` — timeout pojedynczego kroku (sekundy; domyślnie `20.0`)

> Przekazujesz **albo** `--yaml-path`, **albo** `--inline`. Flagi `dry_run/debug/strict` włączaj wg potrzeb.

Przykłady:

```bash
# Plik YAML
python tools/orch_cli.py start \
  --name "load-surge" \
  --yaml-path docs/scenarios/surge.yaml \
  --debug --strict --step-timeout 30

# Inline JSON (pamiętaj o poprawnym quoting'u powłoki)
python tools/orch_cli.py start \
  --inline '{"name":"ad-hoc","steps":[{"run":"echo hello"}]}' \
  --dry-run
```

#### `stop`
Wymaga identyfikatora scenariusza.

```bash
python tools/orch_cli.py stop scn_2025-09-09_123456
```

---

## Zachowanie wyjścia

Każda komenda drukuje surową odpowiedź Orchestratora w JSON, np.:

```json
{
  "scenario_id": "scn_2025-09-09_123456",
  "status": "running",
  "name": "load-surge",
  "log_file": "data/orch/scenarios/scn_2025-09-09_123456.log"
}
```

W przypadku błędów HTTP klient wypisze treść odpowiedzi serwera (jeśli jest), w standardowym formacie JSON.

---

## Integracja z repo

- CLI zakłada działający Orchestrator (`services/orchestrator/app.py`), domyślnie pod `http://127.0.0.1:8070`.
- W `Makefile` możesz dodać aliasy na najczęstsze operacje (np. `orch-list`, `orch-start`, `orch-stop`).

---

## Uwagi

- Skrypt używa standardowej biblioteki `urllib.request` (bez zależności zewnętrznych).
- `--inline` musi być **prawidłowym** JSON-em (jeden string argument dla powłoki).
- Jeżeli korzystasz z WSL/remote hosta/tunelu SSH, pamiętaj o właściwym ustawieniu `BASE` na adres osiągalny z miejsca uruchomienia CLI.

---
