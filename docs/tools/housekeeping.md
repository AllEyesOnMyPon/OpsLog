# Housekeeping (NDJSON cleanup & archive)

Narzędzie do sprzątania katalogu z dziennymi plikami **NDJSON** (np. `data/ingest/20250101.ndjson`).
Usuwa pliki starsze niż `RETENTION_DAYS` lub — w trybie archiwizacji — pakuje je do ZIP i usuwa oryginały.

**Plik:** `tools/housekeeping.py`
**Wymaga:** Python 3.10+, (opcjonalnie) `python-dotenv` dla odczytu `.env`

---

## Jak działa

- Wczytuje konfigurację z **ENV** (priorytet) oraz z **.env** w katalogu repo (fallback).
- Szuka plików w `LOGOPS_SINK_DIR` pasujących do wzorca `YYYYMMDD.ndjson`.
- Dla każdego pliku oblicza datę (`YYYYMMDD` w **UTC**) i porównuje z progiem:
  `now(UTC) - LOGOPS_RETENTION_DAYS`.
- Dla plików starszych niż próg:
  - **delete** (domyślnie): usuwa plik,
  - **zip**: dopisuje plik do `data/archive/YYYYMMDD.zip` (ZIP_DEFLATED), po czym usuwa oryginał.
- Loguje akcje na STDOUT z prefiksem `[housekeep]`.

> Pliki, których nazwy **nie** mają formatu `YYYYMMDD.ndjson`, są ignorowane.

---

## Konfiguracja (ENV / `.env`)

| Zmienna                 | Domyślnie           | Opis |
|-------------------------|---------------------|------|
| `LOGOPS_SINK_DIR`       | `./data/ingest`     | Katalog z plikami NDJSON do sprzątania |
| `LOGOPS_RETENTION_DAYS` | `7`                 | Ile dni trzymać pliki |
| `LOGOPS_ARCHIVE_MODE`   | `delete`            | `delete` lub `zip` (archiwum trafia do `./data/archive`) |

> Jeśli `LOGOPS_ARCHIVE_MODE=zip`, katalog `data/archive/` zostanie utworzony automatycznie.

---

## Uruchamianie

### Jednorazowo (ręcznie)
```bash
python tools/housekeeping.py
```

Przykładowy wynik:
```
[housekeep] archived 20240815.ndjson -> 20240815.zip
[housekeep] deleted 20240814.ndjson
```

### Z poziomu kodu (mostek do gatewaya)
```python
from tools.housekeeping import run_once

run_once()  # wykona pojedyncze sprzątanie wg ENV/.env
```

> Gateway może wywoływać `run_once()` na starcie lub cyklicznie (patrz dokumentacja gatewayów / zmienne `LOGOPS_HOUSEKEEP_AUTORUN`, `LOGOPS_HOUSEKEEP_INTERVAL_SEC` po ich stronie).

### Cron (Linux)
```cron
# Codziennie o 03:15 UTC
15 3 * * * cd /ścieżka/do/logops && /usr/bin/python3 tools/housekeeping.py >> /var/log/logops-housekeep.log 2>&1
```

---

## Struktura katalogów

- `data/ingest/YYYYMMDD.ndjson` — pliki dzienne generowane przez gatewaye
- `data/archive/YYYYMMDD.zip` — archiwa (gdy `LOGOPS_ARCHIVE_MODE=zip`)

---

## Najczęstsze pytania (FAQ)

**Q:** Co jeśli katalog `LOGOPS_SINK_DIR` nie istnieje?
**A:** Skrypt wypisze informację i zakończy się bez błędu.

**Q:** Czy housekeeping usuwa logi z Loki/Grafana?
**A:** Nie. Dotyka **tylko plików** NDJSON na dysku. Dane już wciągnięte do Loki pozostają niezależne.

**Q:** Czy obsługiwane są pliki o innych nazwach?
**A:** Nie. Tylko `YYYYMMDD.ndjson` (inne są pomijane).

**Q:** Czy archiwum jest „appendowane”?
**A:** Tak. Dla danego dnia skrypt dopisze zawartość do `YYYYMMDD.zip` (tryb `'a'`), a potem usunie oryginał.

---

## Przykłady konfiguracji

**Dev lokalnie, minimum:**
```env
LOGOPS_SINK_DIR=./data/ingest
LOGOPS_RETENTION_DAYS=7
LOGOPS_ARCHIVE_MODE=delete
```

**Trzymaj 30 dni i archiwizuj:**
```env
LOGOPS_SINK_DIR=./data/ingest
LOGOPS_RETENTION_DAYS=30
LOGOPS_ARCHIVE_MODE=zip
```

---

## Bezpieczeństwo i idempotencja

- Operacja jest **idempotentna** względem pojedynczego przebiegu — pliki spełniające kryterium zostaną usunięte/zarchiwizowane raz.
- Skrypt działa na podstawie **nazwy pliku** (daty w nazwie), a nie mtime — to gwarantuje jednoznaczność.
- Działa w **UTC**, więc nie jest wrażliwy na lokalne strefy czasu.

---
