# v0.1 - Initial Scaffold & Gateway Basics
## ROBLEM 1- `POST /v1/logs` nie przyjmował JSON (422/500)

**Objawy**:

- `POST /v1/logs` zwracał 422 lub 500 przy poprawnym JSON.

**Przyczyna**:

- W handlerze czytaliśmy `request.query_params`/`request.body()` zamiast `await request.json()`.

- Dla application/json `FastAPI`/`Uvicorn` oczekuje dekodowania strumienia do obiektu Python via `await request.json()`.

**Jak odtworzyć**:
```bash
curl -s -XPOST localhost:8080/v1/logs \
  -H 'Content-Type: application/json' \
  -d '{"msg":"hi"}' -i
```
**Diagnoza**:

- Logi pokazywały puste/niezdekodowane body.

- `print(await request.body())` → bajty; brak `json.loads(...)``/request.json()`.

**Naprawa**:

- Zamiana na:
```py
payload = await request.json()   # zamiast request.body()/query_params
```
**Testy weryfikujące**:

- Jednostkowy:
```py
from fastapi.testclient import TestClient
def test_logs_accepts_json(client: TestClient):
    r = client.post("/v1/logs", json={"msg":"ok"})
    assert r.status_code == 200
```
- Ręczny: `curl` z `-H 'Content-Type: application/json'`.

**Prewencja**:

- Konwencja: dla JSON używamy zawsze `await request.json()` lub parametru `model: PydanticModel`.

## PROBLEM 2- Importy nie działały przez myślnik w nazwie pakietu

**ObjawY**:

- `uvicorn services/ingest-gateway:app` → `ModuleNotFoundError: No module named 'services.ingest-gateway'`.

**Przyczyna**:

- W Pythonie moduły/packagi muszą mieć identyfikator (litera/cyfra/`_`). Myślnik (`-`) nie jest dozwolony w nazwie importu.

**Jak odtworzyć**:

- Nazwij katalog `ingest-gateway` i próbuj `import services.ingest-gateway...` → błąd.

**Diagnoza**:

- Lint/mypy/IDE oraz stacktrace z `ModuleNotFoundError`.

**Naprawa**:

- Zmiana nazwy katalogu na `ingest_gateway` i dostosowanie importów/ścieżek:
```bash
git mv services/ingest-gateway services/ingest_gateway
```
**Testy weryfikujące**:

- `python -c "import services.ingest_gateway"` → brak błędów.

- `uvicorn services.ingest_gateway.gateway:app --reload` startuje.

**Prewencja**:

- Reguła repo: **snake_case** dla katalogów modułów Pythona.

- Pre-commit: `namecheck` (np. prosty skrypt grep/regex).
