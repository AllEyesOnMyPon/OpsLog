# OpsLog Dev Journal

---

## Day 0 

---

### Struktura repo

**Cel:** *przygotować pusty szkielet repozytorium pod projekt* **LogOps**.

**Kroki i ścieżki:**

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground> cd logops
PS C:\Users\kleme\Documents\Github\dev_playground\logops> git init
Initialized empty Git repository in C:/Users/kleme/Documents/Github/dev_playground/logops/.git/
```

➡️ Zainicjowałem puste repozytorium Git w folderze `logops`.

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground\logops> mkdir -p services/ingest-gateway
PS C:\Users\kleme\Documents\Github\dev_playground\logops> mkdir infra/docker
PS C:\Users\kleme\Documents\Github\dev_playground\logops> mkdir docs
PS C:\Users\kleme\Documents\Github\dev_playground\logops> mkdir tests/unit
```

➡️ Utworzyłem katalogi na serwisy, infrastrukturę, dokumentację i testy.

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground\logops> ni README.md
PS C:\Users\kleme\Documents\Github\dev_playground\logops> ni .gitignore
```

➡️ Utworzyłem puste pliki `README.md` i `.gitignore`.

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground\logops> git add .
PS C:\Users\kleme\Documents\Github\dev_playground\logops> git commit -m "init: scaffold repo"
```

➡️ Pierwszy commit ze strukturą repozytorium.

### Lokalne środowisko Pythona

**Cel**: *przygotować izolowane środowisko .venv i zainstalować paczki dla gateway’a*.

**Kroki i ścieżki**:

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground\logops> py -m venv .venv
```

➡️ Utworzyłem środowisko wirtualne .venv w folderze projektu.

```powershell
PS C:\Users\kleme\Documents\Github\dev_playground\logops> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
PS C:\Users\kleme\Documents\Github\dev_playground\logops> .venv\Scripts\Activate.ps1
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops>
```

➡️ Tymczasowo zezwoliłem na uruchamianie skryptów PowerShell **tylko dla tej sesji**. Dzięki temu nie zmieniam globalnych ustawień systemu.

➡️ Aktywowałem środowisko `.venv` i od teraz wszystkie polecenia `pip`/`python` działają wewnątrz tego projektu.

```powershell
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops> .\.venv\Scripts\python.exe -m pip install --upgrade pip
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops> .\.venv\Scripts\python.exe -m pip --version
pip 25.2 from ... (python 3.9)
```

➡️ Zaktualizowałem pip wewnątrz środowiska.

```powershell
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops> .\.venv\Scripts\python.exe -m pip install fastapi uvicorn pydantic[dotenv] requests
```

➡️ Zainstalowałem paczki dla gateway’a:

- fastapi – framework,
- uvicorn – serwer,
- pydantic – walidacja danych,
- requests – klient HTTP.

```powershell
WARNING: pydantic 2.x does not provide the extra 'dotenv'
# Instalacja:
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops> .\.venv\Scripts\python.exe -m pip install python-dotenv

```
➡️ Wersja 2.x Pydantic nie obsługuje już `[dotenv]`, więc doinstalowałem osobno python-dotenv.

```powershell
(.venv) PS C:\Users\kleme\Documents\Github\dev_playground\logops> .\.venv\Scripts\python.exe -m pip freeze > services/ingest-gateway/requirements.txt
```
➡️ Zapisałem wszystkie zależności do `requirements.txt`, żeby zawsze dało się odtworzyć środowisko.

### FastAPI Ingest Gateway

**Cel**: *tworzenie pliku* `services/ingest_gateway/gateway.py` *a w nim początkowo tylko* `FastAPI` *z* `/healthz`.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```

1. **Pierwszy run serwera:**

```lua
.venv\Scripts\python.exe -m uvicorn services.ingest_gateway.gateway:app --reload --port 8080
```
✅ `/healthz` zwrócił `{ "status": "ok" }`.

2. **Próba POST → błąd walidacji**

Próba wysłania JSON:
```bash
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs `
  -ContentType 'application/json' `
  -Body '{"msg":"hello"}'
```

❌ Błąd:

```json
{"detail":[{"type":"missing","loc":["query","payload"],"msg":"Field required"}]}
```
Przyczyna: endpoint w `gateway.py` miał argument `payload` jako query param, a nie body.

3. **Refactor endpointu na body**

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    payload = await request.json()
    return {"accepted": len(payload) if isinstance(payload, list) else 1}
```
4. **Testy `irm`**

- Pojedyńczy log:
```bash
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs `
  -ContentType 'application/json' `
  -Body '{"msg":"hello"}'
```
✅ Odpowiedź:
```powershell
accepted ts
-------- --
       1 2025-08-19T17:31:46.957050+00:00
