# Housekeeping

Housekeeping odpowiada za utrzymanie katalogu z logami (`data/ingest/`).  
Jest to proces usuwania lub archiwizacji starych plików **NDJSON** generowanych przez gateway.

---

## 🔧 Konfiguracja ENV

- `LOGOPS_SINK_DIR` – katalog z plikami NDJSON (domyślnie: `./data/ingest`)  
- `LOGOPS_RETENTION_DAYS` – ile dni przechowywać logi (domyślnie: `7`)  
- `LOGOPS_ARCHIVE_MODE` – tryb dla starych plików:  
  - `delete` (domyślnie) – usuwa pliki starsze niż retention  
  - `zip` – pakuje do `./data/archive/YYYYMMDD.zip` i usuwa oryginał  
- `LOGOPS_HOUSEKEEP_AUTORUN` – (`true|false`) czy uruchomić housekeeping przy starcie gatewaya  
- `LOGOPS_HOUSEKEEP_INTERVAL_SEC` – co ile sekund powtarzać housekeeping w tle (0 = nie uruchamiaj pętli)

---

## 🖥️ Uruchamianie

### Ręczne
```bash
python tools/housekeeping.py
```
Wykona pojedyncze przejście (usunie/zarchiwizuje stare pliki NDJSON).

**Z gatewaya**

Gateway może:

- wywołać housekeeping przy starcie (`LOGOPS_HOUSEKEEP_AUTORUN=true`)

- uruchomić pętlę cykliczną (`LOGOPS_HOUSEKEEP_INTERVAL_SEC>0`)

- loguje wynik jako `[housekeep] ...` w logach aplikacji.

## Struktura

- `data/ingest/YYYYMMDD.ndjson` – logi z danego dnia (output gatewaya)

- `data/archive/YYYYMMDD.zip` – archiwum (jeśli tryb = zip)

## Efekty i wpływ

- Usunięcie/archiwizacja starych plików wpływa na dane widoczne w **Promtail/Loki** (znikają starsze logi).

- Operacja housekeeping nie dotyka danych w Prometheusie ani w Grafanie.
## Typowe scenariusze

- **Dev/test lokalny** – domyślnie retention 7 dni, tryb delete.

- **Dłuższe trzymanie logów** – ustaw `LOGOPS_RETENTION_DAYS=30` i `LOGOPS_ARCHIVE_MODE=zip` aby mieć kopie w `data/archive/`.

- **Ciągła praca gatewaya** – ustaw `LOGOPS_HOUSEKEEP_AUTORUN=true` i np. `LOGOPS_HOUSEKEEP_INTERVAL_SEC=3600` (raz na godzinę).