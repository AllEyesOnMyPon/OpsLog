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