```
- Lista logów
```bash
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs `
  -ContentType 'application/json' `
  -Body '[{"msg":"a"},{"msg":"b"}]'
```
✅ Odpowiedź:
```powershell
accepted ts
-------- --
       2 2025-08-19T17:31:53.936677+00:00
```
5. **Próby `curl.exe` — problemy**
- Manualny JSON
```powershell
curl.exe -s -X POST "http://127.0.0.1:8080/v1/logs" `
  -H "Content-Type: application/json" `
  --data-raw "{\"msg\":\"hello\"}"
```
❌ Rezultat: `Internal Server Error`

Przyczyna: PowerShell + `curl.exe` źle parsują i mieszają stringi (escapowanie).

- Zmienna
```powershell
$one = "{""msg"":""hello""}"
curl.exe -s -X POST "http://127.0.0.1:8080/v1/logs" `
  -H "Content-Type: application/json" `
  --data-raw $one
```
❌ Rezultat: `Internal Server Error`

Przyczyna: JSON przesyłany z niepoprawnym quotingiem (serwer wyrzuca `JSONDecodeError`).

- STDIN (nasza próba z `@-`)
```powershell
@{ msg = "hello" } |
  ConvertTo-Json -Compress |
  curl.exe -s -X POST "http://127.0.0.1:8080/v1/logs" `
    -H "Content-Type: application/json" `
    --data-binary @-
```
❌ W PowerShell → `Unrecognized token '@-'`

W Bash/Linux by zadziałało, ale w PowerShell jest parser error.

6. Decyzja → używamy irm

✔️ `Invoke-RestMethod` (`irm`) jest natywny dla PowerShell, działa **bez kombinacji z escapowaniem**.

✔️ Obsługuje JSON z **ConvertTo-Json**, więc payload może być budowany dynamicznie:
```powershell
@{ msg = "hello" } | ConvertTo-Json -Compress |
  irm -Method Post -Uri http://127.0.0.1:8080/v1/logs `
    -ContentType 'application/json' `
    -Body $_
```
`curl.exe` zostaje tylko do:

cross-platform scriptów (Linux/Mac + Windows)

testów z pliku (``--data-binary "@file.json"``)

**Podsumowanie**
- **Początkowy błąd**: FastAPI traktował payload jako query param → naprawione przez request.json().

- `irm` **działa od razu**: proste wysyłanie pojedynczego JSON i listy.

- `curl.exe` **w PowerShell = problemy**: escapowanie stringów i STDIN trudne do użycia.

- **Decyzja:**

    - w PowerShell → irm (proste i natywne)

    - w cross-platform → `curl --data-binary` z plikiem/STDIN

## Day 1

➡️**Cel**: Gateway: normalizacja + liczniki + poprawa logowania

**Ścieżka robocza**:
`C:\Users\kleme\Documents\Github\dev_playground\logops`

**Zmiany w kodzie**:

`services\ingest_gateway\gateway.py` — endpoint `/v1/logs` czyta surowe body (`Request.json()`),

normalizacja pól do: `ts / level / msg`,

liczniki: `missing_ts` i `missing_level`,

logger zamiast `print()`.

**Start serwera (okno A)**:
```powershell
cd C:\Users\kleme\Documents\Github\dev_playground\logops
.\.venv\Scripts\python.exe -m uvicorn services.ingest_gateway.gateway:app --reload --reload-dir .\services\ingest_gateway --port 8080
```
**Testy (okno B)**:
```powershell
cd C:\Users\kleme\Documents\Github\dev_playground\logops

# health
irm http://127.0.0.1:8080/healthz

# batch minimalny (PS-native JSON)
$batch = @(@{ msg = "a" }, @{ msg = "b" }) | ConvertTo-Json -Compress
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs -ContentType 'application/json' -Body $batch
```
**Oczekiwane**:

- Odpowiedź API (okno B): `{"accepted":2,"ts":"...","missing_ts":2,"missing_level":2}`

- Log serwera (okno A): `INFO gateway: [ingest] accepted=2 missing_ts=2 missing_level=2`

**Notatka**:
W PowerShell używamy `Invoke-RestMethod (irm)` — stabilnie przekazuje JSON; `curl.exe` łatwo „psuje” cudzysłowy.

➡️**Cel**:Emiter „server-style” (`emit_json`)

**Plik**: `emitters\emitter_json\emit_json.py`

**Uruchomienie (z katalogu projektu):**
```powershell
cd C:\Users\kleme\Documents\Github\dev_playground\logops
.\.venv\Scripts\python.exe .\emitters\emitter_json\emit_json.py -n 10 --partial-ratio 0.3
```
**Oczekiwane (w oknie emitera):**
```powershell
status: 200
body: {"accepted":10,"ts":"...","missing_ts":X,"missing_level":Y}
```
**Dlaczego tak:**
Ten emiter ma generować „serwerowy” JSON z polami typu `timestamp/level/message/....` Część rekordów z brakami (`--partial-ratio`) testuje normalizację i liczniki.

