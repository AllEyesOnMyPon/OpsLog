# `tools/hmac_curl.sh` — wygodny wrapper `curl` dla AuthGW (HMAC)

Skrypt Bash, który:
- oblicza **HMAC** (korzystając z `tools/sign_hmac.py`),
- dokłada wymagane nagłówki (`X-Api-Key`, `X-Timestamp`, `X-Content-SHA256`, `X-Signature`, opcjonalnie `X-Nonce`),
- wysyła żądanie `curl` do **Auth Gateway** (`/ingest` domyślnie),
- pozwala na pełną kontrolę: metoda, URL, body (inline/plik), debug, nagłówki.

> Wykorzystuje **tę samą kanonikalizację**, co serwerowy `HmacAuthMiddleware`.

- Plik: `tools/hmac_curl.sh`
- Wymagania: `bash`, `python` (do uruchomienia `tools/sign_hmac.py`)
- Domyślne poświadczenia: `LOGOPS_API_KEY=demo-pub-1`, `LOGOPS_SECRET=demo-priv-1`

---

## Szybki start

**Inline body (JSON) + nonce:**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello"}'
```

**Body z pliku:**
```bash
echo '{"msg":"file"}' > body.json
tools/hmac_curl.sh --nonce -f body.json
```

**GET z query (bez body):**
```bash
tools/hmac_curl.sh -X GET -u 'http://127.0.0.1:8090/ingest?dry=1' --nonce
```

**Zmienna URL/metoda/klucze (ENV):**
```bash
LOGOPS_API_KEY=demo-pub-1 LOGOPS_SECRET=demo-priv-1 \
tools/hmac_curl.sh -X POST -u 'http://127.0.0.1:8090/ingest' --nonce -d '{"msg":"x"}'
```

---

## Parametry

```
tools/hmac_curl.sh [opcje] [-- <dalsze-argumenty-dla-curl>]

-u, --url URL            Docelowy URL (dom: http://127.0.0.1:8090/ingest)
-X, --method METHOD      Metoda HTTP (dom: POST)
-k, --key KEY            X-Api-Key (dom: $LOGOPS_API_KEY lub demo-pub-1)
-s, --secret SECRET      sekret HMAC (dom: $LOGOPS_SECRET lub demo-priv-1)
-d, --data JSON          Treść body (JSON, inline). Wyklucza -f.
-f, --file PATH          Treść body z pliku (–data-binary @PATH). Wyklucza -d.
    --nonce              Dodaj nagłówek X-Nonce (zalecane/gdy require_nonce: true)
    --ts ISO8601Z        Wymuś timestamp (np. 2025-08-27T04:10:00Z)
    --ts-offset SEC      Przesuń timestamp względem teraz (np. -3600)
    --echo-headers       Tylko wypisz nagłówki HMAC, po **jednym** na linię, i wyjdź
--                        Oddzielacz — wszystko po nim trafia **bez zmian** do curl
```

**Przykład `-- echo-headers`:**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"x"}' --echo-headers
# => -H "X-Api-Key: ..." 
#    -H "X-Timestamp: ..." 
#    -H "X-Content-SHA256: ..." 
#    -H "X-Signature: ..." 
#    -H "X-Nonce: ..."
```

**Forwardowanie dodatkowych opcji do `curl`:**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"x"}' -- -i -v -D -
```

---

## Zmienne środowiskowe

| Zmienna           | Domyślnie           | Opis |
|---|---|---|
| `LOGOPS_API_KEY`  | `demo-pub-1`        | Publiczny klucz klienta |
| `LOGOPS_SECRET`   | `demo-priv-1`       | Sekret HMAC klienta |
| `LOGOPS_URL`      | *(nieużywana tutaj)*| Użyj `-u/--url` zamiast ENV (czytelniej) |

> Sekrety trzymaj poza Gitem (np. w `.env`, menedżerze sekretów lub eksporcie sesyjnym).

---

## Jak to działa (pod maską)

1. Źródło body:
   - `--file PATH` → używa `PATH`,
   - `--data JSON` → tworzy tymczasowy plik z JSON,
   - brak obu → body `{}`.
2. Wywołuje `python tools/sign_hmac.py ... --body-file <PLIK> --one-per-line`  
   aby policzyć *ten sam* `sha256(body)` i sygnaturę.
3. Przekształca linie `-H "K: V"` na tablicę `curl` i odpala:
   ```
   curl -s -X "$METHOD" "$URL" -H 'Content-Type: application/json' \
     <nagłówki HMAC> --data-binary "@<PLIK>"
   ```

---

## Przykłady scenariuszy

**Duże body (nagłówek 413 z backpressure):**
```bash
python - <<'PY'
import json
open("big.json","w").write(json.dumps({"msg":"x"*250000}))
PY
tools/hmac_curl.sh --nonce -f big.json -- --dump-header - -s -o /dev/null | sed -n '1,30p'
```

**Zbyt wiele elementów (lista > `max_items`):**
```bash
python - <<'PY'
import json
open("many.json","w").write(json.dumps([{"msg":"x"}]*1200))
PY
tools/hmac_curl.sh --nonce -f many.json -- --dump-header - -s -o /dev/null | sed -n '1,30p'
```

**Negatywny test — stary timestamp (spodziewane 401 skew):**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"old"}' --ts-offset -3600 -- -i -s -o /dev/null -w "code:%{http_code}\n" -D -
```

---

## Najczęstsze problemy

- **401 body hash mismatch** — pamiętaj, że podpis liczony jest po **dokładnych bajtach**. Dlatego wrapper zawsze używa `--data-binary @PLIK`. Nie mieszaj z `-d` (urlencode) po stronie `curl`.
- **401 bad signature** — niespójny `METHOD`/`URL`/`body`/`X-Timestamp` vs. to, co podpisano. Upewnij się, że parametry `-X`, `-u`, body i timestamp są te same przy generowaniu nagłówków i wysyłce.
- **401 timestamp skew** — serwer (HMAC MW) sprawdza `clock_skew_sec`. Używaj domyślnego czasu lub `--ts/--ts-offset`.
- **401 replay detected** — ponowne użycie `X-Nonce` przy włączonym Redis/anty-replay. Przełącz `--nonce` (generowany losowo) lub wyłącz `require_nonce` w konfigu.
- **Brak `python`** — skrypt wymaga Pythona do uruchomienia `sign_hmac.py`.

---

## Integracja z Makefile

W repo znajdziesz gotowe cele (np. `headers`, `bp-big`, `bp-many`, `smoke-authgw`), które używają tego skryptu.  
To najlepszy punkt startu do **szybkich testów E2E**.

---

## Zobacz też

- `tools/sign_hmac.py` — silnik podpisywania (kanonikalizacja)
- `services/authgw/hmac_mw.py` — serwerowa walidacja HMAC
- `docs/services/auth_gateway.md` — pełna dokumentacja AuthGW (HMAC, nonce, backpressure, RL)

```
