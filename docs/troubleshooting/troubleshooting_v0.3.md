# v0.3 - CLI-first, walidacja, alerty
## PROBLEM 1- Walidacja Pydantic zwracała 500 zamiast 422

**Objawy**:

- Błędne rekordy powodowały 500.

**Przyczyna**:

- Niełapany `ValidationError` z Pydantica propagował do ASGI → 500.

**Jak odtworzyć**:

```
curl -s -XPOST :8080/v1/logs -H 'Content-Type: application/json' \
  -d '[{"msg":1},{"level":123}]' -i
```

**Diagnoza**:

- Stacktrace z `ValidationError`.

**Naprawa**:

- try/except `ValidationError` → `HTTPException(status_code=422, detail=errors).`

**Testy weryfikujące**:

- Testy `client.post(..., json=[...])` → 422.
- Metryka `logops_parse_errors_total` rośnie.

**Prewencja**:

- Handlery wyjątków (FastAPI exception_handler).
- Testy negatywne w CI.

## PROBLEM 2- `logops_parse_errors_total` nie przyrastał

**Objawy**:

- W metrykach 0, mimo błędów.

**Przyczyna**:

- Inkrementacja po walidacji „happy path”. Przy błędzie — nigdy nie wołana.

**Naprawa**:

- Przeniesienie `parse_errors_total.inc()` do bloku `except`.

**Testy weryfikujące**:

- Wysyłka `[{}, 123]` → metryka > 0.
- PromQL: `increase(logops_parse_errors_total[5m]) > 0`.

**Prewencja**:

- Zasada: liczniki błędów zwiększamy `w miejscu złapania` wyjątku.

## PROBLEM 3- make scenario-* sypały się

**Objawy**:

- make `scenario-default` nie znajdował celu / pliku.

**Przyczyna**:

- Brak wzorca `scenario-%` i spójnego targetu scenario-run.

**Naprawa**:
```make
scenario-run:
> $(PY) tools/run_scenario.py --scenario $(SCEN)

scenario-%:
> $(PY) tools/run_scenario.py --scenario scenarios/$*.yaml
```

**Testy weryfikujące**:

- `make scenario-default` → działa.

- `make scenario-spike` → działa.

**Prewencja**:

- Prosty test `make -n scenario-default` w CI.
