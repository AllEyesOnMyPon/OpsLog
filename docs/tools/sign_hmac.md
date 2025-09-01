# `tools/sign_hmac.py` — generator nagłówków HMAC dla AuthGW

Mały helper do ręcznego podpisywania żądań do **Auth Gateway** (HMAC). Zwraca gotowy fragment do `curl` w postaci `-H "K: V" -H "K2: V2" ...`. Używa **tej samej kanonikalizacji**, co middleware `HmacAuthMiddleware` w `services/authgw/hmac_mw.py`.

- Plik: `tools/sign_hmac.py`
- Zależności: standardowa biblioteka Pythona
- Kompatybilne z: `authgw` (tryby `hmac` i `any`)

---

## Jak działa podpis

Kanonikalny ciąg to:
```
<HTTP_METHOD_UPPER>\n
<PATH+QUERY>\n
<X-Timestamp>\n
<SHA256-hex(body)>
```

Podpis:
```
base64( HMAC_SHA256( secret, canonical_bytes ) )
```

Nagłówki wysyłane do serwera:
- `X-Api-Key: <publiczny_klucz_klienta>`
- `X-Timestamp: <ISO8601 Z>`
- `X-Content-SHA256: <sha256_hex(body)>`
- `X-Signature: <base64_hmac>`
- `X-Nonce: <uuid>` *(opcjonalnie, ale wymagany gdy `require_nonce: true`)*

> Uwaga: Serwer porównuje `X-Content-SHA256` z realnym body oraz weryfikuje **skew czasu** (`clock_skew_sec` w YAML).

---

## Użycie

### 1) Generowanie nagłówków do `curl` (body inline)
```bash
python tools/sign_hmac.py \
  demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' \
  '{"msg":"hello"}' --nonce
```
Wyjście (jedna linia, gotowe do wklejenia po `curl`):
```
-H "X-Api-Key: demo-pub-1" -H "X-Timestamp: 2025-08-31T10:20:30Z" -H "X-Content-SHA256: ..." -H "X-Signature: ..." -H "X-Nonce: ..."
```

Przykładowe pełne wywołanie:
```bash
curl -sS -X POST 'http://127.0.0.1:8090/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' '{"msg":"hello"}' --nonce) \
  -d '{"msg":"hello"}'
```

### 2) Body z pliku
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' \
  --body-file big.json --nonce
```
Z użyciem `curl`:
```bash
curl -sS -X POST 'http://127.0.0.1:8090/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' --body-file big.json --nonce) \
  --data-binary @big.json
```

### 3) Jedna linia per nagłówek (np. do debug/logów)
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' '{"msg":"x"}' --nonce --one-per-line
```

### 4) Test skew i walidacji czasu
- Przesunięcie czasu (sekundy): `--ts-offset -3600`
- Jawny znacznik czasu: `--ts 2025-08-27T04:10:00Z`
```bash
python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' \
  '{"msg":"old"}' --nonce --ts-offset -3600
```

### 5) Windows PowerShell
```powershell
$H = python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' '{"msg":"hi from ps"}' --nonce
# $H to ciąg " -H \"X-Api-Key: ...\" -H \"X-Timestamp: ...\" ..."
# W PS łatwiej wygenerować nagłówki i wstrzyknąć w Invoke-WebRequest/Invoke-RestMethod ręcznie:
irm 'http://127.0.0.1:8090/ingest' -Method Post -ContentType 'application/json' `
  -Headers @{ 'X-Api-Key'='demo-pub-1'; 'X-Timestamp'='...'; 'X-Content-SHA256'='...'; 'X-Signature'='...'; 'X-Nonce'='...' } `
  -Body '{"msg":"hi from ps"}'
```

---

## Parametry CLI

