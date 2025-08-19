# **OpsLog — jak uruchomić gateway lokalnie (Windows/PowerShell)**
1. Uruchom serwer w bieżącej sesji:
```powershell
# 1. Przejdź do katalogu projektu
cd C:\Users\kleme\Documents\Github\dev_playground\logops

# 2. (Jednorazowo na tę sesję) odblokuj skrypty PS, jeśli trzeba
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Aktywuj wirtualne środowisko
.\.venv\Scripts\Activate.ps1

# 4. Start serwera (FastAPI/Uvicorn) z automatycznym przeładowaniem
.\.venv\Scripts\python.exe -m uvicorn services.ingest_gateway.gateway:app --reload --reload-dir .\services\ingest_gateway --port 8080
```
2. (Opcjonalnie) szybkie testy
```powershell
# healthcheck
irm http://127.0.0.1:8080/healthz

# POST – pojedynczy log
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs -ContentType 'application/json' -Body (@{ msg = "hello" } | ConvertTo-Json -Compress)

# POST – lista logów
$batch = @(@{ msg = "a" }, @{ msg = "b" }) | ConvertTo-Json -Compress
irm -Method Post -Uri http://127.0.0.1:8080/v1/logs -ContentType 'application/json' -Body $batch
```
2) Zatrzymanie i ponowne uruchomienie

```powershell
# Zatrzymanie serwera
# W oknie, w którym działa Uvicorn: naciśnij CTRL + C

# Ponowne uruchomienie (w tym samym oknie lub nowym)
cd C:\Users\kleme\Documents\Github\dev_playground\logops
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m uvicorn services.ingest_gateway.gateway:app --reload --reload-dir .\services\ingest_gateway --port 8080
```
Gdy zapiszesz plik gateway.py, Uvicorn z --reload sam wykryje zmiany i przeładuje aplikację (nie trzeba restartować).