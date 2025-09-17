# `tools/sign_hmac.py` — generator nagłówków HMAC dla AuthGW

Lekki helper CLI do **ręcznego podpisywania** żądań do **Auth Gateway** (HMAC).
Zwraca nagłówki w formacie **wielowierszowym** `K: V` (domyślnie) lub w **pojedynczej linii** gotowej do `curl` (flaga `--one-per-line`).
Używa **tej samej kanonikalizacji**, co serwerowy `HmacAuthMiddleware`.

- Plik: `tools/sign_hmac.py`
- Zależności: standardowa biblioteka Pythona
- Zgodny z: `authgw` (tryby `hmac` i `any`)

---

## Kanonikalizacja i podpis

**Kanonikalny ciąg** (dokładnie jak w `HmacAuthMiddleware`):

```
<HTTP_METHOD_UPPER>
<PATH_ONLY>            # bez query string!
<SHA256_HEX(body)>
<X-Timestamp>
<X-Nonce>              # dołączany tylko, gdy nonce używany
```

**Podpis:**
```
base64( HMAC_SHA256( secret, canonical_bytes ) )
```

**Nagłówki wysyłane do serwera** (w tej kolejności):
- `X-Api-Key: <publiczny_klucz_klienta>`
- `X-Timestamp: <ISO8601 Z>` (np. `2025-08-31T12:00:00Z`)
- `X-Content-SHA256: <sha256_hex(body)>`
- `X-Nonce: <wartość>` *(opcjonalny; wymagany, gdy `require_nonce: true`)*
- `X-Signature: <base64_hmac>`

> Serwer porównuje `X-Content-SHA256` z **realnymi bajtami** body i weryfikuje **skew czasu** (`clock_skew_sec` w YAML).

---

## Użycie (CLI)

```
python tools/sign_hmac.py API_KEY SECRET METHOD URL [BODY]
  --body-file PATH     czytaj body z pliku (priorytet wobec BODY)
  --nonce [VAL]        dodaj X-Nonce; bez wartości → AUTO (losowe, deterministyczne dla ts+len)
  --ts ISO             użyj dokładnego czasu (akceptuje '...Z' lub z offsetem)
  --ts-offset SPEC     przesunięcie czasu: np. +30s, -2m, +1h
  --one-per-line       wyjście w 1 linii: -H "K: V" -H "K2: V2" ...
```

**Argumenty pozycyjne:**
- `API_KEY` — publiczny klucz klienta (musi być w `secrets.clients`).
- `SECRET` — sekret HMAC klienta.
- `METHOD` — `GET|POST|PUT|...` (używany po `upper()`).
- `URL` — pełny URL; do kanonika brany **tylko PATH** (bez query).
- `BODY` — opcjonalny string body (gdy nie używasz `--body-file`).

**Jednostki `--ts-offset`:** `s|sec|second(s)`, `m|min|minute(s)`, `h|hr|hour(s)` (np. `-3600`, `+30s`, `-2m`, `+1h`).

**Nonce (`--nonce`):**
- bez parametru: auto (`sha256(f"{ts}-{len(body)}")[:32]`),
- z wartością: użyty literal,
- bez flagi: nagłówek **nie** jest dodawany.

---

## Przykłady

**1) Domyślne wyjście (nagłówki w wielu liniach):**
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' \
  '{"msg":"hello"}' --nonce
# stdout:
# X-Api-Key: demo-pub-1
# X-Timestamp: 2025-08-31T10:20:30Z
# X-Content-SHA256: <...>
# X-Nonce: <...>
# X-Signature: <...>
```
W połączeniu z wrapperem:
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello"}'
```
(`hmac_curl.sh` oczekuje właśnie **wielowierszowego** formatu `K: V`.)

**2) Jedna linia gotowa do wklejenia w `curl`:**
```bash
curl -sS -X POST 'http://127.0.0.1:8081/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' '{"msg":"hello"}' --nonce --one-per-line) \
  -d '{"msg":"hello"}'
```

**3) Body z pliku (hash liczony z pliku):**
```bash
echo '{"msg":"file"}' > body.json
curl -sS -X POST 'http://127.0.0.1:8081/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' --body-file body.json --nonce --one-per-line) \
  --data-binary @body.json
```

**4) Test skew czasu:**
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' \
  '{"msg":"old"}' --nonce --ts-offset -3600 --one-per-line
```

**5) Windows PowerShell (ręczne złożenie nagłówków):**
```powershell
$H = python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8081/ingest' '{"msg":"hi"}' --nonce
# $H zawiera linie "K: V". Przepisz do hashtable:
irm 'http://127.0.0.1:8081/ingest' -Method Post -ContentType 'application/json' `
  -Headers @{ 'X-Api-Key'='demo-pub-1'; 'X-Timestamp'='...'; 'X-Content-SHA256'='...'; 'X-Signature'='...'; 'X-Nonce'='...' } `
  -Body '{"msg":"hi"}'
```

---

## Różnice względem starszych opisów

- **PATH bez query** (wcześniej bywało `PATH+QUERY`).
- **Kolejność w kanoniku:** `METHOD`, `PATH`, **`SHA256(body)`**, `TIMESTAMP`, `NONCE`.
- Wyjście **domyślnie** to *wielowierszowe* `K: V`. Użyj `--one-per-line`, aby dostać jedną linię `-H "K: V" ...`.

---

## Diagnostyka

- `401 body hash mismatch` — podpis liczony jest z **dokładnych bajtów**; używaj `--data-binary @file` + `--body-file`.
- `401 bad signature` — niespójny `METHOD`/`PATH`/`TIMESTAMP`/`HASH`/`NONCE` lub zły `SECRET`.
- `401 timestamp skew` — zegar poza `clock_skew_sec`; dopasuj `--ts`/`--ts-offset` albo konfigurację.
- `401 replay detected` — powtórzony `X-Nonce` przy włączonym anti-replay (Redis). Użyj `--nonce` bez wartości (AUTO).

---

## Zobacz też

- `tools/hmac_curl.sh` — wrapper `curl` korzystający z tych samych zasad.
- `services/authgw/hmac_mw.py` — weryfikacja HMAC po stronie serwera.
- `docs/services/auth_gateway.md` — pełne README AuthGW (HMAC, nonce, backpressure, RL, retry+CB).