```
python tools/sign_hmac.py API_KEY SECRET METHOD URL [BODY]
  --nonce                 dodaj nagłówek X-Nonce (wymagany, jeśli AuthGW ma require_nonce: true)
  --ts-offset SEC         przesunięcie zegara względem teraz (np. -1200)
  --ts ISO8601Z           jawny timestamp (np. 2025-08-27T04:10:00Z)
  --body-file PATH        czytaj body z pliku (wpływa na hash i podpis)
  --one-per-line          każdy nagłówek w osobnej linii (zamiast w jednym wierszu)
```

Argumenty pozycyjne:
- `API_KEY` — klucz publiczny klienta (musi istnieć w `secrets.clients` w YAML AuthGW).
- `SECRET` — sekret HMAC klienta.
- `METHOD` — `GET|POST|PUT|...` (serwer podpisuje *dokładnie ten tekst po upper-case*).
- `URL` — pełny URL; do kanonikalizacji brane są **path + query** (`/ingest` lub np. `/ingest?x=1`).
- `BODY` — (opcjonalne) treść body jako string; używaj `--body-file` dla dużych ładunków.

---

## Zgodność z AuthGW

- Middleware `HmacAuthMiddleware` oczekuje dokładnie tych samych pól nagłówków.
- `require_nonce: true` → **dodaj `--nonce`** (inaczej 401 `missing X-Nonce`).
- **Skew czasu** (`clock_skew_sec` w YAML) → błąd 401 `timestamp skew`, jeśli `X-Timestamp` zbyt odległy.

> W trybie `auth.mode: any` brak kompletu HMAC spowoduje, że AuthGW potraktuje żądanie jak `apikey` (jeśli jest `X-Api-Key`). Do testów HMAC **generuj pełny zestaw**.

---

## Najczęstsze błędy i diagnoza

- `401 body hash mismatch` — hash liczony z **dokładnie** tych bajtów, które wyślesz (używaj `--data-binary @file` i `--body-file` jednocześnie).
- `401 bad signature` — inny `secret` lub różne kanoniki (np. rozbieżny `METHOD`, `PATH+QUERY`, `X-Timestamp`, hash).
- `401 timestamp skew` — ustaw `--ts-offset 0` (domyślka) lub zwiększ `clock_skew_sec` w YAML.
- `401 replay detected` — ten sam `X-Nonce` podany drugi raz przy włączonym Redis/replay-protection.

---

## Przykłady gotowe do wklejenia

**Prosty POST (inline body):**
```bash
curl -sS -X POST 'http://127.0.0.1:8090/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' '{"msg":"hello"}' --nonce) \
  -d '{"msg":"hello"}'
```

**Duże body z pliku:**
```bash
python - <<'PY'
import json
open("big.json","w").write(json.dumps({"msg":"x"*250000}))
PY

curl -sS -X POST 'http://127.0.0.1:8090/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' --body-file big.json --nonce) \
  --data-binary @big.json -D - | sed -n '1,40p'
```

**Negatywny test (stary timestamp → 401 skew):**
```bash
curl -sS -X POST 'http://127.0.0.1:8090/ingest' \
  -H 'Content-Type: application/json' \
  $(python tools/sign_hmac.py demo-pub-1 demo-priv-1 POST 'http://127.0.0.1:8090/ingest' '{"msg":"old"}' --nonce --ts-offset -3600) \
  -d '{"msg":"old"}' -i
```

---

## Dobre praktyki

- Trzymaj **sekrety** poza historią Gita (plik `.env` / menedżer sekretów).
- Zawijaj generator w skrypt (`tools/hmac_curl.sh` lub Makefile) dla powtarzalności i uniknięcia wklejek w historii terminala.
- Do testów reprodukowalnych możesz ustawiać jawny `--ts` (stały) oraz body z pliku.

---

**Zobacz też:**
- `docs/services/auth_gateway.md` — pełna dokumentacja AuthGW (HMAC, nonce, backpressure, RL).
- `tools/hmac_curl.sh` — wrapper `curl` wykorzystujący tę samą kanonikalizację.
- `services/authgw/hmac_mw.py` — implementacja po stronie serwera.

```