➡️**Cel**: Emiter „minimal” (`emit_minimal.py` *:tylko msg*)

**Plik**: `emitters\emitter_minimal\emit_minimal.py`

**Uruchomienie (z katalogu projektu):**
```powershell
cd C:\Users\kleme\Documents\Github\dev_playground\logops
.\.venv\Scripts\python.exe .\emitters\emitter_minimal\emit_minimal.py -n 10
.\.venv\Scripts\python.exe .\emitters\emitter_minimal\emit_minimal.py -n 25
```
**Oczekiwane (emiter)**:
```powershell
status: 200
body: {"accepted":25,"ts":"...","missing_ts":25,"missing_level":25}
```

**Oczekiwane (log serwera)**:
```powershell
INFO gateway: [ingest] accepted=25 missing_ts=25 missing_level=25
```

**Uwagi:**
Ten emiter świadomie nie wysyła `ts` ani `level`, żeby zobaczyć, że gateway uzupełnia `ts` i mapuje `level` domyślnie.

➡️**Cel**: Porządki: usunięcie starego folderu i wypchnięcie zmian

**Usunięcie starego katalogu (myślnik → podkreślnik):**
```powershell
cd C:\Users\kleme\Documents\Github\dev_playground\logops
Remove-Item -Recurse -Force .\services\ingest-gateway
```
**Commit + push:**
```powershell
git status
git add .
git commit -m "cleanup: remove old ingest-gateway, update ingest_gateway, add emitter_json, add emitter_minimal"
git push origin main
```
**Dlaczego tak:**
Python importuje pakiety z podkreślnikami -(`ingest_gateway`). Stary katalog z myślnikiem potrafił mylić reloader.

**✅ Stan na koniec**

- Gateway: `/healthz`, `/v1/logs` (normalizacja + liczniki + logger).

- Emitery: `emitter_json` (server-style), `emitter_minimal` (only msg).

- Repo: posprzątane (`ingest_gateway` jako jedyny katalog usługi), zmiany wypchnięte na main.

➡️**Cel**: Różnorodne emitery + rozszerzenia gateway

Pokryć **typowe style** logów spotykane w projektach:

- **Ustrukturyzowany JSON** `emit_json.py` (aplikacje/serwisy) ✅,

- **Tylko msg** `emit_minimal.py` (skrypt, log biblioteki) ✅,

- **Linie tekstowe** `emit_syslog.py` (syslog) ❌,

- **CSV** `emit_csv.py` (eksporty/ETL) ❌,

- **„Szum”** `emit_noise.py` (chaotyczne i niejednorodne rekordy spotykane w integracjach) ❌.

Dzięki temu gateway musi umieć **rozpoznać format, wyciągnąć kluczowe pola i znormalizować** je do wspólnego schematu `ts/level/msg`, raportując jednocześnie braki (`missing_ts`, `missing_level`).

**Zmiany w gateway (przegląd)**

- Dodano obsługę formatów wejściowych:

    - `application/json` — obiekt lub lista obiektów,

    - `text/plain` — wielolinijkowe logi w stylu syslog (parser linii),

    - `text/csv` — CSV z nagłówkiem (np. `ts,level,msg`).

- Utrzymano normalizację do `ts` / `level` / `msg` + liczniki braków.

- Ulepszono logowanie (logger zamiast `print`).

- Wersjonowanie w `/healthz`:

    - `v5-text-support` (po dodaniu `text/plain`),

    - `v6-csv-support` (po dodaniu `text/csv`).

### Emitery (dlaczego te typy + jak testowałem)

1. **`emitter_json` — „server-style” JSON**

**Dlaczego**: To najczęstszy format z aplikacji (API, mikroserwisy).

**Plik**: `emitters\emitter_json\emit_json.py`

**Test**: Robiony wcześniej w dzienniku⬆️

2. **`emitter_minimal` — tylko msg**

**Dlaczego**: Minimalny przypadek z reala (np. prosty skrypt lub log z biblioteki), testuje uzupełnianie braków.

**Plik**: `emitters\emitter_minimal\emit_minimal.py`

**Test**: Robiony wcześniej w dzienniku⬆️

3. **`emitter_syslog` — linie tekstowe (legacy/syslog-like)**

**Dlaczego**: Wiele starszych systemów wypisuje logi jako linie tekstowe (`syslog`). To wymusza parser linii po stronie gateway.

**Plik**: `emitters\emitter_syslog\emit_syslog.py`

Wymagane w gateway: wsparcie `text/plain` + regex parser.

