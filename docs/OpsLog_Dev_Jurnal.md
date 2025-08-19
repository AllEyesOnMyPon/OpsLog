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
