# v0.2 - Housekeeping & Observability
## ROBLEM 1- Housekeeping zip wolny/niepewny dla dużych plików

**Objawy**:

- Długi czas archiwizacji NDJSON, czasem time-outy w jobach.

**Przyczyna**:

- `zipfile` w Pythonie jest single-threaded; brak chunkowania i throttlingu I/O, dla bardzo dużych plików robi się wąskim gardłem.

**Jak odtworzyć**:

- Plik NDJSON >1–2 GB + tryb `zip` → długie czasy.

**Diagnoza**:

- Pomiar czasu sekcji `zipfile.ZipFile(...).write(...)`.

- Obserwacja iostat/htop – CPU 1 rdzeń przy zip.

**Naprawa**:

- Produkcyjnie używać `delete` lub zewnętrznego `zip` (asynchronicznie).

- Pozostawić `zip` jako „experimental”.

**Testy weryfikujące**:

- Uruchom housekeeping z trybem `delete` na wielu plikach – czasy akceptowalne.

**Prewencja**:

- Dodać metryki housekeeping (czas, rozmiar).
- Dokument: „zip mode = experimental”.

## PROBLEM 2- Promtail nie widział plików/offsetów

**Objawy**:

- Brak logów w Loki mimo napływu NDJSON.

**Przyczyna**:

- Brak wolumenu dla offsetów (`promtail-data`) i/lub złe `start_position`. Po restarcie Promtail „gubił” pozycję albo zaczynał od początku.

**Jak odtworzyć**:

- Uruchom stack bez volume, zrestartuj – brak nowych wpisów.

**Diagnoza**:

- `docker compose logs promtail` → file not found / 0 scraped.

**Naprawa**:

- Dodać:
```yaml
volumes:
  - promtail-data:/var/lib/promtail
scrape_configs:
  - pipeline_stages:
      - json: {…}
    positions:
      filename: /var/lib/promtail/positions.yaml
    # i start_position: end
```
**Testy weryfikujące**:

- Restart promtail → ingest kontynuowany.

- Grafana → pojawiają się świeże logi.

**Prewencja**:

- Szablon compose z domyślnym volume + `start_position: end`.

## PROBLEM 3- Alerty nie strzelały

**Objawy**:

- Brak alertów w Prometheus/Grafana mimo warunków.

**Przyczyna**:

- Złe `expr` (metryka/label), progi za wysokie/za niskie, brak `for:`.

**Jak odtworzyć**:

- Zaniż ruch, poczekaj – alert nie wchodzi.

**Diagnoza**:

- `promtool check rules`.
- PromQL w UI – czy expr w ogóle daje >0.

**Naprawa**:

- Poprawki `expr` i for: `5m`.
- Ujednolicone nazwy metryk.

**Testy weryfikujące**:

- Wymuszenie stanu (np. brak ingest) → alert firing.

**Prewencja**:

- Review metryk/labeli przy zmianach gatewaya.
- Testy reguł z promtool.