**Test**:
```powershell
.\.venv\Scripts\python.exe .\emitters\emitter_syslog\emit_syslog.py -n 15 --partial-ratio 0.4
```
**Oczekiwane**: `200 OK`, sensowne liczniki braków (część linii celowo „uboga”).

4) **`emitter_csv` — CSV (`ts`,`level`,`msg`)**

**Dlaczego**: CSV bywa formatem wymiany (eksporty, ETL). Łatwy do manualnego generowania, ale wymaga parsera.

**Plik**: `emitters\emitter_csv\emit_csv.py`

**Wymagane w gateway**: wsparcie `text/csv` + `csv.DictReader`.

**Test**:
```powershell
.\.venv\Scripts\python.exe .\emitters\emitter_csv\emit_csv.py -n 12 --partial-ratio 0.4
```
**Oczekiwane**: `200 OK`, liczniki zależne od pustych kolumn.

5) **`emitter_noise` — chaos/edge cases**

**Dlaczego**: Symulacja „prawdziwego życia”: aliasy pól (`message/msg/log`), dziwne typy (`bool/int` zamiast `str`), zagnieżdżenia, braki.

**Plik**: `emitters\emitter_noise\emit_noise.py`

**Test**: 
```powershell
.\.venv\Scripts\python.exe .\emitters\emitter_noise\emit_noise.py --chaos 0.5 -n 20
```
**Oczekiwane**: `200 OK`, zwykle wyższe `missing_ts`/`missing_level`; gateway nadal zwraca spójny rezultat.

**Jak testowałem (wzorce)**

- **Zawsze 2 okna:**

    - **A: serwer** (`uvicorn ... --reload`) → logi gateway (`[ingest] accepted=... missing_ts=...`),

    - **B: emiter** → `status: 200` i `body: {...}`.

- **PowerShell**: testy JSON robiłem `Invoke-RestMethod (irm)`, bo unika problemów z cudzysłowami; dla `text/plain` i `text/csv` ustawiałem odpowiedni `Content-Type`.

- `/healthz`: kontrola wersji gateway po każdym patchu (np. `v5-text-support`, `v6-csv-support`).

**✅ Stan na teraz:**

- **Gateway**: `/healthz`, `/v1/logs` z obsługą `application/json`, `text/plain`, `text/csv`; normalizacja `ts/level/msg` + liczniki braków; logger.

- **Emitery**:

    - `emitter_json` (server-style),

    - `emitter_minimal` (only `msg`),

    - `emitter_syslog` (linie tekstowe),

    - `emitter_csv` (CSV z nagłówkiem),

    - `emitter_noise` (chaotyczne rekordy).

- **Repo**: aktualne, posprzątane, wszystkie testy przeszły lokalnie.

### **📌 Wdrożenie szyfrowania danych wrażliwych (PII) – `wersja v7-pii-encryption`**

1. **Cel**

Dodanie maskowania oraz szyfrowania danych wrażliwych (PII), takich jak adresy e-mail i adresy IP, w systemie LogOps.
Maskowanie służy do logów/analityki, natomiast szyfrowanie zapewnia bezpieczne przechowywanie surowych danych.

2. **Implementacja**

Dodano obsługę konfiguracji w `.env`:

```ini
LOGOPS_SECRET_KEY=...         # klucz Fernet
LOGOPS_ENCRYPT_PII=true       # włączenie szyfrowania
LOGOPS_ENCRYPT_FIELDS=user_email,client_ip
LOGOPS_DEBUG_SAMPLE=true
LOGOPS_DEBUG_SAMPLE_SIZE=3
```
- Zaimplementowano:

    - **Maskowanie** emaili (`u***@example.com`) i IP (`83.11.x.x`).

    - **Szyfrowanie Fernet** dla pól wskazanych w `LOGOPS_ENCRYPT_FIELDS` oraz całej wiadomości (`msg`).

    - Dodanie zaszyfrowanych wersji pól z sufiksem `_enc` (np. `user_email_enc`).

- Rozszerzono normalizację rekordów tak, aby zawsze zwracała:

    - `msg` – zamaskowany,

    - `msg_enc` – zaszyfrowany,

    - `user_email` / `client_ip` – zamaskowane,

    - `user_email_enc` / `client_ip_enc` – zaszyfrowane.

3. **Napotkany problem: `.env` z BOM**

Podczas testów API pojawiał się komunikat:

```powershell
PII encryption enabled but no LOGOPS_SECRET_KEY set; disabling encryption.
```
Mimo że `.env` zawierał prawidłowy wpis `LOGOPS_SECRET_KEY=...`.

Po diagnostyce okazało się, że plik `.env` został zapisany z **UTF-8 BOM**:

4. **Diagnostyka**

