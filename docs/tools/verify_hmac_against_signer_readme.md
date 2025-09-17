# `tools/verify_hmac_against_signer.py` — weryfikator nagłówków HMAC

Konsolowe narzędzie do **sprawdzenia poprawności** podpisu HMAC przesłanych nagłówków (wczytywanych ze **STDIN**) względem **sekretu** (`LOGOPS_SECRET`) i treści body (`--body-file`).
Obsługuje **dwa style** nagłówków:
- **Obecny**: `X-Api-*` z podpisem **base64** i czasem w **ISO8601 Z**,
- **Starszy**: `X-Logops-*` z podpisem **hex** i czasem jako **epoch**.

- Plik: `tools/verify_hmac_against_signer.py`
- Wejście: nagłówki przez **STDIN** (w formie `-H "K: V"` lub linie `K: V`)
- Wymagane: `LOGOPS_SECRET` (sekret HMAC), ścieżka do **pliku** z body (`--body-file`)

---

## Szybki start

**1) Weryfikacja nagłówków wygenerowanych przez `tools/sign_hmac.py`:**
```bash
# przygotuj body
echo '{"msg":"hello"}' > body.json

# wygeneruj nagłówki HMAC i od razu zweryfikuj
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' \
  --body-file body.json --nonce \
| LOGOPS_SECRET=demo-priv-1 \
  python tools/verify_hmac_against_signer.py --url 'http://127.0.0.1:8081/ingest' --method POST --body-file body.json
```

**2) Weryfikacja nagłówków wyjętych z polecenia `curl` (z `--echo-headers`):**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello"}' --echo-headers \
| LOGOPS_SECRET=demo-priv-1 \
  python tools/verify_hmac_against_signer.py --url 'http://127.0.0.1:8081/ingest' --method POST --body-file <(printf %s '{"msg":"hello"}')
```

**Wynik przykładowy:**
```
OK [api_iso_b64]
 provided (b64): <...>
 computed (b64): <...>
 canonical:
POST
/ingest
<sha256hex>
2025-08-31T12:00:00Z
<nonce>
```

Gdy podpis nie pasuje, narzędzie wypisze `MISMATCH [...]` i zwróci kod wyjścia `1`.

---

## Użycie (CLI)

```
python tools/verify_hmac_against_signer.py --url URL --method METHOD --body-file PATH < headers.txt
```

**Argumenty:**
- `--url` *(wymagane)* — pełny URL żądania
- `--method` — metoda HTTP (domyślnie `POST`)
- `--body-file` *(wymagane)* — ścieżka do pliku z **dokładnym** body

**Źródło nagłówków:**
Narzędzie czyta nagłówki ze **STDIN**. Akceptowane formaty:
- klasyczne tokeny `curl`: `-H "K: V" -H "K2: V2" ...` (w jednej lub wielu liniach),
- proste linie `K: V` po jednej na wiersz.

---

## Zmienne środowiskowe

| Zmienna         | Wymagane | Opis                           |
|-----------------|----------|--------------------------------|
| `LOGOPS_SECRET` | ✅        | Sekret HMAC używany do weryfikacji |

---

## Jak to działa (pod maską)

1. **Parsowanie nagłówków** ze STDIN — skrypt rozpoznaje:
   - styl **`X-Api-*`**:
     `X-Api-Key`, `X-Timestamp` *(ISO8601 Z)*, `X-Content-SHA256` *(hex)*, `X-Nonce`, `X-Signature` *(base64)*
     → **styl:** `api_iso_b64`
   - styl **`X-Logops-*`** (legacy):
     `X-Logops-Key`, `X-Logops-Ts` *(epoch)*, `X-Logops-Nonce`, `X-Logops-Signature` *(hex)*
     → **styl:** `logops_epoch_hex`

2. **Kanonikalizacja** (w aktualnym kodzie narzędzia):
   ```
   METHOD
   PATH+QUERY
   SHA256_HEX(body)
   TIMESTAMP
   NONCE
   ```
   Następnie liczony jest `HMAC_SHA256(secret, canonical)` i porównywany z nagłówkiem podpisu
   (base64 dla `api_iso_b64` lub hex dla `logops_epoch_hex`).

3. **Wynik**: `OK [style]` albo `MISMATCH [style]`, wypisywane są także:
   - podpis **z nagłówka** vs **wyliczony**,
   - **kanoniczny** ciąg użyty do obliczeń,
   - dla stylu `api_iso_b64`: ostrzeżenie, jeśli `X-Content-SHA256` ≠ `SHA256(body)`.

> ℹ️ **Uwaga o kanonikalizacji:**
> Ten weryfikator używa **`PATH+QUERY`** w kanoniku. Aktualny `tools/sign_hmac.py` (oraz najnowszy opis AuthGW) **używają `PATH` bez query**.
> **Konsekwencja:** jeżeli w URL masz parametry query, a nagłówki były podpisywane schematem *PATH-only*, to weryfikator pokaże `MISMATCH`.
> **Sposoby obejścia:**
> - zweryfikuj żądanie z **URL bez query**, lub
> - tymczasowo usuń część `?query=...` w `--url` podawanym do weryfikatora, tak aby kanonik był zgodny z tym użytym przez podpisującego.

---

## Kody wyjścia

- `0` — podpis OK
- `1` — podpis nie pasuje (`MISMATCH`)
- `2` — brak `LOGOPS_SECRET`
- `3` — nie udało się odnaleźć wymaganych nagłówków w STDIN

---

## Przykłady

**Weryfikacja nagłówków z pliku (format `K: V`):**
```bash
cat hdrs.txt \
| LOGOPS_SECRET=demo-priv-1 \
  python tools/verify_hmac_against_signer.py --url 'http://127.0.0.1:8081/ingest' --body-file body.json
```

**Weryfikacja nagłówków z polecenia `curl` (parsowanie `-H "K: V"`):**
```bash
echo '-H "X-Api-Key: demo-pub-1" -H "X-Timestamp: 2025-08-31T12:00:00Z" -H "X-Content-SHA256: ..."' \
| LOGOPS_SECRET=demo-priv-1 \
  python tools/verify_hmac_against_signer.py --url 'http://127.0.0.1:8081/ingest' --body-file body.json
```

---

## Najczęstsze problemy

- **`ERR: LOGOPS_SECRET is not set`** — ustaw `LOGOPS_SECRET=<sekret_klienta>`.
- **`MISMATCH` mimo poprawnych danych** — najpierw porównaj sekcję `canonical:` wypisaną przez to narzędzie z kanonikiem wygenerowanym przez podpisującego (np. `tools/sign_hmac.py`).
  Różnice zwykle dotyczą:
  - `PATH` vs `PATH+QUERY`,
  - innego `TIMESTAMP` (np. offset vs Zulu),
  - innego `SHA256(body)` (czytanie pliku vs string, `--data` vs `--data-binary`).
- **`WARN: X-Content-SHA256 mismatch`** — nagłówek `X-Content-SHA256` nie zgadza się z hash’em pliku `--body-file`. Upewnij się, że to **ten sam** plik/bajty, które realnie wysyłasz.

---

## Zobacz też

- `tools/sign_hmac.py` — generator nagłówków HMAC (aktualny kanonikalizator **PATH-only**).
- `tools/hmac_curl.sh` — wrapper `curl` do wygodnego wysyłania żądań HMAC.
- `services/authgw/hmac_mw.py` — weryfikacja HMAC po stronie serwera (AuthGW).

```
