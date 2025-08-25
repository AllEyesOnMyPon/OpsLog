# run_scenario.py — orkiestracja ruchu / scenariusze EPS

Skrypt uruchamia wybrane emitery w „tickach” czasu, przybliżając zadaną prędkość zdarzeń (EPS). Zbiera statystyki poziomów logów ze standardowego wyjścia emiterów na podstawie linii `SC_STAT { ... }`.

> Plik: `tools/run_scenario.py`  
> Wymaga: Python 3.11+ (działa w Twoim `.venv`) i zainstalowanych zależności emiterów.

---

## Szybki start

```bash
# przykład: defaultowy scenariusz
python tools/run_scenario.py -s scenarios/default.yaml

# użyj konkretnego interpretera Pythona
python tools/run_scenario.py -s scenarios/default.yaml --py .venv/bin/python

# tryb „ściśle” – przerwie, gdy emiter zwróci nie-0 (poza timeoutem 124)
python tools/run_scenario.py -s scenarios/spike.yaml --strict

#Na końcu zobaczysz podsumowanie:

[summary]
  emitter_json: ~600 events (approx) | DEBUG=200, INFO=380, ERROR=20
  emitter_csv:  ~300 events (approx) | INFO=300
  ...
  ```
## Format scenariusza (YAML)
```yaml
name: Spike test
duration_sec: 60      # całkowity czas scenariusza
tick_sec: 1.0         # długość jednego „tyknięcia”
emitters:
  - name: emitter_json
    eps: 10           # ~zdarzeń/sekundę
    args:
      partial_ratio: 0.2
      seed: 123
  - name: emitter_csv
    eps: 5
    args:
      partial_ratio: 0.1
```
**Obsługiwane emitery i argumenty**

Skrypt mapuje nazwy emiterów na ścieżki:

- `emitter_csv` → `emitters/emitter_csv/emit_csv.py`
arg: `partial_ratio`, `seed`

- `emitter_json` → `emitters/emitter_json/emit_json.py`
arg: `partial_ratio`, `seed`

- `emitter_minimal` → `emitters/emitter_minimal/emit_minimal.py`
(brak dodatkowych argów)

- `emitter_noise` → `emitters/emitter_noise/emit_noise.py`
arg: `chaos`, `seed`

- `emitter_syslog` → `emitters/emitter_syslog/emit_syslog.py`
arg: `partial_ratio`, `seed`

>`eps * tick_sec` jest zaokrąglane do najbliższej liczby całkowitej i tyle rekordów skrypt emiter ma próbować wysłać w danym ticku.

## Jak to działa

- Każdy **tick**:

    - Dla każdego emitera oblicza `n ≈ round(eps * tick)`.

    - Uruchamia emiter jako podproces: `python <emitter.py> -n n [opcjonalne-arg]`.

    - Zbiera `stdout/stderr` i wyciąga ostatnią linijkę `SC_STAT {...}` (jeśli jest).

- Sumowane są liczniki poziomów logów (np. `INFO/DEBUG/ERROR`) i drukowane w podsumowaniu.

- `SIGINT` (Ctrl+C) zatrzymuje scenariusz **gracefully** po bieżącym ticku.

## Parametry CLI
```less
usage: run_scenario.py [-h] -s SCENARIO [--py PY] [--strict] [--step-timeout STEP_TIMEOUT]

opcje:
  -s, --scenario        ścieżka do pliku YAML ze scenariuszem (wymagane)
  --py                  interpreter Pythona dla emiterów (domyślnie bieżący)
  --strict              zakończ scenariusz, jeśli emiter zwróci nie-0 (poza 124)
  --step-timeout        timeout na jedno uruchomienie emitera (sekundy, domyślnie 20)
```

## Wymagania po stronie emiterów
Każdy emiter powinien:

- wysyłać zdarzenia do gateway’a z nagłówkiem `X-Emitter: <nazwa emitera>`,

- na koniec wypisać linię w formacie:

```arduino
SC_STAT {"level_counts": {"DEBUG": 10, "INFO": 50, "ERROR": 2}}
```
*(dokładny JSON zliczeń poziomów — skrypt to odczyta i zsumuje).*

Przykład poprawnych końcówek main():
```py
print("SC_STAT " + json.dumps({"level_counts": dict(level_counts)}))
```

## FAQ / Troubleshooting

- „Emitter script not found…” — sprawdź ścieżki w EMITTERS w tools/run_scenario.py.

- Brak SC_STAT w podsumowaniu — emitery nie wypisują SC_STAT {...}; sprawdź ich print na końcu.

- Timeout per step — podnieś --step-timeout jeśli emiter potrzebuje więcej czasu.

- Brak logów w Loki/Grafanie — upewnij się, że gateway (/metrics) działa, Prometheus go scrapuje, a promtail/loki są uruchomione.