Główny katalog `LogOps`:
```powershell
Get-Content .\.env -Encoding Byte -TotalCount 16
```
➡️ Pokazuje pierwsze bajty pliku (tu 16 sztuk), wyświetla liczby dziesiętne, np. `239 187 191 76 79 71 ...`.

```powershell
Get-Content .\.env -Encoding Byte -TotalCount 16
```
➡️ Pokazuje linie „jak leci” (żeby wykluczyć literówki/spacje)

**Jak rozróżnić najczęstsze UTF-y po bajtach (BOM)**

| Kodowanie         | Sygnatura na początku pliku (BOM) | Bajty dziesiętne   | Jak to rozpoznać w praktyce |
|-------------------|-----------------------------------|--------------------|-----------------------------|
| **UTF-8 bez BOM** | brak                              | np. `76 79 71`     | Najlepsze dla `.env`. Brak dodatkowych bajtów z przodu. |
| **UTF-8 z BOM**   | `EF BB BF`                        | `239 187 191`      | `python-dotenv` może nie widzieć pierwszego klucza (BOM dokleja się do nazwy). |
| **UTF-16 LE**     | `FF FE`                           | `255 254`          | Każda litera ma „0” obok: np. `76 0 79 0 71 0...`. |
| **UTF-16 BE**     | `FE FF`                           | `254 255`          | Odwrotność LE: `0 76 0 79 0 71...`. |
| **UTF-32 LE**     | `FF FE 00 00`                     | `255 254 0 0`      | Rzadka w takich plikach. |
| **UTF-32 BE**     | `00 00 FE FF`                     | `0 0 254 255`      | Rzadka. |

W tym przypadku było `239 187 191` → `UTF-8 z BOM`. Dlatego `python-dotenv` nie widział `LOGOPS_SECRET_KEY` (nazwę czytał jako `\ufeffLOGOPS_SECRET_KEY`).

**Konwersja UTF-8 z BOM -> UTF-8 bez**

- Przez .NET
```powershell
$body = Get-Content .\.env -Raw
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)  # false = bez BOM
[System.IO.File]::WriteAllText(".\.env", $body, $utf8NoBom)
```
W tym przypadku plik byl zablokowany więc `WriteAllText` pod nazwa `.env.novbom`, `Remove` `.env` i `Rename` `.envnobom` na `.env`
```powershell
[System.IO.File]::WriteAllText(".\.env.nobom", $body, $utf8NoBom)
Remove-Item .\.env
Rename-Item .\.env.nobom .env
```
- Testy po konwersji:

🔎 Sprawdzam czy BOM zniknął:

```powershell
Get-Content .\.env -Encoding Byte -TotalCount 3   # powinno NIE być 239 187 191
```
🔎 Sprawdzam przez Gateway:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.ingest_gateway.gateway:app --reload --port 8080
irm http://127.0.0.1:8080/healthz
# oczekuj: pii_encryption : True
```
- **Dlaczego to miało znaczenie dla `.env`**

    - BOM (np. `EF BB BF`) „przykleja się” do **pierwszego klucza** w pliku.

    - Biblioteka `python-dotenv` widzi wtedy zmienną o nazwie `\ufeffLOGOPS_SECRET_KEY` zamiast `LOGOPS_SECRET_KEY`.

    - Efekt: kod myśli, że **sekret nie istnieje** → szyfrowanie wyłączone.

**ℹ️Ciekawostka**

Po `load_dotenv(...)` można dodać krótki log:
```python
import os
print("DEBUG env:", os.getenv("LOGOPS_SECRET_KEY"), os.getenv("LOGOPS_ENCRYPT_PII"))
```
Jeśli `LOGOPS_SECRET_KEY` jest `None`, a wiesz, że jest w pliku, to pierwsze co sprawdzasz — **BOM**.

5. **Testy końcowe**:

**Health check**
```powershell
irm http://127.0.0.1:8080/healthz
```
✅ Wynik:
```powershell
status version           pii_encryption
------ -------           --------------
ok     v7-pii-encryption           True
```

**Test danych wejściowych**
```powershell
$batch = @(
  @{ message = "login ok user=user1@example.com from 83.11.22.33"; level = "info"; user_email="user1@example.com"; client_ip="83.11.22.33" },
  @{ msg = "fatal error for user2@example.com from 10.1.2.3" }
) | ConvertTo-Json -Compress

$res = irm -Method Post -Uri http://127.0.0.1:8080/v1/logs -ContentType 'application/json' -Body $batch
$res
```
✅ Wynik:

- `msg` zamaskowany (`u***@example.com`, `83.11.x.x`).

- `msg_enc`, `user_email_enc`, `client_ip_enc` – zaszyfrowane wartości.

- `user_email`, `client_ip` – zamaskowane do analityki.

- Brak błędów, `accepted=2`.


**6. Podsumowanie**


- **Problem**: `.env` z BOM uniemożliwiał odczyt LOGOPS_SECRET_KEY.

- **Rozwiązanie**: zapis pliku `.env` w czystym UTF-8 bez BOM.

- **Efekt**: szyfrowanie PII aktywne, testy potwierdziły maskowanie + szyfrowanie.

- **Dalsze kroki**:

    - Rotacja klucza `LOGOPS_SECRET_KEY` wg polityki bezpieczeństwa.

    - Wyłączenie `LOGOPS_DEBUG_SAMPLE` w produkcji.

    - Opcjonalny endpoint `/debug/decrypt` do lokalnego testu odszyfrowania.

## Day 2

### Housekeeping (retencja/archiwizacja)

**Cel**: Dodać lekki moduł housekeeping, który automatycznie sprząta dzienne pliki NDJSON z katalogu `data/ingest` zgodnie z retencją. Opcjonalnie archiwizuje stare pliki do ZIP.

**1. Skrypt narzędziowy**

Dodano `tools/housekeeping.py`:

- czyta konfigurację z `.env` (`LOGOPS_RETENTION_DAYS`, `LOGOPS_ARCHIVE_MODE`, `LOGOPS_SINK_DIR`),

- dla plików `YYYYMMDD.ndjson` porównuje datę z retencją,

- tryb `delete`: usuwa pliki starsze niż N dni,

- tryb `zip`: pakuje plik do `data/archive/YYYYMMDD`.zip, potem usuwa źródło,

- eksportuje `run_once()` – „mostek” do wywołania z gatewaya.

**2. Mostek w gateway (autorun przez lifespan)**

W `services/ingest_gateway/gateway.py`:

- uruchamianie housekeeping **raz przy starcie** (`LOGOPS_HOUSEKEEP_AUTORUN=true`),

- (opcjonalnie) pętla **okresowa** co N sekund `(LOGOPS_HOUSEKEEP_INTERVAL_SEC>0`),

- logi w konsoli, np.:

    - `[housekeep] run_once at startup done`

    - `[housekeep] deleted 20250818.ndjson`

    - [`housekeep] archived 20250818.ndjson` -> `20250818.zip`

**3. Konfiguracja `.env` (fragment)**:
```ini
# File sink
LOGOPS_SINK_FILE=true
LOGOPS_SINK_DIR=./data/ingest

# Housekeeping (lifecycle)
LOGOPS_RETENTION_DAYS=2
LOGOPS_ARCHIVE_MODE=delete   # delete | zip

# Autorun (gateway lifespan)
LOGOPS_HOUSEKEEP_AUTORUN=true
LOGOPS_HOUSEKEEP_INTERVAL_SEC=0   # 0 = tylko na starcie; np. 3600 = co godzinę
```
**Jak to działa w praktyce**

1. **Zapis dobowy**: gateway zapisuje znormalizowane logi do `data/ingest/YYYYMMDD.ndjson`.

2. **Sprzątanie**: przy starcie gatewaya (i ewentualnie cyklicznie) uruchamia się housekeeping:

    - identyfikuje pliki „przeterminowane” względem `LOGOPS_RETENTION_DAYS`,

    - **usuwa** (delete) lub **archiwizuje** (zip),

    - loguje akcje w konsoli.

## Day 3

### Obserwowalność w środowisku Docker 

**Cel:** Zbudowanie podstawowego stacku monitoringowo-logowego w oparciu o cztery komponenty:

- Promtail – agent zbierający logi NDJSON z katalogu projektu, parsujący je i wysyłający do Loki,

- Loki – magazyn logów zoptymalizowany pod query w Grafanie,

- Prometheus – zbiera metryki z logops gatewaya (liczniki accepted/missing itp.) oraz obsługuje reguły alertowe,

- Grafana – dashboardy dla logów i metryk.

- Zmiana struktury katalogów. Wcześniej wszystkie configi były w `infra/docker/`. Wprowadzilem bardziej uporządkowaną strukturę:

```markdown
infra/
└── docker/
    ├── docker-compose.yml
    ├── prometheus/
    │   ├── prometheus.yml
    │   └── alert_rules.yml
    ├── loki/
    │   └── loki-config.yml
    └── promtail/
        └── promtail-config.yml
```
Dzięki temu każdy serwis ma swój własny katalog, a `docker-compose.yml` jedynie montuje pliki konfiguracyjne.

**Kluczowe implementacje:**

**1. Promtail**

- ustawienie `positions.filename: /var/lib/promtail/positions.yaml` i podmontowaliśmy wolumen `promtail-data` → offsety są utrwalane między restartami, więc nie ma re-ingestu starych linii,

- dodanie `start_position`: end → agent zaczyna czytać od końca pliku,

- `pipeline_stages` parsuje NDJSON, mapuje `ts`, `level`, `msg`, `emitter`, a resztę wysyła jako payload.

**2. Loki**

- przeniesiony config do `infra/docker/loki/`,

- problemy z błędnym polem `path` w configu → poprawione, serwis startuje czysto,

- dane trzymane w wolumenie `loki-data`.

**3. Prometheus**

skonfigurowany do scrapowania `logops_gateway` i `self-metrics` innych serwisów,

- dołączony plik `alert_rules.yml` (pusty),

umożliwione **reloady** configu via `irm -Method Post http://localhost:9090/-/reload`.

**4. Grafana**

- postawione podstawowe dashboardy:

  - **Overview (Prometheus)** – statystyki accepted/missing, inflight,

  - **Trends (Loki)** – count_over_time wg levela,

  - **Emitters** – rozbicie po polu emitter,

  - **Raw logs / Live tail** – podgląd bieżących logów.

### Obserwowalność - problemy i fixy

- **Promtail nie startował – pomyłka: `promtail-config.yaml` vs `.yml`.**

  Rozwiązanie: usunięcie duplikatu, spójne `.yml`.

- **Loki wyrzucał błędy `failed to load chunk … no such file` przy starych danych.**
  
  Rozwiązanie: czyszczenie wolumenu i ponowny start.

- **Brak świeżych logów w Grafanie – różnica czasu (PL vs UTC).**
  
  Rozwiązanie: timestampy w NDJSON są w UTC, Grafana też → problem leżał w offsetach, naprawione po prawidłowym ustawieniu `positions` i s`tart_position`.

- **„No volume available” w panelach – Promtail nie miał wolumenu na offsety.**

  Dodaliśmy wolumen `promtail-data:/var/lib/promtail`.

**Efekt**
- End-to-end pipeline działa: logi NDJSON → Promtail → Loki → Grafana.

- Prometheus zbiera metryki i rejestruje alerty.

- Dashboardy w Grafanie pokazują już dane live (Overview + Trends + Raw logs).

### Alerty Prometheus `alert_rules.yml`

**Cel:** Automatyczne wykrywanie anomalii w strumieniu logów.

**1. Struktura plików**

- Alerty umieszczone w:
```bash
infra/docker/prometheus/alert_rules.yml
```
- Dodanie sekcji do `prometheus.yml`:
```bash
rule_files:
  - /etc/prometheus/alert_rules.yml
```
- Reload konfiguracji:
```powershell
irm -Method Post http://localhost:9090/-/reload
```
**2. Zainicjowane reguły:**

**LogOpsGatewayDown**


  - Expr: `up{job="logops_gateway"} == 0`

  - For: **1m**

  - Severity: **critical**

👉 Wykrywa, że gateway w ogóle nie odpowiada na scrape.

⚡ Parametr `for: 1m` chroni przed chwilowymi timeoutami.


**LogOpsNoIngest5m**


- Expr: `increase(logops_accepted_total[5m]) <= 0`

- For: **2m**

- Severity: **warning**

👉 Alarmuje, jeśli w oknie **5 minut** nie ma ani jednego przyjętego logu.

⚡ Praktyczne do wykrycia całkowitej przerwy w **ingest**.

**LogOpsLowIngest**


- Expr: `rate(logops_accepted_total[5m]) < 0.2`

- For: **5m**

- Severity: **info**

👉 Wskazuje, że pipeline „tli się” – średnio **<0.2 loga/s**.

⚡ Informacyjny – nie jest to awaria, ale sygnał podejrzanie niskiego ruchu.

**LogOpsHighIngestBurst**


- Expr: `rate(logops_accepted_total[1m]) > 20`

- For: **1m**

- Severity: **warning**

👉 Wykrywa nagłe wzrosty ruchu (**≥20 logów/s**).

⚡ Może sygnalizować sztorm błędów, pętlę w aplikacji, albo **flood/DDoS**.

**LogOpsHighMissingTS**


- Expr: przy **≥100 logach w 5m**, odsetek brakujących **TS > 20%**

- For: **2m**

- Severity: **warning**

👉 Wykrywa, że sporo logów nie ma pola `ts`.

⚡ Dolny próg (**20%**) daje wczesne ostrzeżenie, ale wymaga też min. **100 logów** (żeby uniknąć fałszywych alarmów przy małej próbce).

**LogOpsVeryHighMissingTS**

- Expr: przy **≥200** logach w 5m, odsetek braków TS > **50%**

- For: **2m**

- Severity: **critical**

👉 Eskalacja alertu z punktu `LogOpsHighMissingTS`.

⚡ Wysoki próg (**50%**) i większa liczba logów (**200**) → **alarm krytyczny**, oznacza masowe problemy z pipeline.

**LogOpsHighMissingLevel**


- Expr: analogiczne do (`LogOpsHighMissingTS`), ale dla pola level.

- For: **2m**

- Severity: **warning**

👉 Ostrzega, gdy **≥20%** logów nie ma poziomu (**INFO/ERROR/WARN/DEBUG**).

**LogOpsVeryHighMissingLevel**


Expr: analogiczne do `LogOpsVeryHighMissingTS`, ale dla pola `level`.

For: **2m**

Severity: **critical**

👉 Krytyczny wariant dla braków pola `level`.

**LogOpsInflightStuckHigh**


Expr: `logops_inflight > 5`

For: **2m**

Severity: **warning**

👉 Monitoruje **gauge „in-flight”** (np. liczba logów w kolejce).

⚡ Jeśli **>5** przez **≥2** minuty → backpressure, przetwarzanie się zapycha.

**LogOpsMetricsAbsent**


Expr: `absent(up{job="logops_gateway"})`

For: **2m**

Severity: **critical**

👉 **Fallback** – jeśli Prometheus całkowicie przestaje widzieć metryki z gatewaya.

⚡ Rozszerza alert nr 1 (nie tylko „0”, ale brak danych w ogóle).

### **Podsumowanie**

- Mamy pokrycie **dostępności** (GatewayDown, MetricsAbsent).

- Mamy pokrycie **wolumenu ruchu** (NoIngest, LowIngest, HighIngestBurst).

- Mamy kontrolę **jakości logów** (MissingTS, MissingLevel – wariant warning i critical).

- Mamy kontrolę **kolejki** (Inflight).

To daje nam **pełne minimum observability**: wykryjemy brak ruchu, anomalie ruchu, błędy w danych i problemy systemowe.

### Rozdzielenie requirements na produkcyjne i developerskie

**Tworzenie dwóch zestawów plików wymagań:**

- `services/ingest_gateway/requirements.txt` – pakiety potrzebne do uruchomienia gateway’a (produkcja).

  Zawiera m.in.:

  - `fastapi`, `uvicorn` → serwer API,

  - `python-dotenv` → konfiguracja środowiska,

  - `cryptography` → obsługa szyfrowania,

  - `prometheus-client` → eksport metryk,

  - `requests` → komunikacja HTTP.


- `requirements-dev.txt` (root repo) – pakiety przydatne do developmentu i testów.

  Zawiera m.in.:

  - `black`, `ruff` → formatowanie i linting,

  - `mypy` → typowanie,

  - `pytest`, `pytest-asyncio` → testy,

  - `httpx` → testy API.

**Cel:** 
- Oddzielić to, co **niezbędne do działania** usługi, od narzędzi developerskich.

- Dzięki temu kontenery produkcyjne będą lżejsze i prostsze w utrzymaniu, a jednocześnie mamy pełne wsparcie narzędzi w środowisku developerskim.

**Efekt**:

- **Czystszy podział obowiązków:** gateway nie ciągnie za sobą zbędnych paczek.

- **Lepsza kontrola zależności:** łatwo sprawdzić, co jest „core”, a co jest tylko „dev tooling”.

Przygotowane do automatyzacji buildów (np. Dockerfile może używać tylko `requirements.txt` z katalogu usługi).

## Day 4-5 

2025/08/23-24 – Dokumentacja i Structurizr

Uporządkowałem strukturę dokumentacji w projekcie **LogOps**.  
Zasada jest prosta: główny `README.md` w root to **mapa projektu** i szybki start, a wszystkie szczegóły są rozbite na osobne pliki w `docs/`.  

- `overview.md` → przegląd projektu, co jest in scope / out of scope  
- `quickstart.md` → jak uruchomić środowisko krok po kroku  
- `infra.md`, `observability.md` → szczegóły Dockera, Prometheus, Grafana, Loki, Promtail  
- `services/` → opis Gatewaya i emiterów (każdy emiter ma własny README)  
- `tools/housekeeping.md` → osobny opis skryptu czyszczącego archiwalne NDJSON  
- `architecture.md` → diagramy C4 (C1, C2, C3)  

Dzięki temu unikam ściany tekstu – każdy moduł ma swoje miejsce i można łatwo znaleźć potrzebne info.

Dodatkowo uruchomiłem **Structurizr Lite** w kontenerze Dockera.  
Za jego pomocą zdefiniowałem model w DSL (`workspace.dsl`) i wyeksportowałem diagramy C1–C3 do PNG.  
Teraz w `architecture.md` są podlinkowane gotowe obrazki (`c1.png`, `c2.png`, `c3.png`), więc całość jest czytelna również w repo na GitHubie bez uruchamiania Structurizr.

Wnioski: **docs muszą żyć równolegle z projektem nie jako uzupełnienie bo łatwo sie zgubić w miarę skalowania.**





